"""Provider-native KMS + Secrets data-plane endpoints, all backed by Vault.

Catalog/CRUD for keys and secrets already exists per provider as metadata-only
extras. This module adds the **operational endpoints** that real SDK clients
hit when they want to actually encrypt/decrypt or retrieve secret values, all
routed through ``core.vault_client``.

Wire shape per provider:

  AWS (boto3 JSON-RPC at /):
    X-Amz-Target: TrentService.Encrypt | Decrypt | GenerateDataKey
    X-Amz-Target: secretsmanager.GetSecretValue | PutSecretValue | CreateSecret

  GCP (REST at /v1/projects/...):
    POST .../keyRings/{r}/cryptoKeys/{k}:encrypt   {plaintext}
    POST .../keyRings/{r}/cryptoKeys/{k}:decrypt   {ciphertext}
    POST .../secrets                                {secretId}
    POST .../secrets/{s}/versions/{v}:access

  Azure Key Vault data-plane (REST at /azure-data/keyvault/{vault}/...):
    POST .../keys/{key}/encrypt?api-version=7.4    {alg, value}
    POST .../keys/{key}/decrypt?api-version=7.4    {alg, value}
    GET  .../secrets/{name}?api-version=7.4
    PUT  .../secrets/{name}?api-version=7.4         {value}

All endpoints fall back to a metadata-only response when Vault is unreachable
(``never break the control plane`` rule). The Vault path namespacing keeps
``aws/<space>/<key>`` distinct from ``gcp/<space>/<key>`` automatically.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from . import vault_client as vc

# Module-level KMS key metadata store: key_id -> key metadata dict
_kms_keys: dict[str, dict] = {}
# Module-level KMS alias store: alias_name -> key_id
_kms_aliases: dict[str, str] = {}


def _active_space_id(request: Request) -> str:
    """Get the active space ID from the platform — needed for Vault namespacing.

    Kept dependency-free of server.py to avoid an import cycle.
    """
    try:
        from core.app_context import PLATFORM  # local import to dodge cycles
        spaces_state = PLATFORM.kernel.state.setdefault(
            "spaces", {"spaces": {}, "active_space_id": "", "settings": {}}
        )
        return spaces_state.get("active_space_id", "default")
    except Exception:
        return "default"


def _vault_unavailable_response(provider: str) -> JSONResponse:
    return JSONResponse(
        {"error": "vault unavailable",
         "message": f"{provider} crypto/secrets ops require Vault; falling back to metadata-only"},
        status_code=503,
    )


# ============================================================================
# AWS — JSON-RPC at "/" dispatched by X-Amz-Target header
# ============================================================================
# We mount our handlers on /__vault_kms_aws and /__vault_secrets_aws and ALSO
# patch server.py's existing root POST dispatcher (see register()) so that
# X-Amz-Target=TrentService.* and =secretsmanager.* route here.

def _kms_resolve_key_name(body: dict) -> str:
    """Resolve the key name from various body fields."""
    key = body.get("KeyId") or body.get("KeyArn") or body.get("KeyAlias") or "default"
    # Check if it's an alias reference
    if key.startswith("alias/"):
        alias_name = key
        resolved = _kms_aliases.get(alias_name)
        if resolved:
            key = resolved
    key_name = key.split("/")[-1] if "/" in key else key
    return key_name


def _kms_key_metadata(key_id: str) -> dict | None:
    """Return stored key metadata, or None."""
    return _kms_keys.get(key_id)


async def _aws_kms_dispatch(target: str, body: dict, space: str) -> dict | None:
    """Return the response dict for an AWS KMS X-Amz-Target, or None if not handled."""
    op = target.split(".", 1)[-1]  # "TrentService.Encrypt" → "Encrypt"
    key = body.get("KeyId") or body.get("KeyArn") or body.get("KeyAlias") or "default"
    key_name = _kms_resolve_key_name(body)

    if op == "Encrypt":
        pt_b64 = body.get("Plaintext", "")
        ct = vc.transit_encrypt("aws", space, key_name, pt_b64) or ""
        ct_wrapped = base64.b64encode(ct.encode()).decode()
        return {"KeyId": key, "CiphertextBlob": ct_wrapped}
    if op == "Decrypt":
        ct_in = body.get("CiphertextBlob", "")
        try:
            ct = base64.b64decode(ct_in).decode()
            if not ct.startswith("vault:"):
                ct = ct_in
        except Exception:
            ct = ct_in
        pt = vc.transit_decrypt("aws", space, key_name, ct) or ""
        return {"KeyId": key, "Plaintext": pt}
    if op == "GenerateDataKey":
        spec = body.get("KeySpec", "AES_256")
        vc.transit_create_key("aws", space, key_name)
        r = vc.transit_generate_data_key("aws", space, key_name, key_spec=spec)
        if not r:
            return None
        return {"KeyId": key, "Plaintext": r["Plaintext"], "CiphertextBlob": r["CiphertextBlob"]}
    if op == "CreateKey":
        import uuid as _uuid
        key_id = body.get("KeyId") or _uuid.uuid4().hex
        vc.transit_create_key("aws", space, key_id)
        metadata = {
            "KeyId": key_id,
            "Arn": f"arn:aws:kms:us-east-1:000000000000:key/{key_id}",
            "Enabled": True,
            "Description": body.get("Description", ""),
            "KeyUsage": body.get("KeyUsage", "ENCRYPT_DECRYPT"),
            "KeySpec": body.get("KeySpec", "SYMMETRIC_DEFAULT"),
            "KeyState": "Enabled",
            "Origin": "AWS_KMS",
            "CreationDate": time.time(),
        }
        _kms_keys[key_id] = metadata
        return {"KeyMetadata": metadata}
    if op == "DescribeKey":
        stored = _kms_key_metadata(key_name)
        if stored:
            return {"KeyMetadata": stored}
        vc.transit_create_key("aws", space, key_name)
        return {"KeyMetadata": {
            "KeyId": key_name, "Arn": f"arn:aws:kms:us-east-1:000000000000:key/{key_name}",
            "Enabled": True, "KeyUsage": "ENCRYPT_DECRYPT",
            "KeyState": "Enabled", "Origin": "AWS_KMS",
        }}
    if op == "ListKeys":
        keys = [{"KeyId": k, "KeyArn": v.get("Arn", f"arn:aws:kms:us-east-1:000000000000:key/{k}")}
                for k, v in _kms_keys.items()]
        return {"Keys": keys, "Truncated": False}
    if op == "ScheduleKeyDeletion":
        stored = _kms_keys.get(key_name)
        if not stored:
            return {"__type": "NotFoundException", "message": f"Key {key_name} not found."}
        pending_days = body.get("PendingWindowInDays", 30)
        stored["KeyState"] = "PendingDeletion"
        stored["Enabled"] = False
        stored["DeletionDate"] = time.time() + (pending_days * 86400)
        return {"KeyId": stored["KeyId"], "KeyState": "PendingDeletion",
                "DeletionDate": stored["DeletionDate"]}
    if op == "EnableKey":
        stored = _kms_keys.get(key_name)
        if not stored:
            return {"__type": "NotFoundException", "message": f"Key {key_name} not found."}
        stored["Enabled"] = True
        stored["KeyState"] = "Enabled"
        return {}
    if op == "DisableKey":
        stored = _kms_keys.get(key_name)
        if not stored:
            return {"__type": "NotFoundException", "message": f"Key {key_name} not found."}
        stored["Enabled"] = False
        stored["KeyState"] = "Disabled"
        return {}
    if op == "CreateAlias":
        alias_name = body.get("AliasName", "")
        target_key_id = body.get("TargetKeyId", "")
        if not alias_name or not target_key_id:
            return {"__type": "ValidationException", "message": "AliasName and TargetKeyId are required."}
        _kms_aliases[alias_name] = target_key_id
        return {}
    if op == "ListAliases":
        aliases = []
        for alias_name, target_key_id in _kms_aliases.items():
            aliases.append({
                "AliasName": alias_name,
                "AliasArn": f"arn:aws:kms:us-east-1:000000000000:{alias_name}",
                "TargetKeyId": target_key_id,
            })
        return {"Aliases": aliases, "Truncated": False}
    return None


async def _aws_secrets_dispatch(target: str, body: dict, space: str) -> dict | None:
    op = target.split(".", 1)[-1]
    name = body.get("SecretId") or body.get("Name") or "default"

    if op == "CreateSecret":
        value = body.get("SecretString") or json.dumps(body.get("SecretBinary", ""))
        md = vc.kv_put("aws", space, name, value)
        if md is None:
            return None
        return {"Name": name, "ARN": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{name}",
                "VersionId": str(md.get("version", 1))}
    if op in ("GetSecretValue",):
        got = vc.kv_get("aws", space, name)
        if got is None:
            return None
        data = got.get("data", {})
        value = data.get("value") if "value" in data else json.dumps(data)
        return {"Name": name, "ARN": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{name}",
                "SecretString": value, "VersionId": str((got.get("metadata") or {}).get("version", 1))}
    if op in ("PutSecretValue", "UpdateSecret"):
        value = body.get("SecretString") or json.dumps(body.get("SecretBinary", ""))
        md = vc.kv_put("aws", space, name, value)
        if md is None:
            return None
        return {"Name": name, "ARN": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{name}",
                "VersionId": str(md.get("version", 1))}
    if op == "DeleteSecret":
        vc.kv_delete("aws", space, name)
        return {"Name": name, "ARN": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{name}",
                "DeletionDate": time.time()}
    if op == "ListSecretVersionIds":
        versions = vc.kv_list_versions("aws", space, name)
        return {"Name": name, "Versions": [
            {"VersionId": str(v["version"]), "CreatedDate": v.get("created_time")}
            for v in versions
        ]}
    return None


# ============================================================================
# GCP — REST endpoints
# ============================================================================
def _register_gcp(app: FastAPI) -> None:
    @app.post("/v1/projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}:encrypt")
    async def gcp_kms_encrypt(project: str, loc: str, ring: str, key: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        key_name = f"{ring}__{key}"
        vc.transit_create_key("gcp", space, key_name)
        pt_b64 = body.get("plaintext", "")
        ct = vc.transit_encrypt("gcp", space, key_name, pt_b64)
        if ct is None:
            return _vault_unavailable_response("gcp.kms")
        # Vault returns ``vault:v1:<base64>`` as an opaque string. Google's KMS
        # proto expects the ``ciphertext`` field to be valid base64-encoded
        # bytes (decoders barf on the "vault:v1:" prefix). Wrap the whole
        # opaque blob in base64 so it round-trips through the proto decoder.
        ct_wrapped = base64.b64encode(ct.encode()).decode()
        return {
            "name": f"projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}/cryptoKeyVersions/1",
            "ciphertext": ct_wrapped,
            "ciphertextCrc32c": str(zlib_crc32(ct_wrapped.encode())),
        }

    @app.post("/v1/projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}:decrypt")
    async def gcp_kms_decrypt(project: str, loc: str, ring: str, key: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        key_name = f"{ring}__{key}"
        # Inbound ciphertext was wrapped by our encrypt response — unwrap before
        # handing to Vault transit. (Backward-compat: if the wrap fails, fall
        # back to using the value directly so old clients still work.)
        ct_in = body.get("ciphertext", "")
        try:
            ct = base64.b64decode(ct_in).decode()
            if not ct.startswith("vault:"):
                ct = ct_in  # not our wrap, pass through
        except Exception:
            ct = ct_in
        pt = vc.transit_decrypt("gcp", space, key_name, ct)
        if pt is None:
            return _vault_unavailable_response("gcp.kms")
        return {
            "plaintext": pt,
            "plaintextCrc32c": str(zlib_crc32(pt.encode())),
        }

    @app.post("/v1/projects/{project}/secrets")
    async def gcp_secrets_create(project: str, request: Request):
        body = await request.json()
        name = request.query_params.get("secretId") or body.get("secretId") or "default"
        # Create the secret metadata; an initial value comes via :addVersion.
        return {
            "name": f"projects/{project}/secrets/{name}",
            "replication": body.get("replication", {"automatic": {}}),
            "createTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @app.post("/v1/projects/{project}/secrets/{secret}:addVersion")
    async def gcp_secrets_add_version(project: str, secret: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        payload = body.get("payload", {})
        data_b64 = payload.get("data", "")
        # Decode base64 since Vault KV stores arbitrary string.
        try:
            raw = base64.b64decode(data_b64).decode()
        except Exception:
            raw = data_b64
        md = vc.kv_put("gcp", space, secret, raw)
        if md is None:
            return _vault_unavailable_response("gcp.secrets")
        return {
            "name": f"projects/{project}/secrets/{secret}/versions/{md.get('version', 1)}",
            "createTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "state": "ENABLED",
        }

    # Real Google Secret Manager allows BOTH GET and POST on :access; the
    # google-cloud-go SDK's REST transport uses GET (with the ?$alt=json query
    # param appended). Register both so unmodified SDK clients work.
    @app.get("/v1/projects/{project}/secrets/{secret}/versions/{version}:access")
    @app.post("/v1/projects/{project}/secrets/{secret}/versions/{version}:access")
    async def gcp_secrets_access(project: str, secret: str, version: str, request: Request):
        space = _active_space_id(request)
        v = None if version == "latest" else int(version)
        got = vc.kv_get("gcp", space, secret, version=v)
        if got is None:
            return _vault_unavailable_response("gcp.secrets")
        data = got.get("data", {})
        raw = data.get("value") if "value" in data else json.dumps(data)
        return {
            "name": f"projects/{project}/secrets/{secret}/versions/{(got.get('metadata') or {}).get('version', 1)}",
            "payload": {"data": base64.b64encode(raw.encode()).decode()},
        }


# ============================================================================
# Azure Key Vault data plane — REST under /azure-data/keyvault/{vault}/
# ============================================================================
def _register_azure(app: FastAPI) -> None:
    @app.post("/azure-data/keyvault/{vault}/keys/{key}/encrypt")
    async def az_kv_encrypt(vault: str, key: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        key_name = f"{vault}__{key}"
        vc.transit_create_key("azure", space, key_name)
        # Azure SDK sends base64url-encoded plaintext (no padding). Vault
        # transit expects base64. Inbound plaintext: b64url → b64.
        # Outbound ciphertext: Vault returns "vault:v1:<b64>" which we pass
        # through as opaque bytes (real Azure ciphertext is also opaque to
        # the caller).
        val_b64url = body.get("value", "")
        ct = vc.transit_encrypt("azure", space, key_name, _b64url_to_b64(val_b64url))
        if ct is None:
            return _vault_unavailable_response("azure.kv")
        return {
            "kid": f"https://{vault}/keys/{key}/{int(time.time())}",
            "value": ct,  # opaque "vault:v1:..." round-trips through decrypt
        }

    @app.post("/azure-data/keyvault/{vault}/keys/{key}/decrypt")
    async def az_kv_decrypt(vault: str, key: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        key_name = f"{vault}__{key}"
        # Ciphertext came back from our encrypt as the opaque vault:v1:...
        # string. Pass it back to Vault as-is.
        ct = body.get("value", "")
        pt_b64 = vc.transit_decrypt("azure", space, key_name, ct)
        if pt_b64 is None:
            return _vault_unavailable_response("azure.kv")
        # Convert b64 plaintext back to b64url for the Azure SDK.
        return {
            "kid": f"https://{vault}/keys/{key}/latest",
            "value": _b64_to_b64url(pt_b64),
        }

    @app.get("/azure-data/keyvault/{vault}/secrets/{secret}")
    async def az_kv_secret_get(vault: str, secret: str, request: Request):
        space = _active_space_id(request)
        got = vc.kv_get("azure", space, f"{vault}__{secret}")
        if got is None:
            return _vault_unavailable_response("azure.kv")
        data = got.get("data", {})
        value = data.get("value") if "value" in data else json.dumps(data)
        return {
            "id": f"https://{vault}/secrets/{secret}/{(got.get('metadata') or {}).get('version', 1)}",
            "value": value,
            "attributes": {"enabled": True, "created": int(time.time())},
        }

    @app.put("/azure-data/keyvault/{vault}/secrets/{secret}")
    async def az_kv_secret_put(vault: str, secret: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        value = body.get("value", "")
        md = vc.kv_put("azure", space, f"{vault}__{secret}", value)
        if md is None:
            return _vault_unavailable_response("azure.kv")
        return {
            "id": f"https://{vault}/secrets/{secret}/{md.get('version', 1)}",
            "value": value,
            "attributes": {"enabled": True, "created": int(time.time())},
        }


# ============================================================================
# Helpers
# ============================================================================
def _b64url_to_b64(s: str) -> str:
    # Azure SDK uses URL-safe base64 without padding; Vault wants standard b64.
    pad = "=" * (-len(s) % 4)
    return base64.b64encode(base64.urlsafe_b64decode(s + pad)).decode()


def _b64_to_b64url(s: str) -> str:
    try:
        return base64.urlsafe_b64encode(base64.b64decode(s)).decode().rstrip("=")
    except Exception:
        return s


def zlib_crc32(data: bytes) -> int:
    import zlib
    return zlib.crc32(data)


# ============================================================================
# Public registration
# ============================================================================
def register(app: FastAPI, aws_dispatchers: dict | None = None) -> None:
    """Mount GCP + Azure routes and expose AWS dispatchers for server.py to wire."""
    _register_gcp(app)
    _register_azure(app)
    if aws_dispatchers is not None:
        aws_dispatchers["TrentService"] = _aws_kms_dispatch        # KMS uses TrentService
        aws_dispatchers["secretsmanager"] = _aws_secrets_dispatch  # Secrets uses secretsmanager
