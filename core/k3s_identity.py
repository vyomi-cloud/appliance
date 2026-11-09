"""Cloud-neutral workload identity for the k3s-backed managed clusters (AKS workload identity / EKS IRSA / GKE workload identity).

OFFLINE-ONLY. Each k3s API server is started with ``--service-account-issuer`` = ``<base>/oidc/<cloud>/<hash>`` and
``--service-account-jwks-uri`` = ``<issuer>/keys``; the simulator serves the OIDC discovery document and the JWKS (the cluster's REAL public
signing keys, read from the k3s API server's /openid/v1/jwks). The cloud STS / Entra cores call ``verify_token(...)`` to validate a projected
service-account token (RS256, pure Python, no third-party deps) and get its claims.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
import threading
import time

JWKS_TTL = 300


class TokenError(Exception):
    pass


def _b64d(s):
    s = str(s)
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def discovery_document(issuer):
    return {"issuer": issuer, "jwks_uri": issuer.rstrip("/") + "/keys", "response_types_supported": ["id_token"],
            "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"],
            "claims_supported": ["sub", "iss", "aud", "exp", "iat", "kubernetes.io"]}


# ── RS256 (RSASSA-PKCS1-v1_5 / SHA-256) ──
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _rs256_verify(jwk, signing_input, signature):
    n, e = int.from_bytes(_b64d(jwk["n"]), "big"), int.from_bytes(_b64d(jwk["e"]), "big")
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    t = _SHA256_PREFIX + hashlib.sha256(signing_input).digest()
    return em == b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


class _JwksCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}                     # (cloud, hash) -> (fetched_at, jwks)

    def get(self, key, fetch, force=False):
        with self.lock:
            hit = self.items.get(key)
            if hit and not force and time.time() - hit[0] < JWKS_TTL:
                return hit[1]
        jwks = fetch()
        with self.lock:
            self.items[key] = (time.time(), jwks)
        return jwks

    def clear(self, key=None):
        with self.lock:
            self.items.pop(key, None) if key else self.items.clear()


CACHE = _JwksCache()
_ISS = re.compile(r"/oidc/([a-z]+)/([0-9a-f]{10})/?$")


def split_issuer(iss):
    m = _ISS.search(str(iss or ""))
    return (m.group(1), m.group(2)) if m else (None, None)


def verify_token(token, audience=None, jwks_fetcher=None, now=None, leeway=30):
    """Validate a projected service-account token against the issuing cluster's JWKS.

    ``jwks_fetcher(cloud, hash) -> {"keys": [...]}`` (default: the shared k3s runtime). Returns
    ``{"sub", "aud": [..], "iss", "namespace", "serviceAccount", "cloud", "clusterHash", "claims"}``; raises ``TokenError``.
    ``audience`` (str or iterable) must intersect the token's ``aud``."""
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise TokenError("malformed token")
    try:
        header, claims = json.loads(_b64d(parts[0])), json.loads(_b64d(parts[1]))
        sig = _b64d(parts[2])
    except Exception:
        raise TokenError("malformed token")
    if header.get("alg") != "RS256":
        raise TokenError("unsupported alg %r" % header.get("alg"))
    cloud, chash = split_issuer(claims.get("iss"))
    if not cloud:
        raise TokenError("issuer %r is not a Vyomi cluster issuer" % claims.get("iss"))
    if jwks_fetcher is None:
        from core import k3s_runtime
        jwks_fetcher = k3s_runtime.runtime().oidc_jwks
    signing_input = (parts[0] + "." + parts[1]).encode()

    def find(force):
        jwks = CACHE.get((cloud, chash), lambda: jwks_fetcher(cloud, chash), force)
        return next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"), None)
    key = find(False) or find(True)               # unknown kid -> the cluster may have rotated keys: refetch once
    if key is None:
        raise TokenError("signing key %r not published by the issuer" % header.get("kid"))
    if not _rs256_verify(key, signing_input, sig):
        raise TokenError("bad signature")
    t = time.time() if now is None else now
    if "exp" in claims and t > float(claims["exp"]) + leeway:
        raise TokenError("token expired")
    if "nbf" in claims and t < float(claims["nbf"]) - leeway:
        raise TokenError("token not yet valid")
    aud = claims.get("aud")
    aud = [aud] if isinstance(aud, str) else list(aud or [])
    if audience is not None:
        want = [audience] if isinstance(audience, str) else list(audience)
        if not set(want) & set(aud):
            raise TokenError("audience mismatch (token aud=%s)" % aud)
    sub = claims.get("sub", "")
    p = sub.split(":")
    ns, sa = (p[2], p[3]) if len(p) == 4 and p[:2] == ["system", "serviceaccount"] else (None, None)
    return {"sub": sub, "aud": aud, "iss": claims.get("iss"), "namespace": ns, "serviceAccount": sa,
            "cloud": cloud, "clusterHash": chash, "claims": claims}
