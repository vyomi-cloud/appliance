"""API coverage: /api/providers/aws/sdk/<lang>[/snippet] and the
/api/aws/extras-config/<stub> GET/PUT round trip (S3 block-public-access)."""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:200]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


TOOLS = {"java": "S3Client", "go": "config.LoadDefaultConfig", "python": "boto3", "nodejs": "S3Client"}
for lang, marker in TOOLS.items():
    check(f"GET /api/providers/aws/sdk/{lang} describes the SDK and endpoint",
          lambda lang=lang: (lambda d: d["provider"] == "aws" and bool(d.get("endpoint")))(call("GET", f"/api/providers/aws/sdk/{lang}")))
    check(f"GET /api/providers/aws/sdk/{lang}/snippet returns a runnable snippet",
          lambda lang=lang, marker=marker: (lambda d: d["language"] == lang and marker in d["snippet"] and d["endpoint"] in d["snippet"])(call("GET", f"/api/providers/aws/sdk/{lang}/snippet")))

STUB = "s3/block-public"
cur = call("GET", f"/api/aws/extras-config/{STUB}")
check("GET extras-config returns values + schema fields", lambda: "block_public_acls" in cur["values"] and cur["schema"]["fields"])
flipped = {k: (not v) if isinstance(v, bool) else v for k, v in cur["values"].items()}
call("PUT", f"/api/aws/extras-config/{STUB}", flipped)
check("PUT extras-config persists and GET returns the edit",
      lambda: call("GET", f"/api/aws/extras-config/{STUB}")["values"]["block_public_acls"] == flipped["block_public_acls"])
call("PUT", f"/api/aws/extras-config/{STUB}", cur["values"])
check("extras-config restored", lambda: call("GET", f"/api/aws/extras-config/{STUB}")["values"] == cur["values"])
sys.exit(1 if failed else 0)
