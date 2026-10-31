"""Appliance store seams for the ONE engine (v4 C0) — Pro/Max only, never vendored.

In v4 the offline appliance serves native S3 / DynamoDB / GCS wire through the SAME
conformance cores Nano uses (core/s3_object_core.py, core/dynamodb_core.py,
core/gcp_storage_core.py via core/aws_wire_router.py). The cores persist through a
store seam; these are the appliance's implementations of that seam.

Design — one state, not two. Each store's working dicts ARE the appliance's existing
space-scoped state (core.app_context `_SpaceScopedDictProxy`):

    S3        buckets / objects / multipart  -> service_states["s3"]{buckets,objects,multiparts}
    GCS       buckets / objects              -> service_states["gcp_gcp_storage"]{buckets,objects}
    DynamoDB  tables                         -> service_states["dynamodb"]{tables}

  v4 C0b adds (new state — the pre-v4 handlers kept these in memory / Vault / Azurite):
    Azure Blob      containers / blobs       -> service_states["azure_azure_blob"]{containers,blobs}
                    (container keys are "{account}/{container}"; bytes inline, mirrored to
                     Azurite when CLOUDLEARN_AZURITE_URL is reachable; pre-v4 Azurite blobs
                     are adopted lazily — metadata imported, bytes fetched on read)
    Secret Manager  secrets                  -> service_states["gcp_gcp_secretmanager"]{secrets}
    Cloud KMS       keys / material / rings  -> service_states["gcp_gcp_kms"]{keys,material,aliases,rings}
                    (pre-v4 Vault-backed secrets / key index are adopted on first use; Vault
                     transit ciphertext still decrypts through `legacy_decrypt`)

  v4 C0c adds (the pre-v4 handlers kept these in Vault + a process-local dict):
    AWS KMS         keys / material / aliases / custom key stores
                                             -> service_states["kms"]{keys,material,aliases,custom_key_stores}
    Secrets Manager secrets (+ every version) -> service_states["secretsmanager"]{secrets}
                    (pre-v4 Vault KV secrets and Vault transit keys are adopted once per space
                     when Vault is reachable; `vault:v1:` ciphertext still decrypts through
                     `legacy_decrypt`)

  v4 C0d adds (new slots — the pre-v4 handlers kept differently-shaped records, see below):
    Firestore       documents + admin plane  -> service_states["gcp_gcp_firestore_engine"]
                    {documents,databases,indexes,fields,backup_schedules,backups,operations,
                     security_rules,meta}
    Compute VPC     networks / subnets / firewalls / routes / addresses
                                             -> service_states["gcp_gcp_compute_vpc"]
    Compute Engine  instances / disks / images / snapshots / templates / groups / health checks
                                             -> service_states["gcp_gcp_compute_vm"]
                    (a Compute instance's REAL runtime — the Docker / LXD / Multipass guest the
                     pre-v4 handler launched — is still the pre-v4 runtime record in
                     service_states["gcp_gcp_compute"]["instances"], linked from the core record
                     by `_runtimeId`; routes/gcp_firestore_compute_unified.py drives it)
                    Once per space (marker in the slot's "meta"), the pre-v4 records are adopted:
                    gcp_firestore_state databases / indexes + the FirestoreEngine SQLite documents
                    (+ the Firestore emulator's, when configured), gcp_vpc_state, gcp_compute_state.

The cores were extracted from the appliance handlers, so the shapes are identical.
Consequences:
  * every v3 consumer of that state — the classic console REST (/api/s3/*,
    /api/dynamodb/*, /api/console/gcs/*, GCS folders / transfer jobs), Lambda
    triggers, inventory, Terraform — sees exactly what the native wire wrote, and
    vice-versa (no sync, no second copy);
  * tenant / space / provider isolation is the proxy's (unchanged);
  * durability is the kernel state store (CLOUDLEARN_STATE_FILE, SQLite), which
    the tier middleware flushes after every POST/PUT/PATCH/DELETE — the same
    write path every other appliance service uses, so a restart restores bucket
    config, version chains, GCS labels/retention and DynamoDB tables;
  * object bytes are additionally written through to the real byte stores
    (S3 -> MinIO via core.minio_mirror, GCS -> fake-gcs-server when configured)
    so external tools see them; when MinIO is not reachable the mirror is
    skipped (logged once) and the inline bytes in the state keep S3 working.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid

from core.azure_blob_core import AzureBlobStore
from core.kms_keystore import InMemoryKmsEngine, KeyStore
from core.kv_store import KvStore
from core.nosql_store import NoSqlStore
from core.object_store import ObjectStore

_log = logging.getLogger("vyomi.engine")


def _proxy(service_key: str, factory, nested: str):
    from core.app_context import _SpaceScopedDictProxy
    return _SpaceScopedDictProxy(service_key, factory, nested)


class _MirrorGate:
    """Probe a byte store at most once a minute; log the first time it is down."""

    def __init__(self, name: str, probe):
        self._name, self._probe = name, probe
        self._ok, self._at, self._logged = False, 0.0, False
        self._lock = threading.Lock()

    def ok(self) -> bool:
        now = time.monotonic()
        if now - self._at < 60:
            return self._ok
        with self._lock:
            if now - self._at < 60:
                return self._ok
            try:
                self._ok = bool(self._probe())
            except Exception:
                self._ok = False
            self._at = now
            if not self._ok and not self._logged:
                self._logged = True
                msg = (f"[engine] {self._name} not reachable — object bytes stay in the appliance "
                       f"state store only (persistent); write-through resumes when it returns")
                print(msg)   # once; stdout reaches the appliance log under uvicorn
        return self._ok


class AppStateObjectStore(ObjectStore):
    """ObjectStore whose state dicts are the appliance's space-scoped state."""

    def __init__(self, buckets, objects, multiparts=None, *, mirror=None, events=None,
                 fetch=None, storage_cap=None, quantity_cap=None):
        # NB: no super().__init__() — buckets/objects are the shared proxies, not new dicts.
        self._b, self._o = buckets, objects
        self._m = multiparts
        self._mirror = mirror            # (put(bucket,key,data,ct,meta), delete(bucket,key)) or None
        self._events = events
        self._fetch = fetch
        self._storage_cap = storage_cap
        self._quantity_cap = quantity_cap

    buckets = property(lambda self: self._b)
    objects = property(lambda self: self._o)

    @property
    def _multipart_uploads(self):
        if self._m is None:
            self._m = {}
        return self._m

    @_multipart_uploads.setter
    def _multipart_uploads(self, value):
        self._m = value

    def mirror_put(self, bucket, key, data, content_type="application/octet-stream", metadata=None):
        if self._mirror:
            try:
                self._mirror[0](bucket, key, data, content_type, metadata)
            except Exception:
                pass

    def mirror_delete(self, bucket, key):
        if self._mirror:
            try:
                self._mirror[1](bucket, key)
            except Exception:
                pass

    def emit_event(self, bucket, key, event_name, version=None, source=""):
        if self._events:
            self._events(bucket, key, event_name, version, source)

    def fetch_bytes(self, bucket, key):
        if self._fetch:
            try:
                return self._fetch(bucket, key)
            except Exception:
                return None
        return None

    def enforce_storage_cap(self, additional_bytes):
        if self._storage_cap:
            self._storage_cap(additional_bytes)

    def enforce_quantity_cap(self, resource_type):
        if self._quantity_cap:
            self._quantity_cap(resource_type)

    # persist(): no-op — the tier middleware persists the kernel state after every
    # mutating request (and the S3/GCS/DDB state lives inside it).


class AppStateNoSqlStore(NoSqlStore):
    """NoSqlStore whose `tables` map is the appliance's space-scoped ddb_state["tables"]."""

    def __init__(self, tables, account_id: str, backups=None):
        self._t = tables
        self._b = backups if backups is not None else {}
        self.account_id = account_id

    tables = property(lambda self: self._t)
    # On-demand backups (CreateBackup/RestoreTableFromBackup) live beside the tables in the
    # same space-scoped, persisted ddb_state, so they survive restarts like the tables do.
    backups = property(lambda self: self._b)


def _active_space_id() -> str:
    """The active space id (the namespace the pre-v4 Vault / Azurite handlers used)."""
    try:
        from core.app_context import STATE
        return (STATE.get("spaces") or {}).get("active_space_id", "") or "global"
    except Exception:
        return "global"


def _http_date() -> str:
    import email.utils
    return email.utils.formatdate(usegmt=True)


class AppStateAzureBlobStore(AzureBlobStore):
    """azure_blob_core store over the appliance's space-scoped Azure state."""

    def __init__(self, containers, blobs, *, azurite=None):
        # NB: no super().__init__() — the dicts are the shared, persisted proxies.
        self._c, self._bl = containers, blobs
        self._az = azurite          # module with the core.azure_blob_store API, or None
        self._adopted: set = set()

    containers = property(lambda self: self._c)
    blobs = property(lambda self: self._bl)

    @staticmethod
    def _split(container_key: str) -> tuple[str, str]:
        acct, _, cont = container_key.partition("/")
        return (acct, cont) if cont else ("devstoreaccount1", acct)

    def _azurite(self):
        try:
            return self._az if (self._az and self._az.available()) else None
        except Exception:
            return None

    def mirror_put(self, container, blob, entry):
        az = self._azurite()
        if az:
            try:
                acct, cont = self._split(container)
                az.put_blob(_active_space_id(), acct, cont, blob, bytes(entry.get("data") or b""),
                            entry.get("content_type"), entry.get("metadata") or {})
            except Exception:
                pass

    def mirror_delete(self, container, blob):
        az = self._azurite()
        if az:
            try:
                acct, cont = self._split(container)
                az.delete_blob(_active_space_id(), acct, cont, blob)
            except Exception:
                pass

    def mirror_delete_container(self, container):
        az = self._azurite()
        if az:
            try:
                acct, cont = self._split(container)
                az.delete_container(_active_space_id(), acct, cont)
            except Exception:
                pass

    def fetch_bytes(self, container, blob):
        az = self._azurite()
        if not az:
            return None
        try:
            acct, cont = self._split(container)
            rec = az.get_blob(_active_space_id(), acct, cont, blob)
            return rec.get("data") if rec else None
        except Exception:
            return None

    def adopt(self, account: str) -> None:
        """Import (once per space+account) the blobs a pre-v4 appliance stored in
        Azurite, so an upgrade keeps them visible. Metadata only — bytes are read
        through `fetch_bytes` on first GET."""
        key = (_active_space_id(), account)
        if key in self._adopted:
            return
        self._adopted.add(key)
        az = self._azurite()
        if not az:
            return
        try:
            sid = key[0]
            for cont in az.list_containers(sid, account):
                ck = f"{account}/{cont}"
                if ck not in self.containers:
                    self.containers[ck] = {"created": _http_date()}
                objs = self.container_blobs(ck)
                for o in az.list_blobs(sid, account, cont):
                    if o["name"] in objs:
                        continue
                    objs[o["name"]] = {
                        "data": None, "size": int(o.get("size") or 0),
                        "content_type": o.get("contentType") or "application/octet-stream",
                        "blob_type": "BlockBlob", "etag": o.get("etag") or '"0x0"',
                        "last_modified": o.get("lastModified") or _http_date(),
                        "created": o.get("lastModified") or _http_date(),
                        "md5": "", "metadata": {}}
        except Exception as exc:   # never break the data plane over a migration
            _log.warning("azure blob: Azurite adoption skipped: %s", exc)


class AppStateKvStore(KvStore):
    """gcp_secretmanager_core store over the appliance's space-scoped GCP state."""

    def __init__(self, secrets, account_id: str = ""):
        self._s = secrets
        self.account_id = account_id
        self._adopted: set = set()

    secrets = property(lambda self: self._s)

    def adopt(self, project: str) -> None:
        """Import (once per space) the secrets a pre-v4 appliance kept in Vault KV
        (name index + every version) into `project`, so an upgrade keeps them."""
        sid = _active_space_id()
        if sid in self._adopted:
            return
        self._adopted.add(sid)
        try:
            from core import vault_client as vc
            from core import vault_routes as vr
            if not vc.available():
                return
            import base64 as _b64
            for name in vr._gcp_idx_get(sid, "secrets"):
                key = f"{project}/{name}"
                if key in self.secrets:
                    continue
                created = vr._gcp_idx_created(sid, "secrets").get(name) or ""
                versions, n = {}, 0
                for meta in vc.kv_list_versions("gcp", sid, name):
                    v = int(meta.get("version") or 0)
                    got = vc.kv_get("gcp", sid, name, version=v) or {}
                    data = (got.get("data") or {})
                    raw = data.get("value") if "value" in data else None
                    destroyed = bool(meta.get("destroyed")) or raw is None
                    versions[v] = {"data": None if destroyed else _b64.b64encode(str(raw).encode()).decode(),
                                   "state": "DESTROYED" if destroyed else "ENABLED",
                                   "createTime": meta.get("created_time") or created}
                    n = max(n, v)
                self.secrets[key] = {"name": f"projects/{project}/secrets/{name}", "project": project,
                                     "secretId": name, "createTime": created or _http_date(),
                                     "replication": {"automatic": {}}, "labels": {},
                                     "versions": versions, "version_counter": n}
        except Exception as exc:
            _log.warning("gcp secret manager: Vault adoption skipped: %s", exc)


class AppStateKeyStore(KeyStore):
    """gcp_kms_core store over the appliance's space-scoped GCP state. Key material
    lives in that (persisted) state, so keys survive a restart and encrypt/decrypt
    round-trips across it; the crypto is the shared core's KmsEngine."""

    def __init__(self, keys, material, aliases, rings, account_id: str = ""):
        self._k, self._m, self._a, self._r = keys, material, aliases, rings
        self.engine = InMemoryKmsEngine()
        self.account_id = account_id
        self._adopted: set = set()

    keys = property(lambda self: self._k)
    material = property(lambda self: self._m)
    aliases = property(lambda self: self._a)
    gcp_key_rings = property(lambda self: self._r)

    def get_material(self, key_id):
        m = self._m.get(key_id)
        return m.encode("latin-1") if isinstance(m, str) else m

    def legacy_decrypt(self, name: str, blob: bytes):
        """Ciphertext minted by the pre-v4 Vault-transit handler (`vault:v1:…`)."""
        try:
            text = blob.decode("ascii")
        except Exception:
            return None
        if not text.startswith("vault:"):
            return None
        try:
            import base64 as _b64
            from core import vault_client as vc
            segs = name.split("/")
            pt = vc.transit_decrypt("gcp", _active_space_id(), f"{segs[5]}__{segs[7]}", text)
            return _b64.b64decode(pt) if pt is not None else None
        except Exception:
            return None

    def adopt(self, project: str) -> None:
        """Register (once per space) the key rings / crypto keys a pre-v4 appliance
        indexed in Vault, so an upgrade keeps them listed. Fresh material is minted
        for new encrypts; old Vault ciphertext still decrypts via legacy_decrypt."""
        sid = _active_space_id()
        if sid in self._adopted:
            return
        self._adopted.add(sid)
        try:
            from core import vault_client as vc
            from core import vault_routes as vr
            if not vc.available():
                return
            created = vr._gcp_idx_created(sid, "kms")
            for entry in vr._gcp_idx_get(sid, "kms"):
                ring, _, key = entry.partition("/")
                if not key:
                    continue
                rname = f"projects/{project}/locations/global/keyRings/{ring}"
                when = created.get(entry) or _http_date()
                if rname not in self._r:
                    self._r[rname] = {"createTime": when}
                kname = f"{rname}/cryptoKeys/{key}"
                if kname not in self._k:
                    meta = (vc.kv_get("gcp", sid, f"__kmsmeta__{key}") or {}).get("data") or {}
                    self.put_key(kname, {
                        "purpose": "ENCRYPT_DECRYPT", "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
                        "createTime": when, "primary": "1",
                        "versions": {"1": {"state": "ENABLED", "createTime": when}},
                        **({"labels": meta["labels"]} if isinstance(meta, dict) and meta.get("labels") else {}),
                        **({"rotationPeriod": meta["rotation_period"]} if isinstance(meta, dict) and meta.get("rotation_period") else {}),
                    }, self.engine.new_key_material())
        except Exception as exc:
            _log.warning("gcp kms: Vault adoption skipped: %s", exc)


def _epoch(ts) -> float:
    """RFC3339 (Vault / the pre-v4 index) → epoch seconds; best effort."""
    if isinstance(ts, (int, float)):
        return float(ts)
    from datetime import datetime
    s = str(ts or "").strip()
    if not s:
        return time.time()
    s = s.replace("Z", "+00:00")
    if "." in s:   # Vault returns nanoseconds; fromisoformat takes ≤ 6 fraction digits
        head, _, rest = s.partition(".")
        import itertools
        frac = "".join(itertools.takewhile(str.isdigit, rest))
        tz = rest[len(frac):]
        s = f"{head}.{frac[:6]}{tz}"
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return time.time()


_HEX32 = frozenset("0123456789abcdef")


class AppStateAwsKeyStore(KeyStore):
    """kms_core (AWS KMS) store over the appliance's space-scoped AWS state. Key
    material lives in that persisted state, so keys survive a restart and ciphertext
    made before it still decrypts; the crypto is the shared core's KmsEngine."""

    def __init__(self, keys, material, aliases, custom_key_stores, account_id: str = ""):
        # NB: no super().__init__() — the dicts are the shared, persisted proxies.
        self._k, self._m, self._a, self._c = keys, material, aliases, custom_key_stores
        self.engine = InMemoryKmsEngine()
        self.account_id = account_id
        self._adopted: set = set()

    keys = property(lambda self: self._k)
    material = property(lambda self: self._m)
    aliases = property(lambda self: self._a)
    custom_key_stores = property(lambda self: self._c)

    def get_material(self, key_id):
        m = self._m.get(key_id)
        return m.encode("latin-1") if isinstance(m, str) else m

    def _vault(self):
        from core import vault_client as vc
        return vc if vc.available() else None

    def legacy_decrypt(self, key_ref: str, blob: bytes):
        """Ciphertext minted by the pre-v4 Vault-transit handler (`vault:v1:…`).
        That handler named the transit key after the request's KeyId (a key id, or
        the tail of an ARN / unresolved alias, or "default"); try those, then every
        key of the space. Returns (key_id, plaintext) or None."""
        try:
            text = bytes(blob).decode("ascii")
        except Exception:
            return None
        if not text.startswith("vault:"):
            return None
        vc = self._vault()
        if vc is None:
            return None
        from core import kms_core as _kc
        cands: list[str] = []
        ref = (key_ref or "").strip()
        if ref:
            resolved = _kc._resolve_key_id(self, ref)
            if resolved:
                cands.append(resolved)
            cands.append(ref.rsplit("/", 1)[-1])
        else:
            cands += list(self.key_ids()) + ["default"]
        import base64 as _b64
        sid = _active_space_id()
        for name in dict.fromkeys(c for c in cands if c):
            pt = vc.transit_decrypt("aws", sid, name, text)
            if pt is not None:
                return name, _b64.b64decode(pt)
        return None

    def adopt(self) -> None:
        """Register (once per space) the KMS keys a pre-v4 appliance created in Vault
        transit (CreateKey ids — 32 hex), so their KeyIds keep describing and their
        old ciphertext keeps decrypting (legacy_decrypt). Fresh material is minted
        for new encrypts. Pre-v4 key metadata / aliases lived in process memory only
        and did not survive a restart, so there is nothing else to adopt."""
        sid = _active_space_id()
        if sid in self._adopted:
            return
        self._adopted.add(sid)
        try:
            vc = self._vault()
            if vc is None:
                return
            import uuid as _uuid
            for name in vc.transit_list_keys("aws", sid):
                if len(name) != 32 or not set(name) <= _HEX32 or name in self._k:
                    continue
                self.put_key(name, {
                    "KeyState": "Enabled", "Description": "", "KeyUsage": "ENCRYPT_DECRYPT",
                    "KeySpec": "SYMMETRIC_DEFAULT", "Origin": "AWS_KMS", "KeyManager": "CUSTOMER",
                    "CreationDate": time.time(), "MaterialId": _uuid.uuid4().hex, "Tags": {},
                }, self.engine.new_key_material())
        except Exception as exc:
            _log.warning("aws kms: Vault adoption skipped: %s", exc)


class AppStateAwsKvStore(KvStore):
    """secrets_core (AWS Secrets Manager) store over the appliance's space-scoped
    AWS state."""

    def __init__(self, secrets, account_id: str = ""):
        self._s = secrets
        self.account_id = account_id
        self._adopted: set = set()

    secrets = property(lambda self: self._s)

    def adopt(self) -> None:
        """Import (once per space) the secrets a pre-v4 appliance kept in Vault KV
        (its name index + every live version + the console's metadata), so an
        upgrade keeps them. The newest version is AWSCURRENT, the one before it
        AWSPREVIOUS; VersionIds are stable UUIDs derived from the Vault version."""
        sid = _active_space_id()
        if sid in self._adopted:
            return
        self._adopted.add(sid)
        try:
            from core import vault_client as vc
            from core import vault_routes as vr
            if not vc.available():
                return
            import json as _json
            import uuid as _uuid
            from core import secrets_core as _sc
            created_idx = vr._aws_secret_created(sid)
            for name in vr._aws_secret_index_get(sid):
                if name in self._s:
                    continue
                meta = vr._aws_secret_meta(sid, name)
                versions = {}
                for vmeta in vc.kv_list_versions("aws", sid, name):
                    if vmeta.get("destroyed") or vmeta.get("deletion_time"):
                        continue
                    v = int(vmeta.get("version") or 0)
                    got = vc.kv_get("aws", sid, name, version=v)
                    if not got:
                        continue
                    data = got.get("data") or {}
                    value = data.get("value") if "value" in data else _json.dumps(data)
                    vid = _uuid.uuid5(_uuid.NAMESPACE_URL, f"vyomi:aws-sec:{sid}:{name}:{v}").hex
                    versions[vid] = {"SecretString": None if value is None else str(value),
                                     "SecretBinary": None, "stages": [], "_n": v,
                                     "CreatedDate": _epoch(vmeta.get("created_time"))}
                if not versions:
                    continue
                order = sorted(versions, key=lambda k: versions[k].pop("_n"))
                versions[order[-1]]["stages"] = [_sc.CURRENT]
                if len(order) > 1:
                    versions[order[-2]]["stages"] = [_sc.PREVIOUS]
                created = _epoch(created_idx.get(name) or meta.get("created"))
                sec = {"name": name, "arn": _sc._secret_arn(self, name),
                       "description": str(meta.get("description") or ""),
                       "created": created, "last_changed": versions[order[-1]]["CreatedDate"],
                       "versions": versions, "deleted_date": None}
                kms_key = str(meta.get("kms_key_id") or "")
                if kms_key and kms_key not in ("aws/secretsmanager", "alias/aws/secretsmanager"):
                    sec["kms_key_id"] = kms_key
                self._s[name] = sec
        except Exception as exc:
            _log.warning("aws secrets manager: Vault adoption skipped: %s", exc)


# ── v4 C0d: Firestore + Compute Engine (VPC and VMs) ───────────────────────
from core import gcp_compute_core as _gcc                 # noqa: E402
from core import gcp_compute_instances_core as _gci       # noqa: E402
from core.gcp_firestore_core import FirestoreStore        # noqa: E402


class _SlotStore:
    """Mixin: the store's state attributes resolve, on every access, to the active
    space's slot (a plain dict inside the persisted kernel state), so a space switch
    — or a restore that swaps the dict in — is followed without any sync."""

    _KEYS: dict = {}

    def _bind(self, proxy) -> None:
        self._proxy = proxy

    def _slot(self) -> dict:
        slot = self._proxy._target()
        for k, factory in self._KEYS.items():
            if k not in slot:
                slot[k] = factory()
        slot.setdefault("meta", {})
        return slot

    def persist(self) -> None:
        """No-op: the tier middleware persists the kernel state after every mutating
        request (the slot lives inside it)."""

    def _begin_adoption(self) -> bool:
        """True exactly once per space (the marker persists with the slot), so a record
        deleted after the upgrade is never resurrected from the pre-v4 state."""
        meta = self._slot()["meta"]
        if meta.get("adopted"):
            return False
        meta["adopted"] = _http_date()
        return True


def _slot_attr(name: str):
    return property(lambda self: self._slot()[name])


def _slot_attr_rw(name: str):
    """Like _slot_attr, but settable — for fields a core reassigns wholesale
    (`store.password_policy = {...}` / `= None`), not just mutates in place."""
    return property(lambda self: self._slot()[name],
                    lambda self, value: self._slot().__setitem__(name, value))


def _space_id_of(slot: dict) -> str:
    """The id of the space whose service_states hold `slot` (the proxy may have pivoted
    away from the globally active space to the request's provider)."""
    try:
        from core.app_context import STATE
        for sid, sp in ((STATE.get("spaces") or {}).get("spaces") or {}).items():
            if isinstance(sp, dict) and any(v is slot for v in (sp.get("service_states") or {}).values()):
                return sid
    except Exception:
        pass
    return _active_space_id()


def _rfc3339(ts) -> str:
    s = str(ts or "").strip()
    return s if s else time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())


class AppStateFirestoreStore(_SlotStore, FirestoreStore):
    """gcp_firestore_core store over the appliance's space-scoped GCP state."""

    _KEYS = {"documents": dict, "databases": dict, "indexes": dict, "fields": dict,
             "backup_schedules": dict, "backups": dict, "operations": dict, "security_rules": dict,
             "backup_snapshots": dict, "history": dict, "usage": dict}

    def __init__(self, proxy):
        self._bind(proxy)          # NB: no FirestoreStore.__init__ — the dicts are the slot's

    documents = _slot_attr("documents")
    databases = _slot_attr("databases")
    indexes = _slot_attr("indexes")
    fields = _slot_attr("fields")
    backup_schedules = _slot_attr("backup_schedules")
    backups = _slot_attr("backups")
    operations = _slot_attr("operations")
    security_rules = _slot_attr("security_rules")
    backup_snapshots = _slot_attr("backup_snapshots")   # PITR / restore payloads
    history = _slot_attr("history")                     # per-document versions (point-in-time reads)
    usage = _slot_attr("usage")                         # per-database read/write/delete counters

    def adopt(self, project: str) -> None:
        """Import (once per space) what the pre-v4 handlers kept: the databases and
        composite indexes in gcp_firestore_state, the documents in the FirestoreEngine
        SQLite table (or the Firestore emulator, when one is configured)."""
        if not self._begin_adoption():
            return
        try:
            from core import gcp_firestore_core as fc
            from core.app_context import gcp_firestore_state as legacy
            slot = self._slot()
            dbs = legacy.get("databases") if isinstance(legacy.get("databases"), dict) else {}
            for dbid, rec in dbs.items():
                if not isinstance(rec, dict) or dbid in self.databases:
                    continue
                db = fc._ensure_db(self, project, dbid)
                for k in ("locationId", "type", "concurrencyMode", "appEngineIntegrationMode",
                          "deleteProtectionState", "pointInTimeRecoveryEnablement", "createTime",
                          "updateTime", "uid"):
                    if rec.get(k):
                        db[k] = rec[k]
            for rec in (legacy.get("indexes") or {}).values():
                if not isinstance(rec, dict) or not rec.get("collection"):
                    continue
                dbid = str(rec.get("database") or "(default)")
                fc._ensure_db(self, project, dbid)
                iid = str(rec.get("name") or "").rsplit("/", 1)[-1] or fc._auto_id()[:16]
                self.indexes.setdefault(dbid, {}).setdefault(iid, {
                    "name": f"projects/{project}/databases/{dbid}/collectionGroups/{rec['collection']}/indexes/{iid}",
                    "collectionGroup": rec["collection"], "queryScope": rec.get("queryScope") or "COLLECTION",
                    "fields": rec.get("fields") or [], "state": rec.get("state") or "READY"})
            n = 0
            for dbid, rel, fields, created, updated in self._legacy_documents(slot, project, list(dbs)):
                key = f"{dbid}/{rel}"
                if key in self.documents or rel.count("/") % 2 != 1:
                    continue
                fc._ensure_db(self, project, dbid)
                self.documents[key] = {"fields": fields if isinstance(fields, dict) else {},
                                       "createTime": _rfc3339(created), "updateTime": _rfc3339(updated or created)}
                n += 1
            if n or dbs:
                _log.info("firestore: adopted %d pre-v4 documents, %d databases", n, len(dbs))
        except Exception as exc:   # never break the data plane over a migration
            _log.warning("firestore: pre-v4 adoption skipped: %s", exc)

    @staticmethod
    def _legacy_documents(slot, project, dbids):
        """(database, rel, fields, createTime, updateTime) of every pre-v4 document."""
        out = []
        try:   # FirestoreEngine (core/vyomi_platform.py) — SQLite rows keyed by space id
            from core.app_context import PLATFORM, STATE
            eng = PLATFORM.firestore
            sids = {_space_id_of(slot), str((STATE.get("spaces") or {}).get("active_space_id") or "global")}
            try:
                sids.add(eng._space_id())    # the space the pre-v4 engine itself keyed rows by
            except Exception:
                pass
            with eng.lock:
                with eng._connect() as conn:
                    eng._ensure_schema(conn)
                    marks = ",".join("?" * len(sids))
                    for row in conn.execute(
                            "SELECT database_id, collection_id, doc_id, fields_json, create_time, update_time "
                            f"FROM gcp_firestore_documents WHERE space_id IN ({marks}) ORDER BY create_time",
                            tuple(sids)).fetchall():
                        import json as _json
                        try:
                            fields = _json.loads(row["fields_json"] or "{}")
                        except Exception:
                            fields = {}
                        out.append((row["database_id"] or "(default)", f"{row['collection_id']}/{row['doc_id']}",
                                    fields, row["create_time"], row["update_time"]))
        except Exception as exc:
            _log.warning("firestore: SQLite document adoption skipped: %s", exc)
        try:   # the Firestore emulator (CLOUDLEARN_FIRESTORE_EMULATOR_HOST), when it held them
            from core import gcp_firestore_emulator as emu
            if emu.available():
                for dbid in dict.fromkeys(list(dbids) + ["(default)"]):
                    for d in emu.list_root(project, dbid) or []:
                        name = str(d.get("name") or "")
                        if "/documents/" in name:
                            out.append((dbid, name.split("/documents/", 1)[1], d.get("fields") or {},
                                        d.get("createTime"), d.get("updateTime")))
        except Exception as exc:
            _log.warning("firestore: emulator document adoption skipped: %s", exc)
        return out


class AppStateComputeVpcStore(_SlotStore, _gcc.ComputeStore):
    """gcp_compute_core (VPC networks / subnets / firewalls / routes / addresses) store over
    the appliance's space-scoped GCP state."""

    _KEYS = {"networks": dict, "subnetworks": dict, "firewalls": dict, "routes": dict,
             "addresses": dict, "routers": dict, "connectivity_tests": dict, "seq": lambda: {"op": 0, "ip": 0}}

    def __init__(self, proxy):
        self._bind(proxy)

    networks = _slot_attr("networks")
    subnetworks = _slot_attr("subnetworks")
    firewalls = _slot_attr("firewalls")
    routes = _slot_attr("routes")
    addresses = _slot_attr("addresses")
    routers = _slot_attr("routers")
    connectivity_tests = _slot_attr("connectivity_tests")
    seq = _slot_attr("seq")

    def adopt(self, project: str) -> None:
        """Import (once per space) the pre-v4 gcp_vpc_state networks, subnetworks,
        firewall rules and routes (keyed by bare name there; `project/…` here)."""
        if not self._begin_adoption():
            return
        try:
            from core.app_context import gcp_vpc_state as legacy

            def items(kind):
                d = legacy.get(kind)
                return [r for r in (d.values() if isinstance(d, dict) else []) if isinstance(r, dict) and r.get("name")]

            def net_name(ref):
                return _gcc._resolve_network_name(project, ref or "default") or "default"

            def ensure_net(proj, name, rec=None):
                key = _gcc._net_key(proj, name)
                if key not in self.networks:
                    rec = rec or {}
                    self.seq["ip"] += 1
                    self.networks[key] = {
                        "id": str(rec.get("id") or 10_000 + self.seq["ip"]), "project": proj, "name": name,
                        "description": str(rec.get("description") or ""),
                        "autoCreateSubnetworks": bool(rec.get("autoCreateSubnetworks", False)),
                        "mtu": int(rec.get("mtu") or _gcc.DEFAULT_MTU),
                        "routingMode": str(rec.get("routingMode") or "REGIONAL"),
                        "creationTimestamp": _rfc3339(rec.get("createTime")), "_subnets": []}
                return self.networks[key]

            for rec in items("networks"):
                ensure_net(str(rec.get("project") or project), rec["name"], rec)
            for rec in items("subnetworks"):
                proj, region = str(rec.get("project") or project), str(rec.get("region") or _gcc.DEFAULT_REGION)
                key = _gcc._sub_key(proj, region, rec["name"])
                if key in self.subnetworks:
                    continue
                net = ensure_net(proj, net_name(rec.get("network")))
                cidr = str(rec.get("ipCidrRange") or "10.0.0.0/24")
                gw = rec.get("gatewayAddress")
                if not gw:
                    import ipaddress
                    try:
                        gw = str(ipaddress.ip_network(cidr, strict=False).network_address + 1)
                    except ValueError:
                        gw = ""
                self.seq["ip"] += 1
                self.subnetworks[key] = {
                    "id": str(rec.get("id") or 20_000 + self.seq["ip"]), "project": proj, "region": region,
                    "name": rec["name"], "description": str(rec.get("description") or ""),
                    "networkName": net["name"], "ipCidrRange": cidr, "gatewayAddress": gw,
                    "privateIpGoogleAccess": bool(rec.get("privateIpGoogleAccess", False)),
                    "stackType": str(rec.get("stackType") or "IPV4_ONLY"), "ipv6CidrRange": "",
                    "flowLogs": False, "creationTimestamp": _rfc3339(rec.get("createTime"))}
                net.setdefault("_subnets", []).append({"region": region, "name": rec["name"]})
            for rec in items("firewalls"):
                proj = str(rec.get("project") or project)
                key = _gcc._fw_key(proj, rec["name"])
                if key in self.firewalls:
                    continue
                net = ensure_net(proj, net_name(rec.get("network")))
                self.seq["ip"] += 1
                self.firewalls[key] = {
                    "id": str(rec.get("id") or 30_000 + self.seq["ip"]), "project": proj, "name": rec["name"],
                    "description": str(rec.get("description") or ""), "networkName": net["name"],
                    "priority": int(rec.get("priority") or 1000), "direction": str(rec.get("direction") or "INGRESS"),
                    "disabled": bool(rec.get("disabled", False)),
                    "logEnable": bool((rec.get("logConfig") or {}).get("enable", False)),
                    "sourceRanges": rec.get("sourceRanges") or [], "destinationRanges": rec.get("destinationRanges") or [],
                    "targetTags": rec.get("targetTags") or [], "sourceTags": rec.get("sourceTags") or [],
                    "allowed": rec.get("allowed") if rec.get("allowed") else None,
                    "denied": rec.get("denied") if rec.get("denied") else None,
                    "creationTimestamp": _rfc3339(rec.get("createTime"))}
            for rec in items("routes"):
                proj = str(rec.get("project") or project)
                key = _gcc._route_key(proj, rec["name"])
                if key in self.routes:
                    continue
                net = ensure_net(proj, net_name(rec.get("network")))
                self.seq["ip"] += 1
                self.routes[key] = {
                    "id": str(rec.get("id") or 40_000 + self.seq["ip"]), "project": proj, "name": rec["name"],
                    "description": str(rec.get("description") or ""), "networkName": net["name"],
                    "destRange": str(rec.get("destRange") or "0.0.0.0/0"), "priority": int(rec.get("priority") or 1000),
                    "tags": rec.get("tags") or [], "nextHop": _gcc._next_hop_fields(proj, rec),
                    "creationTimestamp": _rfc3339(rec.get("createTime"))}
        except Exception as exc:
            _log.warning("compute vpc: pre-v4 adoption skipped: %s", exc)


_LEGACY_VM_STATUS = {"running": _gci.RUNNING, "pending": _gci.RUNNING, "starting": _gci.RUNNING,
                     "provisioning": _gci.RUNNING, "stopped": _gci.TERMINATED, "stopping": _gci.TERMINATED,
                     "suspended": _gci.SUSPENDED}


class AppStateComputeVmStore(_SlotStore, _gci.ComputeStore):
    """gcp_compute_instances_core (instances, disks, images, snapshots, machine images,
    instance templates, instance groups, health checks) store over the appliance's
    space-scoped GCP state."""

    _KEYS = {"instances": dict, "disks": dict, "images": dict, "snapshots": dict,
             "machine_images": dict, "instance_templates": dict, "instance_groups": dict,
             "health_checks": dict, "operations": dict, "project_metadata": dict,
             "seq": lambda: {"op": 0, "id": 1000}}

    def __init__(self, proxy):
        self._bind(proxy)

    instances = _slot_attr("instances")
    disks = _slot_attr("disks")
    images = _slot_attr("images")
    snapshots = _slot_attr("snapshots")
    machine_images = _slot_attr("machine_images")
    instance_templates = _slot_attr("instance_templates")
    instance_groups = _slot_attr("instance_groups")
    health_checks = _slot_attr("health_checks")
    operations = _slot_attr("operations")
    project_metadata = _slot_attr("project_metadata")
    seq = _slot_attr("seq")

    def adopt(self, project: str) -> None:
        """Import (once per space) the pre-v4 gcp_compute_state: disks, images, snapshots,
        instance groups and instances. An adopted instance keeps its real runtime: the
        core record links the pre-v4 runtime record (`_runtimeId`)."""
        if not self._begin_adoption():
            return
        try:
            from core.app_context import gcp_compute_state as legacy

            def items(kind):
                d = legacy.get(kind)
                return [(k, r) for k, r in (d.items() if isinstance(d, dict) else []) if isinstance(r, dict)]

            def zone_of(rec):
                z = _gci._last(rec.get("zone") or rec.get("az") or "")
                return z if z in _gci.ZONE_REGION else _gci.DEFAULT_ZONE

            def name_ok(n):
                return bool(n) and bool(_gci._NAME.match(n))

            for _, d in items("disks"):
                proj, zone, name = str(d.get("project") or project), zone_of(d), str(d.get("name") or "")
                full = "projects/%s/zones/%s/disks/%s" % (proj, zone, name)
                if not name_ok(name) or full in self.disks:
                    continue
                dtype = _gci._last(d.get("type") or "")
                _, rec = _gci._insert_disk_record(self, proj, zone, name, {
                    "sizeGb": d.get("sizeGb") or _gci.DEFAULT_DISK_GB,
                    "type": dtype if dtype in _gci.DISK_TYPES else _gci.DEFAULT_DISK_TYPE,
                    "sourceImage": d.get("sourceImage") or None, "sourceSnapshot": d.get("sourceSnapshot") or None,
                    "labels": d.get("labels") or {}})
                rec["creationTimestamp"] = _rfc3339(d.get("createTime") or d.get("creationTimestamp"))
            for _, im in items("images"):
                proj, name = str(im.get("project") or project), str(im.get("name") or "")
                if name_ok(name) and "projects/%s/global/images/%s" % (proj, name) not in self.images:
                    try:
                        _gci.insert_image(self, proj, {"name": name, "description": im.get("description", ""),
                                                       "labels": im.get("labels") or {}})
                    except Exception:
                        pass
            for _, sn in items("snapshots"):
                proj, name = str(sn.get("project") or project), str(sn.get("name") or "")
                full = "projects/%s/global/snapshots/%s" % (proj, name)
                if not name_ok(name) or full in self.snapshots:
                    continue
                self.snapshots[full] = {
                    "id": _gci._next_id(self), "name": name, "kind": "compute#snapshot", "status": "READY",
                    "sourceDisk": sn.get("sourceDisk") or "", "diskSizeGb": str(sn.get("diskSizeGb") or _gci.DEFAULT_DISK_GB),
                    "storageBytes": str(sn.get("storageBytes") or 0), "snapshotType": "STANDARD",
                    "creationTimestamp": _rfc3339(sn.get("createTime")), "labels": sn.get("labels") or {},
                    "selfLink": _gci._selflink(full), "storageLocations": sn.get("storageLocations") or [_gci.DEFAULT_REGION]}
            for iid, inst in items("instances"):
                state = str(inst.get("state") or "").lower()
                proj, zone, name = str(inst.get("project") or project), zone_of(inst), str(inst.get("name") or "")
                full = "projects/%s/zones/%s/instances/%s" % (proj, zone, name)
                if state not in _LEGACY_VM_STATUS or not name_ok(name) or full in self.instances:
                    continue
                disks = []
                for dn in inst.get("attached_disk_names") or []:
                    if "projects/%s/zones/%s/disks/%s" % (proj, zone, dn) in self.disks:
                        disks.append({"source": "projects/%s/zones/%s/disks/%s" % (proj, zone, dn),
                                      "boot": not disks, "autoDelete": True})
                if not disks:
                    disks = [{"boot": True, "autoDelete": True, "initializeParams": {
                        "diskName": name, "diskSizeGb": str(inst.get("storage_gb") or _gci.DEFAULT_DISK_GB),
                        "sourceImage": inst.get("ami") or None}}]
                mt = _gci._last(inst.get("machine_type") or inst.get("machineType") or "")
                tags = inst.get("tags")
                md = inst.get("metadata_items") if isinstance(inst.get("metadata_items"), dict) else {}
                _gci.insert_instance(self, proj, zone, {
                    "name": name, "machineType": mt if mt in _gci.MACHINE_SHAPES else "e2-medium",
                    "disks": disks, "labels": inst.get("labels") or {},
                    "tags": {"items": list(tags) if isinstance(tags, list) else []},
                    "metadata": {"items": [{"key": k, "value": v} for k, v in md.items()]},
                    "networkInterfaces": [{"networkIP": inst.get("private_ip") or None,
                                           **({"accessConfigs": [{"type": "ONE_TO_ONE_NAT", "name": "External NAT",
                                                                 "natIP": inst["public_ip"]}]} if inst.get("public_ip") else {"accessConfigs": []})}],
                })
                rec = self.instances[full]
                rec["status"] = _LEGACY_VM_STATUS[state]
                rec["creationTimestamp"] = _rfc3339(inst.get("created"))
                rec["_runtimeId"] = iid
            for _, g in items("instance_groups"):
                proj, zone, name = str(g.get("project") or project), zone_of(g), str(g.get("name") or "")
                full = "projects/%s/zones/%s/instanceGroups/%s" % (proj, zone, name)
                if not name_ok(name) or full in self.instance_groups:
                    continue
                _gci.insert_instance_group(self, proj, zone, {"name": name, "description": g.get("description", "")})
                grp = self.instance_groups[full]
                grp["members"] = [m for m in (g.get("instances") or [])
                                  if "projects/%s/zones/%s/instances/%s" % (proj, zone, m) in self.instances]
                grp["size"] = len(grp["members"])
            self.operations.clear()   # the adoption's own bookkeeping operations
        except Exception as exc:
            _log.warning("compute engine: pre-v4 adoption skipped: %s", exc)


# ── v4 C0e: SQS + SNS + EventBridge (+ Scheduler) — ONE messaging store ────────────
from core.messaging_store import MessagingStore   # noqa: E402

_EB_FACTORY = lambda: {"buses": {}, "rules": {}, "archives": {}, "replays": {}, "meta": {}}   # noqa: E731


def _iso_epoch(ts, default: float | None = None) -> float:
    """Pre-v4 SQS timestamps are ISO strings ("2026-10-30T10:00:00.000Z")."""
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts or "").strip()
    if s:
        from datetime import datetime, timezone
        for fmt, n in (("%Y-%m-%dT%H:%M:%S.%f", 26), ("%Y-%m-%dT%H:%M:%S", 19)):
            try:
                return datetime.strptime(s.replace("Z", "")[:n], fmt).replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                continue
    return time.time() if default is None else default


def _unified(service: str) -> bool:
    try:
        from core import wire_ingress
        return wire_ingress.is_unified(service)
    except Exception:
        return False


class AppStateMessagingStore(MessagingStore):
    """The store sqs_core + sns_core + eventbridge_core share on the offline appliance
    (on Nano they share one InMemoryMessagingStore the same way), so an EventBridge rule's
    SQS / SNS targets and an SNS topic's SQS subscriptions are real, receivable deliveries.

    Every attribute resolves, per access, into the active space's persisted state:
        queues                     -> service_states["sqs"]["queues"]     (pre-v4 SQS slot; records
                                      converted to the core shape on adoption)
        topics / sns               -> service_states["sns"]["topics" | "extra"]  (already core-shaped:
                                      SNS has run on sns_core offline since v3)
        event_buses / event_rules / event_archives / event_replays
                                   -> service_states["eventbridge"]["buses" | "rules" | "archives" | "replays"]
        sqs_move_tasks             -> service_states["sqs"]["move_tasks"]
    """

    def __init__(self, account_id: str):
        # NB: no super().__init__() — the dicts are the space's persisted slots.
        self.account_id = account_id
        self._clock = None
        self._adopted: set = set()

    # ── state slots ──────────────────────────────────────────────────────
    @staticmethod
    def _sqs():
        from core import app_context as ctx
        return ctx.sqs_state

    @staticmethod
    def _sns():
        from core import app_context as ctx
        return ctx.sns_state

    @staticmethod
    def _eb() -> dict:
        slot = _proxy("eventbridge", _EB_FACTORY, None)._target()
        for k, f in _EB_FACTORY().items():
            slot.setdefault(k, f)
        return slot

    queues = property(lambda self: self._sqs().setdefault("queues", {}))
    topics = property(lambda self: self._sns().setdefault("topics", {}))
    sqs_move_tasks = property(lambda self: self._sqs().setdefault("move_tasks", {}))
    event_buses = property(lambda self: self._eb()["buses"])
    event_rules = property(lambda self: self._eb()["rules"])
    event_archives = property(lambda self: self._eb()["archives"])
    event_replays = property(lambda self: self._eb()["replays"])

    @property
    def sns(self):
        return self._sns().setdefault("extra", {})

    @sns.setter
    def sns(self, v):
        self._sns()["extra"] = v

    def persist(self) -> None:
        """No-op: the tier middleware persists the kernel state after every mutating
        request (every slot above lives inside it)."""

    # ── queue URLs an SDK can POST back to (`<endpoint>/<account>/<queue>`) ────
    def queue_url_for(self, name: str) -> str:
        return f"{request_base()}/{self.account_id}/{name}"

    # ── cross-service hooks ──────────────────────────────────────────────
    @property
    def deliver_sqs(self):
        """None while SQS is unified (the queues are this store's: the cores enqueue
        directly); opted out, deliveries go to the pre-v4 SQS handler's queues."""
        if _unified("sqs"):
            return None
        return _legacy_deliver_sqs

    def deliver_lambda(self, arn: str, event: dict) -> bool:
        """EventBridge / Scheduler Lambda targets: the appliance's Lambda functions
        (server.py's registry, which the classic console and `/2015-03-31/functions`
        create into) — else the net-new lambda_core router's functions."""
        name = str(arn).split(":function:", 1)[-1].split(":", 1)[0]
        if _unified("lambda"):   # C0f: the appliance's functions ARE the lambda_core store
            try:
                from routes import aws_lambda_unified as _lu
                return _lu.deliver(arn, event)
            except Exception as exc:
                _log.warning("eventbridge: lambda target %s not invoked: %s", name, exc)
                return False
        try:
            import server as _srv
            if _srv._lambda_find_function(name):
                _srv._lambda_invoke_function(name, event, invocation_type="Event", source="events.amazonaws.com")
                return True
        except Exception as exc:
            _log.warning("eventbridge: lambda target %s not invoked: %s", name, exc)
        try:
            from core import lambda_core, wire_ingress
            r = wire_ingress.new_services_router()
            if r is not None:
                return bool(lambda_core.invoke_by_arn(r.lam, arn, event))
        except Exception:
            pass
        return False

    def enqueue_delivery(self, job: dict) -> bool:
        """SNS push deliveries (HTTP/S, Lambda, email) → the JetStream-backed workers."""
        try:
            from routes.aws_sns import DELIVERY
            return DELIVERY.enqueue(job)
        except Exception:
            return False

    def eventbridge_notify(self, kind: str, *args) -> None:
        """Keep the pre-v4 NATS subjects (`aws.eventbridge.<bus>.<source>` per event,
        `aws.eventbridge.rule.<rule>.<target>` per matched target) for tooling that
        tails them (/__nats/inbox, the e2e suites)."""
        try:
            from core import nats_client as nc
        except Exception:
            return
        if kind == "put":
            bus, env = args
            nc.publish(f"aws.eventbridge.{bus}.{env.get('source', '')}", env)
        elif kind == "target":
            rule, tid, env = args
            nc.publish(f"aws.eventbridge.rule.{rule}.{tid or 'default'}", env)

    # ── upgrade path: pre-v4 state → this store, once per space ───────────
    def adopt(self) -> None:
        if _unified("sqs"):
            self._adopt_sqs()
        if _unified("events"):
            self._adopt_eventbridge()

    def _adopt_sqs(self) -> None:
        sqs = self._sqs()
        meta = sqs.setdefault("engine", {})
        key = ("sqs", id(sqs._target() if hasattr(sqs, "_target") else sqs))
        if key in self._adopted:
            return
        self._adopted.add(key)
        if not meta.get("adopted"):
            meta["adopted"] = _http_date()
            try:
                _adopt_elasticmq_queues(self)
            except Exception as exc:
                _log.warning("sqs: ElasticMQ adoption skipped: %s", exc)
        n = 0
        for name, q in list(self.queues.items()):
            if isinstance(q, dict) and "created_epoch" not in q:
                adopt_legacy_queue(self, name, q)
                n += 1
        if n:
            _log.info("sqs: adopted %d pre-v4 queues", n)

    def _adopt_eventbridge(self) -> None:
        slot = self._eb()
        if slot["meta"].get("adopted"):
            return
        slot["meta"]["adopted"] = _http_date()
        try:
            adopt_legacy_eventbridge(self, _legacy_extras_items(), _legacy_nats_rules())
        except Exception as exc:
            _log.warning("eventbridge: pre-v4 adoption skipped: %s", exc)


def _legacy_deliver_sqs(arn, body, attrs, group, dedup) -> bool:
    try:
        import server as s
        q = s._sqs_queue_from_name_or_url(str(arn).rsplit(":", 1)[-1])
        if q is None:
            return False
        s._sqs_enqueue_message(q, body, None, attrs or {}, group or "", dedup or "", source="events")
        return True
    except Exception:
        return False


def adopt_legacy_queue(store, name: str, q: dict) -> dict:
    """Convert a pre-v4 SQS queue record (server.py `_sqs_*` shape: ISO timestamps,
    `fifo_queue`, a `redrive_policy` dict, `group_id` / `dedup_id` on messages) IN PLACE
    into the sqs_core shape, keeping its messages (with their receive counts and any
    still-running visibility lease)."""
    now = store.now()
    attrs = {str(k): str(v) for k, v in dict(q.get("attributes") or {}).items()}
    fifo = bool(q.get("fifo_queue") or str(name).endswith(".fifo"))
    for key, field, default in (("VisibilityTimeout", "visibility_timeout", 30), ("DelaySeconds", "delay_seconds", 0),
                                ("MessageRetentionPeriod", "message_retention_period", 345600),
                                ("MaximumMessageSize", "max_message_size", 262144),
                                ("ReceiveMessageWaitTimeSeconds", "receive_wait_time_seconds", 0)):
        attrs.setdefault(key, str(int(q.get(field, default) or default)))
    rp = q.get("redrive_policy") or {}
    if isinstance(rp, str):
        try:
            rp = json.loads(rp)
        except Exception:
            rp = {}
    if rp:
        rp = dict(rp)
        if "deadLetterTargetArn" not in rp and rp.get("deadLetterTargetQueueArn"):
            rp["deadLetterTargetArn"] = rp.pop("deadLetterTargetQueueArn")
        attrs.setdefault("RedrivePolicy", json.dumps(rp, separators=(",", ":")))
    if fifo:
        attrs["FifoQueue"] = "true"
        attrs["ContentBasedDeduplication"] = "true" if q.get("content_based_deduplication") else "false"
    msgs = []
    for m in q.get("messages") or []:
        if not isinstance(m, dict) or m.get("deleted"):
            continue
        sent = _iso_epoch(m.get("sent_at"), now)
        vis = _iso_epoch(m.get("visible_at"), sent) if m.get("visible_at") else sent
        msgs.append({
            "message_id": m.get("message_id") or "msg-" + uuid.uuid4().hex,
            "body": m.get("body", ""), "md5_of_body": m.get("md5_of_body") or hashlib.md5(
                str(m.get("body", "")).encode("utf-8")).hexdigest(),
            "message_attributes": m.get("message_attributes") or {},
            "sent_at": m.get("sent_at") or _http_date(), "sent_epoch": sent,
            "visible_at": vis, "receive_count": int(m.get("receive_count", 0) or 0),
            "receipt_handle": m.get("receipt_handle", "") if m.get("in_flight") else "",
            "in_flight": bool(m.get("in_flight")), "deleted": False,
            "message_group_id": m.get("group_id") or None, "message_dedup_id": m.get("dedup_id") or None,
            **({"sequence_number": str(m["sequence_number"]).zfill(20)} if fifo and m.get("sequence_number") else {}),
        })
    created = _iso_epoch(q.get("created"), now)
    q.update({
        "queue_name": name, "queue_arn": q.get("queue_arn") or f"arn:aws:sqs:us-east-1:{store.account_id}:{name}",
        "attributes": attrs, "visibility_timeout": int(attrs["VisibilityTimeout"]),
        "delay_seconds": int(attrs["DelaySeconds"]), "tags": dict(q.get("tags") or {}),
        "messages": msgs, "created": q.get("created") or _http_date(), "created_epoch": created,
        "last_modified_epoch": _iso_epoch(q.get("last_modified"), created), "fifo": fifo,
        "content_based_dedup": bool(q.get("content_based_deduplication")),
        "dedup_seen": {}, "sequence": len(msgs),
    })
    return q


def _legacy_extras_items() -> dict:
    """The classic console's pre-v4 EventBridge rows (service_states["aws_extras"]),
    minus the demo seed rows it injected into every space."""
    from core.aws_rail_extras import EXTRAS
    out = {}
    extras = _proxy("aws_extras", dict, None)._target()
    for stub in ("eventbridge/rules", "eventbridge/event-buses", "eventbridge/archives"):
        seeds = {s.get("name") for s in (EXTRAS.get(stub) or {}).get("seed") or []}
        items = ((extras.get(stub) or {}).get("items") or {}) if isinstance(extras, dict) else {}
        out[stub] = {k: v for k, v in items.items() if isinstance(v, dict) and k not in seeds}
    return out


def _legacy_nats_rules() -> tuple[dict, dict]:
    try:
        from core import nats_routes as nr
        return dict(nr._eventbridge_rules), {k: list(v) for k, v in nr._eventbridge_targets.items()}
    except Exception:
        return {}, {}


def adopt_legacy_eventbridge(store, extras: dict, nats: tuple[dict, dict]) -> dict:
    """Import pre-v4 EventBridge state into the core's store: the classic console's
    event buses / rules (+ their one target) / archives, and the rules + targets the
    pre-v4 wire handler (core/nats_routes.py) held in process memory."""
    from core import eventbridge_core as ebc
    T = "AWSEvents."
    n = {"buses": 0, "rules": 0, "targets": 0, "archives": 0}

    def call(op, body):
        return ebc.dispatch(store, T + op, body)

    for name, it in (extras.get("eventbridge/event-buses") or {}).items():
        if name != "default" and call("CreateEventBus", {"Name": name}).status == 200:
            n["buses"] += 1
    for name, it in (extras.get("eventbridge/rules") or {}).items():
        bus = str(it.get("event_bus_name") or "default")
        if bus not in ebc._buses(store):
            call("CreateEventBus", {"Name": bus})
        req = {"Name": name, "EventBusName": bus, "State": str(it.get("state") or "ENABLED")}
        if str(it.get("rule_type")) == "Schedule":
            req["ScheduleExpression"] = str(it.get("schedule_expression") or it.get("schedule") or "rate(1 day)")
        elif it.get("event_pattern"):
            req["EventPattern"] = it["event_pattern"] if isinstance(it["event_pattern"], str) else json.dumps(it["event_pattern"])
        if req["State"] not in ("ENABLED", "DISABLED"):
            req["State"] = "ENABLED"
        if call("PutRule", req).status != 200:
            continue
        n["rules"] += 1
        if it.get("target_arn") and str(it["target_arn"]) not in ("—", "-"):
            call("PutTargets", {"Rule": name, "EventBusName": bus, "Targets": [{"Id": "Target0", "Arn": it["target_arn"]}]})
            n["targets"] += 1
    for name, it in (extras.get("eventbridge/archives") or {}).items():
        src = str(it.get("event_source") or "")
        if src in ("", "—", "-"):
            src = ebc._bus_arn(store, "default")
        if call("CreateArchive", {"ArchiveName": name, "EventSourceArn": src,
                                  "RetentionDays": int(it.get("retention_days") or 0)}).status == 200:
            n["archives"] += 1
    rules, targets = nats
    for name, r in (rules or {}).items():
        bus = str(r.get("EventBusName") or "default")
        if bus not in ebc._buses(store):
            call("CreateEventBus", {"Name": bus})
        req = {"Name": name, "EventBusName": bus, "State": r.get("State") or "ENABLED",
               "Description": r.get("Description") or ""}
        if r.get("EventPattern"):
            pat = r["EventPattern"]
            req["EventPattern"] = pat if isinstance(pat, str) else json.dumps(pat)
        if r.get("ScheduleExpression"):
            req["ScheduleExpression"] = r["ScheduleExpression"]
        if call("PutRule", req).status != 200:
            continue
        n["rules"] += 1
        tg = [t for t in (targets or {}).get(name, []) if isinstance(t, dict) and t.get("Arn")]
        if tg:
            call("PutTargets", {"Rule": name, "EventBusName": bus, "Targets": tg})
            n["targets"] += len(tg)
    if any(n.values()):
        _log.info("eventbridge: adopted pre-v4 %s", n)
    return n


def _adopt_elasticmq_queues(store, fetch=None) -> int:
    """Pre-v4 Query-protocol SQS calls went to ElasticMQ when it ran, so a queue may exist
    only there. Import those queue DEFINITIONS (name + attributes). Their messages are not
    read: an SQS receive is destructive (it would lease them), and ElasticMQ is in-memory
    — the appliance re-seeded it from this same state at boot."""
    import xml.etree.ElementTree as ET
    if fetch is None:
        from core import elasticmq_proxy as emq
        if not emq.available():
            return 0
        import urllib.parse
        import urllib.request

        def fetch(params):
            url = emq._EMQ_URL + "/?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(url, timeout=3) as r:
                return r.read()

    def _strip(tag):
        return tag.rsplit("}", 1)[-1]

    root = ET.fromstring(fetch({"Action": "ListQueues"}))
    urls = [el.text or "" for el in root.iter() if _strip(el.tag) == "QueueUrl"]
    from core import sqs_core
    n = 0
    for url in urls:
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if not name or store.queue_exists(name):
            continue
        attrs = {}
        try:
            ar = ET.fromstring(fetch({"Action": "GetQueueAttributes", "QueueUrl": url, "AttributeName.1": "All"}))
            for el in ar.iter():
                if _strip(el.tag) == "Attribute":
                    kv = {_strip(c.tag): c.text or "" for c in el}
                    if kv.get("Name") in ("VisibilityTimeout", "DelaySeconds", "MessageRetentionPeriod",
                                          "MaximumMessageSize", "ReceiveMessageWaitTimeSeconds", "RedrivePolicy",
                                          "FifoQueue", "ContentBasedDeduplication"):
                        attrs[kv["Name"]] = kv.get("Value", "")
        except Exception:
            pass
        if sqs_core.dispatch(store, "AmazonSQS.CreateQueue", {"QueueName": name, "Attributes": attrs}).status == 200:
            n += 1
    return n


class AppStateSchedulerStore:
    """scheduler_core store over service_states["scheduler"]{groups,schedules}."""

    def _slot(self) -> dict:
        from core import scheduler_core as sc
        slot = _proxy("scheduler", lambda: {"groups": {}, "schedules": {}}, None)._target()
        groups = slot.setdefault("groups", {})
        if "default" not in groups:
            groups["default"] = sc.SchedulerStore().groups["default"]
        slot.setdefault("schedules", {})
        return slot

    groups = property(lambda self: self._slot()["groups"])
    schedules = property(lambda self: self._slot()["schedules"])


# ── the request's endpoint (for queue URLs an SDK can POST back to) ─────────
import contextvars as _cv   # noqa: E402

_REQUEST_BASE: "_cv.ContextVar[str]" = _cv.ContextVar("vyomi_request_base", default="")


def set_request_base(headers: dict) -> None:
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    host = h.get("x-forwarded-host") or h.get("host") or ""
    if host:
        proto = (h.get("x-forwarded-proto") or "http").split(",")[0].strip()
        _REQUEST_BASE.set(f"{proto}://{host}")


def request_base() -> str:
    import os
    return _REQUEST_BASE.get() or os.environ.get("VYOMI_PUBLIC_URL", "http://localhost:9000").rstrip("/")


# ── singletons ─────────────────────────────────────────────────────────────
_S3 = _GCS = _DDB = _AZB = _GSEC = _GKMS = _AKMS = _ASEC = None
_GFS = _GVPC = _GVM = None
_MSG = _SCHED = None


def messaging_store() -> AppStateMessagingStore:
    global _MSG
    if _MSG is None:
        from core import app_context as ctx
        _MSG = AppStateMessagingStore(account_id=ctx.AWS_ACCOUNT_ID)
    return _MSG


def scheduler_store() -> AppStateSchedulerStore:
    global _SCHED
    if _SCHED is None:
        _SCHED = AppStateSchedulerStore()
    return _SCHED


def s3_store() -> AppStateObjectStore:
    global _S3
    if _S3 is None:
        from core import app_context as ctx
        from core import minio_mirror as mm
        gate = _MirrorGate(f"MinIO ({mm._MINIO_URL})", mm.available)

        def put(bucket, key, data, ct, meta):
            if gate.ok():
                mm.put_object(bucket, key, data, content_type=ct, metadata=meta)

        def delete(bucket, key):
            if gate.ok():
                mm.delete_object(bucket, key)

        def fetch(bucket, key):
            return mm.get_object(bucket, key) if gate.ok() else None

        def events(bucket, key, event_name, version, source):
            from routes import aws_s3
            aws_s3._s3_emit_event(bucket, key, event_name, version, source=source)

        def storage_cap(n):
            import server
            server._enforce_storage_cap(n)

        def quantity_cap(kind):
            import server
            server._enforce_quantity_cap(kind)

        _S3 = AppStateObjectStore(ctx.buckets, ctx.objects, ctx.multiparts, mirror=(put, delete),
                                  events=events, fetch=fetch, storage_cap=storage_cap,
                                  quantity_cap=quantity_cap)
    return _S3


def gcs_store() -> AppStateObjectStore:
    global _GCS
    if _GCS is None:
        from core import app_context as ctx
        from core import gcp_gcs_store as gs
        factory = ctx.gcp_storage_state.default_factory
        gate = _MirrorGate("fake-gcs-server (CLOUDLEARN_GCS_URL)",
                           lambda: gs.available() and gs._base().startswith(("http://", "https://")))

        def put(bucket, key, data, ct, meta):
            if gate.ok():
                import urllib.parse
                gs.upload(ctx.tenant_scoped_bucket(bucket),
                          "uploadType=media&name=" + urllib.parse.quote(key, safe=""), data, ct)

        def delete(bucket, key):
            if gate.ok():
                gs.delete(ctx.tenant_scoped_bucket(bucket), key)

        def fetch(bucket, key):
            # pre-v4 objects: metadata in the state, bytes only in fake-gcs
            return gs.download(ctx.tenant_scoped_bucket(bucket), key)[0] if gate.ok() else None

        _GCS = AppStateObjectStore(_proxy("gcp_storage", factory, "buckets"),
                                   _proxy("gcp_storage", factory, "objects"),
                                   mirror=(put, delete), fetch=fetch)
    return _GCS


def ddb_store() -> AppStateNoSqlStore:
    global _DDB
    if _DDB is None:
        from core import app_context as ctx
        _DDB = AppStateNoSqlStore(_proxy("dynamodb", ctx.ddb_state.default_factory, "tables"),
                                  account_id=ctx.AWS_ACCOUNT_ID,
                                  backups=_proxy("dynamodb", ctx.ddb_state.default_factory, "backups"))
    return _DDB


def az_blob_store() -> AppStateAzureBlobStore:
    global _AZB
    if _AZB is None:
        factory = lambda: {"containers": {}, "blobs": {}}   # noqa: E731
        try:
            from core import azure_blob_store as azurite
        except Exception:
            azurite = None
        _AZB = AppStateAzureBlobStore(_proxy("azure_blob", factory, "containers"),
                                      _proxy("azure_blob", factory, "blobs"), azurite=azurite)
    return _AZB


def gcp_secrets_store() -> AppStateKvStore:
    global _GSEC
    if _GSEC is None:
        from core import app_context as ctx
        _GSEC = AppStateKvStore(_proxy("gcp_secretmanager", lambda: {"secrets": {}}, "secrets"),
                                account_id=ctx.AWS_ACCOUNT_ID)
    return _GSEC


def gcp_kms_store() -> AppStateKeyStore:
    global _GKMS
    if _GKMS is None:
        from core import app_context as ctx
        factory = lambda: {"keys": {}, "material": {}, "aliases": {}, "rings": {}}   # noqa: E731
        _GKMS = AppStateKeyStore(_proxy("gcp_kms", factory, "keys"), _proxy("gcp_kms", factory, "material"),
                                 _proxy("gcp_kms", factory, "aliases"), _proxy("gcp_kms", factory, "rings"),
                                 account_id=ctx.AWS_ACCOUNT_ID)
    return _GKMS


def aws_kms_store() -> AppStateAwsKeyStore:
    global _AKMS
    if _AKMS is None:
        from core import app_context as ctx
        factory = lambda: {"keys": {}, "material": {}, "aliases": {}, "custom_key_stores": {}}   # noqa: E731
        _AKMS = AppStateAwsKeyStore(_proxy("kms", factory, "keys"), _proxy("kms", factory, "material"),
                                    _proxy("kms", factory, "aliases"),
                                    _proxy("kms", factory, "custom_key_stores"),
                                    account_id=ctx.AWS_ACCOUNT_ID)
    return _AKMS


def aws_secrets_store() -> AppStateAwsKvStore:
    global _ASEC
    if _ASEC is None:
        from core import app_context as ctx
        _ASEC = AppStateAwsKvStore(_proxy("secretsmanager", lambda: {"secrets": {}}, "secrets"),
                                   account_id=ctx.AWS_ACCOUNT_ID)
    return _ASEC


def gcp_firestore_store() -> AppStateFirestoreStore:
    global _GFS
    if _GFS is None:
        _GFS = AppStateFirestoreStore(_proxy("gcp_firestore_engine", dict, None))
    return _GFS


def gcp_compute_vpc_store() -> AppStateComputeVpcStore:
    global _GVPC
    if _GVPC is None:
        _GVPC = AppStateComputeVpcStore(_proxy("gcp_compute_vpc", dict, None))
    return _GVPC


def gcp_compute_vm_store() -> AppStateComputeVmStore:
    global _GVM
    if _GVM is None:
        _GVM = AppStateComputeVmStore(_proxy("gcp_compute_vm", dict, None))
    return _GVM


# ── v4 C0f: AWS Lambda, Azure Key Vault, Azure Container Registry ─────────────────────
#
#   Lambda          functions / layers / event-source mappings / … (core/lambda_core.py shapes)
#                                            -> service_states["lambda"]{functions,layers,esms,…}
#                   (the pre-v4 snake_case records in "functions" / "layers" are converted IN
#                    PLACE once per space, so every v3 consumer of that slot — inventory, cost,
#                    the space summary — keeps counting the same functions). Invoke runs the
#                    code in the appliance's REAL runtime (a separate Python process with the
#                    function's environment / timeout / layers), installed by
#                    routes/aws_lambda_unified.py as the store's `run_function` hook.
#   Key Vault       secrets / certificates / keys + material
#                                            -> service_states["azure_azure_keyvault"]
#                   {secrets,certificates,keys,material,aliases,rings,meta}
#                   (pre-v4: Vault KV / RSA keys under `{vault}__{name}`, adopted once per space)
#   ACR             repositories / tags / manifests
#                                            -> service_states["azure_azure_acr"]{repos}

_LAMBDA_KEYS = ("functions", "layers", "esms", "capacity_providers", "code_signing_configs",
                "network_connectors", "microvm_images", "microvms", "applications")
_LAMBDA_RUNNER = None   # set by routes/aws_lambda_unified.py: (fn, event, context) -> dict


def set_lambda_runner(fn) -> None:
    global _LAMBDA_RUNNER
    _LAMBDA_RUNNER = fn


def _lam_attr(key: str):
    def _get(self):
        return self._slot()[key]

    def _set(self, value):
        self._slot()[key] = value
    return property(_get, _set)


class AppStateLambdaStore:
    """lambda_core store over the active space's `lambda` slot. lambda_core reaches its
    collections through `_lambda_*` attributes (and reassigns `_lambda_esms`), so each one is
    a read/write property onto the persisted slot. Other attributes (API Gateway v1's, which
    shares this store on the router exactly as on Nano) stay process-local, as before."""

    def _slot(self) -> dict:
        from core import app_context as ctx
        slot = ctx.lambda_state._target()
        for k in _LAMBDA_KEYS:
            if not isinstance(slot.get(k), dict):
                slot[k] = {}
        if not isinstance(slot.get("engine"), dict):
            slot["engine"] = {}
        return slot

    _lambda_functions = _lam_attr("functions")
    _lambda_layers = _lam_attr("layers")
    _lambda_esms = _lam_attr("esms")
    _lambda_capacity_providers = _lam_attr("capacity_providers")
    _lambda_code_signing_configs = _lam_attr("code_signing_configs")
    _lambda_network_connectors = _lam_attr("network_connectors")
    _lambda_microvm_images = _lam_attr("microvm_images")
    _lambda_microvms = _lam_attr("microvms")
    _lambda_applications = _lam_attr("applications")

    @property
    def run_function(self):
        return _LAMBDA_RUNNER

    def persist(self) -> None:
        """No-op: the tier middleware persists the kernel state after every mutating request."""

    def adopt(self) -> None:
        """Convert the pre-v4 records of this space in place, once (marker in slot["engine"])."""
        slot = self._slot()
        if slot["engine"].get("adopted"):
            return
        slot["engine"]["adopted"] = _http_date()
        n = adopt_legacy_lambda(slot)
        if n:
            _log.info("lambda: adopted %d pre-v4 functions/layers", n)


def _lambda_ts(ts) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(_iso_epoch(ts), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _is_legacy_function(rec) -> bool:
    return isinstance(rec, dict) and "source" not in rec and ("code" in rec or "function_arn" in rec)


def _legacy_tags(tags) -> dict:
    if isinstance(tags, dict):
        return {str(k): str(v) for k, v in tags.items()}
    out = {}
    for t in tags or []:
        if isinstance(t, dict) and (t.get("Key") or t.get("key")):
            out[str(t.get("Key") or t.get("key"))] = str(t.get("Value") or t.get("value") or "")
    return out


def adopt_legacy_function(name: str, rec: dict) -> dict:
    """A pre-v4 (server.py / routes/aws_lambda.py) function record → the lambda_core shape."""
    import base64 as _b64
    from core import lambda_core as lc
    source = str(rec.get("code") or "")
    sha = rec.get("code_sha256") or _b64.b64encode(hashlib.sha256(source.encode()).digest()).decode()
    stmts = {}
    for p in rec.get("permissions") or []:
        if not isinstance(p, dict) or not p.get("statement_id"):
            continue
        principal = str(p.get("principal") or "*")
        st = {"Sid": p["statement_id"], "Effect": "Allow", "Action": p.get("action") or "lambda:InvokeFunction",
              "Principal": "*" if principal == "*" else ({"AWS": principal} if principal.startswith("arn:") else {"Service": principal}),
              "Resource": lc._fn_arn(name)}
        cond = {}
        if p.get("source_arn"):
            cond.setdefault("ArnLike", {})["AWS:SourceArn"] = p["source_arn"]
        if p.get("source_account"):
            cond.setdefault("StringEquals", {})["AWS:SourceAccount"] = p["source_account"]
        if cond:
            st["Condition"] = cond
        stmts[p["statement_id"]] = st
    versions, top = {}, 0
    for v in rec.get("versions") or []:
        ver = str((v or {}).get("version", ""))
        if ver.isdigit():
            top = max(top, int(ver))
            versions[ver] = {"source": source, "code_sha256": v.get("code_sha256") or sha,
                             "runtime": v.get("runtime") or rec.get("runtime", "python3.12"),
                             "handler": v.get("handler") or rec.get("handler", "lambda_function.lambda_handler"),
                             "memory_size": int(rec.get("memory_size") or 128), "timeout": int(rec.get("timeout") or 3),
                             "env": dict(rec.get("environment") or {}),
                             "description": v.get("description", ""), "last_modified": _lambda_ts(v.get("created"))}
    invocations = []
    for i in sorted([x for x in rec.get("invocations") or [] if isinstance(x, dict)],
                    key=lambda x: str(x.get("at", "")), reverse=True)[:lc.RECENT_INVOCATIONS_KEPT]:
        row = {"Timestamp": _lambda_ts(i.get("at")), "RequestId": str(i.get("id") or uuid.uuid4().hex),
               "LogStream": "", "DurationInMS": 0, "BilledDurationInMS": 1,
               "MemorySetInMB": int(rec.get("memory_size") or 128), "MemoryUsedInMB": 16,
               "Error": i.get("status") == "error"}
        logs = (i.get("stdout") or "") + (i.get("stderr") or "")
        if logs:
            row["LogTail"] = logs[-4096:]
        if i.get("error"):
            row["ErrorMessage"] = str(i["error"])[:1024]
        invocations.append(row)
    env = rec.get("environment") or {}
    if isinstance(env, dict) and isinstance(env.get("Variables"), dict):
        env = env["Variables"]
    return {
        "name": name, "arn": lc._fn_arn(name), "runtime": rec.get("runtime") or "python3.12",
        "handler": rec.get("handler") or "lambda_function.lambda_handler", "source": source,
        "code_sha256": sha, "env": {str(k): str(v) for k, v in (env or {}).items()},
        "memory_size": int(rec.get("memory_size") or 128), "timeout": int(rec.get("timeout") or 3),
        "role": rec.get("role") or "", "description": rec.get("description") or "",
        "architectures": ["x86_64"], "ephemeral_storage_mb": 512, "snap_start": "None",
        "tags": _legacy_tags(rec.get("tags")), "layers": list(rec.get("layers") or []),
        "vpc_config": None, "dead_letter_config": None, "file_systems": [],
        "recursive_loop": "Terminate", "tracing_mode": "PassThrough", "log_format": "Text",
        "reserved_concurrency": None, "function_url": None, "event_invoke_config": None,
        "policy_statements": stmts, "aliases": {}, "versions": versions, "next_version": top + 1,
        "invocations": invocations, "created": rec.get("created", ""),
        "last_modified": _lambda_ts(rec.get("last_modified") or rec.get("created")),
        "revision_id": uuid.uuid4().hex,
    }


def adopt_legacy_lambda(slot: dict) -> int:
    """Convert a space's pre-v4 Lambda functions + console layers (in place). Returns the count."""
    n = 0
    fns = slot.get("functions") or {}
    for name, rec in list(fns.items()):
        if _is_legacy_function(rec):
            fns[name] = adopt_legacy_function(str(rec.get("function_name") or name), rec)
            n += 1
    layers = slot.get("layers") or {}
    for name, rec in list(layers.items()):
        if isinstance(rec, dict) and "versions" not in rec and ("layer_name" in rec or "code" in rec):
            ver = int(rec.get("latest_version") or 1)
            code = str(rec.get("code") or "")
            layers[name] = {"versions": {ver: {
                "Description": rec.get("description", ""), "CreatedDate": _lambda_ts(rec.get("created")),
                "CompatibleRuntimes": [rec["runtime"]] if rec.get("runtime") else [],
                "CompatibleArchitectures": [], "LicenseInfo": rec.get("license_info") or "",
                "CodeSize": len(code), "Source": code}}, "next_version": ver + 1}
            n += 1
    return n


# ── Azure Key Vault ────────────────────────────────────────────────────────────────────
_KV_FACTORY = lambda: {"secrets": {}, "certificates": {}, "keys": {}, "material": {},   # noqa: E731
                       "aliases": {}, "rings": {}, "meta": {}}


def _kv_slot() -> dict:
    slot = _proxy("azure_keyvault", _KV_FACTORY, None)._target()
    for k, v in _KV_FACTORY().items():
        if not isinstance(slot.get(k), dict):
            slot[k] = v
    return slot


class AppStateAzureKvStore(KvStore):
    """azure_keyvault_secrets_core / _certificates_core store over the space's Key Vault slot."""

    def __init__(self, kind: str):
        self._kind = kind          # "secrets" | "certificates"
        self.account_id = ""

    secrets = property(lambda self: _kv_slot()[self._kind])


class AppStateAzureKeyStore(AppStateKeyStore):
    """azure_keyvault_keys_core store over the space's Key Vault slot (material persisted)."""

    def __init__(self):
        # NB: AppStateKeyStore.__init__ binds fixed dicts; these resolve per access instead.
        self.engine = InMemoryKmsEngine()
        self.account_id = ""
        self._adopted: set = set()

    keys = property(lambda self: _kv_slot()["keys"])
    material = property(lambda self: _kv_slot()["material"])
    aliases = property(lambda self: _kv_slot()["aliases"])
    gcp_key_rings = property(lambda self: _kv_slot()["rings"])

    @property
    def _k(self):
        return self.keys

    @property
    def _m(self):
        return self.material

    def adopt(self, *_a) -> None:
        """Pre-v4 Key Vault data (Vault KV + RSA keys) → this slot, once per space."""
        slot = _kv_slot()
        if slot["meta"].get("adopted"):
            return
        slot["meta"]["adopted"] = _http_date()
        try:
            from core import vault_client as vc
            if not vc.available():
                return
            n = adopt_legacy_keyvault(slot, _active_space_id(), _azure_vault_names(), vc)
            if n:
                _log.info("key vault: adopted %d pre-v4 secrets/keys", n)
        except Exception as exc:
            _log.warning("key vault: pre-v4 adoption skipped: %s", exc)


def _azure_vault_names() -> list:
    """The Key Vault names of this space (ARM Microsoft.KeyVault/vaults records)."""
    try:
        from core import app_context as ctx
        tok = ctx.REQUEST_PROVIDER.set("azure")
        try:
            recs = list(ctx.azure_arm_state.values())
        finally:
            ctx.REQUEST_PROVIDER.reset(tok)
        return sorted({str(r.get("name")) for r in recs if isinstance(r, dict)
                       and str(r.get("_type") or r.get("type") or "").lower() == "microsoft.keyvault/vaults"})
    except Exception:
        return []


def adopt_legacy_keyvault(slot: dict, space_id: str, vaults: list, vc) -> int:
    """Copy the pre-v4 Vault-backed Key Vault state of `vaults` into the core slot. The core
    model is one Key Vault namespace per space (as on Nano), so a name present in two vaults
    keeps the first vault's (sorted) value. Returns the number of secrets + keys adopted."""
    import base64 as _b64
    from core import azure_keyvault_keys_core as kk

    def _idx(vault, kind):
        got = vc.kv_get("azure", space_id, f"__idx__{vault}__{kind}")
        raw = ((got or {}).get("data") or {}).get("value", "[]") if got else "[]"
        try:
            return json.loads(raw) if isinstance(raw, str) else list(raw)
        except Exception:
            return []

    n = 0
    now = int(time.time())
    for vault in vaults:
        for name in _idx(vault, "secrets"):
            if name in slot["secrets"]:
                continue
            got = vc.kv_get("azure", space_id, f"{vault}__{name}")
            if not got:
                continue
            data = got.get("data") or {}
            value = data.get("value") if "value" in data else json.dumps(data)
            ver = uuid.uuid4().hex
            slot["secrets"][name] = {"name": name, "current": ver, "deleted": False, "deletedDate": None,
                                     "versions": {ver: {"value": value, "contentType": None, "tags": None,
                                                        "attributes": {"enabled": True, "created": now, "updated": now,
                                                                       "recoveryLevel": "Recoverable+Purgeable"}}}}
            n += 1
        for name in _idx(vault, "keys"):
            if any(isinstance(m, dict) and m.get("name") == name for m in slot["keys"].values()):
                continue
            got = vc.kv_get("azure", space_id, f"{vault}__{name}__rsapriv")
            pem = ((got or {}).get("data") or {}).get("value") if got else None
            if not pem:
                continue
            try:
                from cryptography.hazmat.primitives import serialization
                priv = serialization.load_pem_private_key(pem.encode(), password=None)
                der = priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption())
                nums = priv.public_key().public_numbers()
            except Exception:
                continue
            ver = uuid.uuid4().hex
            meta = {"name": name, "version": ver, "kty": "RSA", "key_size": priv.key_size,
                    "key_ops": ["encrypt", "decrypt", "wrapKey", "unwrapKey", "sign", "verify"],
                    "n": kk._b64url_encode(nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")),
                    "e": kk._b64url_encode(nums.e.to_bytes(3, "big")), "rsa": True,
                    "enabled": True, "created": now, "updated": now,
                    "seq": 1 + max([m.get("seq", 0) for m in slot["keys"].values() if isinstance(m, dict)] or [0])}
            slot["keys"][f"{name}/{ver}"] = meta
            slot["material"][f"{name}/{ver}"] = der
            n += 1
    _ = _b64
    return n


# ── Azure Container Registry ──────────────────────────────────────────────────────────
class AppStateAcrStore:
    """azure_acr_core store over the space's ACR slot (manifest bytes inline, persisted)."""

    @property
    def repos(self) -> dict:
        return _proxy("azure_acr", lambda: {"repos": {}}, "repos")._target()


_LAM = _AZKVSEC = _AZKVCERT = _AZKVKEY = _ACR = None


def lambda_store() -> AppStateLambdaStore:
    global _LAM
    if _LAM is None:
        _LAM = AppStateLambdaStore()
    return _LAM


def az_kv_secrets_store() -> AppStateAzureKvStore:
    global _AZKVSEC
    if _AZKVSEC is None:
        _AZKVSEC = AppStateAzureKvStore("secrets")
    return _AZKVSEC


def az_kv_certs_store() -> AppStateAzureKvStore:
    global _AZKVCERT
    if _AZKVCERT is None:
        _AZKVCERT = AppStateAzureKvStore("certificates")
    return _AZKVCERT


def az_kv_keys_store() -> AppStateAzureKeyStore:
    global _AZKVKEY
    if _AZKVKEY is None:
        _AZKVKEY = AppStateAzureKeyStore()
    return _AZKVKEY


def acr_store() -> AppStateAcrStore:
    global _ACR
    if _ACR is None:
        _ACR = AppStateAcrStore()
    return _ACR


# ── Azure Service Bus (data plane: entities + message backlogs) ───────────────────────
from core.messaging_store import MessagingStore as _MessagingStore   # noqa: E402


class AppStateServiceBusStore(_MessagingStore):
    """azure_servicebus_core store over service_states["azure_azure_servicebus"]{topics}
    (queues and topics are both "entities" there; message bodies inline, persisted)."""

    def __init__(self):
        # NB: no super().__init__() — `topics` is the space's persisted slot.
        self.account_id = ""
        self._clock = None
        self.queues: dict = {}
        self.sns: dict = {}

    @property
    def topics(self) -> dict:
        return _proxy("azure_servicebus", lambda: {"topics": {}}, "topics")._target()

    def persist(self) -> None:
        """No-op: the tier middleware persists the kernel state after every mutating request."""


_AZSB = None


def az_servicebus_store() -> AppStateServiceBusStore:
    global _AZSB
    if _AZSB is None:
        _AZSB = AppStateServiceBusStore()
    return _AZSB


# ── v4 C0g: GCP Pub/Sub (topics / subscriptions / snapshots / schemas) ────────────────
#
#   Pub/Sub         topics / subscriptions (+ each subscription's message backlog) /
#                   snapshots / schemas      -> service_states["gcp_gcp_pubsub"]
#                                               {topics, subscriptions, snapshots, schemas, engine}
#                   The core's records live IN the pre-v4 slot (`gcp_pubsub_state`), keyed by the
#                   full resource name (projects/{p}/topics/{t}), so every v3 reader of that slot —
#                   the space inventory / cost savings, the console summary counts, the tier
#                   quantity cap, the CloudSim scan — counts exactly what the native wire wrote
#                   (one dict, no sync). Pre-v4 records (keyed by the bare id, with `topicId` /
#                   `subscriptionId` / `project`, plus the per-subscription `messages` backlog)
#                   are converted in place on first use; once per space, the Pub/Sub emulator's
#                   topics / subscriptions are adopted when PUBSUB_EMULATOR_HOST is configured.
class AppStatePubsubStore(MessagingStore):
    """gcp_pubsub_core store over the active space's `gcp_pubsub_state` slot."""

    def __init__(self):
        # NB: no super().__init__() — the dicts are the space's persisted slot.
        self.account_id = ""
        self._clock = None
        self.sns: dict = {}

    @staticmethod
    def _slot() -> dict:
        from core.app_context import gcp_pubsub_state
        slot = gcp_pubsub_state._target()
        for k in ("topics", "subscriptions", "snapshots", "schemas", "engine"):
            if not isinstance(slot.get(k), dict):
                slot[k] = {}
        return slot

    topics = property(lambda self: self._slot()["topics"])
    queues = property(lambda self: self._slot()["subscriptions"])
    pubsub = property(lambda self: self._slot())          # {snapshots, schemas} live beside them

    # the message-id sequence persists with the slot (ids stay unique across restarts)
    @property
    def _pubsub_msg_seq(self) -> int:
        return int(self._slot()["engine"].get("msg_seq") or 0)

    @_pubsub_msg_seq.setter
    def _pubsub_msg_seq(self, v: int) -> None:
        self._slot()["engine"]["msg_seq"] = int(v)

    def persist(self) -> None:
        """No-op: the tier middleware persists the kernel state after every mutating
        request (the slot lives inside it)."""

    # ── upgrade path: pre-v4 records → the core shape ─────────────────────
    def adopt(self) -> None:
        slot = self._slot()
        meta = slot["engine"]
        if not meta.get("adopted"):
            meta["adopted"] = _http_date()
            try:
                _adopt_pubsub_emulator(self)
            except Exception as exc:
                _log.warning("pubsub: emulator adoption skipped: %s", exc)
        if any(not str(k).startswith("projects/") for coll in ("topics", "subscriptions", "schemas")
               for k in slot[coll]):
            n = adopt_legacy_pubsub(slot)
            if n:
                _log.info("pubsub: adopted %d pre-v4 records", n)


def _ps_project(rec: dict, default: str = "") -> str:
    from core.app_context import gcp_project_name
    for f in ("name", "topic"):
        v = str(rec.get(f) or "")
        if v.startswith("projects/"):
            return v.split("/")[1]
    return gcp_project_name(rec.get("project") or default or None)


def adopt_legacy_pubsub(slot: dict) -> int:
    """Convert pre-v4 records (bare-id keys) IN PLACE into gcp_pubsub_core records keyed by
    full resource name; the pre-v4 per-subscription `messages` backlog becomes the core
    subscription's message list (unacked, deliverable)."""
    n = 0
    topics, subs, schemas = slot["topics"], slot["subscriptions"], slot["schemas"]
    for key in [k for k in list(topics) if not str(k).startswith("projects/")]:
        rec = topics.pop(key)
        if not isinstance(rec, dict):
            continue
        project = _ps_project(rec)
        tid = str(rec.get("topicId") or key).rsplit("/", 1)[-1]
        name = f"projects/{project}/topics/{tid}"
        if name in topics:
            continue
        t = {"name": name, "subscriptions": [], "created": _rfc3339(rec.get("createTime")),
             "labels": dict(rec.get("labels") or {})}
        for f in ("kmsKeyName", "messageRetentionDuration", "schemaSettings"):
            if rec.get(f):
                t[f] = rec[f]
        topics[name] = t
        n += 1
    legacy_msgs = slot.get("messages") if isinstance(slot.get("messages"), dict) else {}
    now = time.time()
    for key in [k for k in list(subs) if not str(k).startswith("projects/")]:
        rec = subs.pop(key)
        if not isinstance(rec, dict):
            continue
        project = _ps_project(rec)
        sid = str(rec.get("subscriptionId") or key).rsplit("/", 1)[-1]
        name = f"projects/{project}/subscriptions/{sid}"
        if name in subs:
            continue
        topic = str(rec.get("topic") or "")
        if topic and not topic.startswith("projects/") and topic != "_deleted-topic_":
            topic = f"projects/{project}/topics/{topic}"
        backlog = []
        for m in (legacy_msgs.get(key) or legacy_msgs.get(sid) or []):
            if isinstance(m, dict):
                rec_m = {"_id": uuid.uuid4().hex, "_publish_at": float(m.get("_publishedAt") or now),
                         "data": m.get("data", ""), "attributes": dict(m.get("attributes") or {}),
                         "messageId": str(m.get("messageId") or uuid.uuid4().hex),
                         "publishTime": str(m.get("publishTime") or _rfc3339(""))}
                if m.get("orderingKey"):
                    rec_m["orderingKey"] = m["orderingKey"]
                backlog.append(rec_m)
        s = {"name": name, "topic": topic or "_deleted-topic_",
             "ackDeadlineSeconds": int(rec.get("ackDeadlineSeconds") or 10),
             "messages": backlog, "ackids": {}, "created": _rfc3339(rec.get("createTime")),
             "labels": dict(rec.get("labels") or {}),
             "messageRetentionDuration": str(rec.get("messageRetentionDuration") or "604800s"),
             "retainAckedMessages": bool(rec.get("retainAckedMessages", False)),
             "expirationPolicy": rec.get("expirationPolicy") or {"ttl": "2678400s"},
             "enableMessageOrdering": bool(rec.get("enableMessageOrdering", False)),
             "enableExactlyOnceDelivery": bool(rec.get("enableExactlyOnceDelivery", False)),
             "pushConfig": rec.get("pushConfig") or {}}
        for f in ("filter", "deadLetterPolicy", "retryPolicy"):
            if rec.get(f):
                s[f] = rec[f]
        subs[name] = s
        if s["topic"] in topics and name not in topics[s["topic"]]["subscriptions"]:
            topics[s["topic"]]["subscriptions"].append(name)
        n += 1
    for key in [k for k in list(schemas) if not str(k).startswith("projects/")]:
        rec = schemas.pop(key)
        if not isinstance(rec, dict):
            continue
        name = f"projects/{_ps_project(rec)}/schemas/{str(rec.get('name') or key).rsplit('/', 1)[-1]}"
        if name in schemas:
            continue
        schemas[name] = {"name": name, "type": str(rec.get("type") or "AVRO"),
                         "definition": str(rec.get("definition") or ""),
                         "revisionId": str(rec.get("revisionId") or uuid.uuid4().hex[:8]),
                         "revisionCreateTime": _rfc3339(rec.get("createTime"))}
        n += 1
    if isinstance(slot.get("messages"), dict):
        slot["messages"] = {}          # the backlogs now live on the subscriptions
    return n


def _adopt_pubsub_emulator(store: "AppStatePubsubStore") -> None:
    """Once per space: topics / subscriptions the Pub/Sub emulator held (pre-v4 the
    emulator was authoritative when PUBSUB_EMULATOR_HOST was set) → this state."""
    from core import gcp_pubsub_emulator as emu
    if not emu.available():
        return
    from core.app_context import gcp_project_name
    projects = {gcp_project_name(None), "cloudlearn", "123456789012", "gcp-dev"}
    for p in projects:
        for t in emu.list_topics(p):
            name = f"projects/{p}/topics/{t['name']}"
            if name not in store.topics:
                rec = {"name": name, "subscriptions": [], "created": _rfc3339(""),
                       "labels": dict(t.get("labels") or {})}
                for f in ("messageRetentionDuration", "kmsKeyName"):
                    if t.get(f):
                        rec[f] = t[f]
                store.topics[name] = rec
        for s in emu.list_subscriptions(p):
            name = f"projects/{p}/subscriptions/{s['name']}"
            topic = str(s.get("topic") or "")
            if topic and not topic.startswith("projects/"):
                topic = f"projects/{p}/topics/{topic}"
            if name in store.queues:
                continue
            store.queues[name] = {"name": name, "topic": topic or "_deleted-topic_",
                                  "ackDeadlineSeconds": int(s.get("ackDeadlineSeconds") or 10),
                                  "messages": [], "ackids": {}, "created": _rfc3339(""),
                                  "labels": dict(s.get("labels") or {}),
                                  "messageRetentionDuration": str(s.get("messageRetentionDuration") or "604800s"),
                                  "expirationPolicy": {"ttl": "2678400s"},
                                  "enableMessageOrdering": bool(s.get("enableMessageOrdering", False)),
                                  "pushConfig": {}}
            if topic in store.topics and name not in store.topics[topic]["subscriptions"]:
                store.topics[topic]["subscriptions"].append(name)


_GPS = None


def gcp_pubsub_store() -> AppStatePubsubStore:
    global _GPS
    if _GPS is None:
        _GPS = AppStatePubsubStore()
    return _GPS


# ── Whole-store slots: Microsoft Graph (Entra ID) + Cosmos DB data plane ──────────────
from core.azure_graph_core import GraphStore as _GraphStore   # noqa: E402
from core.azure_cosmos_core import CosmosStore as _CosmosStore   # noqa: E402
from core.azure_table_core import AzureTableStore as _TableStore   # noqa: E402


class _AzureSlotStore:
    """Mixin: every attribute of the core's store (`_BASE`) resolves to the Azure space's
    `_SLOT` dict (seeded with the core's defaults), so the state persists with the kernel
    state. Callers pin REQUEST_PROVIDER to "azure" (core/wire_ingress.dispatch_service)."""

    _BASE: type = object
    _SLOT = ""
    _FIELDS: tuple = ()

    def __init__(self):        # NB: no base __init__ — the attributes are the slot's
        pass

    def _dir(self) -> dict:
        slot = _proxy(self._SLOT, lambda: {"store": {}}, "store")._target()
        if len(slot) < len(self._FIELDS):
            for k, v in vars(self._BASE()).items():
                slot.setdefault(k, v)
        return slot

    def __getattr__(self, name):
        if name in type(self)._FIELDS:
            return self._dir()[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in type(self)._FIELDS:
            self._dir()[name] = value
        else:
            object.__setattr__(self, name, value)


class AppStateGraphStore(_AzureSlotStore, _GraphStore):
    """azure_graph_core store: users / groups / apps / SPs / … in the `azure_graph` slot."""
    _BASE, _SLOT, _FIELDS = _GraphStore, "azure_graph", tuple(vars(_GraphStore()).keys())


class AppStateCosmosStore(_AzureSlotStore, _CosmosStore):
    """azure_cosmos_core store: databases / containers / items in the `azure_cosmos_data` slot."""
    _BASE, _SLOT, _FIELDS = _CosmosStore, "azure_cosmos_data", tuple(vars(_CosmosStore()).keys())


_GRAPH = _COSMOS = None


def graph_store() -> AppStateGraphStore:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = AppStateGraphStore()
    return _GRAPH


class AppStateTableStore(_AzureSlotStore, _TableStore):
    """Azure Table storage (core/azure_table_core.py) over the Azure space's persisted slot."""
    _BASE, _SLOT, _FIELDS = _TableStore, "azure_table", tuple(vars(_TableStore()).keys())


_TABLE = None


def table_store() -> AppStateTableStore:
    global _TABLE
    if _TABLE is None:
        _TABLE = AppStateTableStore()
    return _TABLE


def cosmos_store() -> AppStateCosmosStore:
    global _COSMOS
    if _COSMOS is None:
        _COSMOS = AppStateCosmosStore()
    return _COSMOS


# ── v4 C0g: AWS IAM ─────────────────────────────────────────────────────────────────
#
#   IAM   users / groups / roles / managed policies / access keys / SAML+OIDC providers /
#         account alias+password policy / Vyomi-only org policies + access requests
#                                            -> service_states["iam_core"]{users,groups,roles,
#                                               policies,access_keys,saml_providers,
#                                               oidc_providers,account_aliases,password_policy,
#                                               credential_report,org_policies,access_requests}
#   The pre-v4 handler (server.py `_iam_*` + providers/aws_iam.py, records keyed by opaque
#   ids with flat `policies: [policy_id]` lists) kept its own slot (core.app_context.iam_state,
#   still the classic console's — /api/iam/* REST stays on it). Its users/groups/roles/
#   policies/identity-providers/password-policy are adopted ONCE per space into this slot
#   (keyed by name/ARN, `attached_policies: [arn]`, as the core expects) so an upgrade keeps
#   what the classic console created; the native wire is this slot's from then on.
from core.iam_store import IamStore as _IamStoreBase   # noqa: E402
from core.iam_store import NativeIamEvaluator as _NativeIamEvaluator   # noqa: E402

_IAM_KEYS = {
    "users": dict, "groups": dict, "roles": dict, "policies": dict, "access_keys": dict,
    "saml_providers": dict, "oidc_providers": dict, "account_aliases": list,
    "password_policy": lambda: None, "credential_report": lambda: None,
    "org_policies": dict, "access_requests": dict,
}


class AppStateIamStore(_SlotStore, _IamStoreBase):
    """iam_core store over the appliance's space-scoped IAM state (a new slot — see above)."""

    _KEYS = _IAM_KEYS

    def __init__(self, proxy):
        self._bind(proxy)   # NB: no IamStore.__init__ — the dicts are the slot's
        self.engine = _NativeIamEvaluator()
        from core import app_context as ctx
        self.account_id = ctx.AWS_ACCOUNT_ID

    users = _slot_attr("users")
    groups = _slot_attr("groups")
    roles = _slot_attr("roles")
    policies = _slot_attr("policies")
    access_keys = _slot_attr("access_keys")
    saml_providers = _slot_attr("saml_providers")
    oidc_providers = _slot_attr("oidc_providers")
    account_aliases = _slot_attr_rw("account_aliases")
    password_policy = _slot_attr_rw("password_policy")
    credential_report = _slot_attr_rw("credential_report")
    org_policies = _slot_attr("org_policies")
    access_requests = _slot_attr("access_requests")

    def adopt(self) -> None:
        """Pre-v4 server.py IAM state (core.app_context.iam_state) -> this slot, once per space."""
        if not self._begin_adoption():
            return
        try:
            from core.app_context import iam_state as legacy
            n = adopt_legacy_iam(self._slot(), legacy, account_id=self.account_id)
            if n:
                _log.info("iam: adopted %d pre-v4 users/groups/roles/policies", n)
        except Exception as exc:   # never break the data plane over a migration
            _log.warning("iam: pre-v4 adoption skipped: %s", exc)


def adopt_legacy_iam(slot: dict, legacy: dict, account_id: str = "123456789012") -> int:
    """Convert the pre-v4 IAM records of one space (server.py `_iam_*` / providers/aws_iam.py
    shape: opaque `user-…`/`group-…`/`role-…`/`policy-…` ids, a flat `policies: [policy_id]`
    list per principal, a separate global `attachments` list) into the core/iam_core.py shape
    (keyed by name — policies by ARN — `attached_policies: [arn]`) IN PLACE. Returns the
    number of entities adopted."""
    from core.iam_core import _now as _iam_now

    users, groups, roles = slot.setdefault("users", {}), slot.setdefault("groups", {}), slot.setdefault("roles", {})
    policies = slot.setdefault("policies", {})
    n = 0

    def arn_of(kind: str, name: str) -> str:
        return f"arn:aws:iam::{account_id}:{kind}/{name}"

    policy_arn_by_id: dict[str, str] = {}
    for pid, p in (legacy.get("policies") or {}).items():
        if not isinstance(p, dict) or not p.get("policy_name"):
            continue
        arn = arn_of("policy", p["policy_name"])
        policy_arn_by_id[pid] = arn
        if arn in policies:
            continue
        when = p.get("created") or _iam_now()
        doc = p.get("document") or {}
        policies[arn] = {"policy_name": p["policy_name"], "policy_id": p.get("policy_id") or pid,
                         "arn": arn, "path": p.get("path", "/"), "document": doc,
                         "description": p.get("description", ""), "created": when, "updated": when,
                         "default_version_id": "v1", "attachment_count": 0, "tags": {},
                         "versions": {"v1": {"document": doc, "created": when}}}
        n += 1

    group_name_by_id: dict[str, str] = {}
    for gid, g in (legacy.get("groups") or {}).items():
        if not isinstance(g, dict) or not g.get("group_name"):
            continue
        name = g["group_name"]
        group_name_by_id[gid] = name
        if name in groups:
            continue
        groups[name] = {"group_name": name, "group_id": g.get("group_id") or gid,
                        "path": g.get("path", "/"), "arn": arn_of("group", name),
                        "created": g.get("created") or _iam_now(), "members": [],
                        "attached_policies": [policy_arn_by_id[pid] for pid in g.get("policies") or []
                                              if pid in policy_arn_by_id],
                        "inline_policies": {}}
        n += 1

    for uid, u in (legacy.get("users") or {}).items():
        if not isinstance(u, dict) or not u.get("user_name"):
            continue
        name = u["user_name"]
        if name in users:
            continue
        member_groups = [group_name_by_id[gid] for gid in u.get("groups") or [] if gid in group_name_by_id]
        for gname in member_groups:
            members = groups[gname]["members"]
            if name not in members:
                members.append(name)
        users[name] = {"user_name": name, "user_id": u.get("user_id") or uid,
                       "path": u.get("path", "/"), "arn": arn_of("user", name),
                       "created": u.get("created") or _iam_now(),
                       "attached_policies": [policy_arn_by_id[pid] for pid in u.get("policies") or []
                                             if pid in policy_arn_by_id],
                       "inline_policies": {}, "groups": member_groups, "tags": {},
                       "permissions_boundary": None, "login_profile": None}
        n += 1

    for rid, r in (legacy.get("roles") or {}).items():
        if not isinstance(r, dict) or not r.get("role_name"):
            continue
        name = r["role_name"]
        if name in roles:
            continue
        roles[name] = {"role_name": name, "role_id": r.get("role_id") or rid,
                       "path": r.get("path", "/"), "arn": arn_of("role", name),
                       "created": r.get("created") or _iam_now(),
                       "assume_role_policy_document": r.get("assume_role_policy_document") or {},
                       "description": r.get("description", ""),
                       "max_session_duration": int(r.get("max_session_duration") or 3600),
                       "attached_policies": [policy_arn_by_id[pid] for pid in r.get("policies") or []
                                             if pid in policy_arn_by_id],
                       "inline_policies": {}, "tags": {}, "permissions_boundary": None}
        n += 1

    for arn in policy_arn_by_id.values():
        p = policies.get(arn)
        if p is not None:
            p["attachment_count"] = sum(1 for coll in (users, groups, roles) for rec in coll.values()
                                        if arn in rec.get("attached_policies", []))

    saml, oidc = slot.setdefault("saml_providers", {}), slot.setdefault("oidc_providers", {})
    for p in (legacy.get("identity_providers") or {}).values():
        if not isinstance(p, dict) or not p.get("provider_name"):
            continue
        is_saml = "SAML" in str(p.get("provider_type") or "").upper()
        arn = arn_of("saml-provider" if is_saml else "oidc-provider", p["provider_name"])
        dest = saml if is_saml else oidc
        if arn in dest:
            continue
        when = p.get("created") or _iam_now()
        dest[arn] = ({"name": p["provider_name"], "arn": arn, "created": when,
                     "metadata_document": p.get("url") or ""} if is_saml else
                     {"url": p.get("url") or "", "arn": arn, "created": when,
                      "client_ids": [], "thumbprints": []})
        n += 1

    pol = (legacy.get("account_settings") or {}).get("password_policy")
    if pol and not slot.get("password_policy"):
        slot["password_policy"] = dict(pol)

    return n


_IAM = None


def iam_store() -> AppStateIamStore:
    global _IAM
    if _IAM is None:
        _IAM = AppStateIamStore(_proxy("iam_core", dict, None))
    return _IAM
