"""Binary Authorization: policy + attestors + attestation occurrences, ENFORCED at Cloud Run deploy.
Signatures are real ECDSA P-256 / SHA-256 (pure-Python verifier in core/gcp_binauthz_core.py).
Run: PYTHONPATH=. python tests/conformance/test_gcp_binauthz.py"""
import base64
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import ci_core as ci  # noqa: E402
from core import gcp_binauthz_core as ba  # noqa: E402
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False


class StubBuilder:
    name, runs_containers = "stub-buildkit", True

    def build(self, job, tree, log):
        tag = job["spec"]["tag"]
        return {"ok": True, "artifact": {"type": "image", "tag": tag, "digest": "sha256:" + hashlib.sha256(tag.encode()).hexdigest(), "size": 10}}

    def export(self, tag):
        return {"layers": [tag.encode()], "config": json.dumps({"os": "linux"}).encode()}


ci.set_builder(StubBuilder())
R = AwsWireRouter()
PASS = FAIL = 0
P = "ba-proj"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:500] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


# crypto self-check against a known P-256 key: sign/verify round trip + tamper detection
priv = int.from_bytes(hashlib.sha256(b"vyomi-test-key").digest(), "big") % (ba._N - 1) + 1
pub = ba.public_point(priv)
pem = ba.point_to_pem(pub)
sig = ba.ecdsa_sign(priv, b"hello")
check("ecdsa verify ok", ba.ecdsa_verify(ba.pem_to_point(pem), b"hello", sig))
check("ecdsa tamper rejected", not ba.ecdsa_verify(ba.pem_to_point(pem), b"hellO", sig))
other = ba.public_point(priv + 1)
check("ecdsa wrong key rejected", not ba.ecdsa_verify(other, b"hello", sig))
# interop with OpenSSL where available (real-world signatures verify)
try:
    import subprocess, tempfile
    d = tempfile.mkdtemp()
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", d + "/k.pem"], check=True, capture_output=True)
    subprocess.run(["openssl", "ec", "-in", d + "/k.pem", "-pubout", "-out", d + "/p.pem"], check=True, capture_output=True)
    open(d + "/m", "wb").write(b"payload")
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", d + "/k.pem", "-out", d + "/s", d + "/m"], check=True, capture_output=True)
    check("OpenSSL-made signature verifies", ba.ecdsa_verify(ba.pem_to_point(open(d + "/p.pem").read()), b"payload", open(d + "/s", "rb").read()))
except (FileNotFoundError, subprocess.CalledProcessError):
    print("[SKIP] openssl interop")

REPO = f"us-central1-docker.pkg.dev/{P}/app"
check("AR repo", call("POST", f"/v1/projects/{P}/locations/us-central1/repositories", {"format": "DOCKER"}, {"repositoryId": "app"})[0] == 200)
call("POST", f"/v1/projects/{P}/triggers:vyomiPush", {"repoName": "shop", "branch": "main", "files": {"Dockerfile": "FROM scratch\n"}, "message": "i"})
DOCKER = "gcr.io/cloud-builders/docker"
b = call("POST", f"/v1/projects/{P}/builds", {"source": {"repoSource": {"repoName": "shop", "branchName": "main"}},
         "steps": [{"name": DOCKER, "args": ["build", "-t", REPO + "/web:v1", "."]}, {"name": DOCKER, "args": ["push", REPO + "/web:v1"]}]})[1]["response"]
digest = b["results"]["images"][0]["digest"]
check("image pushed", digest.startswith("sha256:"), b)

# default policy = allow all
st, pol = call("GET", f"/v1/projects/{P}/policy")
check("default policy ALWAYS_ALLOW", st == 200 and pol["defaultAdmissionRule"]["evaluationMode"] == "ALWAYS_ALLOW", pol)
LOC = f"/v2/projects/{P}/locations/us-central1"


def deploy(sid, image, ba_field=None, patch=False):
    tpl = {"containers": [{"image": image}]}
    if patch:
        return call("PATCH", f"{LOC}/services/{sid}", {"template": tpl, **({"binaryAuthorization": ba_field} if ba_field else {})}, {"updateMask": "template" + (",binaryAuthorization" if ba_field else "")})
    return call("POST", f"{LOC}/services", {"template": tpl, **({"binaryAuthorization": ba_field} if ba_field else {})}, {"serviceId": sid})


check("no binauthz field: not subject to policy", deploy("s0", REPO + "/web:v1")[0] == 200)
check("useDefault + allow-all policy deploys", deploy("s1", REPO + "/web:v1", {"useDefault": True})[0] == 200)

# validation
check("bad evaluationMode", call("PUT", f"/v1/projects/{P}/policy", {"defaultAdmissionRule": {"evaluationMode": "NOPE", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG"}})[0] == 400)
check("REQUIRE_ATTESTATION needs attestors", call("PUT", f"/v1/projects/{P}/policy", {"defaultAdmissionRule": {"evaluationMode": "REQUIRE_ATTESTATION", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG"}})[0] == 400)
check("unknown attestor rejected", call("PUT", f"/v1/projects/{P}/policy", {"defaultAdmissionRule": {"evaluationMode": "REQUIRE_ATTESTATION", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG", "requireAttestationsBy": [f"projects/{P}/attestors/ghost"]}})[0] == 400)

# attestor
NOTE = f"projects/{P}/notes/prod-note"
att = {"userOwnedGrafeasNote": {"noteReference": NOTE, "publicKeys": [{"pkixPublicKey": {"publicKeyPem": pem, "signatureAlgorithm": "ECDSA_P256_SHA256"}}]}}
st, a = call("POST", f"/v1/projects/{P}/attestors", att, {"attestorId": "prod"})
ANAME = f"projects/{P}/attestors/prod"
check("attestor created, key id derived", st == 200 and a["name"] == ANAME and a["userOwnedGrafeasNote"]["publicKeys"][0]["id"].startswith("ni:///sha-256;"), a)
KID = a["userOwnedGrafeasNote"]["publicKeys"][0]["id"]
rsa = {"userOwnedGrafeasNote": {"noteReference": NOTE, "publicKeys": [{"pkixPublicKey": {"publicKeyPem": pem, "signatureAlgorithm": "RSA_PSS_2048_SHA256"}}]}}
check("unsupported algorithm refused (not faked)", call("POST", f"/v1/projects/{P}/attestors", rsa, {"attestorId": "rsa"})[0] == 400)
check("duplicate attestor 409", call("POST", f"/v1/projects/{P}/attestors", att, {"attestorId": "prod"})[0] == 409)

# policy requiring attestation + an allowlist
policy = {"admissionWhitelistPatterns": [{"namePattern": f"us-central1-docker.pkg.dev/{P}/trusted/*"}],
          "defaultAdmissionRule": {"evaluationMode": "REQUIRE_ATTESTATION", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG", "requireAttestationsBy": [ANAME]}}
check("policy PUT", call("PUT", f"/v1/projects/{P}/policy", policy)[0] == 200)
check("attestor in use cannot be deleted", call("DELETE", f"/v1/projects/{P}/{ANAME.split('/',2)[2]}")[0] == 400)

st, o = deploy("s2", REPO + "/web:v1", {"useDefault": True})
check("unattested image is BLOCKED at deploy", st == 400 and o["error"]["status"] == "FAILURE_PRECONDITION".replace("FAILURE", "FAILED") and "Binary Authorization" in o["error"]["message"], o)
check("blocked service was not created", call("GET", f"{LOC}/services/s2")[0] == 404)
check("allowlisted image passes", deploy("s3", f"us-central1-docker.pkg.dev/{P}/trusted/img:1", {"useDefault": True})[0] == 200)
check("service without the field still deploys", deploy("s4", REPO + "/web:v1")[0] == 200)

# forged attestation: signed by a different key
ref = f"{REPO}/web@{digest}"
payload = ba.container_payload(ref, digest)
bad = ba.ecdsa_sign(priv + 7, payload)
occ = lambda s, kid=KID, pl=payload: {"resourceUri": ref, "noteName": NOTE, "kind": "ATTESTATION",
                                      "attestation": {"serializedPayload": base64.b64encode(pl).decode(), "signatures": [{"publicKeyId": kid, "signature": base64.b64encode(s).decode()}]}}
check("forged attestation stored (as in Container Analysis)", call("POST", f"/v1/projects/{P}/occurrences", occ(bad))[0] == 200)
st, o = deploy("s5", REPO + "/web:v1", {"useDefault": True})
check("forged attestation does NOT satisfy the policy", st == 400, o)
st, v = call("POST", f"/v1/projects/{P}/attestors/prod:validateAttestationOccurrence", {"attestation": occ(bad)["attestation"], "occurrenceResourceUri": ref})
check("validateAttestationOccurrence rejects forged", v.get("result") == "ATTESTATION_NOT_VERIFIABLE", v)

# a payload for a DIFFERENT digest, validly signed, must not help
other_pl = ba.container_payload(ref, "sha256:" + "0" * 64)
call("POST", f"/v1/projects/{P}/occurrences", occ(ba.ecdsa_sign(priv, other_pl), pl=other_pl))
check("valid signature over another digest doesn't help", deploy("s6", REPO + "/web:v1", {"useDefault": True})[0] == 400)

# genuine attestation
good = ba.ecdsa_sign(priv, payload)
st, v = call("POST", f"/v1/projects/{P}/attestors/prod:validateAttestationOccurrence", {"attestation": occ(good)["attestation"], "occurrenceResourceUri": ref})
check("validateAttestationOccurrence VERIFIED", v.get("result") == "VERIFIED", v)
check("genuine attestation stored", call("POST", f"/v1/projects/{P}/occurrences", occ(good))[0] == 200)
check("attested image (by tag, resolved to digest) deploys", deploy("s7", REPO + "/web:v1", {"useDefault": True})[0] == 200)
check("attested image by digest deploys", deploy("s8", ref, {"useDefault": True})[0] == 200)

# update path: PATCH to an unattested image is blocked
check("PATCH to an unattested image blocked", deploy("s7", f"us-central1-docker.pkg.dev/{P}/app/other:9", {"useDefault": True}, patch=True)[0] == 400)

# named platform policy + dry-run mode
dry = {"defaultAdmissionRule": {"evaluationMode": "ALWAYS_DENY", "enforcementMode": "DRYRUN_AUDIT_LOG_ONLY"}}
st, o = call("POST", f"/v1/projects/{P}/platforms/cloudRun/policies", dry, {"policyId": "audit"})
check("platform policy created", st == 200 and o["name"] == f"projects/{P}/platforms/cloudRun/policies/audit", o)
NP = f"projects/{P}/platforms/cloudRun/policies/audit"
check("dry-run deny does not block", deploy("s9", REPO + "/web:v1", {"policy": NP})[0] == 200)
call("PUT", f"/v1/{NP}", {"defaultAdmissionRule": {"evaluationMode": "ALWAYS_DENY", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG"}})
check("ALWAYS_DENY enforced", deploy("s10", REPO + "/web:v1", {"policy": NP})[0] == 400)
check("global allowlist (gcr.io/google-containers) bypasses deny", deploy("s11", "gcr.io/google-containers/pause:3.2", {"policy": NP})[0] == 200)
st, d = call("GET", f"/v1/projects/{P}/policy:decisions")
check("decision log records allow/deny/dry-run", st == 200 and {x["allowed"] for x in d["decisions"]} == {True, False} and any(x["mode"] == "ALWAYS_DENY" and not x["enforced"] for x in d["decisions"]), d)
st, e = call("POST", f"/v1/projects/{P}/policy:evaluate", {"image": REPO + "/web:v1"})
check("policy:evaluate dry-run extension", st == 200 and e["allowed"] is True, e)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
