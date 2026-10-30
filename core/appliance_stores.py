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

import logging
import threading
import time

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


# ── singletons ─────────────────────────────────────────────────────────────
_S3 = _GCS = _DDB = _AZB = _GSEC = _GKMS = _AKMS = _ASEC = None


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
