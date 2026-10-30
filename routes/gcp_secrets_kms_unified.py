"""v4 C0b — GCP Secret Manager + Cloud KMS on the offline appliance, ONE engine.

The native REST paths (/v1/projects/{p}/secrets…, /v1/projects/{p}/locations/{l}/
keyRings…) are served by the shared cores (core/gcp_secretmanager_core.py,
core/gcp_kms_core.py — the same ones Nano and dev_server use, via
core.wire_ingress.mount_gcp_secrets_kms) over the appliance's space-scoped, persisted
state (core/appliance_stores.py). Before v4 they were Vault-backed handlers in
core/vault_routes.py that 404'd every list/get and failed outright without Vault.

The classic console REST (/api/gcp/secrets*, /api/gcp/kms/keys* — the shapes the
gcp_catalog console pages consume) is re-implemented here on the SAME stores by
calling the cores, so a secret or key created by the console is visible to the
google-cloud-* SDKs / gcloud and vice-versa.

Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without gcp_secrets / gcp_kms (or
VYOMI_LEGACY_WIRE=1) restores the Vault handlers.
"""
from __future__ import annotations

import base64
import json

from fastapi import Request
from fastapi.responses import JSONResponse

from core import wire_ingress as _wi

DEFAULT_LOCATION = "global"
DEFAULT_RING = "default-ring"


def _default_project(request: Request) -> str:
    from core.app_context import gcp_project_name
    return gcp_project_name(request.query_params.get("project"))


def _call(service: str, method: str, path: str, query: dict | None = None, body: dict | None = None):
    out = _wi.dispatch_service(service, method, path, query or {}, {"content-type": "application/json"},
                               json.dumps(body).encode() if body is not None else b"")
    try:
        data = json.loads(out["body"] or b"{}")
    except Exception:
        data = {}
    return out["status"], data


async def _json_body(request: Request) -> dict:
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _err(status: int, data: dict, **extra) -> JSONResponse:
    msg = ((data or {}).get("error") or {}).get("message") or "request failed"
    return JSONResponse(status_code=status, content={"ok": False, "error": msg, **extra})


# ── Secret Manager console ────────────────────────────────────────────────
def _secret_rows(request: Request) -> list:
    """Every secret of the space (all projects), newest data included."""
    from core import appliance_stores as aps
    st = aps.gcp_secrets_store()
    st.adopt(_default_project(request))
    rows = []
    for key in st.names():
        sec = st.get_secret(key) or {}
        vers = sec.get("versions") or {}
        latest = max((int(n) for n in vers), default=0)
        rows.append({"key": key, "project": sec.get("project") or key.split("/", 1)[0],
                     "name": sec.get("secretId") or key.split("/", 1)[-1],
                     "created": sec.get("createTime", ""), "latest_version": str(latest or 1),
                     "labels": sec.get("labels") or {}})
    return rows


def _find_secret(request: Request, name: str) -> tuple[str, str] | None:
    want = request.query_params.get("project")
    for r in _secret_rows(request):
        if r["name"] == name and (not want or r["project"] == want):
            return r["project"], r["name"]
    return None


def _add_value(project: str, name: str, value: str):
    return _call("gcp_secrets", "POST", f"/v1/projects/{project}/secrets/{name}:addVersion",
                 body={"payload": {"data": base64.b64encode(str(value).encode()).decode()}})


def _register_secrets_console(app) -> None:
    @app.get("/api/gcp/secrets", include_in_schema=False)
    async def gcp_console_secrets_list(request: Request):
        return {"items": [{"name": r["name"], "project": r["project"], "replication": "automatic",
                           "created": r["created"], "latest_version": r["latest_version"],
                           "labels": r["labels"]} for r in _secret_rows(request)]}

    @app.post("/api/gcp/secrets", include_in_schema=False)
    async def gcp_console_secret_create(request: Request):
        body = await _json_body(request)
        name = (body.get("name") or body.get("secretId") or body.get("secret_id") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "missing 'name'"})
        project = body.get("project") or _default_project(request)
        st, data = _call("gcp_secrets", "POST", f"/v1/projects/{project}/secrets", {"secretId": name},
                         {"replication": {"automatic": {}}, "labels": body.get("labels") or {}})
        if st not in (200, 409):        # 409 = exists: the console adds a version (pre-v4 behaviour)
            return _err(st, data, name=name)
        st, data = _add_value(project, name, body.get("value") or body.get("secret_value") or "changeme")
        if st != 200:
            return _err(st, data, name=name)
        return {"ok": True, "name": name, "project": project}

    @app.get("/api/gcp/secrets/{name}", include_in_schema=False)
    async def gcp_console_secret_get(name: str, request: Request):
        found = _find_secret(request, name)
        if not found:
            return JSONResponse(status_code=404, content={"ok": False, "error": "secret not found", "name": name})
        project, _ = found
        st, data = _call("gcp_secrets", "GET", f"/v1/projects/{project}/secrets/{name}/versions/latest:access")
        if st != 200:     # created without a version yet (or all disabled): metadata only
            return {"ok": True, "name": name, "project": project, "value": ""}
        raw = base64.b64decode(((data.get("payload") or {}).get("data")) or "")
        return {"ok": True, "name": name, "project": project, "value": raw.decode("utf-8", "replace"),
                "version": data.get("name", "").rsplit("/", 1)[-1]}

    @app.put("/api/gcp/secrets/{name}", include_in_schema=False)
    async def gcp_console_secret_update(name: str, request: Request):
        body = await _json_body(request)
        value = body.get("value")
        if value is None:
            enc = (body.get("payload") or {}).get("data")
            value = base64.b64decode(enc).decode("utf-8", "replace") if enc else ""
        found = _find_secret(request, name)
        project = found[0] if found else (body.get("project") or _default_project(request))
        if not found:   # pre-v4 behaviour: updating an unknown secret creates it
            _call("gcp_secrets", "POST", f"/v1/projects/{project}/secrets", {"secretId": name},
                  {"replication": {"automatic": {}}})
        st, data = _add_value(project, name, value)
        if st != 200:
            return _err(st, data, name=name)
        return {"ok": True, "name": name, "updated": True,
                "version": data.get("name", "").rsplit("/", 1)[-1]}

    @app.delete("/api/gcp/secrets/{name}", include_in_schema=False)
    async def gcp_console_secret_delete(name: str, request: Request):
        found = _find_secret(request, name)
        if found:
            _call("gcp_secrets", "DELETE", f"/v1/projects/{found[0]}/secrets/{name}")
        return {"ok": True, "deleted": True, "name": name}


# ── Cloud KMS console ─────────────────────────────────────────────────────
def _key_rows(request: Request) -> list:
    from core import appliance_stores as aps
    from core import gcp_kms_core as _kc
    st = aps.gcp_kms_store()
    st.adopt(_default_project(request))
    rows = []
    for kname in st.key_ids():
        segs = kname.split("/")
        if len(segs) != 8:
            continue
        meta = st.get_key(kname) or {}
        prim = str(meta.get("primary", "1"))
        rows.append({"resource": kname, "project": segs[1], "location": segs[3], "keyring": segs[5],
                     "name": segs[7],
                     "purpose": _kc._enum(meta.get("purpose"), _kc._PURPOSES, "ENCRYPT_DECRYPT"),
                     "algorithm": _kc._enum(meta.get("algorithm"), _kc._ALGORITHMS, "GOOGLE_SYMMETRIC_ENCRYPTION"),
                     "protection": "SOFTWARE",
                     "state": ((meta.get("versions") or {}).get(prim) or {}).get("state", "ENABLED"),
                     "created": meta.get("createTime", ""), "labels": meta.get("labels") or {},
                     "rotation_period": meta.get("rotationPeriod", ""),
                     "next_rotation": meta.get("nextRotationTime", "")})
    return rows


def _find_key(request: Request, name: str) -> dict | None:
    ring = request.query_params.get("keyring")
    for r in _key_rows(request):
        if (r["name"] == name or f"{r['keyring']}/{r['name']}" == name) and (not ring or r["keyring"] == ring):
            return r
    return None


def _register_kms_console(app) -> None:
    @app.get("/api/gcp/kms/keys", include_in_schema=False)
    async def gcp_console_kms_list(request: Request):
        return {"items": [{k: r[k] for k in ("name", "keyring", "project", "location", "purpose",
                                              "algorithm", "protection", "state", "created")}
                          for r in _key_rows(request)]}

    @app.post("/api/gcp/kms/keys", include_in_schema=False)
    async def gcp_console_kms_create(request: Request):
        body = await _json_body(request)
        name = (body.get("name") or body.get("keyRingId") or body.get("keyId") or "").strip()
        ring = (body.get("keyring") or DEFAULT_RING).strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "missing 'name'"})
        project = body.get("project") or _default_project(request)
        loc = body.get("location") or DEFAULT_LOCATION
        parent = f"/v1/projects/{project}/locations/{loc}/keyRings"
        st, data = _call("gcp_kms", "POST", parent, {"keyRingId": ring}, {})
        if st not in (200, 409):
            return _err(st, data, name=name)
        st, data = _call("gcp_kms", "POST", f"{parent}/{ring}/cryptoKeys", {"cryptoKeyId": name},
                         {"purpose": "ENCRYPT_DECRYPT", "labels": body.get("labels") or {}})
        if st != 200:
            return _err(st, data, name=name)
        return {"ok": True, "name": name, "keyring": ring, "project": project, "resource": data.get("name")}

    @app.get("/api/gcp/kms/keys/{name}", include_in_schema=False)
    async def gcp_console_kms_get(name: str, request: Request):
        r = _find_key(request, name)
        if not r:
            return JSONResponse(status_code=404, content={"ok": False, "error": "key not found", "name": name})
        return {"ok": True, **{k: v for k, v in r.items() if k != "resource"}, "resource": r["resource"]}

    @app.put("/api/gcp/kms/keys/{name}", include_in_schema=False)
    async def gcp_console_kms_update(name: str, request: Request):
        r = _find_key(request, name)
        if not r:
            return JSONResponse(status_code=404, content={"ok": False, "error": "key not found", "name": name})
        body = await _json_body(request)
        patch = {}
        if isinstance(body.get("labels"), dict):
            patch["labels"] = body["labels"]
        if "rotation_period" in body:
            patch["rotationPeriod"] = str(body.get("rotation_period") or "")
        if "next_rotation" in body:
            patch["nextRotationTime"] = str(body.get("next_rotation") or "")
        mask = list(patch)
        if mask:
            st, data = _call("gcp_kms", "PATCH", "/v1/" + r["resource"], {"updateMask": ",".join(mask)}, patch)
            if st != 200:
                return _err(st, data, name=name)
        else:
            data = {}
        return {"ok": True, "name": name, "labels": data.get("labels", r["labels"]),
                "rotation_period": data.get("rotationPeriod", r["rotation_period"])}

    @app.delete("/api/gcp/kms/keys/{name}", include_in_schema=False)
    async def gcp_console_kms_delete(name: str, request: Request):
        # Real Cloud KMS never deletes a CryptoKey; the classic console's "delete"
        # (pre-v4: drop it from the list) removes it from the space's store.
        r = _find_key(request, name)
        if r:
            from core import appliance_stores as aps
            st = aps.gcp_kms_store()
            st.drop_key(r["resource"])
            st.persist()
        return {"ok": True, "deleted": True, "name": name}


def register(app) -> set:
    """Mount whichever of the two services is unified; returns the legacy path
    prefixes the caller must NOT register (core/vault_routes skips them)."""
    skip: set = set()
    _wi.mount_gcp_secrets_kms(app)
    if _wi.is_unified("gcp_secrets"):
        _register_secrets_console(app)
        skip |= {"/v1/projects/{project}/secrets", "/api/gcp/secrets"}
    if _wi.is_unified("gcp_kms"):
        _register_kms_console(app)
        skip |= {"/v1/projects/{project}/locations/{loc}/keyRings", "/api/gcp/kms/"}
    return skip


def inventory(space: dict) -> dict:
    """{(svc, kind): {name: created}} of a space's core-backed secrets / keys, read
    straight from its service_states (for the cost / inventory collectors)."""
    ss = (space or {}).get("service_states") or {}
    out = {("secretmanager", "secret"): {}, ("kms", "key"): {}}
    for key, sec in ((ss.get("gcp_gcp_secretmanager") or {}).get("secrets") or {}).items():
        if isinstance(sec, dict):
            out[("secretmanager", "secret")][key] = sec.get("createTime", "")
    for key, meta in ((ss.get("gcp_gcp_kms") or {}).get("keys") or {}).items():
        if isinstance(meta, dict):
            out[("kms", "key")][key] = meta.get("createTime", "")
    return out
