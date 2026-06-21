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
        _aws_secret_index_add(space, name)   # so the console list sees SDK-created secrets
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
        _aws_secret_index_add(space, name)
        return {"Name": name, "ARN": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{name}",
                "VersionId": str(md.get("version", 1))}
    if op == "DeleteSecret":
        vc.kv_delete("aws", space, name)
        _aws_secret_index_remove(space, name)
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
def _gcp_idx_get(space: str, kind: str) -> list:
    """KV-backed name index for GCP secrets / KMS keys (Vault has no list)."""
    got = vc.kv_get("gcp", space, f"__idx__{kind}")
    if not got:
        return []
    try:
        raw = (got.get("data") or {}).get("value", "[]")
        return json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        return []


def _gcp_idx_add(space: str, kind: str, entry: str) -> None:
    items = _gcp_idx_get(space, kind)
    if entry not in items:
        vc.kv_put("gcp", space, f"__idx__{kind}", json.dumps(sorted(items + [entry])))


def _gcp_idx_remove(space: str, kind: str, entry: str) -> None:
    items = [x for x in _gcp_idx_get(space, kind) if x != entry]
    vc.kv_put("gcp", space, f"__idx__{kind}", json.dumps(items))


def _register_gcp(app: FastAPI) -> None:
    @app.post("/v1/projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}:encrypt")
    async def gcp_kms_encrypt(project: str, loc: str, ring: str, key: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        key_name = f"{ring}__{key}"
        vc.transit_create_key("gcp", space, key_name)
        _gcp_idx_add(space, "kms", f"{ring}/{key}")   # so the console list sees SDK-used keys
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

    # Native createKeyRing / createCryptoKey / getCryptoKey — the google-cloud-kms
    # SDK creates the ring + key before encrypting; these were unserved (404).
    # Encrypt auto-provisions the transit key anyway, so create just registers it.
    @app.post("/v1/projects/{project}/locations/{loc}/keyRings")
    async def gcp_kms_create_keyring(project: str, loc: str, request: Request):
        ring = request.query_params.get("keyRingId", "")
        return {"name": f"projects/{project}/locations/{loc}/keyRings/{ring}",
                "createTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def _gcp_cryptokey_view(project: str, loc: str, ring: str, key: str) -> dict:
        base = f"projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {
            "name": base, "purpose": "ENCRYPT_DECRYPT", "createTime": now,
            "primary": {"name": f"{base}/cryptoKeyVersions/1", "state": "ENABLED",
                        "protectionLevel": "SOFTWARE",
                        "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION", "createTime": now},
            "versionTemplate": {"protectionLevel": "SOFTWARE",
                                "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION"},
        }

    @app.post("/v1/projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys")
    async def gcp_kms_create_cryptokey(project: str, loc: str, ring: str, request: Request):
        space = _active_space_id(request)
        key = request.query_params.get("cryptoKeyId", "")
        vc.transit_create_key("gcp", space, f"{ring}__{key}")
        _gcp_idx_add(space, "kms", f"{ring}/{key}")
        return _gcp_cryptokey_view(project, loc, ring, key)

    @app.get("/v1/projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}")
    async def gcp_kms_get_cryptokey(project: str, loc: str, ring: str, key: str, request: Request):
        return _gcp_cryptokey_view(project, loc, ring, key)

    @app.post("/v1/projects/{project}/secrets")
    async def gcp_secrets_create(project: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        name = request.query_params.get("secretId") or body.get("secretId") or "default"
        _gcp_idx_add(space, "secrets", name)   # so the console list sees SDK-created secrets
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
        _gcp_idx_add(space, "secrets", secret)
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

    # Native DELETE (the google-cloud-secretmanager SDK's deleteSecret) — was
    # missing, so SDK + console cleanup had nowhere to land.
    @app.delete("/v1/projects/{project}/secrets/{secret}")
    async def gcp_secrets_delete(project: str, secret: str, request: Request):
        space = _active_space_id(request)
        vc.kv_delete("gcp", space, secret)
        _gcp_idx_remove(space, "secrets", secret)
        return {}

    # ── GCP console CRUD (conformant — same Vault paths the native HttpJson
    #    Secret Manager / Cloud KMS SDKs use). Catalog points the consoles here,
    #    off the in-process /api/gcp/extras/* (which would be a false green).
    @app.get("/api/gcp/secrets")
    async def gcp_console_secrets_list(request: Request):
        space = _active_space_id(request)
        return {"items": [{"name": n, "replication": "automatic", "latest_version": "1"}
                          for n in _gcp_idx_get(space, "secrets")]}

    @app.post("/api/gcp/secrets")
    async def gcp_console_secret_create(request: Request):
        space = _active_space_id(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "missing 'name'"})
        if vc.kv_put("gcp", space, name, body.get("value", "changeme")) is None:
            return _vault_unavailable_response("gcp.secrets")
        _gcp_idx_add(space, "secrets", name)
        return {"ok": True, "name": name}

    @app.get("/api/gcp/secrets/{name}")
    async def gcp_console_secret_get(name: str, request: Request):
        space = _active_space_id(request)
        got = vc.kv_get("gcp", space, name)
        if got is None:
            return JSONResponse(status_code=404,
                                content={"ok": False, "error": "secret not found", "name": name})
        data = got.get("data", {})
        value = data.get("value") if "value" in data else json.dumps(data)
        return {"ok": True, "name": name, "value": value}

    @app.put("/api/gcp/secrets/{name}")
    async def gcp_console_secret_update(name: str, request: Request):
        space = _active_space_id(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        value = body.get("value") or body.get("payload", {}).get("data") or ""
        if vc.kv_put("gcp", space, name, value) is None:
            return _vault_unavailable_response("gcp.secrets")
        _gcp_idx_add(space, "secrets", name)
        return {"ok": True, "name": name, "updated": True}

    @app.delete("/api/gcp/secrets/{name}")
    async def gcp_console_secret_delete(name: str, request: Request):
        space = _active_space_id(request)
        vc.kv_delete("gcp", space, name)
        _gcp_idx_remove(space, "secrets", name)
        return {"ok": True, "deleted": True, "name": name}

    @app.get("/api/gcp/kms/keys")
    async def gcp_console_kms_list(request: Request):
        space = _active_space_id(request)
        out = []
        for entry in _gcp_idx_get(space, "kms"):
            ring, _, key = entry.partition("/")
            out.append({"name": key or entry, "keyring": ring,
                        "purpose": "ENCRYPT_DECRYPT",
                        "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
                        "protection": "SOFTWARE", "state": "ENABLED"})
        return {"items": out}

    @app.post("/api/gcp/kms/keys")
    async def gcp_console_kms_create(request: Request):
        space = _active_space_id(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = (body.get("name") or "").strip()
        ring = (body.get("keyring") or "default-ring").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "missing 'name'"})
        vc.transit_create_key("gcp", space, f"{ring}__{name}")
        _gcp_idx_add(space, "kms", f"{ring}/{name}")
        return {"ok": True, "name": name, "keyring": ring}

    def _gcp_kms_ring(space: str, name: str) -> str:
        for entry in _gcp_idx_get(space, "kms"):
            if entry == name or entry.split("/")[-1] == name:
                return entry.partition("/")[0]
        return "default-ring"

    def _gcp_kms_meta(space: str, name: str) -> dict:
        raw = vc.kv_get("gcp", space, f"__kmsmeta__{name}")
        data = (raw or {}).get("data") if isinstance(raw, dict) else None
        return data if isinstance(data, dict) else {}

    @app.get("/api/gcp/kms/keys/{name}")
    async def gcp_console_kms_get(name: str, request: Request):
        space = _active_space_id(request)
        ring = _gcp_kms_ring(space, name)
        meta = _gcp_kms_meta(space, name)
        return {"ok": True, "name": name, "keyring": ring,
                "purpose": "ENCRYPT_DECRYPT",
                "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
                "protection": "SOFTWARE", "state": "ENABLED",
                "labels": meta.get("labels", {}),
                "rotation_period": meta.get("rotation_period", ""),
                "next_rotation": meta.get("next_rotation", "")}

    @app.put("/api/gcp/kms/keys/{name}")
    async def gcp_console_kms_update(name: str, request: Request):
        space = _active_space_id(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        meta = _gcp_kms_meta(space, name)
        if "labels" in body and isinstance(body["labels"], dict):
            meta["labels"] = {str(k): str(v) for k, v in body["labels"].items()}
        if "rotation_period" in body:
            meta["rotation_period"] = str(body.get("rotation_period") or "")
        if "next_rotation" in body:
            meta["next_rotation"] = str(body.get("next_rotation") or "")
        vc.kv_put("gcp", space, f"__kmsmeta__{name}", dict(meta))
        return {"ok": True, "name": name, "labels": meta.get("labels", {}),
                "rotation_period": meta.get("rotation_period", "")}

    @app.delete("/api/gcp/kms/keys/{name}")
    async def gcp_console_kms_delete(name: str, request: Request):
        space = _active_space_id(request)
        for entry in list(_gcp_idx_get(space, "kms")):
            if entry == name or entry.split("/")[-1] == name:
                _gcp_idx_remove(space, "kms", entry)
        vc.kv_delete("gcp", space, f"__kmsmeta__{name}")
        return {"ok": True, "deleted": True, "name": name}


# ============================================================================
# Azure Key Vault data plane — REST under /azure-data/keyvault/{vault}/
# ============================================================================
def _register_azure(app: FastAPI) -> None:
    # ── Key Vault KEYS (real RSA) ─────────────────────────────────────────────
    # The native CryptographyClient does RSA-OAEP *client-side*: it fetches the
    # public key (create/get) and encrypts locally, then calls the service only
    # to DECRYPT with the private key. Vault transit's symmetric encrypt/decrypt
    # can't satisfy that, so we generate a real RSA keypair (stored in Vault KV)
    # and decrypt with the private key. The `kid` is built from the request Host
    # so the SDK sends decrypt back to THIS appliance (not real *.vault.azure.net).
    def _azkv_key_enabled(space: str, vault: str, key: str) -> bool:
        raw = vc.kv_get("azure", space, f"{vault}__{key}__attrs")
        data = (raw or {}).get("data") if isinstance(raw, dict) else None
        if isinstance(data, dict) and "enabled" in data:
            return str(data["enabled"]).lower() != "false"
        return True

    def _azkv_key_set_enabled(space: str, vault: str, key: str, enabled: bool) -> None:
        vc.kv_put("azure", space, f"{vault}__{key}__attrs", {"enabled": bool(enabled)})

    @app.post("/azure-data/keyvault/{vault}/keys/{key}/create")
    async def az_kv_key_create(vault: str, key: str, request: Request):
        space = _active_space_id(request)
        try:
            await request.json()
        except Exception:
            pass
        jwk = _azkv_rsa_create(space, vault, key, request)
        if jwk is None:
            return _vault_unavailable_response("azure.kv")
        _azkv_key_set_enabled(space, vault, key, True)
        now = int(time.time())
        return {"key": jwk, "attributes": {"enabled": True, "created": now,
                "updated": now, "recoveryLevel": "Purgeable"}}

    @app.get("/azure-data/keyvault/{vault}/keys/{key}")
    @app.get("/azure-data/keyvault/{vault}/keys/{key}/{version}")
    async def az_kv_key_get(vault: str, key: str, request: Request, version: str = ""):
        space = _active_space_id(request)
        jwk = _azkv_rsa_jwk(space, vault, key, request)
        if jwk is None:
            return JSONResponse(status_code=404, content={"error": {
                "code": "KeyNotFound", "message": f"Key {key} not found"}})
        return {"key": jwk, "attributes": {"enabled": _azkv_key_enabled(space, vault, key),
                "created": int(time.time()),
                "updated": int(time.time()), "recoveryLevel": "Purgeable"}}

    @app.patch("/azure-data/keyvault/{vault}/keys/{key}")
    @app.patch("/azure-data/keyvault/{vault}/keys/{key}/{version}")
    async def az_kv_key_update(vault: str, key: str, request: Request, version: str = ""):
        # Native KeyClient.updateKeyProperties() PATCHes {attributes:{enabled}}.
        space = _active_space_id(request)
        jwk = _azkv_rsa_jwk(space, vault, key, request)
        if jwk is None:
            return JSONResponse(status_code=404, content={"error": {
                "code": "KeyNotFound", "message": f"Key {key} not found"}})
        try:
            body = await request.json()
        except Exception:
            body = {}
        attrs = body.get("attributes") or {}
        if "enabled" in attrs:
            _azkv_key_set_enabled(space, vault, key, bool(attrs["enabled"]))
        now = int(time.time())
        return {"key": jwk, "attributes": {"enabled": _azkv_key_enabled(space, vault, key),
                "created": now, "updated": now, "recoveryLevel": "Purgeable"}}

    @app.get("/azure-data/keyvault/{vault}/keys")
    async def az_kv_key_list(vault: str, request: Request):
        space = _active_space_id(request)
        host = request.headers.get("host", "localhost")
        return {"value": [{"kid": f"https://{host}/keys/{n}",
                "attributes": {"enabled": _azkv_key_enabled(space, vault, n)}}
                for n in _azkv_index_get(space, vault, "keys")]}

    @app.delete("/azure-data/keyvault/{vault}/keys/{key}")
    async def az_kv_key_delete(vault: str, key: str, request: Request):
        space = _active_space_id(request)
        vc.kv_delete("azure", space, f"{vault}__{key}__rsapriv")
        vc.kv_delete("azure", space, f"{vault}__{key}__attrs")
        _azkv_index_remove(space, vault, "keys", key)
        return {"recoveryId": f"{vault}/deletedkeys/{key}", "deletedDate": int(time.time())}

    @app.post("/azure-data/keyvault/{vault}/keys/{key}/encrypt")
    @app.post("/azure-data/keyvault/{vault}/keys/{key}/{version}/encrypt")
    async def az_kv_encrypt(vault: str, key: str, request: Request, version: str = ""):
        space = _active_space_id(request)
        body = await request.json()
        ct = _azkv_rsa_encrypt(space, vault, key, body.get("value", ""), body.get("alg", "RSA-OAEP"))
        if ct is None:
            return JSONResponse(status_code=404, content={"error": {"code": "KeyNotFound"}})
        host = request.headers.get("host", "localhost")
        return {"kid": f"https://{host}/keys/{key}", "value": ct}

    @app.post("/azure-data/keyvault/{vault}/keys/{key}/decrypt")
    @app.post("/azure-data/keyvault/{vault}/keys/{key}/{version}/decrypt")
    async def az_kv_decrypt(vault: str, key: str, request: Request, version: str = ""):
        space = _active_space_id(request)
        body = await request.json()
        pt = _azkv_rsa_decrypt(space, vault, key, body.get("value", ""), body.get("alg", "RSA-OAEP"))
        if pt is None:
            return JSONResponse(status_code=404, content={"error": {"code": "KeyNotFound"}})
        host = request.headers.get("host", "localhost")
        return {"kid": f"https://{host}/keys/{key}", "value": pt}

    # ── Key Vault SECRETS (Vault KV-backed) — get/put + list/delete + index ───
    @app.get("/azure-data/keyvault/{vault}/secrets/{secret}")
    @app.get("/azure-data/keyvault/{vault}/secrets/{secret}/{version:path}")
    async def az_kv_secret_get(vault: str, secret: str, request: Request, version: str = ""):
        space = _active_space_id(request)
        got = vc.kv_get("azure", space, f"{vault}__{secret}")
        if got is None:
            return _vault_unavailable_response("azure.kv")
        data = got.get("data", {})
        value = data.get("value") if "value" in data else json.dumps(data)
        host = request.headers.get("host", "localhost")
        return {
            "id": f"https://{host}/secrets/{secret}/{(got.get('metadata') or {}).get('version', 1)}",
            "value": value,
            "attributes": {"enabled": True, "created": int(time.time()),
                           "updated": int(time.time()), "recoveryLevel": "Purgeable"},
        }

    @app.put("/azure-data/keyvault/{vault}/secrets/{secret}")
    async def az_kv_secret_put(vault: str, secret: str, request: Request):
        space = _active_space_id(request)
        body = await request.json()
        value = body.get("value", "")
        md = vc.kv_put("azure", space, f"{vault}__{secret}", value)
        if md is None:
            return _vault_unavailable_response("azure.kv")
        _azkv_index_add(space, vault, "secrets", secret)
        host = request.headers.get("host", "localhost")
        return {
            "id": f"https://{host}/secrets/{secret}/{md.get('version', 1)}",
            "value": value,
            "attributes": {"enabled": True, "created": int(time.time()),
                           "updated": int(time.time()), "recoveryLevel": "Purgeable"},
        }

    @app.get("/azure-data/keyvault/{vault}/secrets")
    async def az_kv_secret_list(vault: str, request: Request):
        space = _active_space_id(request)
        host = request.headers.get("host", "localhost")
        return {"value": [{"id": f"https://{host}/secrets/{n}",
                "attributes": {"enabled": True}} for n in _azkv_index_get(space, vault, "secrets")]}

    @app.delete("/azure-data/keyvault/{vault}/secrets/{secret}")
    async def az_kv_secret_delete(vault: str, secret: str, request: Request):
        space = _active_space_id(request)
        vc.kv_delete("azure", space, f"{vault}__{secret}")
        _azkv_index_remove(space, vault, "secrets", secret)
        return {"recoveryId": f"{vault}/deletedsecrets/{secret}", "deletedDate": int(time.time())}


# ── Azure Key Vault helpers (RSA keys + KV-backed name index for list) ────────
def _azkv_index_get(space: str, vault: str, kind: str) -> list:
    got = vc.kv_get("azure", space, f"__idx__{vault}__{kind}")
    if not got:
        return []
    try:
        raw = (got.get("data") or {}).get("value", "[]")
        return json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        return []


def _azkv_index_add(space: str, vault: str, kind: str, name: str) -> None:
    names = _azkv_index_get(space, vault, kind)
    if name not in names:
        vc.kv_put("azure", space, f"__idx__{vault}__{kind}", json.dumps(sorted(names + [name])))


def _azkv_index_remove(space: str, vault: str, kind: str, name: str) -> None:
    names = [n for n in _azkv_index_get(space, vault, kind) if n != name]
    vc.kv_put("azure", space, f"__idx__{vault}__{kind}", json.dumps(names))


def _azkv_b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _azkv_b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _azkv_jwk_from_priv(priv, vault: str, key: str, request: Request) -> dict:
    nums = priv.public_key().public_numbers()

    def _i(i):
        return _azkv_b64url(i.to_bytes((i.bit_length() + 7) // 8, "big"))
    host = request.headers.get("host", "localhost")
    return {"kid": f"https://{host}/keys/{key}/1",
            "kty": "RSA",
            "key_ops": ["encrypt", "decrypt", "wrapKey", "unwrapKey", "sign", "verify"],
            "n": _i(nums.n), "e": _i(nums.e)}


def _azkv_load_priv(space: str, vault: str, key: str):
    from cryptography.hazmat.primitives import serialization
    got = vc.kv_get("azure", space, f"{vault}__{key}__rsapriv")
    pem = ((got or {}).get("data") or {}).get("value") if got else None
    if not pem:
        return None
    try:
        return serialization.load_pem_private_key(pem.encode(), password=None)
    except Exception:
        return None


def _azkv_rsa_create(space: str, vault: str, key: str, request: Request):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    if vc.kv_put("azure", space, f"{vault}__{key}__rsapriv", pem) is None:
        return None
    _azkv_index_add(space, vault, "keys", key)
    return _azkv_jwk_from_priv(priv, vault, key, request)


def _azkv_rsa_jwk(space: str, vault: str, key: str, request: Request):
    priv = _azkv_load_priv(space, vault, key)
    return _azkv_jwk_from_priv(priv, vault, key, request) if priv else None


def _azkv_oaep(alg: str):
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    if (alg or "").upper().replace("_", "-") == "RSA-OAEP-256":
        return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)


def _azkv_rsa_encrypt(space: str, vault: str, key: str, value_b64url: str, alg: str):
    priv = _azkv_load_priv(space, vault, key)
    if not priv:
        return None
    try:
        ct = priv.public_key().encrypt(_azkv_b64url_decode(value_b64url), _azkv_oaep(alg))
        return _azkv_b64url(ct)
    except Exception:
        return None


def _azkv_rsa_decrypt(space: str, vault: str, key: str, value_b64url: str, alg: str):
    priv = _azkv_load_priv(space, vault, key)
    if not priv:
        return None
    try:
        pt = priv.decrypt(_azkv_b64url_decode(value_b64url), _azkv_oaep(alg))
        return _azkv_b64url(pt)
    except Exception:
        return None


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
# ── AWS console CRUD (conformant — same Vault backend the native SDKs use) ────
# The legacy /api/aws/extras/* console routes write to in-process service_states
# dicts, which the native Secrets Manager / KMS SDKs (Vault-backed) never see —
# a false green. These routes read/write the SAME Vault paths as the native
# dispatchers (_aws_secrets_dispatch / _aws_kms_dispatch), so console writes are
# SDK-visible and vice-versa. The AWS catalog points the consoles here.
def _aws_secret_index_get(space: str) -> list:
    got = vc.kv_get("aws", space, "__idx__secrets")
    if not got:
        return []
    try:
        raw = (got.get("data") or {}).get("value", "[]")
        return json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        return []


def _aws_secret_index_add(space: str, name: str) -> None:
    names = _aws_secret_index_get(space)
    if name not in names:
        vc.kv_put("aws", space, "__idx__secrets", json.dumps(sorted(names + [name])))


def _aws_secret_index_remove(space: str, name: str) -> None:
    names = [n for n in _aws_secret_index_get(space) if n != name]
    vc.kv_put("aws", space, "__idx__secrets", json.dumps(names))


def _aws_alias_for(key_id: str) -> str:
    for a, k in _kms_aliases.items():
        if k == key_id:
            return a
    return ""


def _register_aws_console(app: FastAPI) -> None:
    @app.get("/api/aws/secrets")
    async def aws_console_secrets_list(request: Request):
        space = _active_space_id(request)
        return {"items": [{"name": n, "secret_type": "SecretString"}
                          for n in _aws_secret_index_get(space)]}

    @app.post("/api/aws/secrets")
    async def aws_console_secret_create(request: Request):
        space = _active_space_id(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"ok": False, "error": "missing 'name'"})
        # Accept the console wizard's field (`secret_string`, key=value lines) as
        # well as the plain `value` / native `SecretString`.
        value = (body.get("value") or body.get("SecretString")
                 or body.get("secret_string") or "changeme")
        if vc.kv_put("aws", space, name, value) is None:
            return _vault_unavailable_response("aws.secrets")
        _aws_secret_index_add(space, name)
        return {"ok": True, "name": name}

    @app.get("/api/aws/secrets/{name}")
    async def aws_console_secret_get(name: str, request: Request):
        space = _active_space_id(request)
        got = vc.kv_get("aws", space, name)
        if got is None:
            return JSONResponse(status_code=404,
                                content={"ok": False, "error": "secret not found", "name": name})
        data = got.get("data", {})
        value = data.get("value") if "value" in data else json.dumps(data)
        return {"ok": True, "name": name, "value": value,
                "arn": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{name}"}

    @app.put("/api/aws/secrets/{name}")
    async def aws_console_secret_update(name: str, request: Request):
        """Update (overwrite) a secret's value — the conformant Update, same as
        the native Secrets Manager PutSecretValue."""
        space = _active_space_id(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        value = (body.get("value") or body.get("SecretString")
                 or body.get("secret_string") or "")
        if vc.kv_put("aws", space, name, value) is None:
            return _vault_unavailable_response("aws.secrets")
        _aws_secret_index_add(space, name)
        return {"ok": True, "name": name, "updated": True}

    @app.delete("/api/aws/secrets/{name}")
    async def aws_console_secret_delete(name: str, request: Request):
        space = _active_space_id(request)
        vc.kv_delete("aws", space, name)
        _aws_secret_index_remove(space, name)
        return {"ok": True, "deleted": True, "name": name}

    @app.get("/api/aws/kms/keys")
    async def aws_console_kms_list(request: Request):
        return {"items": [{"key_id": k, "alias": _aws_alias_for(k),
                           "key_spec": v.get("KeySpec", "SYMMETRIC_DEFAULT"),
                           "key_usage": v.get("KeyUsage", "ENCRYPT_DECRYPT"),
                           "state": v.get("KeyState", "Enabled"),
                           "created": v.get("CreationDate")}
                          for k, v in _kms_keys.items()]}

    @app.post("/api/aws/kms/keys")
    async def aws_console_kms_create(request: Request):
        space = _active_space_id(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        import uuid as _uuid
        key_id = _uuid.uuid4().hex
        vc.transit_create_key("aws", space, key_id)
        _kms_keys[key_id] = {
            "KeyId": key_id, "Arn": f"arn:aws:kms:us-east-1:000000000000:key/{key_id}",
            "Enabled": True, "Description": body.get("description", ""),
            "KeyUsage": "ENCRYPT_DECRYPT", "KeySpec": body.get("key_spec", "SYMMETRIC_DEFAULT"),
            "KeyState": "Enabled", "Origin": "AWS_KMS", "CreationDate": time.time(),
        }
        alias = (body.get("name") or "").strip()
        if alias:
            _kms_aliases[alias if alias.startswith("alias/") else f"alias/{alias}"] = key_id
        return {"ok": True, "key_id": key_id}

    @app.get("/api/aws/kms/keys/{key_id}")
    async def aws_console_kms_get(key_id: str, request: Request):
        v = _kms_keys.get(key_id)
        if not v:
            return JSONResponse(status_code=404, content={"ok": False, "error": "key not found", "key_id": key_id})
        return {"ok": True, "key_id": key_id, "arn": v.get("Arn", ""),
                "description": v.get("Description", ""), "enabled": bool(v.get("Enabled", True)),
                "state": v.get("KeyState", "Enabled"), "key_spec": v.get("KeySpec", "SYMMETRIC_DEFAULT"),
                "key_usage": v.get("KeyUsage", "ENCRYPT_DECRYPT"), "alias": _aws_alias_for(key_id),
                "created": v.get("CreationDate")}

    @app.put("/api/aws/kms/keys/{key_id}")
    async def aws_console_kms_update(key_id: str, request: Request):
        """Edit key metadata — description + enable/disable (= UpdateKeyDescription
        / EnableKey / DisableKey). Updates _kms_keys so native DescribeKey agrees."""
        v = _kms_keys.get(key_id)
        if not v:
            return JSONResponse(status_code=404, content={"ok": False, "error": "key not found", "key_id": key_id})
        try:
            body = await request.json()
        except Exception:
            body = {}
        if "description" in body:
            v["Description"] = str(body.get("description") or "")
        if "enabled" in body:
            en = bool(body.get("enabled"))
            v["Enabled"] = en
            v["KeyState"] = "Enabled" if en else "Disabled"
        return {"ok": True, "key_id": key_id, "description": v.get("Description", ""),
                "enabled": bool(v.get("Enabled", True)), "state": v.get("KeyState", "Enabled")}

    @app.delete("/api/aws/kms/keys/{key_id}")
    async def aws_console_kms_delete(key_id: str, request: Request):
        stored = _kms_keys.get(key_id)
        if stored:
            stored["KeyState"] = "PendingDeletion"
            stored["Enabled"] = False
        return {"ok": True, "scheduled": True, "key_id": key_id}


def register(app: FastAPI, aws_dispatchers: dict | None = None) -> None:
    """Mount GCP + Azure routes and expose AWS dispatchers for server.py to wire."""
    _register_gcp(app)
    _register_azure(app)
    _register_aws_console(app)
    if aws_dispatchers is not None:
        aws_dispatchers["TrentService"] = _aws_kms_dispatch        # KMS uses TrentService
        aws_dispatchers["secretsmanager"] = _aws_secrets_dispatch  # Secrets uses secretsmanager
