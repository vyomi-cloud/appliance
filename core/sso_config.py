"""Tier-feature implementation: SSO (Enterprise tier).

Real OIDC integration: the operator configures their IdP (Okta / Auth0 /
Azure AD / Google Workspace) — discovery URL, audience, allowed-issuer,
JWKS endpoint. When a request comes in with `Authorization: Bearer <JWT>`,
the middleware validates the signature against the IdP's JWKS and matches
the token's `sub`/`email` to a CloudLearn user.

We use the `cryptography` library for RSA verification (already a dep via
fastapi's transitive). The `python-jose` library would be cleaner but adds
a runtime dep — for MVP fidelity we hand-roll RS256 verification using the
JWKS keys.

State:
  STATE["sso_config"][tenant_id] = {
    enabled, idp_discovery_url, issuer, audience, jwks, jwks_fetched_at,
    user_mapping: "email" | "sub", default_role
  }
"""
from __future__ import annotations

import base64
import json
import time
import urllib.request
import urllib.error
from typing import Any


def _now() -> float:
    return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _conf_for(state: dict, tenant_id: str) -> dict:
    return state.setdefault("sso_config", {}).setdefault(tenant_id, {"enabled": False})


def get_config(state: dict, tenant_id: str) -> dict:
    c = dict(_conf_for(state, tenant_id))
    # Don't echo back JWKS blob (large); just the count.
    jwks = c.get("jwks") or {}
    c["jwks_keys_count"] = len((jwks.get("keys") or []) if isinstance(jwks, dict) else [])
    c.pop("jwks", None)
    return c


def configure(state: dict, tenant_id: str, spec: dict) -> dict:
    """Configure SSO for a tenant. Required: `idp_discovery_url` OR direct
    `issuer` + `jwks_uri`. Optional: `audience`, `user_mapping` ("email"/"sub")."""
    conf = _conf_for(state, tenant_id)
    discovery = str(spec.get("idp_discovery_url") or "").strip()
    issuer = str(spec.get("issuer") or "").strip()
    jwks_uri = str(spec.get("jwks_uri") or "").strip()

    if discovery:
        if not discovery.startswith(("http://", "https://")):
            raise ValueError("idp_discovery_url must be http(s)://")
        # Fetch the discovery document → extract issuer + jwks_uri
        try:
            with urllib.request.urlopen(discovery, timeout=5) as resp:
                doc = json.load(resp)
                issuer = issuer or doc.get("issuer") or ""
                jwks_uri = jwks_uri or doc.get("jwks_uri") or ""
        except Exception as e:
            raise ValueError(f"failed to fetch discovery doc: {e}")

    if not issuer or not jwks_uri:
        raise ValueError("issuer + jwks_uri required (or a working idp_discovery_url)")

    # Fetch JWKS now so we have it cached for validation.
    try:
        with urllib.request.urlopen(jwks_uri, timeout=5) as resp:
            jwks = json.load(resp)
    except Exception as e:
        raise ValueError(f"failed to fetch JWKS: {e}")

    conf.update({
        "enabled": True,
        "configured_at": _now_iso(),
        "idp_discovery_url": discovery,
        "issuer": issuer,
        "jwks_uri": jwks_uri,
        "jwks": jwks,
        "jwks_fetched_at": _now_iso(),
        "audience": str(spec.get("audience") or "").strip(),
        "user_mapping": str(spec.get("user_mapping") or "email").strip().lower(),
        "default_role": str(spec.get("default_role") or "user").strip(),
    })
    return get_config(state, tenant_id)


def disable(state: dict, tenant_id: str) -> dict:
    conf = _conf_for(state, tenant_id)
    conf["enabled"] = False
    conf.pop("jwks", None)
    conf["disabled_at"] = _now_iso()
    return get_config(state, tenant_id)


# ── JWT validation ──────────────────────────────────────────────────────────

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _verify_signature(header: dict, signing_input: bytes, signature: bytes, jwks: dict) -> bool:
    """Verify RS256/ES256 signature against a JWKS. Returns True on valid sig.
    Falls back to allowing HS256 only if the JWKS contains an `oct` key (rare —
    most IdPs use RS256)."""
    alg = header.get("alg", "")
    kid = header.get("kid", "")
    keys = (jwks or {}).get("keys") or []
    key = next((k for k in keys if k.get("kid") == kid), None) or (keys[0] if keys else None)
    if not key:
        return False
    try:
        if alg == "RS256":
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives import hashes
            n = int.from_bytes(_b64url_decode(key["n"]), "big")
            e = int.from_bytes(_b64url_decode(key["e"]), "big")
            pub = RSAPublicNumbers(e, n).public_key()
            pub.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
            return True
        if alg == "ES256":
            from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicNumbers, SECP256R1, ECDSA
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
            x = int.from_bytes(_b64url_decode(key["x"]), "big")
            y = int.from_bytes(_b64url_decode(key["y"]), "big")
            pub = EllipticCurvePublicNumbers(x, y, SECP256R1()).public_key()
            r = int.from_bytes(signature[:32], "big")
            s = int.from_bytes(signature[32:], "big")
            der = encode_dss_signature(r, s)
            pub.verify(der, signing_input, ECDSA(hashes.SHA256()))
            return True
        return False
    except Exception:
        return False


def validate_bearer(state: dict, tenant_id: str, authz_header: str) -> dict:
    """Validate `Authorization: Bearer <jwt>`. Returns
       {ok: True, claims: {...}, user_identifier: "..."} on success
       {ok: False, reason: "..."} on failure
    """
    conf = _conf_for(state, tenant_id)
    if not conf.get("enabled"):
        return {"ok": False, "reason": "sso_not_configured"}
    if not authz_header.startswith("Bearer "):
        return {"ok": False, "reason": "missing_bearer"}
    token = authz_header[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        return {"ok": False, "reason": "malformed_jwt"}
    try:
        header = json.loads(_b64url_decode(parts[0]))
        claims = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except Exception as e:
        return {"ok": False, "reason": f"decode_failed: {e}"}

    signing_input = (parts[0] + "." + parts[1]).encode("ascii")
    if not _verify_signature(header, signing_input, signature, conf.get("jwks") or {}):
        return {"ok": False, "reason": "signature_invalid"}

    # Claim checks
    now = _now()
    if int(claims.get("exp") or 0) < now - 30:  # 30s clock-skew tolerance
        return {"ok": False, "reason": "token_expired"}
    if int(claims.get("nbf") or 0) > now + 30:
        return {"ok": False, "reason": "token_not_yet_valid"}
    iss = claims.get("iss") or ""
    if conf.get("issuer") and iss != conf["issuer"]:
        return {"ok": False, "reason": f"issuer_mismatch (got {iss!r})"}
    aud = claims.get("aud") or ""
    expected_aud = conf.get("audience") or ""
    if expected_aud:
        if isinstance(aud, list):
            if expected_aud not in aud:
                return {"ok": False, "reason": "audience_mismatch"}
        elif aud != expected_aud:
            return {"ok": False, "reason": "audience_mismatch"}

    mapping = conf.get("user_mapping", "email")
    user_id = claims.get(mapping) or claims.get("email") or claims.get("sub") or ""
    return {"ok": True, "claims": claims, "user_identifier": str(user_id)}
