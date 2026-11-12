"""API Gateway API v1 core (core/gcp_apigateway_core): apis / api configs (OpenAPI 2.0) / gateways over the router, incl. validation and in-use refusals.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_apigateway_core.py
"""
import base64
import json

from core.aws_wire_router import AwsWireRouter

P = "/v1/projects/nano-project/locations"
rt = AwsWireRouter()
fails = 0


def call(m, p, b=None, q=None):
    o = rt.handle(m, p, q or {}, {"content-type": "application/json"}, json.dumps(b).encode() if b is not None else b"")
    return o["status"], json.loads(o["body"] or b"{}")


def check(name, ok, extra=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else " :: " + str(extra)[:200]))
    fails += 0 if ok else 1


SPEC = 'swagger: "2.0"\ninfo:\n  title: t\n  version: "1"\npaths:\n  /a:\n    get:\n      operationId: a\n      x-google-backend:\n        address: https://example.com\n      responses:\n        "200":\n          description: ok\n  /b:\n    post:\n      operationId: b\n      x-google-backend:\n        address: https://example.com\n      responses:\n        "200":\n          description: ok\n'
doc = lambda t: {"openapiDocuments": [{"document": {"path": "o.yaml", "contents": base64.b64encode(t.encode()).decode()}}]}

st, r = call("POST", P + "/global/apis", {"displayName": "A"}, {"apiId": "demo-api"})
check("create api (LRO done)", st == 200 and r.get("done") and r["response"]["state"] == "ACTIVE", r)
check("api id validated", call("POST", P + "/global/apis", {}, {"apiId": "Bad_ID"})[0] == 400)
check("duplicate api -> 409", call("POST", P + "/global/apis", {}, {"apiId": "demo-api"})[0] == 409)
check("list apis", [a["name"].split("/")[-1] for a in call("GET", P + "/global/apis")[1]["apis"]] == ["demo-api"])
check("config on missing api -> 404", call("POST", P + "/global/apis/nope/configs", doc(SPEC), {"apiConfigId": "c1"})[0] == 404)
check("config without documents -> 400", call("POST", P + "/global/apis/demo-api/configs", {}, {"apiConfigId": "c1"})[0] == 400)
st, r = call("POST", P + "/global/apis/demo-api/configs", doc("swagger: '3.0'"), {"apiConfigId": "bad"})
check("non-2.0 document refused with a sentence", st == 400 and "OpenAPI 2.0" in r["error"]["message"], r)
st, r = call("POST", P + "/global/apis/demo-api/configs", doc(SPEC.replace("operationId: b", "operationId: a")), {"apiConfigId": "dup"})
check("duplicate operationId refused", st == 400 and "duplicate operationId" in r["error"]["message"], r)
st, r = call("POST", P + "/global/apis/demo-api/configs", doc(SPEC.replace("https://example.com", "http://example.com")), {"apiConfigId": "http"})
check("non-https backend refused", st == 400 and "https" in r["error"]["message"], r)
st, r = call("POST", P + "/global/apis/demo-api/configs", doc(SPEC), {"apiConfigId": "c1"})
check("create config from base64 YAML", st == 200 and r["response"]["state"] == "ACTIVE", r)
st, r = call("GET", P + "/global/apis/demo-api/configs/c1")
check("get config derives its 2 routes", st == 200 and sorted(x["path"] for x in r["routes"]) == ["/a", "/b"], r)
check("list configs hides the document by default", "openapiDocuments" not in call("GET", P + "/global/apis/demo-api/configs")[1]["apiConfigs"][0])
check("api with configs can't be deleted", call("DELETE", P + "/global/apis/demo-api")[0] == 400)
CFG = "projects/nano-project/locations/global/apis/demo-api/configs/c1"
check("gateway on missing config -> 404", call("POST", P + "/us-central1/gateways", {"apiConfig": CFG + "x"}, {"gatewayId": "g1"})[0] == 404)
check("gateway region validated", call("POST", P + "/mars-1/gateways", {"apiConfig": CFG}, {"gatewayId": "g1"})[0] == 400)
st, r = call("POST", P + "/us-central1/gateways", {"apiConfig": CFG}, {"gatewayId": "g1"})
check("create gateway: hostname .uc.gateway.dev", st == 200 and r["response"]["defaultHostname"].endswith(".uc.gateway.dev"), r)
check("list gateways across regions (locations/-)", len(call("GET", P + "/-/gateways")[1]["gateways"]) == 1)
check("config in use by a gateway can't be deleted", call("DELETE", P + "/global/apis/demo-api/configs/c1")[0] == 400)
call("POST", P + "/global/apis/demo-api/configs", doc(SPEC), {"apiConfigId": "c2"})
st, r = call("PATCH", P + "/us-central1/gateways/g1", {"apiConfig": CFG.replace("c1", "c2")}, {"updateMask": "apiConfig"})
check("patch gateway to another config", st == 200 and call("GET", P + "/us-central1/gateways/g1")[1]["apiConfig"].endswith("/c2"), r)
check("operation polling answers done", call("GET", r["name"].replace("/v1/", "/v1/") if r["name"].startswith("/") else "/v1/" + r["name"])[1].get("done") is True)
check("delete gateway", call("DELETE", P + "/us-central1/gateways/g1")[0] == 200 and call("GET", P + "/us-central1/gateways/g1")[0] == 404)
check("delete configs then api", call("DELETE", P + "/global/apis/demo-api/configs/c1")[0] == 200 and call("DELETE", P + "/global/apis/demo-api/configs/c2")[0] == 200 and call("DELETE", P + "/global/apis/demo-api")[0] == 200)
print("\nRESULT: " + ("PASS" if not fails else "FAIL") + f" — API Gateway core ({fails} failed)")
raise SystemExit(1 if fails else 0)
