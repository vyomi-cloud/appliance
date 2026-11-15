"""Agent Engine (core/gcp_agentengine_core) must answer an unimplemented reasoningEngines sub-resource with a modeled 404, never an
unhandled 500. Found by the Phase 0 GCP probe (tools/ai_probe/gcp_probe.py): 62 requests (runtimeRevisions, sandboxEnvironmentTemplates, ...)
reached the engine, missed its path regex and crashed with AttributeError ('NoneType' has no attribute 'groups').

Run: PYTHONPATH=. python3 tests/conformance/test_gcp_agentengine_unmatched_path.py
"""
import json
import sys

from core.aws_wire_router import AwsWireRouter

AwsWireRouter.STRICT_GCP_PROJECT = False
r = AwsWireRouter()
P = "/v1/projects/demo/locations/us-central1/reasoningEngines/e1"
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(("  ok  " if cond else "  FAIL ") + name + ("" if cond else f" {str(extra)[:300]}"))


def call(method, path, body=b"{}"):
    o = r.handle(method, path, {}, {"content-type": "application/json"}, body)
    try:
        return o["status"], json.loads(o["body"] or b"{}")
    except Exception:
        return o["status"], {"raw": o["body"]}


for method, path in [("POST", P + "/runtimeRevisions/rev1:query"), ("GET", P + "/sandboxEnvironmentTemplates"),
                     ("POST", P + "/sandboxEnvironmentTemplates"), ("DELETE", P + "/sandboxEnvironmentTemplates/t1")]:
    st, b = call(method, path)
    check(f"{method} .../{path.split('/reasoningEngines/e1/')[1]} -> modeled 404, not 500", st == 404 and b.get("error", {}).get("status") == "NOT_FOUND", (st, b))
check("a real reasoningEngines list still works", call("GET", "/v1/projects/demo/locations/us-central1/reasoningEngines", b"")[0] == 200)
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
