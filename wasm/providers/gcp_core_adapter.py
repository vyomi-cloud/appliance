"""GCP console adapter — the in-browser analogue of aws_core_adapter for GCP.

The GCP console drives every service through the registry's generic CRUD
(`_resource_dispatch` → List/Create/Get/Delete on a catalog service key). This
module routes those 7 services to the PROVEN GCP conformance cores (the same
cores the relay serves over the native google-cloud-* wire), so the console and
the SDKs share one implementation. Each service keeps its own in-tab store
singleton (the console's source of truth for that tab).

Pure stdlib + the cores → loads under Pyodide. Returns the registry envelope:
List → {ok, items:[record,...]}; Create/Get → {ok, **record}; Delete → {ok, code}.
"""
from __future__ import annotations

import base64
import json

from core import gcp_storage_core as _gcs
from core.object_store import InMemoryObjectStore
from core import gcp_firestore_core as _fs
from core.gcp_firestore_core import FirestoreStore
from core import gcp_kms_core as _kms
from core.kms_keystore import InMemoryKeyStore
from core import gcp_secretmanager_core as _sec
from core.kv_store import InMemoryKvStore
from core import gcp_pubsub_core as _ps
from core.messaging_store import InMemoryMessagingStore
from core import gcp_iam_core as _iam
from core.iam_store import InMemoryIamStore
from core import gcp_cloudsql_core as _sql
from core.sql_store import InMemorySqlStore

PROJ = "demo"          # the console's default project
LOC = "global"         # default KMS location
RING = "demo"          # default KMS key ring
COLL = "console"       # default Firestore collection

# Draw every store from the SHARED nano_registry (keyed gcs/gcp_* there) so the GCP
# console (UI) and the native-wire relay (CLI/SDK/curl via AwsWireRouter) read/write
# ONE store per service — and nano_persist captures them for reload/cross-context sync.
from core import nano_registry as _reg
_R = _reg.get()
_STORES = {
    "storage":       _R["gcs"],
    "firestore":     _R["gcp_fs"],
    "kms":           _R["gcp_kms"],
    "secretmanager": _R["gcp_sec"],
    "pubsub":        _R["gcp_msg"],
    "iam":           _R["gcp_iam"],
    "cloudsql":      _R["gcp_sql"],
}

_MOD = {
    "storage": _gcs, "firestore": _fs, "kms": _kms, "secretmanager": _sec,
    "pubsub": _ps, "iam": _iam, "cloudsql": _sql,
}


def _call(svc, method, path, query=None, body=b""):
    """Dispatch a native GCP-wire request to a service's core; return (status, parsed_json)."""
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    elif isinstance(body, str):
        body = body.encode()
    r = _MOD[svc].dispatch(_STORES[svc], method, path, query or {},
                           {"content-type": "application/json"}, body or b"")
    try:
        parsed = json.loads(r.body.decode("utf-8")) if r.body else {}
    except Exception:
        parsed = {}
    return r.status, parsed


def _items(parsed):
    for k in ("items", "documents", "cryptoKeys", "secrets", "topics",
              "subscriptions", "accounts", "keyRings", "databases"):
        if isinstance(parsed.get(k), list):
            return parsed[k]
    for v in parsed.values():
        if isinstance(v, list):
            return v
    return []


def _short(nm):
    return nm.rsplit("/", 1)[-1] if isinstance(nm, str) and "/" in nm else nm


def _rec(d, name_field="name"):
    """Flatten a native resource into a console record with a short `name`."""
    out = dict(d) if isinstance(d, dict) else {"name": d}
    full = out.get("name", "")
    if isinstance(full, str) and "/" in full:
        out["resourceName"] = full
        out["name"] = _short(full)
    if name_field != "name" and name_field in out:
        out.setdefault("name", out[name_field])
    return out


def _ok_list(svc, name_field="name"):
    st, parsed = _call(svc, "GET", _COLLECTION[svc]())
    return {"ok": True, "items": [_rec(x, name_field) for x in _items(parsed)]}


# ── per-service native path builders ──────────────────────────────────────
_P = f"/v1/projects/{PROJ}"
_COLLECTION = {
    "storage": lambda: "/storage/v1/b",
    "firestore": lambda: f"{_P}/databases/(default)/documents/{COLL}",
    "kms": lambda: f"{_P}/locations/{LOC}/keyRings/{RING}/cryptoKeys",
    "secretmanager": lambda: f"{_P}/secrets",
    "pubsub": lambda: f"{_P}/topics",
    "iam": lambda: f"{_P}/serviceAccounts",
    "cloudsql": lambda: f"/sql/v1beta4/projects/{PROJ}/instances",
}


def _ensure_keyring():
    _call("kms", "POST", f"{_P}/locations/{LOC}/keyRings",
          {"keyRingId": RING}, {})   # idempotent; 409 if it exists — ignored


# ── Durable sub-resource store (child lists NOT natively backed by a core) ──
# Cloud SQL users/backups/replicas, Pub/Sub schemas, IAM service-account members
# & keys, etc. have no dedicated conformance core. We hold them in a plain public
# dict attached to an EXISTING registry store (gcp_iam) so nano_persist captures
# + restores + cross-tab-syncs them on the SAME IndexedDB path as S3/DynamoDB —
# i.e. they survive a reload and are the console's durable source of truth. Keyed
# "service/parent/childType" → {childName: record}. (gcp_iam is a plain object,
# no __slots__, and the attr is public + JSON-safe, so _public_state captures it.)
def _sub_root():
    st = _STORES["iam"]
    d = getattr(st, "nano_sub", None)
    if not isinstance(d, dict):
        d = {}
        st.nano_sub = d
    return d


def _sub_coll(service, parent, child_type, create=False):
    root = _sub_root()
    key = f"{service}/{parent}/{child_type}"
    coll = root.get(key)
    if coll is None and create:
        coll = {}
        root[key] = coll
    return coll if coll is not None else {}


def _sub_list(service, parent, child_type):
    return {"ok": True, "items": list(_sub_coll(service, parent, child_type).values())}


def _sub_create(service, parent, child_type, rec):
    coll = _sub_coll(service, parent, child_type, create=True)
    nm = str(rec.get("name") or "").strip()
    if not nm:
        return {"ok": False, "code": "InvalidName"}
    if nm in coll:
        return {"ok": False, "code": "AlreadyExists", "name": nm}
    coll[nm] = rec
    return {"ok": True, **rec}


def _sub_delete(service, parent, child_type, child):
    coll = _sub_coll(service, parent, child_type, create=True)
    existed = coll.pop(str(child), None) is not None
    return {"ok": existed, "code": None if existed else "NotFound", "name": child}


def resource_op(service, operation, name="", body=None):
    """Console CRUD → GCP core. Returns the registry _resource_dispatch envelope."""
    body = body or {}
    svc = service
    rid = str(body.get("name") or body.get("accountId") or body.get("secretId")
              or body.get("topicId") or name or "").strip()

    # ---------------- STORAGE (GCS buckets) ----------------
    if svc == "storage":
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "POST", "/storage/v1/b", {}, {"name": rid})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"/storage/v1/b/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"/storage/v1/b/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "Update":   # settings edits (lifecycle/encryption/retention/…) → bucket PATCH
            st, p = _call(svc, "PATCH", f"/storage/v1/b/{name}", {}, body)
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "UpdateFailed", "name": name}
        # Objects inside a bucket (the GCS Objects browser: upload/list/delete) —
        # served by the SAME gcp_storage_core as the native google-cloud-storage SDK.
        if operation == "ListObjects":
            st, p = _call(svc, "GET", f"/storage/v1/b/{body.get('bucket','')}/o")
            items = p.get("items", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "objects": items, "items": items}
        if operation == "PutObject":
            raw = base64.b64decode(body.get("body_b64", "") or "")
            key = str(body.get("key") or "upload")
            bucket = str(body.get("bucket") or "")
            r = _MOD["storage"].dispatch(_STORES["storage"], "POST",
                f"/upload/storage/v1/b/{bucket}/o", {"uploadType": "media", "name": key},
                {"content-type": body.get("content_type", "application/octet-stream")}, raw)
            return {"ok": r.status < 300, "key": key, "size": len(raw)} if r.status < 300 \
                else {"ok": False, "code": "UploadFailed", "key": key, "status": r.status}
        if operation == "DeleteObject":
            from urllib.parse import quote
            st, _ = _call(svc, "DELETE",
                          f"/storage/v1/b/{body.get('bucket','')}/o/{quote(str(body.get('key','')), safe='')}")
            return {"ok": st < 300, "key": body.get("key"), "code": None if st < 300 else "NotFound"}

    # ---------------- FIRESTORE (documents in a default collection) ----------------
    if svc == "firestore":
        base = f"{_P}/databases/(default)/documents/{COLL}"
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "POST", base, {"documentId": rid}, {"fields": {}})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "Update":   # Data tab edit → document PATCH (merge typed fields)
            fields = body.get("fields", body)
            st, p = _call(svc, "PATCH", f"{base}/{name}", {}, {"fields": fields})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "UpdateFailed", "name": name}

    # ---------------- KMS (cryptoKeys under a default key ring) ----------------
    if svc == "kms":
        base = f"{_P}/locations/{LOC}/keyRings/{RING}/cryptoKeys"
        if operation == "List":
            _ensure_keyring()
            return _ok_list(svc)
        if operation == "Create":
            _ensure_keyring()
            st, p = _call(svc, "POST", base, {"cryptoKeyId": rid}, {"purpose": "ENCRYPT_DECRYPT"})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            # Cloud KMS keeps key material; drop it from the store for console UX.
            _STORES["kms"].drop_key(f"projects/{PROJ}/locations/{LOC}/keyRings/{RING}/cryptoKeys/{name}")
            return {"ok": True, "code": None, "name": name}
        if operation == "ListVersions":   # cryptoKeyVersions under a key
            st, p = _call(svc, "GET", f"{base}/{name}/cryptoKeyVersions")
            vs = p.get("cryptoKeyVersions", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "items": [_rec(v) for v in vs]}
        if operation == "CreateVersion":   # add a new cryptoKeyVersion (ENABLED)
            st, p = _call(svc, "POST", f"{base}/{name}/cryptoKeyVersions", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "CreateFailed", "name": name}
        if operation in ("DestroyVersion", "DisableVersion", "EnableVersion"):
            ver = str(body.get("name") or "")
            verb = operation[:-7].lower()   # Destroy/Disable/Enable
            st, p = _call(svc, "POST", f"{base}/{name}/cryptoKeyVersions/{ver}:{verb}", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "ActionFailed", "name": ver}

    # ---------------- SECRET MANAGER (secrets + a seeded version) ----------------
    if svc == "secretmanager":
        base = f"{_P}/secrets"
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "POST", base, {"secretId": rid}, {"replication": {"automatic": {}}})
            if st < 300:
                _call(svc, "POST", f"{base}/{rid}:addVersion", {},
                      {"payload": {"data": base64.b64encode(b"changeme").decode()}})
                return {"ok": True, **_rec(p)}
            return {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "ListVersions":   # secret versions (live metadata)
            st, p = _call(svc, "GET", f"{base}/{name}/versions")
            vs = p.get("versions", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "items": [_rec(v) for v in vs]}
        if operation == "AddVersion":      # add a new secret version (payload data)
            data = body.get("value") or body.get("data") or "changeme"
            payload_b64 = base64.b64encode(str(data).encode()).decode()
            st, p = _call(svc, "POST", f"{base}/{name}:addVersion", {},
                          {"payload": {"data": payload_b64}})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AddFailed", "name": name}
        if operation in ("DestroyVersion", "DisableVersion", "EnableVersion"):
            ver = str(body.get("name") or "")
            # short form "projects/.../versions/5" or "5" — take trailing id
            ver = ver.rsplit("/", 1)[-1]
            verb = operation[:-7].lower()   # destroy/disable/enable
            st, p = _call(svc, "POST", f"{base}/{name}/versions/{ver}:{verb}", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "ActionFailed", "name": ver}

    # ---------------- PUB/SUB (topics) ----------------
    if svc == "pubsub":
        base = f"{_P}/topics"
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "PUT", f"{base}/{rid}", {}, {})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "ListSubscriptions":   # subscriptions attached to THIS topic
            topic_full = f"projects/{PROJ}/topics/{name}"
            st, p = _call(svc, "GET", f"{_P}/subscriptions")
            subs = p.get("subscriptions", []) if isinstance(p, dict) else []
            subs = [s for s in subs if s.get("topic") == topic_full]
            return {"ok": st < 300, "items": [_rec(s) for s in subs]}
        if operation == "CreateSubscription":
            sub_id = str(body.get("name") or body.get("subscriptionId") or "").strip()
            topic_full = f"projects/{PROJ}/topics/{name}"
            st, p = _call(svc, "PUT", f"{_P}/subscriptions/{sub_id}", {}, {"topic": topic_full})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "CreateFailed", "name": sub_id}

    # ---------------- IAM (service accounts) ----------------
    if svc == "iam":
        base = f"{_P}/serviceAccounts"
        if operation == "List":
            return _ok_list(svc, name_field="email")
        if operation == "Create":
            st, p = _call(svc, "POST", base, {},
                          {"accountId": rid, "serviceAccount": {"displayName": rid}})
            return {"ok": st < 300, **_rec(p, "email")} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p, "email")} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}

    # ---------------- CLOUD SQL (instances) ----------------
    if svc == "cloudsql":
        base = f"/sql/v1beta4/projects/{PROJ}/instances"
        if operation == "List":
            return _ok_list(svc)
        if operation == "Create":
            st, p = _call(svc, "POST", base, {},
                          {"name": rid, "databaseVersion": body.get("databaseVersion", "POSTGRES_15"),
                           "settings": {"tier": body.get("tier", "db-f1-micro")}})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            st, p = _call(svc, "GET", f"{base}/{name}")
            return {"ok": True, **_rec(p)} if st < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            st, _ = _call(svc, "DELETE", f"{base}/{name}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": name}
        if operation == "ListDatabases":   # databases hosted on THIS instance
            st, p = _call(svc, "GET", f"{base}/{name}/databases")
            dbs = p.get("items", []) if isinstance(p, dict) else []
            return {"ok": st < 300, "items": [_rec(d) for d in dbs]}
        if operation == "CreateDatabase":
            db = str(body.get("name") or body.get("database") or "").strip()
            st, p = _call(svc, "POST", f"{base}/{name}/databases", {}, {"name": db})
            return {"ok": st < 300, **_rec(p)} if st < 300 else {"ok": False, "code": "CreateFailed", "name": db}
        if operation == "DeleteDatabase":
            # `name` is the parent instance (via the /sub/ route); body carries the child db.
            child = str(body.get("name") or "")
            st, _ = _call(svc, "DELETE", f"{base}/{name}/databases/{child}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": child}
        # users / backups / replicas — no Cloud SQL control-plane core; durable adapter store.
        if operation in ("ListUsers", "ListBackups", "ListReplicas"):
            return _sub_list(svc, name, operation[4:].lower())
        if operation == "CreateUser":
            return _sub_create(svc, name, "users",
                               {"name": rid, "host": body.get("host", "%"), "type": "BUILT_IN"})
        if operation == "DeleteUser":
            return _sub_delete(svc, name, "users", body.get("name"))
        if operation == "CreateBackup":
            import time as _t
            bid = str(body.get("name") or "").strip() or ("backup-" + str(int(_t.time())))
            return _sub_create(svc, name, "backups",
                               {"name": bid, "status": "SUCCESSFUL", "type": "ON_DEMAND"})
        if operation == "DeleteBackup":
            return _sub_delete(svc, name, "backups", body.get("name"))
        if operation == "CreateReplica":
            return _sub_create(svc, name, "replicas",
                               {"name": rid, "masterInstance": name, "status": "RUNNABLE"})
        if operation == "DeleteReplica":
            return _sub_delete(svc, name, "replicas", body.get("name"))

    # ---------------- PUB/SUB schemas (adapter-store child) ----------------
    if svc == "pubsub":
        if operation == "DeleteSubscription":
            sub_id = str(body.get("name") or "")
            st, _ = _call(svc, "DELETE", f"{_P}/subscriptions/{sub_id}")
            return {"ok": st < 300, "code": None if st < 300 else "NotFound", "name": sub_id}
        if operation == "ListSchemas":
            return _sub_list(svc, name, "schemas")
        if operation == "CreateSchema":
            return _sub_create(svc, name, "schemas",
                               {"name": rid, "type": body.get("type", "AVRO"), "topic": name})
        if operation == "DeleteSchema":
            return _sub_delete(svc, name, "schemas", body.get("name"))

    # ---------------- IAM members / keys (adapter-store children) ----------------
    if svc == "iam":
        if operation == "ListMembers":
            return _sub_list(svc, name, "members")
        if operation == "CreateMember":
            return _sub_create(svc, name, "members",
                               {"name": rid, "role": body.get("role", "roles/viewer")})
        if operation == "DeleteMember":
            return _sub_delete(svc, name, "members", body.get("name"))
        if operation == "ListKeys":
            return _sub_list(svc, name, "keys")
        if operation == "CreateKey":
            import time as _t, uuid as _u
            kid = str(body.get("name") or "").strip() or _u.uuid4().hex[:24]
            return _sub_create(svc, name, "keys",
                               {"name": kid, "keyType": "USER_MANAGED",
                                "validAfterTime": "now", "created": int(_t.time())})
        if operation == "DeleteKey":
            return _sub_delete(svc, name, "keys", body.get("name"))

    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": svc}


GCP_CORE_SERVICES = frozenset(_MOD.keys())
