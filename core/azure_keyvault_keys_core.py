"""Azure Key Vault — keys (data plane) core — substrate-independent, the Azure
analogue of core/kms_core.py. Speaks the native **Key Vault Keys REST API**
(`/keys/{name}/create`, `/keys/{name}`, `/keys/{name}/{version}/encrypt`, …) so
the native `azure-keyvault-keys` SDK works unchanged against it (point its
`KeyClient(vault_url=...)` at the endpoint). All requests carry
`?api-version=7.4`.

NO fastapi / azure / socket / subprocess imports → loads under Pyodide. Persists
key material + metadata through the SAME KeyStore seam as KMS
(core/kms_keystore.py InMemoryKeyStore) and does crypto through the SAME KmsEngine
seam — so encrypt→decrypt round-trips and tamper / cross-key blobs are rejected
by the real authenticated-envelope cipher (SHA-256 keystream + encrypt-then-MAC).

Per the native-SDK-conformance principle the backing primitive is our private
pick — what must conform is the WIRE. Key Vault models RSA keys, so the create /
get responses advertise `kty:"RSA"` with base64url `n` (modulus) + `e` (public
exponent AQAB). Those public-key fields are synthesized deterministically from
the key material (cosmetic wire shape); the encrypt/decrypt data path uses the
symmetric envelope under the hood, so the round-trip is real crypto, not a stub.

CRITICAL: Key Vault puts base64URL (RFC 4648 §5, `-`/`_` alphabet, no `=`
padding) on the wire for every binary field — `n`, `e`, encrypt/decrypt `value`.
Errors use the native `{"error":{"code":..,"message":..}}` shape with a matching
HTTP status (KeyNotFound → 404).

Scope (v1 slice): create key, get key (latest + by version), list keys, encrypt,
decrypt, delete key. Import/rotate/sign/verify/wrap reuse the same helpers.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

from core.kms_keystore import KeyStore

# The vault host advertised in `kid`. azure-keyvault-keys derives the vault from
# the KeyClient(vault_url=...) it was constructed with; the kid we emit just has
# to be a well-formed https URL ending in /keys/{name}/{version}.
VAULT_HOST = "https://vault.vault.azure.net"
API_VERSION = "7.4"


@dataclass
class KvResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── base64url (no padding, -/_ alphabet) — the Key Vault wire encoding ──────
def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    s = (s or "").strip()
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _json(status: int, obj: dict) -> KvResponse:
    return KvResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> KvResponse:
    return KvResponse(status=status,
                      body=json.dumps({"error": {"code": code, "message": message}}).encode())


def _now() -> int:
    return int(time.time())


def _new_version() -> str:
    return uuid.uuid4().hex  # 32-hex, exactly what Key Vault emits


# ── deterministic RSA public numbers (cosmetic wire shape) ─────────────────
# Key Vault advertises kty:"RSA" with base64url modulus `n` + exponent `e`. We
# synthesize a well-formed-looking modulus of key_size bits from the (secret)
# key material so every get returns the same n; e is the conventional 65537.
def _rsa_public_numbers(material: bytes, key_size: int) -> tuple[bytes, bytes]:
    nbytes = max(1, key_size // 8)
    buf = bytearray()
    counter = 0
    while len(buf) < nbytes:
        buf.extend(hashlib.sha256(material + counter.to_bytes(4, "big")).digest())
        counter += 1
    n = bytearray(buf[:nbytes])
    n[0] |= 0x80   # top bit set → full key_size bits
    n[-1] |= 0x01  # odd
    e = (65537).to_bytes(3, "big")  # → base64url "AQAB"
    return bytes(n), bytes(e)


# ── real RSA (when the `cryptography` package is importable — the offline appliance;
# Pyodide without it keeps the synthetic numbers + envelope cipher above) ───────────────
# A real Key Vault RSA key lets the native CryptographyClient encrypt LOCALLY with the
# public key (n, e) it fetched and send only decrypt to the service — so (n, e) must be a
# real modulus whose private half the service holds. Material for such a key is the
# private key's PKCS#8 DER; meta["rsa"] marks it.
def _rsa_mod():
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa, padding  # noqa: F401
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
        return True
    except Exception:
        return False


def _rsa_new(key_size: int):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    priv = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    der = priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    nums = priv.public_key().public_numbers()
    return der, nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big"), nums.e.to_bytes(3, "big")


def _rsa_priv(material: bytes):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_der_private_key(material, password=None)


def _rsa_pad(alg: str):
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    a = (alg or "RSA-OAEP").upper().replace("_", "-")
    if a == "RSA1-5":
        return padding.PKCS1v15()
    h = hashes.SHA256() if a == "RSA-OAEP-256" else hashes.SHA1()
    return padding.OAEP(mgf=padding.MGF1(h), algorithm=h, label=None)


def _rsa_sig(alg: str):
    from cryptography.hazmat.primitives.asymmetric import padding, utils
    from cryptography.hazmat.primitives import hashes
    a = (alg or "RS256").upper()
    h = {"256": hashes.SHA256(), "384": hashes.SHA384(), "512": hashes.SHA512()}.get(a[-3:], hashes.SHA256())
    pad = padding.PSS(mgf=padding.MGF1(h), salt_length=h.digest_size) if a.startswith("PS") else padding.PKCS1v15()
    return pad, utils.Prehashed(h)


# ── store helpers (key_id in the KeyStore == "name/version") ───────────────
def _kid_key(name: str, version: str) -> str:
    return f"{name}/{version}"


def _versions_for(store: KeyStore, name: str) -> list[dict]:
    out = [store.get_key(kid) for kid in store.key_ids()
           if store.get_key(kid) and store.get_key(kid).get("name") == name]
    return sorted(out, key=lambda m: m.get("seq", 0))


def _latest(store: KeyStore, name: str) -> dict | None:
    vs = _versions_for(store, name)
    return vs[-1] if vs else None


def _next_seq(store: KeyStore) -> int:
    best = 0
    for kid in store.key_ids():
        best = max(best, (store.get_key(kid) or {}).get("seq", 0))
    return best + 1


def _kid_url(name: str, version: str) -> str:
    return f"{VAULT_HOST}/keys/{name}/{version}"


# ── views ──────────────────────────────────────────────────────────────────
def _attributes(meta: dict) -> dict:
    return {
        "enabled": meta.get("enabled", True),
        "created": meta.get("created", _now()),
        "updated": meta.get("updated", _now()),
        "recoveryLevel": "Purgeable",
        "exportable": False,
    }


def _key_jwk(meta: dict) -> dict:
    return {
        "kid": _kid_url(meta["name"], meta["version"]),
        "kty": meta.get("kty", "RSA"),
        "key_ops": list(meta.get("key_ops", [])),
        "n": meta["n"],
        "e": meta["e"],
    }


def _key_bundle(meta: dict) -> dict:
    out = {"key": _key_jwk(meta), "attributes": _attributes(meta)}
    if meta.get("tags"):
        out["tags"] = dict(meta["tags"])
    return out


# ── operations ──────────────────────────────────────────────────────────────
def _create_key(store: KeyStore, name: str, body: dict) -> KvResponse:
    kty = str(body.get("kty", "RSA"))
    key_size = int(body.get("key_size") or 2048)
    key_ops = body.get("key_ops") or ["encrypt", "decrypt", "sign", "verify",
                                      "wrapKey", "unwrapKey"]
    version = _new_version()
    real_rsa = kty.upper().startswith("RSA") and key_size in (2048, 3072, 4096) and _rsa_mod()
    if real_rsa:
        material, n, e = _rsa_new(key_size)
    else:
        material = store.engine.new_key_material()
        n, e = _rsa_public_numbers(material, key_size)
    now = _now()
    meta = {
        "name": name, "version": version, "kty": kty, "key_size": key_size,
        "key_ops": list(key_ops), "n": _b64url_encode(n), "e": _b64url_encode(e),
        "enabled": True, "created": now, "updated": now, "seq": _next_seq(store),
    }
    if real_rsa:
        meta["rsa"] = True
    attrs = body.get("attributes") or {}
    if "enabled" in attrs:
        meta["enabled"] = bool(attrs["enabled"])
    if body.get("tags") is not None:
        meta["tags"] = dict(body.get("tags") or {})
    store.put_key(_kid_key(name, version), meta, material)
    store.persist()
    return _json(200, _key_bundle(meta))


def _get_key(store: KeyStore, name: str, version: str | None) -> KvResponse:
    if version:
        meta = store.get_key(_kid_key(name, version))
    else:
        meta = _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    return _json(200, _key_bundle(meta))


def _list_keys(store: KeyStore) -> KvResponse:
    # One entry per key name (its latest version), as the SDK's list_properties.
    seen: dict[str, dict] = {}
    for kid in store.key_ids():
        m = store.get_key(kid)
        if not m:
            continue
        cur = seen.get(m["name"])
        if cur is None or m.get("seq", 0) > cur.get("seq", 0):
            seen[m["name"]] = m
    value = [{"kid": _kid_url(m["name"], m["version"]), "attributes": _attributes(m)}
             for m in sorted(seen.values(), key=lambda x: x["name"])]
    return _json(200, {"value": value})


def _encrypt(store: KeyStore, name: str, version: str, body: dict) -> KvResponse:
    meta = store.get_key(_kid_key(name, version)) if version else _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    version = meta["version"]
    try:
        plaintext = _b64url_decode(body.get("value", ""))
    except Exception:
        return _err(400, "BadParameter", "The 'value' field is not valid base64url.")
    material = store.get_material(_kid_key(name, version))
    if meta.get("rsa"):
        try:
            blob = _rsa_priv(material).public_key().encrypt(plaintext, _rsa_pad(body.get("alg")))
        except Exception:
            return _err(400, "BadParameter", "The plaintext could not be encrypted with this key/algorithm.")
    else:
        blob = store.engine.encrypt(material, _kid_key(name, version), plaintext)
    return _json(200, {"kid": _kid_url(name, version), "value": _b64url_encode(blob)})


def _decrypt(store: KeyStore, name: str, version: str, body: dict) -> KvResponse:
    meta = store.get_key(_kid_key(name, version)) if version else _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    version = meta["version"]
    try:
        blob = _b64url_decode(body.get("value", ""))
    except Exception:
        return _err(400, "BadParameter", "The 'value' field is not valid base64url.")
    material = store.get_material(_kid_key(name, version))
    try:
        plaintext = (_rsa_priv(material).decrypt(blob, _rsa_pad(body.get("alg"))) if meta.get("rsa")
                     else store.engine.decrypt(material, blob))
    except Exception:
        return _err(400, "BadParameter", "The ciphertext could not be decrypted.")
    return _json(200, {"kid": _kid_url(name, version), "value": _b64url_encode(plaintext)})


def _wrap_key(store: KeyStore, name: str, version: str, body: dict) -> KvResponse:
    """Key-wrapping: envelope a symmetric key with the KV key. Same crypto as
    encrypt (the KV key protects the wrapped material); distinct SDK operation."""
    meta = store.get_key(_kid_key(name, version)) if version else _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    version = meta["version"]
    try:
        key_bytes = _b64url_decode(body.get("value", ""))
    except Exception:
        return _err(400, "BadParameter", "The 'value' field is not valid base64url.")
    material = store.get_material(_kid_key(name, version))
    if meta.get("rsa"):
        try:
            blob = _rsa_priv(material).public_key().encrypt(key_bytes, _rsa_pad(body.get("alg")))
        except Exception:
            return _err(400, "BadParameter", "The key could not be wrapped with this key/algorithm.")
    else:
        blob = store.engine.encrypt(material, _kid_key(name, version), key_bytes)
    return _json(200, {"kid": _kid_url(name, version), "value": _b64url_encode(blob)})


def _unwrap_key(store: KeyStore, name: str, version: str, body: dict) -> KvResponse:
    meta = store.get_key(_kid_key(name, version)) if version else _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    version = meta["version"]
    try:
        blob = _b64url_decode(body.get("value", ""))
    except Exception:
        return _err(400, "BadParameter", "The 'value' field is not valid base64url.")
    material = store.get_material(_kid_key(name, version))
    try:
        key_bytes = (_rsa_priv(material).decrypt(blob, _rsa_pad(body.get("alg"))) if meta.get("rsa")
                     else store.engine.decrypt(material, blob))
    except Exception:
        return _err(400, "BadParameter", "The wrapped key could not be unwrapped.")
    return _json(200, {"kid": _kid_url(name, version), "value": _b64url_encode(key_bytes)})


def _signature(material: bytes, alg: str, digest: bytes) -> bytes:
    """Deterministic MAC-based signature over the caller-supplied digest, keyed by
    the (secret) key material. Not native RSA/ECDSA, but a self-consistent
    sign→verify pair — an unmodified KV client round-trips sign then verify."""
    return hmac.new(material, (alg or "").encode() + b"|" + digest, hashlib.sha256).digest()


def _sign(store: KeyStore, name: str, version: str, body: dict) -> KvResponse:
    meta = store.get_key(_kid_key(name, version)) if version else _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    version = meta["version"]
    alg = str(body.get("alg", "RS256"))
    try:
        digest = _b64url_decode(body.get("value", ""))
    except Exception:
        return _err(400, "BadParameter", "The 'value' field is not valid base64url.")
    material = store.get_material(_kid_key(name, version))
    if meta.get("rsa"):
        try:
            pad, pre = _rsa_sig(alg)
            sig = _rsa_priv(material).sign(digest, pad, pre)
        except Exception:
            return _err(400, "BadParameter", "The digest could not be signed with this key/algorithm.")
    else:
        sig = _signature(material, alg, digest)
    return _json(200, {"kid": _kid_url(name, version), "value": _b64url_encode(sig)})


def _verify(store: KeyStore, name: str, version: str, body: dict) -> KvResponse:
    meta = store.get_key(_kid_key(name, version)) if version else _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    version = meta["version"]
    alg = str(body.get("alg", "RS256"))
    try:
        digest = _b64url_decode(body.get("digest", ""))
        provided = _b64url_decode(body.get("value", ""))
    except Exception:
        return _err(400, "BadParameter", "digest/value must be valid base64url.")
    material = store.get_material(_kid_key(name, version))
    if meta.get("rsa"):
        try:
            pad, pre = _rsa_sig(alg)
            _rsa_priv(material).public_key().verify(provided, digest, pad, pre)
            return _json(200, {"value": True})
        except Exception:
            return _json(200, {"value": False})
    expected = _signature(material, alg, digest)
    return _json(200, {"value": hmac.compare_digest(expected, provided)})


def _delete_key(store: KeyStore, name: str) -> KvResponse:
    versions = _versions_for(store, name)
    if not versions:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    latest = versions[-1]
    for m in versions:
        store.drop_key(_kid_key(name, m["version"]))
    store.persist()
    bundle = _key_bundle(latest)
    bundle["recoveryId"] = f"{VAULT_HOST}/deletedkeys/{name}"
    bundle["deletedDate"] = _now()
    bundle["scheduledPurgeDate"] = _now() + 90 * 86400
    return _json(200, bundle)


_OPS = ("encrypt", "decrypt", "wrapkey", "unwrapkey", "sign", "verify")


def _update_key(store: KeyStore, name: str, version: str, body: dict) -> KvResponse:
    """UpdateKeyProperties: PATCH {attributes:{enabled}, tags, key_ops}."""
    meta = store.get_key(_kid_key(name, version)) if version else _latest(store, name)
    if not meta:
        return _err(404, "KeyNotFound",
                    f"A key with (name/id) {name} was not found in this key vault.")
    attrs = body.get("attributes") or {}
    if "enabled" in attrs:
        meta["enabled"] = bool(attrs["enabled"])
    if body.get("tags") is not None:
        meta["tags"] = dict(body.get("tags") or {})
    if body.get("key_ops"):
        meta["key_ops"] = list(body["key_ops"])
    meta["updated"] = _now()
    kid = _kid_key(name, meta["version"])
    store.put_key(kid, meta, store.get_material(kid))
    store.persist()
    return _json(200, _key_bundle(meta))


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: KeyStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> KvResponse:
    query = query or {}
    method = method.upper()
    lheaders = {(k or "").lower(): v for k, v in (headers or {}).items()}

    # Key Vault auth challenge (as in the secrets / certificates cores): every azure-keyvault-*
    # client — CryptographyClient included — first sends the request WITHOUT its body or token
    # and expects 401 + WWW-Authenticate; answering that probe (e.g. decrypt with an empty
    # value) instead fails the call. Gated on an SDK marker so substrate tests are unaffected.
    _sdk = ("x-ms-client-request-id" in lheaders or "azsdk" in lheaders.get("user-agent", "").lower())
    if _sdk and "authorization" not in lheaders:
        return KvResponse(status=401, headers={
            "www-authenticate": ('Bearer authorization="https://login.microsoftonline.com/common", '
                                 'resource="https://vault.azure.net"')},
            body=b"", media_type=None)

    p = path.split("?", 1)[0].rstrip("/")
    segs = [unquote(s) for s in p.split("/") if s != ""]

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}

    if not segs or segs[0] != "keys":
        return _err(404, "NotFound", f"Unknown path: {path}")

    # /keys  → list
    if len(segs) == 1:
        if method == "GET":
            return _list_keys(store)
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on /keys")

    # /keys/{name}/create → create
    if len(segs) == 3 and segs[2] == "create" and method == "POST":
        return _create_key(store, segs[1], payload)

    name = segs[1]

    # /keys/{name}  → get latest | delete
    if len(segs) == 2:
        if method == "GET":
            return _get_key(store, name, None)
        if method == "DELETE":
            return _delete_key(store, name)
        if method == "PATCH":
            return _update_key(store, name, "", payload)
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on /keys/{name}")

    # /keys/{name}/{op}  → encrypt | decrypt | … on the latest version (versionless kid)
    if len(segs) == 3 and method == "POST" and segs[2] in _OPS:
        segs = [segs[0], name, "", segs[2]]

    # /keys/{name}/{version}  → get by version | update attributes
    if len(segs) == 3:
        if method == "GET":
            return _get_key(store, name, segs[2])
        if method == "PATCH":
            return _update_key(store, name, segs[2], payload)
        return _err(405, "MethodNotAllowed", f"Unsupported method {method}")

    # /keys/{name}/{version}/{op}  → encrypt | decrypt
    if len(segs) == 4:
        version, op = segs[2], segs[3]
        if method == "POST" and op == "encrypt":
            return _encrypt(store, name, version, payload)
        if method == "POST" and op == "decrypt":
            return _decrypt(store, name, version, payload)
        if method == "POST" and op == "wrapkey":
            return _wrap_key(store, name, version, payload)
        if method == "POST" and op == "unwrapkey":
            return _unwrap_key(store, name, version, payload)
        if method == "POST" and op == "sign":
            return _sign(store, name, version, payload)
        if method == "POST" and op == "verify":
            return _verify(store, name, version, payload)
        return _err(404, "NotFound", f"Unknown operation: {op}")

    return _err(404, "NotFound", f"Unknown path: {path}")
