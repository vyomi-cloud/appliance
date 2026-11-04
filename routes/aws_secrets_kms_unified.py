"""v4 C0c — AWS KMS + Secrets Manager on the offline appliance, ONE engine.

The native wire (POST / and /_wire/ with X-Amz-Target `TrentService.*` /
`secretsmanager.*`) is served by the shared cores (core/kms_core.py,
core/secrets_core.py — the same ones Nano and dev_server use) through
core.wire_ingress.dispatch_service, over the appliance's space-scoped, persisted state
(core/appliance_stores.py). Before v4 these were Vault-only handlers in
core/vault_routes.py: without Vault, Encrypt returned an empty CiphertextBlob and
ListSecrets a 500, and key metadata / aliases lived in a process-local dict.

The classic console REST (/api/aws/secrets*, /api/aws/kms/keys* — the shapes the
providers/aws_catalog.py console pages consume) is re-implemented here on the SAME
stores by calling the cores, so a secret or key created by the console is visible to
boto3 / the aws CLI / the v4 console and vice-versa.

Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without kms / secretsmanager (or
VYOMI_LEGACY_WIRE=1) restores the Vault handlers.
"""
from __future__ import annotations

import datetime as _dt
import json

from fastapi import Request
from fastapi.responses import JSONResponse

from core import wire_ingress as _wi

_DEFAULT_SECRET_KEY = "aws/secretsmanager"


def _iso(ts) -> str:
    if not ts:
        return ""
    try:
        return _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(ts)


def _call(service: str, action: str, body: dict) -> tuple[int, dict]:
    prefix = "TrentService." if service == "kms" else "secretsmanager."
    out = _wi.dispatch_service(service, "POST", "/", {},
                               {"x-amz-target": prefix + action,
                                "content-type": "application/x-amz-json-1.1"},
                               json.dumps(body).encode())
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
    return JSONResponse(status_code=status, content={
        "ok": False, "error": (data or {}).get("message") or "request failed",
        "code": (data or {}).get("__type", ""), **extra})


# ── Secrets Manager console ───────────────────────────────────────────────
def _secret_value(body: dict, default: str | None) -> str | None:
    for k in ("value", "SecretString", "secret_string"):
        if body.get(k) not in (None, ""):
            return str(body[k])
    return default


def _register_secrets_console(app) -> None:
    @app.get("/api/aws/secrets", include_in_schema=False)
    async def aws_console_secrets_list(request: Request):
        st, data = _call("secretsmanager", "ListSecrets", {})
        if st != 200:
            return _err(st, data)
        return {"items": [{"name": s["Name"], "secret_type": "SecretString",
                           "created": _iso(s.get("CreatedDate")),
                           "kms_key_id": s.get("KmsKeyId") or _DEFAULT_SECRET_KEY,
                           "description": s.get("Description", ""), "arn": s["ARN"]}
                          for s in data.get("SecretList", [])]}

    @app.post("/api/aws/secrets", include_in_schema=False)
    async def aws_console_secret_create(request: Request):
        body = await _json_body(request)
        name = (body.get("name") or body.get("Name") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "missing 'name'"})
        value = _secret_value(body, "changeme")
        req = {"Name": name, "SecretString": value, "Description": str(body.get("description") or "")}
        kms_key = str(body.get("kms_key_id") or "").strip()
        if kms_key and kms_key not in (_DEFAULT_SECRET_KEY, "alias/" + _DEFAULT_SECRET_KEY):
            req["KmsKeyId"] = kms_key
        st, data = _call("secretsmanager", "CreateSecret", req)
        if st != 200 and data.get("__type") == "ResourceExistsException":
            # pre-v4 console behaviour: creating an existing name writes a new value
            st, data = _call("secretsmanager", "PutSecretValue", {"SecretId": name, "SecretString": value})
        if st != 200:
            return _err(st, data, name=name)
        return {"ok": True, "name": name, "arn": data.get("ARN", ""), "version": data.get("VersionId", "")}

    @app.get("/api/aws/secrets/{name:path}", include_in_schema=False)
    async def aws_console_secret_get(name: str, request: Request):
        st, data = _call("secretsmanager", "GetSecretValue", {"SecretId": name})
        if st != 200:
            if data.get("__type") == "ResourceNotFoundException":
                return JSONResponse(status_code=404, content={"ok": False, "error": "secret not found", "name": name})
            return _err(st, data, name=name)
        value = data.get("SecretString")
        if value is None and data.get("SecretBinary") is not None:
            value = data["SecretBinary"]
        return {"ok": True, "name": data.get("Name", name), "value": value or "",
                "arn": data.get("ARN", ""), "version": data.get("VersionId", "")}

    @app.put("/api/aws/secrets/{name:path}", include_in_schema=False)
    async def aws_console_secret_update(name: str, request: Request):
        body = await _json_body(request)
        value = _secret_value(body, "") or ""
        st, data = _call("secretsmanager", "PutSecretValue", {"SecretId": name, "SecretString": value})
        if st != 200 and data.get("__type") == "ResourceNotFoundException":
            # pre-v4 console behaviour: updating an unknown secret creates it
            st, data = _call("secretsmanager", "CreateSecret", {"Name": name, "SecretString": value})
        if st != 200:
            return _err(st, data, name=name)
        return {"ok": True, "name": name, "updated": True, "version": data.get("VersionId", "")}

    @app.delete("/api/aws/secrets/{name:path}", include_in_schema=False)
    async def aws_console_secret_delete(name: str, request: Request):
        # The classic console's delete removes the secret now (pre-v4 behaviour) =
        # DeleteSecret with ForceDeleteWithoutRecovery. The native wire keeps the
        # recovery window.
        _call("secretsmanager", "DeleteSecret", {"SecretId": name, "ForceDeleteWithoutRecovery": True})
        return {"ok": True, "deleted": True, "name": name}


# ── KMS console ───────────────────────────────────────────────────────────
def _alias_for(key_id: str) -> str:
    from core import appliance_stores as aps
    for alias, kid in aps.aws_kms_store().alias_items():
        if kid == key_id and not alias.startswith("alias/aws/"):
            return alias
    return ""


def _key_row(md: dict) -> dict:
    return {"key_id": md["KeyId"], "name": md["KeyId"], "alias": _alias_for(md["KeyId"]),
            "arn": md.get("Arn", ""), "description": md.get("Description", ""),
            "enabled": bool(md.get("Enabled")), "state": md.get("KeyState", "Enabled"),
            "key_spec": md.get("KeySpec", "SYMMETRIC_DEFAULT"),
            "key_usage": md.get("KeyUsage", "ENCRYPT_DECRYPT"),
            "key_manager": md.get("KeyManager", "CUSTOMER"),
            "created": _iso(md.get("CreationDate"))}


def _describe(key_ref: str) -> tuple[int, dict]:
    return _call("kms", "DescribeKey", {"KeyId": key_ref})


def _register_kms_console(app) -> None:
    @app.get("/api/aws/kms/keys", include_in_schema=False)
    async def aws_console_kms_list(request: Request):
        st, data = _call("kms", "ListKeys", {})
        if st != 200:
            return _err(st, data)
        rows = []
        for k in data.get("Keys", []):
            dst, d = _describe(k["KeyId"])
            md = d.get("KeyMetadata") if dst == 200 else None
            if md and md.get("KeyManager", "CUSTOMER") == "CUSTOMER":   # "Customer managed keys"
                rows.append(_key_row(md))
        return {"items": rows}

    @app.post("/api/aws/kms/keys", include_in_schema=False)
    async def aws_console_kms_create(request: Request):
        body = await _json_body(request)
        req = {"Description": str(body.get("description") or ""),
               "KeySpec": str(body.get("key_spec") or "SYMMETRIC_DEFAULT"),
               "KeyUsage": str(body.get("key_usage") or "ENCRYPT_DECRYPT")}
        st, data = _call("kms", "CreateKey", req)
        if st != 200:
            return _err(st, data)
        key_id = data["KeyMetadata"]["KeyId"]
        alias = (body.get("name") or body.get("alias") or "").strip()
        if alias:
            alias = alias if alias.startswith("alias/") else f"alias/{alias}"
            ast, adata = _call("kms", "CreateAlias", {"AliasName": alias, "TargetKeyId": key_id})
            if ast != 200:
                return _err(ast, adata, key_id=key_id)
        return {"ok": True, "key_id": key_id, "alias": alias, "arn": data["KeyMetadata"].get("Arn", "")}

    @app.get("/api/aws/kms/keys/{key_id:path}", include_in_schema=False)
    async def aws_console_kms_get(key_id: str, request: Request):
        st, data = _describe(key_id)
        if st != 200:
            return JSONResponse(status_code=404, content={"ok": False, "error": "key not found", "key_id": key_id})
        return {"ok": True, **_key_row(data["KeyMetadata"])}

    @app.put("/api/aws/kms/keys/{key_id:path}", include_in_schema=False)
    async def aws_console_kms_update(key_id: str, request: Request):
        """Edit key metadata — description + enable/disable (= UpdateKeyDescription /
        EnableKey / DisableKey on the same store the native wire uses)."""
        st, data = _describe(key_id)
        if st != 200:
            return JSONResponse(status_code=404, content={"ok": False, "error": "key not found", "key_id": key_id})
        kid = data["KeyMetadata"]["KeyId"]
        body = await _json_body(request)
        if "description" in body:
            st, d = _call("kms", "UpdateKeyDescription", {"KeyId": kid, "Description": str(body.get("description") or "")})
            if st != 200:
                return _err(st, d, key_id=kid)
        if "enabled" in body:
            st, d = _call("kms", "EnableKey" if bool(body.get("enabled")) else "DisableKey", {"KeyId": kid})
            if st != 200:
                return _err(st, d, key_id=kid)
        md = _describe(kid)[1]["KeyMetadata"]
        return {"ok": True, "key_id": kid, "description": md.get("Description", ""),
                "enabled": bool(md.get("Enabled")), "state": md.get("KeyState", "Enabled")}

    @app.delete("/api/aws/kms/keys/{key_id:path}", include_in_schema=False)
    async def aws_console_kms_delete(key_id: str, request: Request):
        # Real KMS never deletes a key at once: schedule it (pre-v4 console behaviour).
        try:
            days = int(request.query_params.get("pending_window_days") or 30)
        except ValueError:
            days = 30
        st, data = _call("kms", "ScheduleKeyDeletion", {"KeyId": key_id, "PendingWindowInDays": days})
        if st != 200 and data.get("__type") != "KMSInvalidStateException":
            return _err(st, data, key_id=key_id)
        return {"ok": True, "scheduled": True, "key_id": key_id,
                "deletion_date": _iso(data.get("DeletionDate"))}


def register(app) -> set:
    """Mount the console REST of whichever of the two services is unified; returns
    the legacy path prefixes core/vault_routes must NOT register. (The native wire
    is routed by routes/aws_s3.aws_query_root.)"""
    skip: set = set()
    if _wi.is_unified("secretsmanager"):
        _register_secrets_console(app)
        skip.add("/api/aws/secrets")
    if _wi.is_unified("kms"):
        _register_kms_console(app)
        skip.add("/api/aws/kms/")
    return skip


def inventory(space: dict) -> dict:
    """{(svc, kind): {id: created_iso}} of a space's core-backed secrets / customer
    managed keys (billable), read straight from its service_states (for the cost /
    inventory collectors). Secrets scheduled for deletion and keys pending deletion
    are not counted; AWS managed keys are free, as in AWS."""
    ss = (space or {}).get("service_states") or {}
    out = {("secretsmanager", "secret"): {}, ("kms", "key"): {}}
    for name, sec in ((ss.get("secretsmanager") or {}).get("secrets") or {}).items():
        if isinstance(sec, dict) and not sec.get("deleted_date"):
            out[("secretsmanager", "secret")][name] = _iso(sec.get("created"))
    for kid, meta in ((ss.get("kms") or {}).get("keys") or {}).items():
        if (isinstance(meta, dict) and meta.get("KeyState") != "PendingDeletion"
                and meta.get("KeyManager", "CUSTOMER") == "CUSTOMER"):
            out[("kms", "key")][kid] = _iso(meta.get("CreationDate"))
    return out
