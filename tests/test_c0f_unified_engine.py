"""v4 C0f — the offline appliance serves AWS Lambda, Azure Key Vault, Azure Container
Registry and the Azure Service Bus REST data plane through the shared cores (the engines Nano
uses) over space-scoped, persisted state; ARM types the core ARM engine knows (ACR, AKS, …)
and resource groups are served by core/azure_arm_core.AzureArm over the offline ARM state.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway state file.
"""
from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0f-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_ELASTICMQ_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

SIG = ("AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/{svc}/aws4_request, "
       "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64)
SUB = "00000000-0000-0000-0000-000000000000"
KV = {"api-version": "7.4"}


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _zip(src: str, mod: str = "app.py") -> str:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(mod, src)
    return base64.b64encode(b.getvalue()).decode()


def _lam(client, method, path, body=None, headers=None, prefix=""):
    return client.request(method, prefix + "/2015-03-31/functions" + path,
                          content=json.dumps(body).encode() if body is not None else None,
                          headers={"Authorization": SIG.format(svc="lambda"), **(headers or {})})


def _ev(client, op, body):
    return client.post("/", content=json.dumps(body), headers={
        "Authorization": SIG.format(svc="events"), "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": f"AWSEvents.{op}"})


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _first_route(path: str, method: str):
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "query_string": b"", "headers": []}
    for r in server.app.routes:
        m, _ = r.matches(scope)
        if m == Match.FULL:
            return r
    return None


def test_route_precedence(client):
    for p, m in (("/2015-03-31/functions", "GET"), ("/2015-03-31/functions/f/invocations", "POST"),
                 ("/2015-03-31/layers/l/versions", "POST")):
        assert _first_route(p, m).endpoint.__module__ == "routes.aws_lambda_unified", (p, m)
    for p, m in (("/api/lambda/functions", "GET"), ("/api/lambda/functions/f/invoke", "POST"),
                 ("/api/lambda/layers", "POST")):
        assert _first_route(p, m).endpoint.__module__ == "routes.aws_lambda_unified", (p, m)
    for p in ("/azure-data/keyvault/v/secrets/x", "/azure-data/keyvault/v/keys/k/create"):
        assert _first_route(p, "POST").endpoint.__module__ == "routes.azure_dataplane_unified", p


def test_lambda_native_shape_real_runtime_and_console_share_one_store(client):
    fn = _u("c0f-fn")
    src = "import os, platform\ndef handler(event, context):\n    print('log', event['k'])\n" \
          "    return {'k': event['k'], 'env': os.environ['GREETING'], 'py': platform.system(), 'fn': context.function_name}\n"
    r = _lam(client, "POST", "", {"FunctionName": fn, "Runtime": "python3.12", "Handler": "app.handler",
                                  "Code": {"ZipFile": _zip(src)}, "Environment": {"Variables": {"GREETING": "hi"}}})
    assert r.status_code == 201, r.text
    listed = _lam(client, "GET", "", prefix="/_wire").json()["Functions"]   # the v4 console's call
    row = next(f for f in listed if f["FunctionName"] == fn)
    assert "Description" in row and row["Handler"] == "app.handler"
    inv = _lam(client, "POST", f"/{fn}/invocations", {"k": 4}, headers={"X-Amz-Log-Type": "Tail"})
    # the REAL runtime: os / platform imports work (the in-process sandbox forbids them)
    assert inv.status_code == 200 and inv.json() == {"k": 4, "env": "hi", "py": inv.json()["py"], "fn": fn}
    assert "log 4" in base64.b64decode(inv.headers["x-amz-log-result"]).decode()
    view = client.get(f"/api/lambda/functions/{fn}").json()         # classic console, same record
    assert view["function_name"] == fn and view["handler"] == "app.handler" and view["environment"] == {"GREETING": "hi"}
    c = client.post(f"/api/lambda/functions/{fn}/invoke", json={"payload": {"k": 9}}).json()
    assert c["status"] == "success" and c["payload"]["k"] == 9
    created = client.post("/api/lambda/functions", json={"function_name": _u("c0f-classic")}).json()
    got = _lam(client, "GET", f"/{created['function_name']}").json()
    assert got["Configuration"]["Handler"] == "lambda_function.lambda_handler"
    out = _lam(client, "POST", f"/{created['function_name']}/invocations", {"x": 1}).json()
    assert out["message"] == "Hello from Lambda" and out["received_event"] == {"x": 1}
    assert _lam(client, "DELETE", f"/{fn}").status_code == 204
    assert client.get(f"/api/lambda/functions/{fn}").status_code == 404


def test_eventbridge_and_internal_callers_reach_the_same_functions(client):
    fn = _u("c0f-target")
    _lam(client, "POST", "", {"FunctionName": fn, "Handler": "index.handler",
                              "Code": {"Source": "def handler(e, c):\n    return e.get('detail')\n"}})
    arn = f"arn:aws:lambda:us-east-1:123456789012:function:{fn}"
    rule = _u("c0f-rule")
    _ev(client, "PutRule", {"Name": rule, "EventPattern": json.dumps({"source": ["c0f.t"]})})
    _ev(client, "PutTargets", {"Rule": rule, "Targets": [{"Id": "l", "Arn": arn}]})
    assert _ev(client, "PutEvents", {"Entries": [{"Source": "c0f.t", "DetailType": "x", "Detail": "{}"}]}).status_code == 200
    n = 0
    for _ in range(40):
        n = _lam(client, "GET", f"/{fn}/invocations").json()["Metrics"]["Invocations"]
        if n:
            break
        time.sleep(0.1)
    assert n >= 1
    # server.py helpers (S3 notifications, SNS, API Gateway V2) delegate to the engine
    rec = server._lambda_invoke_function(fn, {"detail": {"a": 1}})
    assert rec["status"] == "success" and rec["response_payload"] == {"a": 1}
    assert server._lambda_resolve_function(arn)["function_name"] == fn
    with pytest.raises(Exception):   # a service source needs a resource-policy permission
        server._lambda_invoke_function(fn, {}, source_principal="s3.amazonaws.com", source_arn="arn:aws:s3:::b")


def test_lambda_state_is_durable_in_the_kernel_store(client):
    fn = _u("c0f-dur")
    _lam(client, "POST", "", {"FunctionName": fn, "Code": {"Source": "def handler(e, c):\n    return 1\n"}})
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    fns = {}
    for sp in (state.get("spaces") or {}).get("spaces", {}).values():
        fns.update(((sp.get("service_states") or {}).get("lambda") or {}).get("functions") or {})
    assert fns.get(fn, {}).get("source", "").startswith("def handler")


def test_upgrade_converts_pre_v4_functions_once(client):
    from core import app_context as ctx
    from core import wire_ingress
    st = wire_ingress.appliance_router().lam
    st.adopt()
    name = _u("legacy-fn")
    ctx.lambda_state.setdefault("functions", {})[name] = {
        "function_name": name, "function_arn": f"arn:aws:lambda:us-east-1:123456789012:function:{name}",
        "runtime": "python3.12", "handler": "lambda_function.lambda_handler", "description": "old",
        "code": "def lambda_handler(event, context):\n    return {'legacy': True}\n", "environment": {},
        "timeout": 3, "memory_size": 128, "permissions": [], "versions": [], "invocations": [],
        "created": "2026-10-01T00:00:00Z", "last_modified": "2026-10-01T00:00:00Z"}
    st._slot()["engine"].pop("adopted", None)      # as on a space that never ran v4
    got = _lam(client, "GET", f"/{name}").json()
    assert got["Configuration"]["Description"] == "old"
    assert _lam(client, "POST", f"/{name}/invocations", {}).json() == {"legacy": True}
    _lam(client, "DELETE", f"/{name}")
    st.adopt()
    assert _lam(client, "GET", f"/{name}").status_code == 404


def test_keyvault_root_and_vault_paths_share_one_space_scoped_store(client):
    name = _u("c0f-sec")
    r = client.put(f"/_wire/secrets/{name}", params=KV, json={"value": "v1"})     # the v4 console
    assert r.status_code == 200 and r.json()["id"].startswith("https://testserver/secrets/")
    g = client.get(f"/azure-data/keyvault/anyvault/secrets/{name}", params=KV)    # an SDK at vaultUri
    assert g.status_code == 200 and g.json()["value"] == "v1"
    k = client.post("/keys/c0fk/create", params=KV, json={"kty": "RSA", "key_size": 2048}).json()
    assert k["key"]["kid"].startswith("https://testserver/keys/c0fk/")
    pt = base64.urlsafe_b64encode(b"x").decode().rstrip("=")
    e = client.post("/keys/c0fk/encrypt", params=KV, json={"alg": "RSA-OAEP", "value": pt}).json()
    assert client.post("/keys/c0fk/decrypt", params=KV, json={"alg": "RSA-OAEP", "value": e["value"]}).json()["value"] == pt
    assert client.post("/certificates/c0fc/create", params=KV, json={"policy": {}}).status_code == 200
    # a plain S3 path named "secrets" (no api-version) is not Key Vault
    assert "Key Vault" not in client.get("/secrets/x").text
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    kv = {}
    for sp in (state.get("spaces") or {}).get("spaces", {}).values():
        if sp.get("provider") == "azure":
            kv = (sp.get("service_states") or {}).get("azure_azure_keyvault") or kv
    assert name in kv.get("secrets", {})


def test_acr_and_aks_arm_on_the_core_arm_engine(client):
    rg, reg, aks = _u("c0f-rg"), "c0facr" + uuid.uuid4().hex[:6], _u("c0f-aks")
    base = f"/subscriptions/{SUB}/resourceGroups/{rg}/providers"
    assert client.put(f"/subscriptions/{SUB}/resourcegroups/{rg}", params={"api-version": "2021-04-01"},
                      json={"location": "eastus", "tags": {"a": "1"}}).status_code == 200
    r = client.patch(f"/subscriptions/{SUB}/resourcegroups/{rg}", params={"api-version": "2021-04-01"}, json={"tags": {"b": "2"}})
    assert r.json()["tags"] == {"a": "1", "b": "2"}
    r = client.put(f"{base}/Microsoft.ContainerRegistry/registries/{reg}", params={"api-version": "2023-07-01"},
                   json={"location": "eastus", "sku": {"name": "Basic"}, "properties": {"adminUserEnabled": True}})
    assert r.status_code == 200 and r.headers.get("azure-asyncoperation")
    lst = client.get(f"/_wire/subscriptions/{SUB}/providers/Microsoft.ContainerRegistry/registries",
                     params={"api-version": "2023-07-01"}).json()["value"]
    assert any(x["name"] == reg for x in lst)
    creds = client.post(f"{base}/Microsoft.ContainerRegistry/registries/{reg}/listCredentials", params={"api-version": "2023-07-01"}).json()
    assert creds["username"] == reg and len(creds["passwords"]) == 2
    client.put(f"{base}/Microsoft.ContainerRegistry/registries/{reg}/webhooks/wh1", params={"api-version": "2023-07-01"}, json={"location": "eastus"})
    wh = client.get(f"{base}/Microsoft.ContainerRegistry/registries/{reg}/webhooks", params={"api-version": "2023-07-01"}).json()["value"]
    assert [w["name"] for w in wh] == ["wh1"]
    r = client.put(f"{base}/Microsoft.ContainerService/managedClusters/{aks}", params={"api-version": "2024-09-02-preview"},
                   json={"location": "eastus", "properties": {"dnsPrefix": "x", "agentPoolProfiles": [{"name": "np1", "count": 1, "mode": "System"}]}})
    assert r.status_code == 200, r.text
    pools = client.get(f"{base}/Microsoft.ContainerService/managedClusters/{aks}/agentPools", params={"api-version": "2024-09-02-preview"})
    assert pools.status_code == 200
    res = client.get(f"/subscriptions/{SUB}/resourceGroups/{rg}/resources", params={"api-version": "2021-04-01"}).json()["value"]
    assert {reg, aks} <= {x["name"] for x in res}
    assert client.delete(f"/subscriptions/{SUB}/resourcegroups/{rg}", params={"api-version": "2021-04-01"}).status_code == 200
    assert client.get(f"{base}/Microsoft.ContainerRegistry/registries/{reg}", params={"api-version": "2023-07-01"}).status_code == 404


def test_acr_and_servicebus_data_planes(client):
    repo = _u("c0frepo")
    r = client.put(f"/_wire/v2/{repo}/manifests/v1", content=b'{"schemaVersion":2}',
                   headers={"content-type": "application/vnd.oci.image.manifest.v1+json"})
    assert r.status_code == 201 and r.headers["docker-content-digest"].startswith("sha256:")
    assert repo in client.get("/v2/_catalog").json()["repositories"]
    assert client.get(f"/acr/v1/{repo}/_tags").json()["tags"][0]["name"] == "v1"
    q = _u("c0fq")
    assert client.put(f"/_wire/{q}", headers={"content-type": "application/atom+xml"}).status_code == 201
    assert client.post(f"/_wire/{q}/messages", content=b"hi", headers={"content-type": "text/plain", "brokerproperties": "{}"}).status_code == 201
    assert client.get(f"/_wire/{q}/messages").json()["messages"][0]["Body"] == "hi"
    # an unknown entity is never claimed (S3 / other handlers keep it)
    assert "messages" not in client.get(f"/{_u('nope')}/messages").text[:20]


def test_legacy_opt_out_restores_the_pre_v4_handlers(monkeypatch):
    from core import wire_ingress
    from routes import aws_lambda_unified as lu, azure_dataplane_unified as adu
    monkeypatch.setenv("VYOMI_UNIFIED_INGRESS_SERVICES", "s3,dynamodb,gcs")
    for svc in ("lambda", "azure_keyvault", "azure_acr", "azure_servicebus"):
        assert not wire_ingress.is_unified(svc)
    from fastapi import FastAPI
    app = FastAPI()
    lu.register(app)
    adu.register(app)
    assert not [r for r in app.routes if getattr(r, "endpoint", None)
                and r.endpoint.__module__ in (lu.__name__, adu.__name__)]
    assert server._lambda_unified() is None
    monkeypatch.setenv("VYOMI_LEGACY_WIRE", "1")
    monkeypatch.delenv("VYOMI_UNIFIED_INGRESS_SERVICES")
    assert not wire_ingress.is_unified("lambda")
    monkeypatch.delenv("VYOMI_LEGACY_WIRE")
    app2 = FastAPI()
    lu.register(app2)
    assert "/2015-03-31/{rest:path}" in {r.path for r in app2.routes}
