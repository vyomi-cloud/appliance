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

_STORES = {
    "storage": InMemoryObjectStore(),
    "firestore": FirestoreStore(),
    "kms": InMemoryKeyStore(),
    "secretmanager": InMemoryKvStore(),
    "pubsub": InMemoryMessagingStore(),
    "iam": InMemoryIamStore(),
    "cloudsql": InMemorySqlStore(),
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

    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": svc}


GCP_CORE_SERVICES = frozenset(_MOD.keys())
