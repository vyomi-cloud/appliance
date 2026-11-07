# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Binary Authorization (binaryauthorization.googleapis.com/v1) + the Container Analysis attestation occurrences
it verifies — substrate-free (stdlib only: runs on Nano/Pyodide and offline).

State lives on the Cloud Run store (``store.binauthz``, a public dict so nano_persist keeps it):
  policies      {full policy name -> Policy}      projects/P/policy and projects/P/platforms/{platform}/policies/{id}
  attestors     {full attestor name -> Attestor}
  occurrences   {occurrence name -> ATTESTATION Occurrence}
  decisions     [admission decisions, newest last, capped]

Enforcement (``evaluate`` / ``enforce``) is what Cloud Run deploys call (core/gcp_run_core.py): the image's
policy is resolved (project default policy, or a named platform policy), the admission allowlist is applied,
then the rule's evaluationMode runs — ALWAYS_ALLOW / ALWAYS_DENY / REQUIRE_ATTESTATION. REQUIRE_ATTESTATION
really verifies signatures: every required attestor needs at least one ATTESTATION occurrence for the image
digest whose payload names that digest and whose ECDSA P-256 / SHA-256 signature verifies against one of the
attestor's PKIX public keys (verified by a pure-Python ECDSA implementation below — no OpenSSL needed).

Honest limits: only ECDSA_P256_SHA256 PKIX keys verify (RSA / other curves / Cloud KMS-backed keys are
rejected at attestor write time); tags are resolved to digests through the Artifact Registry (an image that
cannot be resolved has no attestations and so fails REQUIRE_ATTESTATION); continuous validation and GKE
cluster rules are stored but only the Cloud Run platform is enforced.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field

DEFAULT_RULE = {"evaluationMode": "ALWAYS_ALLOW", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG"}
EVAL_MODES = ("ALWAYS_ALLOW", "ALWAYS_DENY", "REQUIRE_ATTESTATION")
ENFORCE_MODES = ("ENFORCED_BLOCK_AND_AUDIT_LOG", "DRYRUN_AUDIT_LOG_ONLY")
# Google-maintained images the global policy allows (globalPolicyEvaluationMode=ENABLE), a representative subset.
GLOBAL_ALLOW = ["gcr.io/google_containers/*", "gcr.io/google-containers/*", "k8s.gcr.io/**", "gcr.io/stackdriver-agents/*",
                "gke.gcr.io/**", "registry.k8s.io/**"]
MAX_DECISIONS = 200


class BaError(Exception):
    def __init__(self, status, gstatus, message):
        super().__init__(message)
        self.status, self.gstatus, self.message = status, gstatus, message


@dataclass
class Resp:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str = "application/json"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def state(store) -> dict:
    s = getattr(store, "binauthz", None)
    if s is None:
        s = {"policies": {}, "attestors": {}, "occurrences": {}, "decisions": []}
        store.binauthz = s
    return s


# ── pure-Python ECDSA P-256 verify / sign (RFC 6979-free test signer uses a fixed nonce derivation) ─────────
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_A = _P - 3
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
# SubjectPublicKeyInfo prefix of a P-256 key (id-ecPublicKey, prime256v1, 65-byte uncompressed point).
_SPKI_P256 = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0] + _A) * pow(2 * p[1], -1, _P) % _P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (lam * lam - p[0] - q[0]) % _P
    return x, (lam * (p[0] - x) - p[1]) % _P


def _mul(k, p):
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)
        k >>= 1
    return r


_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B


def _der_len(b, i):
    n = b[i]
    i += 1
    if n < 0x80:
        return n, i
    k = n & 0x7F
    return int.from_bytes(b[i:i + k], "big"), i + k


def _der_read(b, i, tag):
    if i >= len(b) or b[i] != tag:
        raise ValueError("bad DER")
    n, i = _der_len(b, i + 1)
    return b[i:i + n], i + n


def parse_signature(sig: bytes):
    seq, _ = _der_read(sig, 0, 0x30)
    r, i = _der_read(seq, 0, 0x02)
    s, _ = _der_read(seq, i, 0x02)
    return int.from_bytes(r, "big"), int.from_bytes(s, "big")


def _der_int(v):
    b = v.to_bytes((v.bit_length() + 7) // 8 or 1, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return b"\x02" + bytes([len(b)]) + b


def encode_signature(r, s):
    body = _der_int(r) + _der_int(s)
    return b"\x30" + bytes([len(body)]) + body


def pem_to_point(pem: str):
    """(x, y) of a P-256 PKIX/SPKI PEM public key; ValueError otherwise."""
    m = re.search(r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----", pem or "", re.S)
    if not m:
        raise ValueError("publicKeyPem must be a PEM 'PUBLIC KEY' (PKIX) block")
    der = base64.b64decode("".join(m.group(1).split()))
    if not der.startswith(_SPKI_P256) or len(der) != len(_SPKI_P256) + 65 or der[len(_SPKI_P256)] != 4:
        raise ValueError("only ECDSA P-256 (prime256v1) PKIX public keys are supported")
    pt = der[len(_SPKI_P256) + 1:]
    x, y = int.from_bytes(pt[:32], "big"), int.from_bytes(pt[32:], "big")
    if (y * y - x * x * x - _A * x - _B) % _P:
        raise ValueError("public key point is not on the P-256 curve")
    return x, y


def point_to_pem(pt) -> str:
    der = _SPKI_P256 + b"\x04" + pt[0].to_bytes(32, "big") + pt[1].to_bytes(32, "big")
    b = base64.b64encode(der).decode()
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(b[i:i + 64] for i in range(0, len(b), 64)) + "\n-----END PUBLIC KEY-----\n"


def ecdsa_verify(pt, message: bytes, sig_der: bytes) -> bool:
    try:
        r, s = parse_signature(sig_der)
    except Exception:
        return False
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    z = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, _N)
    q = _add(_mul(z * w % _N, (_GX, _GY)), _mul(r * w % _N, pt))
    return q is not None and q[0] % _N == r


def ecdsa_sign(priv: int, message: bytes) -> bytes:
    """Deterministic-nonce signer (tests / the console's 'sign with a demo key' helper); not a hardened signer."""
    z = int.from_bytes(hashlib.sha256(message).digest(), "big")
    k_seed = hashlib.sha256(priv.to_bytes(32, "big") + hashlib.sha256(message).digest()).digest()
    k = int.from_bytes(k_seed, "big") % (_N - 1) + 1
    while True:
        x, _ = _mul(k, (_GX, _GY))
        r = x % _N
        s = pow(k, -1, _N) * (z + r * priv) % _N
        if r and s:
            return encode_signature(r, s)
        k = k % (_N - 1) + 1


def public_point(priv: int):
    return _mul(priv, (_GX, _GY))


def key_id(pem: str) -> str:
    der = base64.b64decode("".join(re.search(r"-----BEGIN PUBLIC KEY-----(.*?)-----END", pem, re.S).group(1).split()))
    return "ni:///sha-256;" + base64.urlsafe_b64encode(hashlib.sha256(der).digest()).decode().rstrip("=")


def container_payload(image_ref: str, digest: str) -> bytes:
    """The 'Google cloud binauthz container signature' simple-signing payload gcloud signs."""
    return json.dumps({"critical": {"identity": {"docker-reference": image_ref},
                                     "image": {"docker-manifest-digest": digest},
                                     "type": "Google cloud binauthz container signature"}}, separators=(",", ":")).encode()


# ── names / validation ───────────────────────────────────────────────────
_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9-_.]{0,99}$")


def _b64(s, what):
    try:
        return base64.b64decode(s or "", validate=False)
    except Exception:
        raise BaError(400, "INVALID_ARGUMENT", "%s is not valid base64." % what)


def _norm_policy_name(project, platform, pid):
    return "projects/%s/policy" % project if not platform else "projects/%s/platforms/%s/policies/%s" % (project, platform, pid)


def _validate_rule(rule, where, attestors, project):
    if not isinstance(rule, dict):
        raise BaError(400, "INVALID_ARGUMENT", "%s must be an object." % where)
    mode = rule.get("evaluationMode")
    if mode not in EVAL_MODES:
        raise BaError(400, "INVALID_ARGUMENT", "%s.evaluationMode must be one of %s." % (where, ", ".join(EVAL_MODES)))
    if rule.get("enforcementMode") not in ENFORCE_MODES:
        raise BaError(400, "INVALID_ARGUMENT", "%s.enforcementMode must be one of %s." % (where, ", ".join(ENFORCE_MODES)))
    req = rule.get("requireAttestationsBy") or []
    if mode == "REQUIRE_ATTESTATION" and not req:
        raise BaError(400, "INVALID_ARGUMENT", "%s.requireAttestationsBy is required for REQUIRE_ATTESTATION." % where)
    if mode != "REQUIRE_ATTESTATION" and req:
        raise BaError(400, "INVALID_ARGUMENT", "%s.requireAttestationsBy is only valid with REQUIRE_ATTESTATION." % where)
    for a in req:
        if a not in attestors:
            raise BaError(400, "INVALID_ARGUMENT", "Attestor %s does not exist." % a)
    return {"evaluationMode": mode, "enforcementMode": rule["enforcementMode"], **({"requireAttestationsBy": list(req)} if req else {})}


def _validate_policy(st, project, body, name):
    if not isinstance(body, dict):
        raise BaError(400, "INVALID_ARGUMENT", "Policy body must be an object.")
    out = {"name": name, "globalPolicyEvaluationMode": body.get("globalPolicyEvaluationMode") or "ENABLE"}
    if out["globalPolicyEvaluationMode"] not in ("ENABLE", "DISABLE"):
        raise BaError(400, "INVALID_ARGUMENT", "globalPolicyEvaluationMode must be ENABLE or DISABLE.")
    if "defaultAdmissionRule" not in body:
        raise BaError(400, "INVALID_ARGUMENT", "defaultAdmissionRule is required.")
    out["defaultAdmissionRule"] = _validate_rule(body["defaultAdmissionRule"], "defaultAdmissionRule", st["attestors"], project)
    pats = []
    for w in body.get("admissionWhitelistPatterns") or []:
        if not isinstance(w, dict) or not w.get("namePattern"):
            raise BaError(400, "INVALID_ARGUMENT", "admissionWhitelistPatterns[].namePattern is required.")
        pats.append({"namePattern": str(w["namePattern"])})
    if pats:
        out["admissionWhitelistPatterns"] = pats
    for kind in ("clusterAdmissionRules", "kubernetesNamespaceAdmissionRules", "kubernetesServiceAccountAdmissionRules", "istioServiceIdentityAdmissionRules"):
        m = body.get(kind)
        if m is not None:
            if not isinstance(m, dict):
                raise BaError(400, "INVALID_ARGUMENT", "%s must be a map." % kind)
            out[kind] = {k: _validate_rule(v, "%s[%s]" % (kind, k), st["attestors"], project) for k, v in m.items()}
    if body.get("description"):
        out["description"] = str(body["description"])
    out["updateTime"] = _now()
    return out


def _validate_attestor(project, aid, body):
    if not isinstance(body, dict):
        raise BaError(400, "INVALID_ARGUMENT", "Attestor body must be an object.")
    note = (body.get("userOwnedGrafeasNote") or {})
    if not note.get("noteReference"):
        raise BaError(400, "INVALID_ARGUMENT", "userOwnedGrafeasNote.noteReference is required.")
    if not re.match(r"^projects/[^/]+/notes/[^/]+$", note["noteReference"]):
        raise BaError(400, "INVALID_ARGUMENT", "noteReference must look like projects/P/notes/N.")
    keys = []
    for k in note.get("publicKeys") or []:
        pk = k.get("pkixPublicKey") or {}
        alg = pk.get("signatureAlgorithm") or "ECDSA_P256_SHA256"
        if alg != "ECDSA_P256_SHA256":
            raise BaError(400, "INVALID_ARGUMENT", "signatureAlgorithm %s is not supported by this simulator (ECDSA_P256_SHA256 only)." % alg)
        try:
            pem_to_point(pk.get("publicKeyPem"))
        except ValueError as e:
            raise BaError(400, "INVALID_ARGUMENT", str(e))
        keys.append({"id": k.get("id") or key_id(pk["publicKeyPem"]), "comment": k.get("comment", ""),
                     "pkixPublicKey": {"publicKeyPem": pk["publicKeyPem"], "signatureAlgorithm": alg}})
    gnote = {"noteReference": note["noteReference"], "publicKeys": keys}
    if note.get("delegationServiceAccountEmail"):
        gnote["delegationServiceAccountEmail"] = note["delegationServiceAccountEmail"]
    return {"name": "projects/%s/attestors/%s" % (project, aid), "description": body.get("description", ""),
            "userOwnedGrafeasNote": gnote, "updateTime": _now()}


# ── attestation verification ─────────────────────────────────────────────
def _verify_occurrence(attestor, occ, digest):
    """True if the occurrence carries a signature by one of the attestor's keys over a payload naming ``digest``."""
    att = occ.get("attestation") or {}
    payload = _b64(att.get("serializedPayload"), "serializedPayload")
    try:
        pd = json.loads(payload.decode("utf-8"))
        if pd["critical"]["image"]["docker-manifest-digest"] != digest:
            return False
    except Exception:
        return False
    keys = attestor["userOwnedGrafeasNote"]["publicKeys"]
    for sg in att.get("signatures") or []:
        sig = _b64(sg.get("signature"), "signature")
        for k in keys:
            if sg.get("publicKeyId") and sg["publicKeyId"] != k["id"]:
                continue
            if ecdsa_verify(pem_to_point(k["pkixPublicKey"]["publicKeyPem"]), payload, sig):
                return True
    return False


def attested_by(st, attestor_name, digest):
    a = st["attestors"].get(attestor_name)
    if a is None:
        return False
    note = a["userOwnedGrafeasNote"]["noteReference"]
    for occ in st["occurrences"].values():
        if occ.get("noteName") == note and occ.get("resourceUri", "").endswith(digest) and _verify_occurrence(a, occ, digest):
            return True
    return False


def _pattern_re(p):
    out, i = "", 0
    while i < len(p):
        if p.startswith("**", i):
            out += ".*"
            i += 2
        elif p[i] == "*":
            out += "[^/]*"
            i += 1
        else:
            out += re.escape(p[i])
            i += 1
    return re.compile("^" + out + "$")


def _strip_digest(image):
    return re.split(r"[@]", image, 1)[0]


def _whitelisted(policy, image):
    base = _strip_digest(image)
    base_notag = re.sub(r":[^/:]+$", "", base)
    pats = [w["namePattern"] for w in policy.get("admissionWhitelistPatterns") or []]
    if policy.get("globalPolicyEvaluationMode", "ENABLE") == "ENABLE":
        pats += GLOBAL_ALLOW
    for p in pats:
        rx = _pattern_re(p)
        if rx.match(image) or rx.match(base) or rx.match(base_notag):
            return p
    return None


def default_policy(project):
    return {"name": "projects/%s/policy" % project, "globalPolicyEvaluationMode": "ENABLE",
            "defaultAdmissionRule": dict(DEFAULT_RULE), "updateTime": _now()}


def get_policy(st, name, project):
    if name in st["policies"]:
        return st["policies"][name]
    return default_policy(project) if name == "projects/%s/policy" % project else None


def evaluate(store, project, policy_ref, image, digest=None, platform="cloudRun"):
    """Decision for one image: {allowed, enforced, mode, reason, policy, attestors}. ``policy_ref``: None/'' =
    project default policy, else a projects/P/platforms/cloudRun/policies/N name."""
    st = state(store)
    name = policy_ref if policy_ref else "projects/%s/policy" % project
    pol = get_policy(st, name, project)
    if pol is None:
        return {"allowed": False, "enforced": True, "mode": "MISSING_POLICY", "policy": name, "image": image,
                "reason": "Binary Authorization policy %s does not exist." % name}
    rule = pol["defaultAdmissionRule"]
    base = {"policy": name, "image": image, "digest": digest or "", "mode": rule["evaluationMode"],
            "enforcementMode": rule["enforcementMode"]}
    hit = _whitelisted(pol, image)
    if hit:
        return {**base, "allowed": True, "enforced": False, "reason": "Image matches admission allowlist pattern %s." % hit}
    mode = rule["evaluationMode"]
    if mode == "ALWAYS_ALLOW":
        return {**base, "allowed": True, "enforced": False, "reason": "Policy allows all images."}
    if mode == "ALWAYS_DENY":
        return {**base, "allowed": False, "enforced": rule["enforcementMode"] == "ENFORCED_BLOCK_AND_AUDIT_LOG",
                "reason": "Denied by Binary Authorization default admission rule (ALWAYS_DENY)."}
    missing = []
    for a in rule.get("requireAttestationsBy") or []:
        if not digest or not attested_by(st, a, digest):
            missing.append(a)
    if not missing:
        return {**base, "allowed": True, "enforced": False, "reason": "All required attestors have verified attestations."}
    why = "Denied by Binary Authorization default admission rule. Image %s denied by %s: " % (image, ", ".join(missing))
    why += "No attestations found that were valid and signed by a key trusted by the attestor." if digest else "image could not be resolved to a digest."
    return {**base, "allowed": False, "enforced": rule["enforcementMode"] == "ENFORCED_BLOCK_AND_AUDIT_LOG",
            "reason": why, "missingAttestors": missing}


def _record(st, project, decision):
    st["decisions"].append({"time": _now(), "project": project, **{k: v for k, v in decision.items()}})
    del st["decisions"][:-MAX_DECISIONS]


def enforce(store, project, binauthz, images, resolver=None, label="revision"):
    """Called by Cloud Run before a revision is created. ``binauthz``: the service's binaryAuthorization field
    ({useDefault:true} | {policy:...} | None). Raises BaError(FAILED_PRECONDITION) when a decision is enforced.
    A service without the field is not subject to Binary Authorization (as on Cloud Run)."""
    if not binauthz:
        return []
    ref = None if binauthz.get("useDefault") else binauthz.get("policy")
    st = state(store)
    out = []
    for img in images:
        dg = None
        m = re.search(r"@(sha256:[0-9a-f]{64})$", img)
        if m:
            dg = m.group(1)
        elif callable(resolver):
            try:
                dg = resolver(img)
            except Exception:  # noqa: BLE001
                dg = None
        d = evaluate(store, project, ref, img, dg)
        _record(st, project, d)
        out.append(d)
        if not d["allowed"] and d["enforced"]:
            raise BaError(400, "FAILED_PRECONDITION", "Binary Authorization denied the %s: %s" % (label, d["reason"]))
    return out


# ── REST ─────────────────────────────────────────────────────────────────
def handles(path):
    return bool(re.match(r"^/v1/projects/[^/]+/(policy|attestors|platforms/[^/]+/policies|occurrences)([/:?]|$)", path))


def _json(status, obj):
    return Resp(status, json.dumps(obj).encode())


def _err(e):
    return _json(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gstatus}})


def dispatch(store, method, path, query=None, headers=None, body=b"", resolver=None, vuln=None):
    """``vuln(project)`` -> Container Analysis VULNERABILITY occurrences from the Artifact Registry image scans."""
    try:
        return _dispatch(store, method.upper(), path, query or {}, body, resolver, vuln)
    except BaError as e:
        return _err(e)


def _body(body):
    if not body:
        return {}
    try:
        v = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    except Exception:
        raise BaError(400, "INVALID_ARGUMENT", "Request body is not valid JSON.")
    return v if isinstance(v, dict) else {}


def _dispatch(store, method, path, query, body, resolver, vuln=None):
    st = state(store)
    m = re.match(r"^/v1/projects/([^/]+)/(.*)$", path)
    project, rest = m.group(1), m.group(2)
    verb = ""
    if ":" in rest.rsplit("/", 1)[-1]:
        rest, verb = rest.rsplit(":", 1)
    # project default policy
    if rest == "policy":
        name = "projects/%s/policy" % project
        if method == "GET" and not verb:
            return _json(200, get_policy(st, name, project))
        if method == "PUT" and not verb:
            st["policies"][name] = _validate_policy(st, project, _body(body), name)
            return _json(200, st["policies"][name])
        if verb == "evaluate" and method == "POST":   # Vyomi extension: dry-run an image against this policy
            b = _body(body)
            return _json(200, evaluate(store, project, "", b.get("image", ""), b.get("digest") or (resolver(b["image"]) if resolver and b.get("image") else None)))
        if verb == "decisions" and method == "GET":    # Vyomi extension: the admission decision log
            return _json(200, {"decisions": [d for d in st["decisions"] if d.get("project") == project]})
        raise BaError(405, "METHOD_NOT_ALLOWED", "Unsupported %s on policy." % method)
    # platform policies
    pm = re.match(r"^platforms/([^/]+)/policies(?:/([^/]+))?$", rest)
    if pm:
        platform, pid = pm.group(1), pm.group(2)
        if platform not in ("cloudRun", "gke"):
            raise BaError(400, "INVALID_ARGUMENT", "Unknown platform %s." % platform)
        if not pid:
            if method == "GET":
                pre = "projects/%s/platforms/%s/policies/" % (project, platform)
                return _json(200, {"policies": [v for k, v in sorted(st["policies"].items()) if k.startswith(pre)]})
            if method == "POST":   # createPlatformPolicy: the body is {policy:{...}} in v1, accept both shapes
                b = _body(body)
                pid = query.get("policyId") or (b.get("policy") or b).get("name", "").rsplit("/", 1)[-1] or ""
                if not _ID.match(pid):
                    raise BaError(400, "INVALID_ARGUMENT", "policyId is required.")
                name = _norm_policy_name(project, platform, pid)
                if name in st["policies"]:
                    raise BaError(409, "ALREADY_EXISTS", "Policy %s already exists." % name)
                st["policies"][name] = _validate_policy(st, project, b.get("policy") or b, name)
                return _json(200, st["policies"][name])
            raise BaError(405, "METHOD_NOT_ALLOWED", "Unsupported %s." % method)
        name = _norm_policy_name(project, platform, pid)
        if verb == "evaluate" and method == "POST":
            b = _body(body)
            return _json(200, evaluate(store, project, name, b.get("image", ""), b.get("digest") or (resolver(b["image"]) if resolver and b.get("image") else None)))
        if method == "GET":
            if name not in st["policies"]:
                raise BaError(404, "NOT_FOUND", "Policy %s not found." % name)
            return _json(200, st["policies"][name])
        if method in ("PUT", "PATCH"):
            if name not in st["policies"]:
                raise BaError(404, "NOT_FOUND", "Policy %s not found." % name)
            b = _body(body)
            st["policies"][name] = _validate_policy(st, project, b.get("policy") or b, name)
            return _json(200, st["policies"][name])
        if method == "DELETE":
            if st["policies"].pop(name, None) is None:
                raise BaError(404, "NOT_FOUND", "Policy %s not found." % name)
            return _json(200, {})
        raise BaError(405, "METHOD_NOT_ALLOWED", "Unsupported %s." % method)
    # attestors
    am = re.match(r"^attestors(?:/([^/]+))?$", rest)
    if am:
        aid = am.group(1)
        pre = "projects/%s/attestors/" % project
        if not aid:
            if method == "GET":
                return _json(200, {"attestors": [v for k, v in sorted(st["attestors"].items()) if k.startswith(pre)]})
            if method == "POST":
                aid = query.get("attestorId") or ""
                if not _ID.match(aid):
                    raise BaError(400, "INVALID_ARGUMENT", "attestorId is required.")
                if pre + aid in st["attestors"]:
                    raise BaError(409, "ALREADY_EXISTS", "Attestor %s already exists." % (pre + aid))
                st["attestors"][pre + aid] = _validate_attestor(project, aid, _body(body))
                return _json(200, st["attestors"][pre + aid])
            raise BaError(405, "METHOD_NOT_ALLOWED", "Unsupported %s." % method)
        name = pre + aid
        if verb == "validateAttestationOccurrence" and method == "POST":
            if name not in st["attestors"]:
                raise BaError(404, "NOT_FOUND", "Attestor %s not found." % name)
            b = _body(body)
            occ = {"noteName": st["attestors"][name]["userOwnedGrafeasNote"]["noteReference"], "attestation": b.get("attestation") or {}}
            uri = b.get("occurrenceResourceUri", "")
            dg = re.search(r"(sha256:[0-9a-f]{64})", uri)
            ok = bool(dg) and _verify_occurrence(st["attestors"][name], occ, dg.group(1))
            return _json(200, {"result": "VERIFIED" if ok else "ATTESTATION_NOT_VERIFIABLE",
                               **({} if ok else {"denialReason": "No signature verified against the attestor's public keys for the image digest."})})
        if method == "GET":
            if name not in st["attestors"]:
                raise BaError(404, "NOT_FOUND", "Attestor %s not found." % name)
            return _json(200, st["attestors"][name])
        if method == "PUT":
            if name not in st["attestors"]:
                raise BaError(404, "NOT_FOUND", "Attestor %s not found." % name)
            st["attestors"][name] = _validate_attestor(project, aid, _body(body))
            return _json(200, st["attestors"][name])
        if method == "DELETE":
            if name not in st["attestors"]:
                raise BaError(404, "NOT_FOUND", "Attestor %s not found." % name)
            for pn, p in st["policies"].items():
                refs = [r for rule in [p["defaultAdmissionRule"]] + [x for k in ("clusterAdmissionRules",) for x in (p.get(k) or {}).values()] for r in rule.get("requireAttestationsBy", [])]
                if name in refs:
                    raise BaError(400, "FAILED_PRECONDITION", "Attestor %s is still referenced by policy %s." % (name, pn))
            del st["attestors"][name]
            return _json(200, {})
        raise BaError(405, "METHOD_NOT_ALLOWED", "Unsupported %s." % method)
    # Container Analysis occurrences (attestations only)
    if rest == "occurrences":
        if method == "POST":
            b = _body(body)
            if b.get("kind", "ATTESTATION") != "ATTESTATION" or not b.get("attestation"):
                raise BaError(400, "INVALID_ARGUMENT", "Only ATTESTATION occurrences are supported.")
            if not b.get("resourceUri") or not b.get("noteName"):
                raise BaError(400, "INVALID_ARGUMENT", "resourceUri and noteName are required.")
            if not re.search(r"@sha256:[0-9a-f]{64}$", b["resourceUri"]):
                raise BaError(400, "INVALID_ARGUMENT", "resourceUri must reference an image digest (...@sha256:<hex>).")
            _b64(b["attestation"].get("serializedPayload"), "serializedPayload")
            oid = hashlib.sha256((b["resourceUri"] + b["noteName"] + json.dumps(b["attestation"], sort_keys=True)).encode()).hexdigest()[:16]
            name = "projects/%s/occurrences/%s" % (project, oid)
            st["occurrences"][name] = {"name": name, "resourceUri": b["resourceUri"], "noteName": b["noteName"], "kind": "ATTESTATION",
                                       "attestation": b["attestation"], "createTime": _now(), "updateTime": _now()}
            return _json(200, st["occurrences"][name])
        if method == "GET":
            pre = "projects/%s/occurrences/" % project
            flt = str(query.get("filter") or "")
            kind = (re.search(r'kind\s*=\s*"?(\w+)"?', flt) or [None, ""])[1]
            res = (re.search(r'resource_?[uU](?:rl|ri)\s*=\s*"([^"]+)"', flt) or [None, ""])[1].replace("https://", "")
            occs = []
            if kind in ("", "ATTESTATION"):
                occs += [v for k, v in sorted(st["occurrences"].items()) if k.startswith(pre)]
            if kind in ("", "VULNERABILITY") and callable(vuln):
                occs += vuln(project)
            if res:
                occs = [o for o in occs if o.get("resourceUri", "").replace("https://", "") == res]
            if verb == "vulnerabilitySummary":
                by = {}
                for o in occs:
                    if o.get("kind") == "VULNERABILITY":
                        c = by.setdefault(o["vulnerability"]["severity"], [0, 0])
                        c[0] += 1
                        c[1] += 1 if o["vulnerability"]["packageIssue"][0].get("fixAvailable") else 0
                return _json(200, {"counts": [{"severity": k, "totalCount": str(n), "fixableCount": str(f)} for k, (n, f) in by.items()]})
            return _json(200, {"occurrences": occs})
    om = re.match(r"^occurrences/([^/]+)$", rest)
    if om:
        name = "projects/%s/occurrences/%s" % (project, om.group(1))
        if method == "GET" and name in st["occurrences"]:
            return _json(200, st["occurrences"][name])
        if method == "DELETE" and st["occurrences"].pop(name, None) is not None:
            return _json(200, {})
        raise BaError(404, "NOT_FOUND", "Occurrence %s not found." % name)
    raise BaError(404, "NOT_FOUND", "Unknown Binary Authorization resource %s." % path)
