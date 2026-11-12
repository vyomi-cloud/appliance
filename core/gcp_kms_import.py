"""Cloud KMS key import crypto — pure Python (stdlib only), Pyodide-loadable.

Implements what a customer's wrapping tool (gcloud / openssl / the console docs) produces
and what Cloud KMS unwraps on `cryptoKeyVersions:import`:

  * RSA key-pair generation (Miller-Rabin) for an ImportJob's wrapping key
  * RSAES-OAEP (RFC 8017) with MGF1 and SHA-1 or SHA-256
  * AES-256 block cipher + AES Key Wrap with Padding (KWP, RFC 5649)
  * the RSA_OAEP_*_AES_256 combined format: RSA-OAEP(ephemeral AES-256 key) || KWP(ephemeral, target key)

Pure Python on every substrate so the offline appliance and Nano behave identically
(the `cryptography` package is not a dependency of either).
"""
from __future__ import annotations

import hashlib
import os
import secrets

# ── AES-256 (encrypt + decrypt single blocks) ─────────────────────────────
_SBOX = bytearray(256)


def _init_sbox() -> None:
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        _SBOX[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    _SBOX[0] = 0x63


_init_sbox()
_INV_SBOX = bytearray(256)
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _xt(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _expand_key(key: bytes) -> list:
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")
    w = [list(key[i:i + 4]) for i in range(0, 32, 4)]
    rcon = 1
    for i in range(8, 60):
        t = list(w[i - 1])
        if i % 8 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        elif i % 8 == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - 8][j] ^ t[j] for j in range(4)])
    return [sum((w[4 * r + c] for c in range(4)), []) for r in range(15)]


def _aes_encrypt_block(rk: list, block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, rk[0])]
    for rnd in range(1, 15):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]            # ShiftRows
        if rnd != 14:
            n = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                n += [_xt(a[0]) ^ (_xt(a[1]) ^ a[1]) ^ a[2] ^ a[3],
                      a[0] ^ _xt(a[1]) ^ (_xt(a[2]) ^ a[2]) ^ a[3],
                      a[0] ^ a[1] ^ _xt(a[2]) ^ (_xt(a[3]) ^ a[3]),
                      (_xt(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _xt(a[3])]
            s = n
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return bytes(s)


def _aes_decrypt_block(rk: list, block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, rk[14])]
    for rnd in range(13, -1, -1):
        s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]            # InvShiftRows
        s = [_INV_SBOX[b] for b in s]
        s = [b ^ k for b, k in zip(s, rk[rnd])]
        if rnd != 0:
            n = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                n += [_mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9),
                      _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13),
                      _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11),
                      _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)]
            s = n
    return bytes(s)


# ── AES Key Wrap with Padding (RFC 5649) ──────────────────────────────────
_KWP_IV = b"\xa6\x59\x59\xa6"


def _wrap_core(rk: list, blocks: list) -> list:
    n = len(blocks) - 1
    a = blocks[0]
    r = list(blocks[1:])
    for j in range(6):
        for i in range(n):
            b = _aes_encrypt_block(rk, a + r[i])
            t = n * j + i + 1
            a = (int.from_bytes(b[:8], "big") ^ t).to_bytes(8, "big")
            r[i] = b[8:]
    return [a] + r


def kwp_wrap(kek: bytes, key: bytes) -> bytes:
    rk = _expand_key(kek)
    pad = (-len(key)) % 8
    aiv = _KWP_IV + len(key).to_bytes(4, "big")
    padded = key + b"\x00" * pad
    if len(padded) == 8:
        return _aes_encrypt_block(rk, aiv + padded)
    blocks = [aiv] + [padded[i:i + 8] for i in range(0, len(padded), 8)]
    return b"".join(_wrap_core(rk, blocks))


def kwp_unwrap(kek: bytes, wrapped: bytes) -> bytes:
    rk = _expand_key(kek)
    if len(wrapped) < 16 or len(wrapped) % 8:
        raise ValueError("invalid wrapped key length")
    if len(wrapped) == 16:
        d = _aes_decrypt_block(rk, wrapped)
        a, padded = d[:8], d[8:]
    else:
        c = [wrapped[i:i + 8] for i in range(0, len(wrapped), 8)]
        n = len(c) - 1
        a, r = c[0], list(c[1:])
        for j in range(5, -1, -1):
            for i in range(n - 1, -1, -1):
                t = n * j + i + 1
                b = _aes_decrypt_block(rk, (int.from_bytes(a, "big") ^ t).to_bytes(8, "big") + r[i])
                a, r[i] = b[:8], b[8:]
        padded = b"".join(r)
    mli = int.from_bytes(a[4:], "big")
    if a[:4] != _KWP_IV or not (8 * (len(padded) // 8 - 1) < mli <= len(padded)) \
            or any(padded[mli:]):
        raise ValueError("AES-KWP integrity check failed")
    return padded[:mli]


# ── RSA ────────────────────────────────────────────────────────────────────
_SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** .5) + 1, 2))]


def _is_prime(n: int, rounds: int = 8) -> bool:
    if n < 2:
        return False
    for p in _SMALL_PRIMES[:100]:
        if n == p:
            return True
        if n % p == 0:
            return False
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if any(c % p == 0 for p in _SMALL_PRIMES):
            continue
        if _is_prime(c, 1) and _is_prime(c, 6):
            return c


def rsa_generate(bits: int, e: int = 65537) -> dict:
    """-> {"n","e","d"} ints. Pure-Python keygen: seconds for 3072 bits."""
    while True:
        p, q = _gen_prime(bits // 2), _gen_prime(bits // 2)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        return {"n": n, "e": e, "d": pow(e, -1, phi)}


# ── DER / PEM (SubjectPublicKeyInfo for RSA) ──────────────────────────────
def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(body)) + body


def _der_int(v: int) -> bytes:
    b = v.to_bytes((v.bit_length() + 8) // 8, "big")
    return _der(0x02, b)


def rsa_public_pem(n: int, e: int) -> str:
    import base64
    rsapub = _der(0x30, _der_int(n) + _der_int(e))
    algid = _der(0x30, bytes.fromhex("06092a864886f70d010101") + b"\x05\x00")
    spki = _der(0x30, algid + _der(0x03, b"\x00" + rsapub))
    b64 = base64.b64encode(spki).decode()
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n"


def rsa_public_from_pem(pem: str) -> tuple:
    """Parse an RSA SPKI/PKCS#1 PEM -> (n, e). Raises ValueError."""
    import base64
    import re
    m = re.search(r"-----BEGIN (?:RSA )?PUBLIC KEY-----(.+?)-----END (?:RSA )?PUBLIC KEY-----", pem, re.S)
    if not m:
        raise ValueError("not a PEM public key")
    der = base64.b64decode("".join(m.group(1).split()))

    def read(buf, i):
        tag = buf[i]
        ln = buf[i + 1]
        i += 2
        if ln & 0x80:
            k = ln & 0x7F
            ln = int.from_bytes(buf[i:i + k], "big")
            i += k
        return tag, buf[i:i + ln], i + ln

    tag, body, _ = read(der, 0)
    if tag != 0x30:
        raise ValueError("bad DER")
    t1, b1, nxt = read(body, 0)
    if t1 == 0x30:                                   # SPKI: algid, BIT STRING(RSAPublicKey)
        t2, b2, _ = read(body, nxt)
        body = b2[1:]
        tag, body, _ = read(body, 0)
        t1, b1, nxt = read(body, 0)
    t2, b2, _ = read(body, nxt)
    return int.from_bytes(b1, "big"), int.from_bytes(b2, "big")


# ── RSAES-OAEP ─────────────────────────────────────────────────────────────
def _mgf1(seed: bytes, length: int, h) -> bytes:
    out = b""
    c = 0
    while len(out) < length:
        out += h(seed + c.to_bytes(4, "big")).digest()
        c += 1
    return out[:length]


def _hash(name: str):
    return {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256}[name]


def oaep_encrypt(n: int, e: int, msg: bytes, hash_name: str = "SHA256", label: bytes = b"") -> bytes:
    h = _hash(hash_name)
    k = (n.bit_length() + 7) // 8
    hl = h().digest_size
    if len(msg) > k - 2 * hl - 2:
        raise ValueError("message too long for RSA-OAEP")
    lhash = h(label).digest()
    db = lhash + b"\x00" * (k - len(msg) - 2 * hl - 2) + b"\x01" + msg
    seed = os.urandom(hl)
    masked_db = bytes(a ^ b for a, b in zip(db, _mgf1(seed, k - hl - 1, h)))
    masked_seed = bytes(a ^ b for a, b in zip(seed, _mgf1(masked_db, hl, h)))
    em = b"\x00" + masked_seed + masked_db
    return pow(int.from_bytes(em, "big"), e, n).to_bytes(k, "big")


def oaep_decrypt(n: int, d: int, ct: bytes, hash_name: str = "SHA256", label: bytes = b"") -> bytes:
    h = _hash(hash_name)
    k = (n.bit_length() + 7) // 8
    hl = h().digest_size
    if len(ct) != k:
        raise ValueError("decryption error")
    c = int.from_bytes(ct, "big")
    if c >= n:
        raise ValueError("decryption error")
    em = pow(c, d, n).to_bytes(k, "big")
    masked_seed, masked_db = em[1:1 + hl], em[1 + hl:]
    seed = bytes(a ^ b for a, b in zip(masked_seed, _mgf1(masked_db, hl, h)))
    db = bytes(a ^ b for a, b in zip(masked_db, _mgf1(seed, k - hl - 1, h)))
    rest = db[hl:]
    i = rest.find(b"\x01")
    if em[0] != 0 or db[:hl] != h(label).digest() or i < 0 or any(rest[:i]):
        raise ValueError("decryption error")
    return rest[i + 1:]


# ── Cloud KMS import methods ───────────────────────────────────────────────
IMPORT_METHODS = {
    "RSA_OAEP_3072_SHA1_AES_256": (3072, "SHA1", True),
    "RSA_OAEP_4096_SHA1_AES_256": (4096, "SHA1", True),
    "RSA_OAEP_3072_SHA256_AES_256": (3072, "SHA256", True),
    "RSA_OAEP_4096_SHA256_AES_256": (4096, "SHA256", True),
    "RSA_OAEP_3072_SHA256": (3072, "SHA256", False),
    "RSA_OAEP_4096_SHA256": (4096, "SHA256", False),
}


def wrap_for_import(method: str, n: int, e: int, key: bytes) -> bytes:
    """What the customer's tooling does: wrap `key` for an ImportJob public key."""
    bits, hn, with_aes = IMPORT_METHODS[method]
    if not with_aes:
        return oaep_encrypt(n, e, key, hn)
    eph = os.urandom(32)
    return oaep_encrypt(n, e, eph, hn) + kwp_wrap(eph, key)


def unwrap_import(method: str, n: int, d: int, wrapped: bytes) -> bytes:
    bits, hn, with_aes = IMPORT_METHODS[method]
    k = (n.bit_length() + 7) // 8
    if not with_aes:
        return oaep_decrypt(n, d, wrapped, hn)
    if len(wrapped) <= k:
        raise ValueError("wrapped key too short")
    eph = oaep_decrypt(n, d, wrapped[:k], hn)
    if len(eph) != 32:
        raise ValueError("ephemeral AES key must be 32 bytes")
    return kwp_unwrap(eph, wrapped[k:])
