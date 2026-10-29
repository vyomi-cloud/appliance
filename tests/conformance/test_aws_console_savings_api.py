"""Console-created IAM users, Secrets Manager secrets and KMS keys must count
in the space's cost_savings.resource_count, and secrets/KMS (billed by AWS) must
raise AWS savings; a secret lists its encryption key.  Prints PASS/FAIL lines."""
import json, os, sys, urllib.request, uuid

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
fails = 0


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def cs():
    sp = call("GET", "/api/spaces").get("active_space") or {}
    c = sp.get("cost_savings") or {}
    return c.get("resource_count", 0), (c.get("by_provider") or {}).get("aws", 0.0)


def check(ok, what):
    global fails
    print(("[PASS] " if ok else "[FAIL] ") + what)
    fails += 0 if ok else 1


for sp in call("GET", "/api/spaces").get("spaces", []):
    if sp.get("provider") == "aws":
        call("POST", f"/api/spaces/{sp.get('space_id') or sp.get('id')}/switch")
        break
sfx = uuid.uuid4().hex[:6]
for label, create, billed in (
    ("IAM user", lambda: call("POST", "/api/iam/users", {"user_name": "u" + sfx}), False),
    ("Secrets Manager secret", lambda: call("POST", "/api/aws/secrets", {"name": "s-" + sfx}), True),
    ("KMS key", lambda: call("POST", "/api/aws/kms/keys", {"name": "k-" + sfx}), True),
):
    n0, d0 = cs()
    create()
    n1, d1 = cs()
    check(n1 == n0 + 1, f"{label}: resource_count rises {n0} -> {n1}")
    if billed:
        check(d1 > d0, f"{label}: aws savings rise {d0} -> {d1}")
item = next((i for i in call("GET", "/api/aws/secrets")["items"] if i["name"] == "s-" + sfx), {})
check(item.get("kms_key_id") == "aws/secretsmanager", f"secret lists its encryption key ({item.get('kms_key_id')!r})")
sys.exit(1 if fails else 0)
