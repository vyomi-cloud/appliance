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
             "backup_schedules": dict, "backups": dict, "operations": dict, "security_rules": dict}

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
             "addresses": dict, "seq": lambda: {"op": 0, "ip": 0}}

    def __init__(self, proxy):
        self._bind(proxy)

    networks = _slot_attr("networks")
    subnetworks = _slot_attr("subnetworks")
    firewalls = _slot_attr("firewalls")
    routes = _slot_attr("routes")
    addresses = _slot_attr("addresses")
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
