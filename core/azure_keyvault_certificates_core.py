"""Azure Key Vault — certificates data-plane core — substrate-independent, the
Azure analogue of core/azure_keyvault_secrets_core.py. Speaks the native **Key
Vault Certificates REST API** (`/certificates/...?api-version=7.x`) so the
native `azure-keyvault-certificates` SDK's lower-level HTTP shape works against
it (point its `CertificateClient(vault_url=...)` at the endpoint).

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide.
Persists through the SAME KvStore seam as secrets/KMS (core/kv_store.py); Azure
just gets its own namespaced store instance (az_kvcerts), independent of the
secrets store (a cert and a secret may share a name in real Key Vault).

Scope (v1 slice): create (self-signed, completes synchronously — no polling
CertificateOperation, same simplification the keys/secrets cores make), get
latest, list, delete. The `cer`/`x5t` fields are synthesized deterministically
from the name + version (cosmetic wire shape, not real X.509 DER) — what must
conform is the WIRE shape, not the certificate math (same principle as the keys
core's RSA public-number synthesis).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

from core.kv_store import InMemoryKvStore

VAULT_HOST = "https://vault.vault.azure.net"
_RECOVERY_LEVEL = "Recoverable+Purgeable"
_B64URL = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"


@dataclass
class KvResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


def _now() -> int:
    return int(time.time())


def _new_version() -> str:
    return uuid.uuid4().hex


def _cert_id(name: str, version: str = "") -> str:
    if version:
        return f"{VAULT_HOST}/certificates/{name}/{version}"
    return f"{VAULT_HOST}/certificates/{name}"


def _b64url(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _synth_thumbprint(name: str, version: str) -> str:
    """base64url(SHA-1) — the real `x5t` wire shape. Deterministic from name+version
    so repeated GETs of the same certificate return the same thumbprint."""
    return _b64url(hashlib.sha1(f"{name}/{version}".encode()).digest())


def _synth_cer(name: str, version: str) -> str:
    """A stand-in for the base64 DER certificate body — not parseable X.509, but a
    well-formed base64 blob of plausible size, deterministic per name+version."""
    import base64
    raw = hashlib.sha256(f"cer:{name}/{version}".encode()).digest() * 4
    return base64.b64encode(raw).decode("ascii")


def _json(status: int, obj: dict) -> KvResponse:
    return KvResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> KvResponse:
    return KvResponse(status=status, body=json.dumps({"error": {"code": code, "message": message}}).encode())


def _bundle(name: str, version: str, rec: dict) -> dict:
    out = {"id": _cert_id(name, version), "x5t": rec["x5t"], "cer": rec["cer"], "attributes": rec["attributes"]}
    if rec.get("policy") is not None:
        out["policy"] = rec["policy"]
    if rec.get("tags") is not None:
        out["tags"] = rec["tags"]
    return out


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: InMemoryKvStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> KvResponse:
    query = query or {}
    method = method.upper()
    lheaders = {(k or "").lower(): v for k, v in (headers or {}).items()}

    _sdk = ("x-ms-client-request-id" in lheaders or "azsdk" in lheaders.get("user-agent", "").lower())
    if _sdk and "authorization" not in lheaders:
        return KvResponse(status=401, headers={
            "www-authenticate": ('Bearer authorization="https://login.microsoftonline.com/common", '
                                 'resource="https://vault.azure.net"')},
            body=b"", media_type=None)

    if not query.get("api-version"):
        return _err(400, "BadParameter", "The api-version query parameter is required.")

    p = path.split("?", 1)[0].rstrip("/")
    segs = [unquote(s) for s in p.split("/") if s != ""]

    if not segs or segs[0] != "certificates":
        return _err(404, "NotFound", f"Unknown path: {path}")

    # ---- /certificates (collection) ----
    if len(segs) == 1:
        if method == "GET":
            items = []
            for name in store.names():
                rec = store.get_secret(name)
                if rec and not rec.get("deleted"):
                    items.append({"id": _cert_id(name), "x5t": rec["x5t"],
                                  "attributes": rec["attributes"], "tags": rec.get("tags")})
            return _json(200, {"value": items, "nextLink": None})
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on /certificates")

    name = segs[1]

    # ---- /certificates/{name}/create ----
    if len(segs) == 3 and segs[2] == "create":
        if method != "POST":
            return _err(405, "MethodNotAllowed", f"Unsupported method {method} on create")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return _err(400, "BadParameter", "Request body is not valid JSON.")
        version = _new_version()
        now = _now()
        policy = payload.get("policy") or {}
        months = ((policy.get("x509_certificate_properties") or policy.get("x509CertificateProperties") or {})
                  .get("validity_in_months") or (policy.get("x509_certificate_properties") or policy.get("x509CertificateProperties") or {}).get("validityInMonths") or 12)
        req_attrs = payload.get("attributes") or {}
        rec = {
            "name": name, "version": version, "deleted": False,
            "x5t": _synth_thumbprint(name, version), "cer": _synth_cer(name, version),
            "policy": policy, "tags": payload.get("tags"),
            "attributes": {
                "enabled": req_attrs.get("enabled", True), "created": now, "updated": now,
                "nbf": now, "exp": now + int(months) * 30 * 24 * 3600,
                "recoveryLevel": _RECOVERY_LEVEL,
            },
        }
        store.put_secret(name, rec)
        store.persist()
        store.mirror_put(name, rec)
        return _json(200, _bundle(name, version, rec))

    # ---- /certificates/{name} ----
    if len(segs) == 2:
        if method == "GET":
            rec = store.get_secret(name)
            if not rec or rec.get("deleted"):
                return _err(404, "CertificateNotFound", f"A certificate with (name/id) {name} was not found in this key vault.")
            return _json(200, _bundle(name, rec["version"], rec))
        if method == "DELETE":
            rec = store.get_secret(name)
            if not rec or rec.get("deleted"):
                return _err(404, "CertificateNotFound", f"A certificate with (name/id) {name} was not found in this key vault.")
            now = _now()
            rec["deleted"] = True
            store.put_secret(name, rec)
            store.persist()
            store.mirror_delete(name)
            bundle = _bundle(name, rec["version"], rec)
            bundle.update({"recoveryId": f"{VAULT_HOST}/deletedcertificates/{name}", "deletedDate": now,
                           "scheduledPurgeDate": now + 90 * 24 * 3600})
            return _json(200, bundle)
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on certificate")

    return _err(404, "NotFound", f"Unknown path: {path}")
