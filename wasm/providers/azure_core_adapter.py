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
from core import azure_subresource_core as _sub

APIV = {"api-version": "7.4"}
XMS = {"x-ms-version": "2021-12-02"}

# Draw every store from the SHARED nano_registry (keyed az_* there) so the Azure
# console (UI) and the native-wire relay (CLI/SDK/curl via AwsWireRouter) read/write
# ONE store per service — and nano_persist captures them for reload/cross-context sync.
from core import nano_registry as _reg
_R = _reg.get()
_STORES = {
    "blobcontainers": _R["az_blob"],
    "cosmosdbs":      _R["az_cosmos"],
    "kvsecrets":      _R["az_kvsec"],
    "kvkeys":         _R["az_kvkeys"],
    "queues":         _R["az_queue"],
}

# Generic child-resource (sub-resource) store. Durable: `azure_subresource_core`
# hangs its state on this ALREADY-registered store's public `nano_sub` dict attr,
# which nano_persist captures/restores automatically (no registry/persist edit).
_SUB_STORE = _R["az_cosmos"]

# Detail-view sub-resource blades the console drives via /api/azure/sub/<service>/…
# Each: console parent service key → {childType: {friendly labels only for docs}}.
# The adapter serves List/Create/Update/Delete<Child> for exactly these (service,
# childType) pairs; anything else returns UnsupportedOperation so the console can
# fall back cleanly. childType is the SINGULAR-ish verb suffix the console uses.
_SUB_SERVICES = {
    "sql":        {"Database", "FirewallRule"},
    "servicebus": {"Queue"},
    "cosmos":     set(),   # settings-only (GetSettings/UpdateSettings), no child list
    "keyvault":   set(),   # settings-only
    "vnet":       set(),   # settings-only
    "storage":    set(),   # settings-only
    "vm":         set(),   # settings-only
}


def _sub_op(service, operation, name, body):
    """Serve a generic child-resource op coming over /api/azure/sub/<service>/…

    operation is "<Verb><Child>" (ListDatabases / CreateFirewallRule / DeleteQueue);
    `name` is the PARENT resource id for List/Create, or "<parent>/<child>" for
    Delete/Update (the console encodes the child as the last path segment so it
    survives the body-less DELETE). Returns the registry envelope the console reads:
      List → {ok, items:[{name,...},...]};  Create/Update → {ok, name, ...};
      Delete → {ok, code, name}.
    """
    body = body or {}

    # ---- Durable editable SETTINGS (GetSettings / UpdateSettings) ----
    # A settings blade reads its current value, edits it, PATCHes, reads back. The
    # settings KEY (which blade) is the first path segment after the resource, so
    # the console calls:
    #   GET   /api/azure/sub/<service>/getSettings/<resource>/<settingsKey>
    #   PATCH /api/azure/sub/<service>/updateSettings/<resource>/<settingsKey>  {<fields>}
    # Stored as a child of childType "_settings" so it rides the same durable bag.
    if operation in ("GetSettings", "UpdateSettings"):
        resource, skey = str(name or ""), ""
        if "/" in resource:
            resource, skey = resource.rsplit("/", 1)
        skey = skey or str(body.get("_key") or "default")
        if operation == "GetSettings":
            coll = _sub.list_children(_SUB_STORE, service, resource, "_settings")
            cur = next((c for c in coll if c.get("name") == skey), None)
            vals = {k: v for k, v in (cur or {}).items() if k != "name"}
            return {"ok": True, "key": skey, "settings": vals}
        # UpdateSettings: upsert the settings record, then read back.
        attrs = {k: v for k, v in body.items() if k not in ("name", "_key")}
        existing = next((c for c in _sub.list_children(_SUB_STORE, service, resource, "_settings")
                         if c.get("name") == skey), None)
        if existing is None:
            _sub.create_child(_SUB_STORE, service, resource, "_settings", skey, attrs)
        else:
            _sub.update_child(_SUB_STORE, service, resource, "_settings", skey, attrs)
        try:
            from core import nano_events
            nano_events.record(provider="azure", service=service, resource=resource,
                               action="UpdateSettings", status="ok", detail=skey)
        except Exception:
            pass
        coll = _sub.list_children(_SUB_STORE, service, resource, "_settings")
        cur = next((c for c in coll if c.get("name") == skey), None)
        vals = {k: v for k, v in (cur or {}).items() if k != "name"}
        return {"ok": True, "key": skey, "settings": vals}

    # Split "<Verb><Child>" → verb, childType. Longest known child suffix wins.
    verb = child_type = None
    for ct in ("FirewallRule", "Database", "Queue", "Topic", "Subscription"):
        for v in ("List", "Create", "Update", "Delete"):
            if operation == v + ct + ("s" if v == "List" else ""):
                verb, child_type = v, ct
                break
        if verb:
            break
    if verb is None:
        # Tolerate non-pluralised List too (ListDatabase) + unknown children.
        for v in ("List", "Create", "Update", "Delete"):
            if operation.startswith(v):
                verb, child_type = v, operation[len(v):].rstrip("s") or "Item"
                break
    if verb is None:
        return {"ok": False, "code": "UnsupportedOperation", "operation": operation}

    parent, child = str(name or ""), ""
    if verb in ("Delete", "Update") and "/" in parent:
        parent, child = parent.rsplit("/", 1)
    child = child or str(body.get("name") or "")

    if verb == "List":
        return {"ok": True, "items": _sub.list_children(_SUB_STORE, service, parent, child_type)}

    if verb == "Create":
        attrs = {k: v for k, v in body.items() if k != "name"}
        out = _sub.create_child(_SUB_STORE, service, parent, child_type, child, attrs)
    elif verb == "Update":
        attrs = {k: v for k, v in body.items() if k != "name"}
        out = _sub.update_child(_SUB_STORE, service, parent, child_type, child, attrs)
    elif verb == "Delete":
        out = _sub.delete_child(_SUB_STORE, service, parent, child_type, child)
    else:
        return {"ok": False, "code": "UnsupportedOperation", "operation": operation}

    # Record a cloudsim event so the PARENT's Activity/Logs tab reflects child CRUD
    # (registry._MUTATING_OPS is frozen & doesn't know these composite verbs, so we
    # emit here — best-effort, mirrors registry._emit_event; NEVER raises).
    try:
        from core import nano_events
        status = "ok" if out.get("ok") else (str(out.get("code")) or "error")
        action = f"{verb}{child_type}"
        nano_events.record(provider="azure", service=service, resource=parent,
                           action=action, status=status)
        if child:
            nano_events.record(provider="azure", service=service, resource=child,
                               action=verb, status=status)
    except Exception:
        pass
    return out


def _call(svc_mod, store, method, path, query=None, headers=None, body=b""):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    r = svc_mod.dispatch(store, method, path, query or {}, headers or {}, body or b"")
    txt = r.body.decode("utf-8", "replace") if r.body else ""
    return r.status, txt


def kv_raw(method, params):
    """Console Key Vault data plane: forward /{secrets|keys}[/…] to the native
    Key Vault core and return its HTTP envelope (JSON body) under __http."""
    kind = params.get("kind")
    mod, st = (_kvsec, _STORES["kvsecrets"]) if kind == "secrets" else (_kvkeys, _STORES["kvkeys"])
    body = params.get("body")
    status, txt = _call(mod, st, method, "/" + kind + (params.get("rest") or ""), APIV, {},
                        body if body is not None else b"")
    try:
        data = json.loads(txt) if txt else None
    except Exception:
        data = {"raw": txt}
    return {"ok": status < 400, "__http": {"status": status, "headers": {}, "body": data}}


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

    # ---- Generic child/sub-resource ops (SQL DBs + firewall rules, SB queues) ----
    # These arrive as composite ops ("ListDatabases"/"CreateQueue"/…) via the shared
    # /api/azure/sub/<service>/… route, NOT as the flat List/Create/Get/Delete the
    # data-plane services below use. Handle them first.
    if service in _SUB_SERVICES:
        return _sub_op(service, operation, name, body)

    # ---- Blob containers (XML list) ----
    if service == "blobcontainers":
        st = _STORES[service]
        # Console shapes (/api/azure/storage/{account}/containers…): {value:[…]}.
        if operation == "ConsoleList":
            _, x = _call(_blob, st, "GET", "/", {"comp": "list"}, XMS)
            out = []
            for n in _xml_names(x):
                _, bx = _call(_blob, st, "GET", f"/{n}", {"restype": "container", "comp": "list"}, XMS)
                out.append({"name": n, "blobCount": len(re.findall(r"<Blob>", bx))})
            return {"ok": True, "value": out}
        if operation == "ListBlobs":
            _, bx = _call(_blob, st, "GET", f"/{name}", {"restype": "container", "comp": "list"}, XMS)
            blobs = []
            for b in re.findall(r"<Blob>(.*?)</Blob>", bx, re.S):
                g = lambda tag: (re.search(rf"<{tag}>([^<]*)</{tag}>", b) or [None, ""])[1]
                blobs.append({"name": g("Name"), "size": int(g("Content-Length") or 0),
                              "contentType": g("Content-Type"), "lastModified": g("Last-Modified"),
                              "etag": g("Etag")})
            return {"ok": True, "value": blobs}
        if operation == "DeleteObject":
            s, _ = _call(_blob, st, "DELETE", f"/{name}/{body.get('blob', '')}", {}, XMS)
            return {"ok": s < 300, "deleted": s < 300, "container": name, "blob": body.get("blob")}
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

    # ---- Key Vault data plane, native wire shape (/azure-data/keyvault/{vault}/…) ----
    # The vault blade's Secrets / Keys tabs speak the SDK's own JSON (value[] with id/kid,
    # {value}, attributes.enabled), so hand the core's body through untouched.
    if operation == "KvData" and service == "kvcerts":
        # Key Vault certificates: the shared certificates core (real self-signed X.509),
        # its state hung on the registered KV secrets store (public attr → persisted).
        try:
            from core import azure_keyvault_certificates_core as _kvc
        except ImportError:  # pragma: no cover - flat Pyodide layout
            import azure_keyvault_certificates_core as _kvc  # type: ignore
        cs = _kvc.CertStore()
        cs.vaults = _STORES["kvsecrets"].__dict__.setdefault("kv_certs", {})
        vault = str(body.get("vault") or "")
        m = str(body.get("method") or "GET").upper()
        sub = str(body.get("sub") or "").strip("/")
        status, out = _kvc.dispatch(cs, vault, m, "/certificates/" + sub, body.get("body") or {})
        name = sub.split("/")[0] if sub else ""
        if status < 300 and m == "POST" and sub.endswith("/create"):
            _call(_kvsec, _STORES["kvsecrets"], "PUT", f"/secrets/{name}", APIV, {},
                  {"value": _kvc.secret_value(cs, vault, name), "contentType": "application/x-pem-file"})
        elif status < 300 and m == "DELETE" and name:
            _call(_kvsec, _STORES["kvsecrets"], "DELETE", f"/secrets/{name}", APIV, {}, b"")
        return {"ok": status < 400, "__http": {"status": status, "headers": {}, "body": out}}

    if operation == "KvData" and service in ("kvsecrets", "kvkeys"):
        coll = "secrets" if service == "kvsecrets" else "keys"
        core = _kvsec if service == "kvsecrets" else _kvkeys
        sub = str(body.get("sub") or "").strip("/")
        s, t = _call(core, _STORES[service], str(body.get("method") or "GET").upper(),
                     f"/{coll}/{sub}" if sub else f"/{coll}", APIV, {}, body.get("body") or {})
        try:
            data = json.loads(t) if t else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {"value": data}
        return {**data, "ok": s < 300, "status": s}

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
        if operation == "ConsoleList":
            _, x = _call(_queue, st, "GET", "/", {"comp": "list"}, XMS)
            return {"ok": True, "value": _xml_names(x)}
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


AZURE_DP_SERVICES = frozenset(_STORES.keys()) | frozenset(_SUB_SERVICES.keys()) | {"kvcerts"}  # kvcerts: Key Vault certificates (KvData only)
