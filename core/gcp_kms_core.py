"""GCP Cloud KMS core — substrate-independent, the GCP analogue of core/kms_core.py.
Speaks the native **Cloud KMS REST API v1** (`/v1/projects/{p}/locations/{l}/
keyRings/...`) so the native `google-cloud-kms` SDK and `gcloud kms` work unchanged
against it (point them at the endpoint via api_endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Reuses the SAME seams as AWS KMS (core/kms_keystore.py): the KeyStore holds the
key material and the KmsEngine does the real (stdlib, deterministic, authenticated)
envelope crypto — so encrypt/decrypt round-trip and the CryptoKey resource name is
recovered from the ciphertext exactly as AWS recovers its KeyId. GCP just gets its
own store instance, so key rings / crypto keys are cloud-namespaced.

Wire shape follows the REST resource model:
    projects/{p}/locations/{l}/keyRings/{kr}
    projects/{p}/locations/{l}/keyRings/{kr}/cryptoKeys/{k}
    projects/{p}/locations/{l}/keyRings/{kr}/cryptoKeys/{k}/cryptoKeyVersions/{v}
Custom methods use the `:verb` suffix (`:encrypt`, `:decrypt`). `plaintext` /
`ciphertext` fields are base64 per the REST wire. Errors use the Google shape
`{"error":{"code","message","status"}}` (status e.g. NOT_FOUND / INVALID_ARGUMENT).

Scope (v1 slice): keyRings create/get/list, cryptoKeys create/get/list,
cryptoKeyVersions get/list, :encrypt, :decrypt. IAM policy, rotation, asymmetric
keys, and key-version lifecycle reuse the same helpers and slot in next.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.kms_keystore import KeyStore


# ── transport type ─────────────────────────────────────────────────────────
@dataclass
class GcpKmsResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ─────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _err(status: int, gcp_status: str, message: str) -> GcpKmsResponse:
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return GcpKmsResponse(status=status, body=json.dumps(body).encode())


def _json(status: int, obj: dict) -> GcpKmsResponse:
    return GcpKmsResponse(status=status, body=json.dumps(obj).encode())


# ── GCP key-ring bookkeeping (crypto-key material lives in the KeyStore seam) ─
def _rings(store: KeyStore) -> dict:
    # Key rings hold no secret material, so they hang off the store instance
    # (which is dedicated to this GCP KMS namespace) rather than the key map.
    return store.__dict__.setdefault("gcp_key_rings", {})


# ── resource views ─────────────────────────────────────────────────────────
def _key_ring_view(name: str, entry: dict) -> dict:
    return {"name": name, "createTime": entry.get("createTime", _now())}


def _version_name(key_name: str, ver: str) -> str:
    return f"{key_name}/cryptoKeyVersions/{ver}"


def _version_view(key_name: str, ver: str, entry: dict) -> dict:
    return {
        "name": _version_name(key_name, ver),
        "state": entry.get("state", "ENABLED"),
        "protectionLevel": entry.get("protectionLevel", "SOFTWARE"),
        "algorithm": entry.get("algorithm", "GOOGLE_SYMMETRIC_ENCRYPTION"),
        "createTime": entry.get("createTime", _now()),
        "generateTime": entry.get("createTime", _now()),
        **{k: entry[k] for k in ("destroyTime", "destroyEventTime") if entry.get(k)},
    }


def _crypto_key_view(store: KeyStore, name: str) -> dict:
    meta = store.get_key(name) or {}
    primary = str(meta.get("primary", "1"))
    versions = meta.get("versions", {primary: {}})
    return {
        "name": name,
        "primary": _version_view(name, primary, versions.get(primary, {})),
        **{k: meta[k] for k in ("rotationPeriod", "nextRotationTime", "labels") if meta.get(k)},
        "purpose": meta.get("purpose", "ENCRYPT_DECRYPT"),
        "createTime": meta.get("createTime", _now()),
        "versionTemplate": {
            "protectionLevel": "SOFTWARE",
            "algorithm": meta.get("algorithm", "GOOGLE_SYMMETRIC_ENCRYPTION"),
        },
    }


# ── key versions, rotation, primary, import jobs (shared with the offline appliance) ──
# Version 1's material is the key's own (ciphertexts embed the CryptoKey name, as
# before); a version N > 1 gets fresh material and its ciphertexts embed the version
# name, so decrypt finds the version — and refuses one that isn't ENABLED.
DESTROY_SCHEDULED_SECONDS = 30 * 86400   # Cloud KMS default destroy_scheduled_duration


class KmsTabError(Exception):
    def __init__(self, status: int, gcp_status: str, message: str):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _parse_ts(s: str) -> float:
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _dur(v) -> int:
    try:
        return int(float(str(v or "").rstrip("s")))
    except ValueError:
        raise KmsTabError(400, "INVALID_ARGUMENT", "Invalid duration '%s' (seconds, e.g. 7776000s)." % v)


def validate_rotation(period, next_time) -> dict:
    """CryptoKey rotation_period / next_rotation_time rules (symmetric keys)."""
    out = {}
    if period not in (None, ""):
        secs = _dur(period)
        if secs < 86400:
            raise KmsTabError(400, "INVALID_ARGUMENT", "rotation_period must be at least 24 hours.")
        if secs > 876000 * 3600:
            raise KmsTabError(400, "INVALID_ARGUMENT", "rotation_period must be at most 100 years.")
        out["rotationPeriod"] = "%ds" % secs
    if next_time not in (None, ""):
        t = _parse_ts(next_time)
        if not t:
            raise KmsTabError(400, "INVALID_ARGUMENT", "next_rotation_time must be an RFC 3339 timestamp.")
        out["nextRotationTime"] = _ts(t)
    elif "rotationPeriod" in out:
        out["nextRotationTime"] = _ts(datetime.now(timezone.utc).timestamp() + _dur(out["rotationPeriod"]))
    return out


def _vmat_key(name: str, ver: str) -> str:
    return f"{name}/cryptoKeyVersions/{ver}"


def _version_material(store: KeyStore, name: str, ver: str):
    return store.get_material(name) if str(ver) == "1" else store.material.get(_vmat_key(name, ver))


def _new_version(store: KeyStore, name: str, meta: dict) -> str:
    versions = meta.setdefault("versions", {})
    ver = str(max([int(v) for v in versions] + [0]) + 1)
    versions[ver] = {"state": "ENABLED", "createTime": _now()}
    store.material[_vmat_key(name, ver)] = store.engine.new_key_material()
    return ver


def _maybe_rotate(store: KeyStore, name: str) -> None:
    """Automatic rotation: once next_rotation_time passes a new primary version is made."""
    meta = store.get_key(name) or {}
    nxt, period = meta.get("nextRotationTime"), meta.get("rotationPeriod")
    if not nxt or not period:
        return
    now = datetime.now(timezone.utc).timestamp()
    t, rotated = _parse_ts(nxt), False
    while t and t <= now:
        meta["primary"] = _new_version(store, name, meta)
        t += _dur(period)
        rotated = True
    if rotated:
        meta["nextRotationTime"] = _ts(t)
        store.persist()


def rotation_due(meta: dict) -> int:
    """How many automatic rotations are due (next_rotation_time passed), and move
    next_rotation_time past now — for backends that rotate their own key material."""
    nxt, period = meta.get("nextRotationTime"), meta.get("rotationPeriod")
    if not nxt or not period:
        return 0
    now, t, n = datetime.now(timezone.utc).timestamp(), _parse_ts(nxt), 0
    while t and t <= now:
        t += _dur(period)
        n += 1
    if n:
        meta["nextRotationTime"] = _ts(t)
    return n


def _purge_destroyed(store: KeyStore, name: str) -> None:
    """DESTROY_SCHEDULED versions whose destroy time passed lose their material."""
    meta = store.get_key(name) or {}
    now = datetime.now(timezone.utc).timestamp()
    for ver, v in (meta.get("versions") or {}).items():
        if v.get("state") == "DESTROY_SCHEDULED" and _parse_ts(v.get("destroyTime", "")) <= now:
            v["state"], v["destroyEventTime"] = "DESTROYED", _now()
            if str(ver) != "1":
                store.material.pop(_vmat_key(name, ver), None)


def set_version_state(meta: dict, ver: str, action: str) -> dict:
    """enable / disable / destroy / restore one version per Cloud KMS's state machine."""
    v = (meta.get("versions") or {}).get(str(ver))
    if v is None:
        raise KmsTabError(404, "NOT_FOUND", "CryptoKeyVersion %s not found." % ver)
    st = v.get("state", "ENABLED")
    if action in ("enable", "disable"):
        if st not in ("ENABLED", "DISABLED"):
            raise KmsTabError(400, "FAILED_PRECONDITION", "CryptoKeyVersion %s is %s; only ENABLED or DISABLED versions can change state." % (ver, st))
        # (disabling the primary is allowed: encrypt then fails until a new primary is set)
        v["state"] = "ENABLED" if action == "enable" else "DISABLED"
    elif action == "destroy":
        if st not in ("ENABLED", "DISABLED"):
            raise KmsTabError(400, "FAILED_PRECONDITION", "CryptoKeyVersion %s is already %s." % (ver, st))
        v["state"] = "DESTROY_SCHEDULED"
        v["destroyTime"] = _ts(datetime.now(timezone.utc).timestamp() + DESTROY_SCHEDULED_SECONDS)
    elif action == "restore":
        if st != "DESTROY_SCHEDULED":
            raise KmsTabError(400, "FAILED_PRECONDITION", "Only a version scheduled for destruction can be restored (it is %s)." % st)
        v["state"] = "DISABLED"
        v.pop("destroyTime", None)
    else:
        raise KmsTabError(400, "INVALID_ARGUMENT", "Unknown version action %s." % action)
    return v


def set_primary(meta: dict, ver: str) -> None:
    v = (meta.get("versions") or {}).get(str(ver))
    if v is None:
        raise KmsTabError(404, "NOT_FOUND", "CryptoKeyVersion %s not found." % ver)
    if v.get("state") != "ENABLED":
        raise KmsTabError(400, "FAILED_PRECONDITION", "The primary version must be ENABLED (version %s is %s)." % (ver, v.get("state")))
    meta["primary"] = str(ver)


# Import jobs: a real RSA wrapping key (OAEP) per job. With `cryptography` (the offline
# appliance) the key is generated at once; under Pyodide a pure-Python generator searches
# for the primes a slice of time per request, so the job stays PENDING_GENERATION until the
# key really exists — then ACTIVE, with its public key.
IMPORT_METHODS = {"RSA_OAEP_3072_SHA1_AES_256": 3072, "RSA_OAEP_4096_SHA1_AES_256": 4096,
                  "RSA_OAEP_3072_SHA256_AES_256": 3072, "RSA_OAEP_4096_SHA256_AES_256": 4096,
                  "RSA_OAEP_3072_SHA256": 3072, "RSA_OAEP_4096_SHA256": 4096}
_SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** 0.5) + 1, 2))]


def _probable_prime(n: int, rounds: int = 24) -> bool:
    import random
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    rnd = random.SystemRandom()
    for _ in range(rounds):
        a = rnd.randrange(2, n - 2)
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


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(body)) + body


def _der_int(v: int) -> bytes:
    b = v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big")
    return _der(0x02, b)


def rsa_public_pem(n: int, e: int) -> str:
    """SubjectPublicKeyInfo PEM for an RSA public key."""
    algo = _der(0x30, _der(0x06, bytes.fromhex("2a864886f70d010101")) + b"\x05\x00")
    spki = _der(0x30, algo + _der(0x03, b"\x00" + _der(0x30, _der_int(n) + _der_int(e))))
    b64 = base64.b64encode(spki).decode()
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64)) + "\n-----END PUBLIC KEY-----\n"


def rsa_generate(bits: int) -> dict:
    """A real RSA key pair {n, e, d, p, q} (`cryptography` when available, else pure Python)."""
    import os
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        nums = _rsa.generate_private_key(public_exponent=65537, key_size=bits).private_numbers()
        return {"n": nums.public_numbers.n, "e": 65537, "d": nums.d, "p": nums.p, "q": nums.q}
    except Exception:
        pass
    primes = []
    while len(primes) < 2:
        c = int.from_bytes(os.urandom(bits // 16), "big") | (3 << (bits // 2 - 2)) | 1
        if (c - 1) % 65537 and _probable_prime(c) and c not in primes:
            primes.append(c)
    p, q = primes
    return {"n": p * q, "e": 65537, "d": pow(65537, -1, (p - 1) * (q - 1)), "p": p, "q": q}


def rsa_private_pem(k: dict) -> str:
    """PKCS#8 PEM ('BEGIN PRIVATE KEY', what Google key files carry) of an RSA key."""
    n, e, d, p, q = (int(k[x]) for x in ("n", "e", "d", "p", "q"))
    rsa_der = _der(0x30, b"".join(_der_int(v) for v in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))
    algo = _der(0x30, _der(0x06, bytes.fromhex("2a864886f70d010101")) + b"\x05\x00")
    pk8 = _der(0x30, _der_int(0) + algo + _der(0x04, rsa_der))
    b64 = base64.b64encode(pk8).decode()
    return "-----BEGIN PRIVATE KEY-----\n" + "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64)) + "\n-----END PRIVATE KEY-----\n"


def _advance_keygen(job: dict, budget_s: float) -> None:
    """Grow the job's RSA key: (cryptography) at once, else prime search within the budget."""
    import os
    import time as _time
    if job.get("state") != "PENDING_GENERATION":
        return
    bits = IMPORT_METHODS[job["importMethod"]]
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        k = _rsa.generate_private_key(public_exponent=65537, key_size=bits)
        nums = k.private_numbers()
        job["_rsa"] = {"n": str(nums.public_numbers.n), "e": "65537", "p": str(nums.p), "q": str(nums.q)}
    except Exception:
        primes = [int(x) for x in job.setdefault("_primes", [])]
        stop = _time.time() + budget_s
        while len(primes) < 2 and _time.time() < stop:
            c = int.from_bytes(os.urandom(bits // 16), "big") | (3 << (bits // 2 - 2)) | 1
            if (c - 1) % 65537 and _probable_prime(c):
                primes.append(c)
        job["_primes"] = [str(p) for p in primes]
        if len(primes) < 2:
            return
        p, q = primes
        job["_rsa"] = {"n": str(p * q), "e": "65537", "p": str(p), "q": str(q)}
        job.pop("_primes", None)
    job["state"] = "ACTIVE"
    job["generateTime"] = _now()
    job["publicKey"] = {"pem": rsa_public_pem(int(job["_rsa"]["n"]), 65537)}


def import_job_view(name: str, job: dict) -> dict:
    return {"name": name, **{k: v for k, v in job.items() if not k.startswith("_")}}


def _import_jobs(store: KeyStore) -> dict:
    return store.__dict__.setdefault("gcp_import_jobs", {})


def import_job_create(jobs: dict, ring: str, jid: str, payload: dict, budget_s: float) -> dict:
    """importJobs.create into `jobs` ({job name: job}); returns the job view."""
    import re as _re
    if not _re.match(r"^[a-zA-Z0-9_-]{1,63}$", jid or ""):
        raise KmsTabError(400, "INVALID_ARGUMENT", "importJobId must be 1-63 letters, digits, '-' or '_'.")
    name = f"{ring}/importJobs/{jid}"
    if name in jobs:
        raise KmsTabError(409, "ALREADY_EXISTS", f"ImportJob {name} already exists.")
    meth = str(payload.get("importMethod") or "")
    if meth not in IMPORT_METHODS:
        raise KmsTabError(400, "INVALID_ARGUMENT", "import_method must be one of " + ", ".join(IMPORT_METHODS) + ".")
    lvl = str(payload.get("protectionLevel") or "SOFTWARE")
    if lvl not in ("SOFTWARE", "HSM"):
        raise KmsTabError(400, "INVALID_ARGUMENT", "protection_level must be SOFTWARE or HSM for import jobs.")
    now = datetime.now(timezone.utc).timestamp()
    jobs[name] = {"importMethod": meth, "protectionLevel": lvl, "createTime": _ts(now),
                  "expireTime": _ts(now + 3 * 86400), "state": "PENDING_GENERATION"}
    _advance_keygen(jobs[name], budget_s)
    return import_job_view(name, jobs[name])


def import_job_list(jobs: dict, ring: str, budget_s: float) -> list:
    out = []
    for n, j in sorted(jobs.items()):
        if n.startswith(ring + "/importJobs/"):
            _advance_keygen(j, budget_s)
            if j.get("state") == "ACTIVE" and _parse_ts(j.get("expireTime", "")) <= datetime.now(timezone.utc).timestamp():
                j["state"] = "EXPIRED"
            out.append(import_job_view(n, j))
    return out


def _import_job_route(store, method, segs, query, payload, budget_s):
    ring = "/".join(segs[:6])
    jobs = _import_jobs(store)
    if ring not in _rings(store):
        return _err(404, "NOT_FOUND", f"KeyRing {ring} not found.")
    if len(segs) == 7:
        if method == "POST":
            try:
                view = import_job_create(jobs, ring, str(query.get("importJobId") or payload.get("importJobId") or ""), payload, budget_s)
            except KmsTabError as e:
                return _err(e.status, e.gcp_status, e.message)
            store.persist()
            return _json(200, view)
        if method == "GET":
            out = import_job_list(jobs, ring, budget_s)
            store.persist()
            return _json(200, {"importJobs": out} if out else {})
    if len(segs) == 8 and method == "GET":
        name = "/".join(segs)
        if name not in jobs:
            return _err(404, "NOT_FOUND", f"ImportJob {name} not found.")
        _advance_keygen(jobs[name], budget_s)
        store.persist()
        return _json(200, import_job_view(name, jobs[name]))
    return _err(400, "INVALID_ARGUMENT", "Unsupported request on importJobs")


# ── path parsing ───────────────────────────────────────────────────────────
def _parse(path: str) -> tuple[list, str | None]:
    """Strip the /v1 prefix + query, split off a trailing `:verb` custom method,
    and return (segments, verb)."""
    p = path
    if p.startswith("/v1/") or p == "/v1":
        p = p[3:]
    p = p.split("?", 1)[0]
    verb = None
    # The custom-method colon is only ever in the LAST path segment.
    last_slash = p.rfind("/")
    tail = p[last_slash + 1:]
    if ":" in tail:
        tail, verb = tail.split(":", 1)
        p = p[: last_slash + 1] + tail
    segs = [s for s in p.strip("/").split("/") if s]
    return segs, verb


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store: KeyStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcpKmsResponse:
    query = query or {}
    method = method.upper()
    segs, verb = _parse(path)

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    if len(segs) < 5 or segs[0] != "projects" or segs[2] != "locations" or segs[4] != "keyRings":
        return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")

    parent = "/".join(segs[:5])  # projects/{p}/locations/{l}/keyRings

    # ── keyRings collection: .../keyRings ──────────────────────────────────
    if len(segs) == 5:
        rings = _rings(store)
        if method == "POST":
            ring_id = query.get("keyRingId") or payload.get("keyRingId")
            if not ring_id:
                return _err(400, "INVALID_ARGUMENT", "keyRingId is required.")
            name = f"{parent}/{ring_id}"
            if name in rings:
                return _err(409, "ALREADY_EXISTS", f"KeyRing {name} already exists.")
            rings[name] = {"createTime": _now()}
            return _json(200, _key_ring_view(name, rings[name]))
        if method == "GET":
            items = [_key_ring_view(n, e) for n, e in sorted(rings.items())
                     if n.startswith(parent + "/") and n.count("/") == 5]
            return _json(200, {"keyRings": items})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on keyRings")

    # ── single keyRing: .../keyRings/{kr} ──────────────────────────────────
    if len(segs) == 6:
        rings = _rings(store)
        name = "/".join(segs)
        if method == "GET":
            if name not in rings:
                return _err(404, "NOT_FOUND", f"KeyRing {name} not found.")
            return _json(200, _key_ring_view(name, rings[name]))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on keyRing")

    # .../keyRings/{kr}/importJobs[/{job}]
    if segs[6] == "importJobs":
        return _import_job_route(store, method, segs, query, payload, float(query.get("_keygen_budget_s") or 0.6))

    # From here on the 7th segment must be cryptoKeys.
    if segs[6] != "cryptoKeys":
        return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")
    if len(segs) >= 8 and store.key_exists("/".join(segs[:8])):
        _maybe_rotate(store, "/".join(segs[:8]))
        _purge_destroyed(store, "/".join(segs[:8]))

    ring_name = "/".join(segs[:6])

    # ── cryptoKeys collection: .../cryptoKeys ──────────────────────────────
    if len(segs) == 7:
        rings = _rings(store)
        if method == "POST":
            if ring_name not in rings:
                return _err(404, "NOT_FOUND", f"KeyRing {ring_name} not found.")
            key_id = query.get("cryptoKeyId") or payload.get("cryptoKeyId")
            if not key_id:
                return _err(400, "INVALID_ARGUMENT", "cryptoKeyId is required.")
            name = f"{ring_name}/cryptoKeys/{key_id}"
            if store.key_exists(name):
                return _err(409, "ALREADY_EXISTS", f"CryptoKey {name} already exists.")
            now = _now()
            store.put_key(name, {
                "purpose": str(payload.get("purpose", "ENCRYPT_DECRYPT")),
                "algorithm": (payload.get("versionTemplate", {}) or {}).get(
                    "algorithm", "GOOGLE_SYMMETRIC_ENCRYPTION"),
                "createTime": now,
                "primary": "1",
                "versions": {"1": {"state": "ENABLED", "createTime": now}},
            }, store.engine.new_key_material())
            store.persist()
            return _json(200, _crypto_key_view(store, name))
        if method == "GET":
            items = [_crypto_key_view(store, n) for n in store.key_ids()
                     if n.startswith(ring_name + "/cryptoKeys/")
                     and n.count("/") == 7]
            return _json(200, {"cryptoKeys": items})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on cryptoKeys")

    # ── single cryptoKey + custom methods: .../cryptoKeys/{k}[:verb] ────────
    if len(segs) == 8:
        name = "/".join(segs)
        if verb == "encrypt":
            return _encrypt(store, name, payload)
        if verb == "decrypt":
            return _decrypt(store, name, payload)
        if not store.key_exists(name):
            return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
        meta = store.get_key(name)
        if verb == "updatePrimaryVersion" and method == "POST":
            try:
                set_primary(meta, str(payload.get("cryptoKeyVersionId") or ""))
            except KmsTabError as e:
                return _err(e.status, e.gcp_status, e.message)
            store.persist()
            return _json(200, _crypto_key_view(store, name))
        if verb:
            return _err(400, "INVALID_ARGUMENT", f"Unknown method :{verb}")
        if method == "GET":
            return _json(200, _crypto_key_view(store, name))
        if method == "PATCH":                       # cryptoKeys.patch (rotation, labels)
            mask = [m.strip() for m in str(query.get("updateMask") or "").split(",") if m.strip()] or list(payload)
            try:
                for m in mask:
                    if m not in ("rotationPeriod", "nextRotationTime", "labels", "rotation_period", "next_rotation_time"):
                        raise KmsTabError(400, "INVALID_ARGUMENT", "Field %s can't be updated." % m)
                if any(m in mask for m in ("rotationPeriod", "nextRotationTime", "rotation_period", "next_rotation_time")):
                    period = payload.get("rotationPeriod")
                    if period in (None, "") and "nextRotationTime" not in payload:
                        meta.pop("rotationPeriod", None)
                        meta.pop("nextRotationTime", None)
                    else:
                        meta.pop("rotationPeriod", None)
                        meta.update(validate_rotation(period, payload.get("nextRotationTime")))
                if "labels" in mask:
                    meta["labels"] = {str(a): str(b) for a, b in (payload.get("labels") or {}).items()}
            except KmsTabError as e:
                return _err(e.status, e.gcp_status, e.message)
            store.persist()
            return _json(200, _crypto_key_view(store, name))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on cryptoKey")

    # ── cryptoKeyVersions: .../cryptoKeys/{k}/cryptoKeyVersions[/{v}] ───────
    if len(segs) >= 9 and segs[8] == "cryptoKeyVersions":
        key_name = "/".join(segs[:8])
        if not store.key_exists(key_name):
            return _err(404, "NOT_FOUND", f"CryptoKey {key_name} not found.")
        meta = store.get_key(key_name) or {}
        versions = meta.get("versions", {})
        if len(segs) == 9 and method == "GET":       # list versions
            items = [_version_view(key_name, v, versions[v]) for v in sorted(versions, key=int)]
            return _json(200, {"cryptoKeyVersions": items})
        if len(segs) == 9 and method == "POST":      # create a version (not primary until promoted)
            ver = _new_version(store, key_name, meta)
            store.persist()
            return _json(200, _version_view(key_name, ver, versions[ver]))
        if len(segs) == 10:
            ver = segs[9]
            if ver not in versions:
                return _err(404, "NOT_FOUND", f"CryptoKeyVersion {ver} not found.")
            try:
                if verb in ("destroy", "restore") and method == "POST":
                    set_version_state(meta, ver, verb)
                elif method == "PATCH" and not verb:     # updateMask=state {state: ENABLED|DISABLED}
                    want = str(payload.get("state") or "")
                    if want not in ("ENABLED", "DISABLED"):
                        raise KmsTabError(400, "INVALID_ARGUMENT", "state can only be set to ENABLED or DISABLED.")
                    set_version_state(meta, ver, "enable" if want == "ENABLED" else "disable")
                elif method == "GET" and not verb:
                    return _json(200, _version_view(key_name, ver, versions[ver]))
                else:
                    return _err(400, "INVALID_ARGUMENT", f"Unsupported request on cryptoKeyVersions")
            except KmsTabError as e:
                return _err(e.status, e.gcp_status, e.message)
            store.persist()
            return _json(200, _version_view(key_name, ver, versions[ver]))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported request on cryptoKeyVersions")

    return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")


# ── crypto operations (reuse the AWS KMS engine + key material) ─────────────
def _encrypt(store: KeyStore, name: str, payload: dict) -> GcpKmsResponse:
    if not store.key_exists(name):
        return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
    try:
        plaintext = base64.b64decode(payload.get("plaintext", "") or "")
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "plaintext must be valid base64.")
    if not plaintext:
        return _err(400, "INVALID_ARGUMENT", "plaintext must not be empty.")
    meta = store.get_key(name) or {}
    primary = str(meta.get("primary", "1"))
    pv = (meta.get("versions") or {}).get(primary, {})
    if pv.get("state", "ENABLED") != "ENABLED":
        return _err(400, "FAILED_PRECONDITION",
                    f"The primary version {_version_name(name, primary)} is not enabled ({pv.get('state')}).")
    kid = name if primary == "1" else _version_name(name, primary)   # v1 ciphertexts keep their original shape
    blob = store.engine.encrypt(_version_material(store, name, primary), kid, plaintext)
    return _json(200, {
        "name": name,
        "ciphertext": _b64e(blob),
        "ciphertextCrc32c": None,
        "protectionLevel": "SOFTWARE",
    })


def _decrypt(store: KeyStore, name: str, payload: dict) -> GcpKmsResponse:
    if not store.key_exists(name):
        return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
    try:
        blob = base64.b64decode(payload.get("ciphertext", "") or "")
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "ciphertext must be valid base64.")
    # The ciphertext self-identifies its crypto key; it must match this resource.
    embedded = store.engine.key_id_in(blob)
    ver = "1"
    if embedded and embedded.startswith(name + "/cryptoKeyVersions/"):
        ver = embedded.rsplit("/", 1)[-1]
    elif embedded and embedded != name:
        return _err(400, "INVALID_ARGUMENT",
                    "Decryption failed: the ciphertext is for a different CryptoKey.")
    v = ((store.get_key(name) or {}).get("versions") or {}).get(ver, {})
    if v.get("state", "ENABLED") != "ENABLED":
        return _err(400, "FAILED_PRECONDITION",
                    f"{_version_name(name, ver)} is not enabled, current state is: {v.get('state')}.")
    try:
        plaintext = store.engine.decrypt(_version_material(store, name, ver), blob)
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Decryption failed: the ciphertext is invalid.")
    return _json(200, {"plaintext": _b64e(plaintext), "protectionLevel": "SOFTWARE"})
