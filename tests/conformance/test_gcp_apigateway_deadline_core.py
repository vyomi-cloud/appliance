"""API Gateway: negative x-google-backend deadlines in an OpenAPI 2.0 config are NOT rejected
(Nov 4 2026 release note withdrew the deprecation; negative == default deadline, same as 0)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core.gcp_console_tabs import openapi_routes  # noqa: E402

failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def doc(deadline):
    return {"swagger": "2.0", "info": {"title": "t", "version": "1"},
            "x-google-backend": {"address": "https://b.example.com", "deadline": deadline},
            "paths": {"/a": {"get": {"operationId": "a", "x-google-backend": {
                "address": "https://b.example.com", "deadline": deadline}, "responses": {"200": {"description": "ok"}}}}}}


for d in (-1, -30.5, 0, 15):
    try:
        r = openapi_routes(doc(d))
        check("deadline %s accepted" % d, len(r) == 1 and r[0]["operationId"] == "a")
    except Exception as e:
        check("deadline %s accepted (%s)" % (d, e), False)
sys.exit(1 if failed else 0)
