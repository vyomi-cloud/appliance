"""Azure OpenAI data-plane route: an anonymous call is refused 401 like real Azure (it used to be accepted); wrong key 401; key or bearer passes the gate.
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 tests/conformance/test_azure_openai_route_auth.py"""
import sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
from providers import azure_openai_routes as r

fails = []
def check(label, ok):
    print(("PASS: " if ok else "FAIL: ") + label)
    if not ok: fails.append(label)

REC = {"id": "acct", "_keys": {"key1": "K1", "key2": "K2"}, "properties": {}}
r._account = lambda name: REC if name == "acct" else None
r.ai_models_core.azure_openai_dispatch = lambda *a, **k: {"status": 200, "headers": {"content-type": "application/json"}, "body": b'{"ok":true}'}
app = FastAPI(); r.register(app); c = TestClient(app)
U = "/azure-data/openai/acct/openai/deployments/d/chat/completions"
B = {"messages": [{"role": "user", "content": "x"}]}

a = c.post(U, json=B)
check("no key and no bearer -> 401", a.status_code == 401)
check("401 uses Azure's missing-subscription-key wording", "missing subscription key" in a.text)
check("wrong key -> 401 invalid", c.post(U, json=B, headers={"api-key": "nope"}).status_code == 401)
check("valid key passes the gate", c.post(U, json=B, headers={"api-key": "K1"}).status_code == 200)
check("bearer token passes the gate", c.post(U, json=B, headers={"Authorization": "Bearer t"}).status_code == 200)
check("unknown account -> 404", c.post(U.replace("acct", "ghost"), json=B, headers={"api-key": "K1"}).status_code == 404)
sys.exit(1 if fails else 0)
