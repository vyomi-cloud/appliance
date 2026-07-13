"""Azure data-plane console adapter — the Azure analogue of gcp_core_adapter.

The Azure console's ARM path (azure_arm_core) covers the CONTROL plane (create a
storage account / cosmos account / vault / namespace). This adapter adds the
DATA plane the SDKs use — containers, cosmos databases, key-vault secrets/keys,
queues — backed by the 5 proven Azure data-plane cores, exposed to the console
as flat catalog services (dataPlane: true) via the registry's _resource_dispatch.

Pure stdlib + the cores → loads under Pyodide. Returns the registry envelope:
List → {ok, items:[record,...]}; Create/Get → {ok, **record}; Delete → {ok, code}.
"""
from __future__ import annotations

import base64
import json
import re

from core import azure_blob_core as _blob
from core.azure_blob_core import AzureBlobStore
from core import azure_cosmos_core as _cosmos
from core.azure_cosmos_core import CosmosStore
from core import azure_keyvault_secrets_core as _kvsec
from core.kv_store import InMemoryKvStore
from core import azure_keyvault_keys_core as _kvkeys
from core.kms_keystore import InMemoryKeyStore
from core import azure_queue_core as _queue
from core.azure_queue_core import AzureQueueStore

APIV = {"api-version": "7.4"}
XMS = {"x-ms-version": "2021-12-02"}

_STORES = {
    "blobcontainers": AzureBlobStore(),
    "cosmosdbs": CosmosStore(),
    "kvsecrets": InMemoryKvStore(),
    "kvkeys": InMemoryKeyStore(),
    "queues": AzureQueueStore(),
}


def _call(svc_mod, store, method, path, query=None, headers=None, body=b""):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    r = svc_mod.dispatch(store, method, path, query or {}, headers or {}, body or b"")
    txt = r.body.decode("utf-8", "replace") if r.body else ""
    return r.status, txt


def _xml_names(xml):
    return re.findall(r"<Name>([^<]*)</Name>", xml)


def _kv_name(idurl):
    """Extract the vault object NAME from a KV id URL, ignoring any version:
    https://vault/keys|secrets/{name}[/{version}] → {name}."""
    m = re.search(r"/(?:keys|secrets)/([^/]+)", idurl or "")
    return m.group(1) if m else idurl


def _json_items(txt):
    try:
        d = json.loads(txt)
    except Exception:
        return []
    for k in ("Databases", "value", "secrets", "keys"):
        if isinstance(d.get(k), list):
            return d[k]
    for v in d.values():
        if isinstance(v, list):
            return v
    return []


def resource_op(service, operation, name="", body=None):
    """Console CRUD → Azure data-plane core. Returns the registry envelope."""
    body = body or {}
    rid = str(body.get("name") or name or "").strip()

    # ---- Blob containers (XML list) ----
    if service == "blobcontainers":
        st = _STORES[service]
        if operation == "List":
            _, x = _call(_blob, st, "GET", "/", {"comp": "list"}, XMS)
            return {"ok": True, "items": [{"name": n} for n in _xml_names(x)]}
        if operation == "Create":
            s, _ = _call(_blob, st, "PUT", f"/{rid}", {"restype": "container"}, XMS)
            return {"ok": s < 300, "name": rid} if s < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            _, x = _call(_blob, st, "GET", "/", {"comp": "list"}, XMS)
            return {"ok": True, "name": name} if name in _xml_names(x) else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            s, _ = _call(_blob, st, "DELETE", f"/{name}", {"restype": "container"}, XMS)
            return {"ok": s < 300, "code": None if s < 300 else "NotFound", "name": name}

    # ---- Cosmos databases (JSON) ----
    if service == "cosmosdbs":
        st = _STORES[service]
        if operation == "List":
            _, t = _call(_cosmos, st, "GET", "/dbs")
            return {"ok": True, "items": [{"name": d.get("id"), **d} for d in _json_items(t)]}
        if operation == "Create":
            s, t = _call(_cosmos, st, "POST", "/dbs", {}, {}, {"id": rid})
            return {"ok": s < 300, "name": rid} if s < 300 else {"ok": False, "code": "Conflict", "name": rid}
        if operation == "Get":
            s, t = _call(_cosmos, st, "GET", f"/dbs/{name}")
            return {"ok": True, "name": name} if s < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            s, _ = _call(_cosmos, st, "DELETE", f"/dbs/{name}")
            return {"ok": s < 300, "code": None if s < 300 else "NotFound", "name": name}

    # ---- Key Vault secrets (JSON) ----
    if service == "kvsecrets":
        st = _STORES[service]
        if operation == "List":
            _, t = _call(_kvsec, st, "GET", "/secrets", APIV)
            return {"ok": True, "items": [{"name": _kv_name(s.get("id","")), **s}
                                          for s in _json_items(t)]}
        if operation == "Create":
            s, t = _call(_kvsec, st, "PUT", f"/secrets/{rid}", APIV, {},
                         {"value": body.get("value", "changeme")})
            return {"ok": s < 300, "name": rid} if s < 300 else {"ok": False, "code": "Conflict", "name": rid}
        if operation == "Get":
            s, t = _call(_kvsec, st, "GET", f"/secrets/{name}", APIV)
            return {"ok": True, "name": name} if s < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            s, _ = _call(_kvsec, st, "DELETE", f"/secrets/{name}", APIV)
            return {"ok": s < 300, "code": None if s < 300 else "NotFound", "name": name}

    # ---- Key Vault keys (JSON) ----
    if service == "kvkeys":
        st = _STORES[service]
        if operation == "List":
            _, t = _call(_kvkeys, st, "GET", "/keys", APIV)
            return {"ok": True, "items": [{"name": _kv_name(k.get("kid","")), **k}
                                          for k in _json_items(t)]}
        if operation == "Create":
            s, t = _call(_kvkeys, st, "POST", f"/keys/{rid}/create", APIV, {}, {"kty": "RSA"})
            return {"ok": s < 300, "name": rid} if s < 300 else {"ok": False, "code": "Conflict", "name": rid}
        if operation == "Get":
            s, t = _call(_kvkeys, st, "GET", f"/keys/{name}", APIV)
            return {"ok": True, "name": name} if s < 300 else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            s, _ = _call(_kvkeys, st, "DELETE", f"/keys/{name}", APIV)
            return {"ok": s < 300, "code": None if s < 300 else "NotFound", "name": name}

    # ---- Storage queues (XML list) ----
    if service == "queues":
        st = _STORES[service]
        if operation == "List":
            _, x = _call(_queue, st, "GET", "/", {"comp": "list"}, XMS)
            return {"ok": True, "items": [{"name": n} for n in _xml_names(x)]}
        if operation == "Create":
            s, _ = _call(_queue, st, "PUT", f"/{rid}", {}, XMS)
            return {"ok": s < 300, "name": rid} if s < 300 else {"ok": False, "code": "AlreadyExists", "name": rid}
        if operation == "Get":
            _, x = _call(_queue, st, "GET", "/", {"comp": "list"}, XMS)
            return {"ok": True, "name": name} if name in _xml_names(x) else {"ok": False, "code": "NotFound", "name": name}
        if operation == "Delete":
            s, _ = _call(_queue, st, "DELETE", f"/{name}", {}, XMS)
            return {"ok": s < 300, "code": None if s < 300 else "NotFound", "name": name}

    return {"ok": False, "code": "UnsupportedOperation", "operation": operation, "service": service}


AZURE_DP_SERVICES = frozenset(_STORES.keys())
