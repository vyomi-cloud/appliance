"""Cloud Functions HTTPS trigger URL /gcf/{project}/{location}/{function} must reach the handler, not FastAPI's param validation
(regression: `request: Request` was unresolved under `from __future__ import annotations`, so every call answered 422
"query.request Field required"; the API Gateway data plane forwards here, so offline-post-create-gcp-apigateway-invoke failed).
Run: VYOMI_BASE_URL=http://localhost:9000 python3 tests/conformance/test_gcp_gcf_trigger_url_api.py"""
import json, os, sys, urllib.error, urllib.request

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
fails = 0


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(name, ok, extra=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)}")
    fails += not ok


s, b = call("GET", "/gcf/vyomi-project/us-central1/no-such-fn-xyz")
check("unknown function -> 404 NOT_FOUND (not 422)", s == 404 and b"NOT_FOUND" in b, f"{s} {b[:150]}")
fn = "gcfurl" + os.urandom(3).hex()
s, _ = call("POST", "/api/gcp/cloudfunctions/v2/projects/vyomi-project/locations/us-central1/functions",
            {"name": fn, "runtime": "python312", "entryPoint": "h", "code": 'def h(request):\n    return "gcf-ok"\n', "httpsTrigger": {}})
check("create function", s < 300, s)
s, b = call("GET", f"/gcf/vyomi-project/us-central1/{fn}")
check("trigger URL runs the handler and returns its body", s == 200 and b"gcf-ok" in b, f"{s} {b[:150]}")
sys.exit(1 if fails else 0)
