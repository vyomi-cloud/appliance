"""Azure Key Vault certificates data plane — substrate-free (stdlib only), shared by the
appliance (core/vault_routes) and Nano (wasm azure_core_adapter), so a certificate
created in either console is the same real object.

Real X.509: ``create`` with the ``Self`` issuer generates an RSA key pair (Miller-Rabin
primes, e = 65537), builds a v3 certificate (subject, SANs, key usage, EKU) and signs
it SHA256withRSA (PKCS#1 v1.5) — any X.509 parser / ``openssl x509`` reads the ``cer``.
The certificate's secret (``sid``) holds the PEM private key + certificate, like Key
Vault's ``application/x-pem-file`` content type. Certificates from other issuers need a
CA, which the simulator doesn't have, so those requests are rejected (no fake chain).

Key Vault REST shapes (api-version 7.4):
    GET    /certificates                         list   {value:[{id,x5t,attributes,tags}]}
    POST   /certificates/{name}/create           202    pending operation (status completed)
    GET    /certificates/{name}[/{version}]      bundle {id,kid,sid,x5t,cer,attributes,policy}
    GET    /certificates/{name}/pending          the (completed) operation
    GET    /certificates/{name}/versions         versions list
    PATCH  /certificates/{name}[/{version}]      attributes.enabled / tags
    DELETE /certificates/{name}                  deleted bundle (recoveryId, deletedDate)

``dispatch(store, vault, method, rest, body)`` returns ``(status, body_dict)``.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import random
import time
import uuid

_SYS = random.SystemRandom()
_SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** 0.5) + 1, 2))]


# ── RSA ──────────────────────────────────────────────────────────────────────
def _is_probable_prime(n: int, rounds: int = 24) -> bool:
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = _SYS.randrange(2, n - 2)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        c = _SYS.getrandbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if _is_probable_prime(c):
            return c


def rsa_generate(bits: int = 2048, e: int = 65537) -> dict:
    while True:
        p, q = _prime(bits // 2), _prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        d = pow(e, -1, phi)
        return {"n": n, "e": e, "d": d, "p": p, "q": q,
                "dp": d % (p - 1), "dq": d % (q - 1), "qi": pow(q, -1, p)}


# ── DER ──────────────────────────────────────────────────────────────────────
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _len(len(content)) + content


def _int(v: int) -> bytes:
    b = v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big")
    return _tlv(0x02, b)


def _seq(*items: bytes) -> bytes:
    return _tlv(0x30, b"".join(items))


def _set(*items: bytes) -> bytes:
    return _tlv(0x31, b"".join(items))


def _oid(dotted: str) -> bytes:
    parts = [int(x) for x in dotted.split(".")]
    out = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        enc = [p & 0x7F]
        p >>= 7
        while p:
            enc.append(0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(reversed(enc))
    return _tlv(0x06, out)


_NULL = b"\x05\x00"


def _utf8(s: str) -> bytes:
    return _tlv(0x0C, s.encode("utf-8"))


def _bitstr(b: bytes) -> bytes:
    return _tlv(0x03, b"\x00" + b)


def _octet(b: bytes) -> bytes:
    return _tlv(0x04, b)


def _time(dt: datetime.datetime) -> bytes:
    if dt.year < 2050:
        return _tlv(0x17, dt.strftime("%y%m%d%H%M%SZ").encode())
    return _tlv(0x18, dt.strftime("%Y%m%d%H%M%SZ").encode())


_RDN_OIDS = {"CN": "2.5.4.3", "O": "2.5.4.10", "OU": "2.5.4.11", "L": "2.5.4.7", "ST": "2.5.4.8", "C": "2.5.4.6"}


def _name(subject: str) -> bytes:
    rdns = []
    for part in [x.strip() for x in subject.split(",") if x.strip()]:
        if "=" not in part:
            raise ValueError(f"Invalid subject component '{part}'")
        k, v = part.split("=", 1)
        oid = _RDN_OIDS.get(k.strip().upper())
        if not oid:
            raise ValueError(f"Unsupported subject attribute '{k.strip()}'")
        val = _tlv(0x13, v.strip().encode()) if k.strip().upper() == "C" else _utf8(v.strip())
        rdns.append(_set(_seq(_oid(oid), val)))
    return _seq(*rdns)


def _rsa_pub(k) -> bytes:
    return _seq(_seq(_oid("1.2.840.113549.1.1.1"), _NULL), _bitstr(_seq(_int(k["n"]), _int(k["e"]))))


_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def rsa_sign_sha256(k, data: bytes) -> bytes:
    nlen = (k["n"].bit_length() + 7) // 8
    t = _SHA256_PREFIX + hashlib.sha256(data).digest()
    em = b"\x00\x01" + b"\xff" * (nlen - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), k["d"], k["n"]).to_bytes(nlen, "big")


def build_certificate(k, subject: str, dns_names, months: int, key_usage, ekus) -> bytes:
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    nb = now - datetime.timedelta(minutes=5)
    na = nb + datetime.timedelta(days=round(months * 30.44))
    serial = int.from_bytes(uuid.uuid4().bytes, "big") >> 1
    sig_alg = _seq(_oid("1.2.840.113549.1.1.11"), _NULL)
    name = _name(subject)
    exts = [_seq(_oid("2.5.29.19"), _tlv(0x01, b"\xff"), _octet(_seq()))]             # basicConstraints: not a CA
    ku_bits = {"digitalSignature": 0, "nonRepudiation": 1, "keyEncipherment": 2, "dataEncipherment": 3,
               "keyAgreement": 4, "keyCertSign": 5, "cRLSign": 6}
    if key_usage:
        v = 0
        for u in key_usage:
            v |= 1 << (7 - ku_bits[u])
        exts.append(_seq(_oid("2.5.29.15"), _tlv(0x01, b"\xff"), _octet(_tlv(0x03, b"\x00" + bytes([v])))))
    if ekus:
        exts.append(_seq(_oid("2.5.29.37"), _octet(_seq(*[_oid(o) for o in ekus]))))
    if dns_names:
        exts.append(_seq(_oid("2.5.29.17"), _octet(_seq(*[_tlv(0x82, d.encode()) for d in dns_names]))))
    spki = _rsa_pub(k)
    ski = hashlib.sha1(_seq(_int(k["n"]), _int(k["e"]))).digest()
    exts.append(_seq(_oid("2.5.29.14"), _octet(_octet(ski))))
    tbs = _seq(_tlv(0xA0, _int(2)), _int(serial), sig_alg, name, _seq(_time(nb), _time(na)), name, spki,
               _tlv(0xA3, _seq(*exts)))
    return _seq(tbs, sig_alg, _bitstr(rsa_sign_sha256(k, tbs))), int(nb.timestamp()), int(na.timestamp())


def _pem(label: str, der: bytes) -> str:
    b = base64.b64encode(der).decode()
    return f"-----BEGIN {label}-----\n" + "\n".join(b[i:i + 64] for i in range(0, len(b), 64)) + f"\n-----END {label}-----\n"


def _pkcs8(k) -> bytes:
    rsa = _seq(_int(0), _int(k["n"]), _int(k["e"]), _int(k["d"]), _int(k["p"]), _int(k["q"]),
               _int(k["dp"]), _int(k["dq"]), _int(k["qi"]))
    return _seq(_int(0), _seq(_oid("1.2.840.113549.1.1.1"), _NULL), _octet(rsa))


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


# ── store ────────────────────────────────────────────────────────────────────
class CertStore:
    """Certificates per vault: vaults[vault][name] = [version dicts, newest last]."""

    def __init__(self):
        self.vaults = {}


EKU = {"serverAuth": "1.3.6.1.5.5.7.3.1", "clientAuth": "1.3.6.1.5.5.7.3.2"}
KEY_USAGES = ("digitalSignature", "keyEncipherment", "dataEncipherment", "keyAgreement", "nonRepudiation", "keyCertSign", "cRLSign")


def _base(vault):
    return f"https://{vault}.vault.azure.net"


def _bundle(vault, name, v, full=True):
    ids = f"{_base(vault)}/certificates/{name}/{v['version']}"
    out = {"id": ids, "x5t": v["x5t"], "attributes": dict(v["attributes"]), "tags": dict(v.get("tags") or {})}
    if full:
        out.update({"kid": f"{_base(vault)}/keys/{name}/{v['version']}", "sid": f"{_base(vault)}/secrets/{name}/{v['version']}",
                    "cer": v["cer"], "policy": dict(v["policy"], id=f"{_base(vault)}/certificates/{name}/policy")})
    return out


def _op(vault, name, v):
    return {"id": f"{_base(vault)}/certificates/{name}/pending", "issuer": {"name": "Self"},
            "csr": v.get("csr", ""), "cancellation_requested": False, "status": "completed",
            "target": f"{_base(vault)}/certificates/{name}", "request_id": v["request_id"]}


def _err(status, code, msg):
    return status, {"error": {"code": code, "message": msg}}


def _create(store, vault, name, body):
    pol = (body or {}).get("policy") or {}
    issuer = (pol.get("issuer") or {}).get("name", "Self")
    if issuer != "Self":
        return _err(400, "BadParameter", f"Issuer '{issuer}' requires a certificate authority; this vault can only issue self-signed (issuer 'Self') certificates.")
    x5 = pol.get("x509_props") or {}
    subject = x5.get("subject") or f"CN={name}"
    months = int(x5.get("validity_months") or 12)
    if not 1 <= months <= 120:
        return _err(400, "BadParameter", "validity_months must be between 1 and 120.")
    kp = pol.get("key_props") or {}
    if (kp.get("kty") or "RSA") not in ("RSA", "RSA-HSM"):
        return _err(400, "BadParameter", "Only RSA keys are supported for self-signed certificates.")
    size = int(kp.get("key_size") or 2048)
    if size not in (2048, 3072, 4096):
        return _err(400, "BadParameter", "key_size must be 2048, 3072 or 4096.")
    dns = list(((x5.get("sans") or {}).get("dns_names")) or [])
    ku = x5.get("key_usage") or ["digitalSignature", "keyEncipherment"]
    if any(u not in KEY_USAGES for u in ku):
        return _err(400, "BadParameter", f"key_usage must be from {', '.join(KEY_USAGES)}.")
    ekus = x5.get("ekus") or [EKU["serverAuth"], EKU["clientAuth"]]
    try:
        k = rsa_generate(size)
        der, nbf, exp = build_certificate(k, subject, dns, months, ku, ekus)
    except ValueError as e:
        return _err(400, "BadParameter", str(e))
    now = int(time.time())
    content_type = (pol.get("secret_props") or {}).get("contentType") or "application/x-pem-file"
    if content_type != "application/x-pem-file":
        return _err(400, "BadParameter", "Only the application/x-pem-file secret content type is supported by this vault.")
    v = {"version": uuid.uuid4().hex, "cer": base64.b64encode(der).decode(), "x5t": _b64url(hashlib.sha1(der).digest()),
         "thumbprint": hashlib.sha1(der).hexdigest().upper(), "request_id": uuid.uuid4().hex,
         "secret": _pem("PRIVATE KEY", _pkcs8(k)) + _pem("CERTIFICATE", der),
         "attributes": {"enabled": True, "nbf": nbf, "exp": exp, "created": now, "updated": now, "recoveryLevel": "Recoverable+Purgeable"},
         "tags": dict((body or {}).get("tags") or {}),
         "policy": {"key_props": {"exportable": bool(kp.get("exportable", True)), "kty": "RSA", "key_size": size, "reuse_key": False},
                    "secret_props": {"contentType": content_type},
                    "x509_props": {"subject": subject, "sans": {"dns_names": dns}, "ekus": ekus, "key_usage": ku, "validity_months": months},
                    "lifetime_actions": [{"trigger": {"lifetime_percentage": 80}, "action": {"action_type": "AutoRenew"}}],
                    "issuer": {"name": "Self"}, "attributes": {"enabled": True, "created": now, "updated": now}}}
    store.vaults.setdefault(vault, {}).setdefault(name, []).append(v)
    return 202, _op(vault, name, v)


def dispatch(store, vault, method, rest, body=None):
    method = (method or "GET").upper()
    segs = [x for x in str(rest or "").strip("/").split("/") if x]
    if segs and segs[0] == "certificates":
        segs = segs[1:]
    certs = store.vaults.setdefault(vault, {})
    if not segs:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "GET only.")
        return 200, {"value": [_bundle(vault, n, vs[-1], full=False) | {"id": f"{_base(vault)}/certificates/{n}"}
                               for n, vs in sorted(certs.items()) if vs], "nextLink": None}
    name = segs[0]
    vs = certs.get(name) or []
    if len(segs) == 2 and segs[1] == "create" and method == "POST":
        return _create(store, vault, name, body)
    if not vs:
        return _err(404, "CertificateNotFound", f"A certificate with (name/id) {name} was not found in this key vault.")
    if len(segs) == 2 and segs[1] == "pending":
        return 200, _op(vault, name, vs[-1])
    if len(segs) == 2 and segs[1] == "versions":
        return 200, {"value": [_bundle(vault, name, v, full=False) for v in vs]}
    if len(segs) == 2 and segs[1] == "policy":
        return 200, dict(vs[-1]["policy"], id=f"{_base(vault)}/certificates/{name}/policy")
    ver = segs[1] if len(segs) == 2 else None
    v = next((x for x in vs if x["version"] == ver), None) if ver else vs[-1]
    if v is None:
        return _err(404, "CertificateNotFound", f"Version {ver} of certificate {name} was not found.")
    if method == "GET":
        return 200, _bundle(vault, name, v)
    if method == "PATCH":
        a = (body or {}).get("attributes") or {}
        if "enabled" in a:
            v["attributes"]["enabled"] = bool(a["enabled"])
        if isinstance((body or {}).get("tags"), dict):
            v["tags"] = dict(body["tags"])
        v["attributes"]["updated"] = int(time.time())
        return 200, _bundle(vault, name, v)
    if method == "DELETE" and ver is None:
        certs.pop(name, None)
        out = _bundle(vault, name, vs[-1])
        out.update({"recoveryId": f"{_base(vault)}/deletedcertificates/{name}", "deletedDate": int(time.time()),
                    "scheduledPurgeDate": int(time.time()) + 90 * 86400})
        return 200, out
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def secret_value(store, vault, name, version=None):
    """The PEM bundle (private key + certificate) a certificate's secret holds."""
    vs = (store.vaults.get(vault) or {}).get(name) or []
    v = next((x for x in vs if x["version"] == version), None) if version else (vs[-1] if vs else None)
    return v["secret"] if v else None
