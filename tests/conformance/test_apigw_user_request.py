"""API Gateway v1 local invoke URL + v2 ApiEndpoint, through the SAME AwsWireRouter the Nano relay uses.

  /restapis/<id>/<stage>/_user_request_/<path>  runs the deployed API (MOCK + Lambda proxy);
  a v2 ApiEndpoint is the origin's path-style /apigw/<id> form, not a name nothing resolves.
Run: python3 tests/conformance/test_apigw_user_request.py
"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core.aws_wire_router import AwsWireRouter

H = {"host": "localhost:9421"}


def _check(name, cond, extra=""):
    if not cond:
        raise AssertionError(f"{name} {extra}")
    print(f"  ok  {name}")


def call(r, method, path, body=None):
    out = r.handle(method, path, {}, dict(H), json.dumps(body).encode() if body is not None else b"")
    b = out["body"]
    return out["status"], (json.loads(b) if b[:1] in (b"{", b"[") else b)


r = AwsWireRouter()
s, api = call(r, "POST", "/restapis", {"name": "t"})
aid = api["id"]
s, res = call(r, "GET", f"/restapis/{aid}/resources")
root = res["item"][0]["id"]
s, m = call(r, "POST", f"/restapis/{aid}/resources/{root}", {"pathPart": "mock"})
call(r, "PUT", f"/restapis/{aid}/resources/{m['id']}/methods/GET", {"authorizationType": "NONE"})
call(r, "PUT", f"/restapis/{aid}/resources/{m['id']}/methods/GET/integration", {"type": "MOCK", "mockBody": "mock-ok", "mockStatus": 200})
call(r, "POST", f"/restapis/{aid}/deployments", {"stageName": "prod"})
s, b = call(r, "GET", f"/restapis/{aid}/prod/_user_request_/mock")
_check("MOCK integration served at /restapis/<id>/<stage>/_user_request_/<path>", s == 200 and b == b"mock-ok", f"{s} {b}")
s, b = call(r, "GET", f"/restapis/{aid}/prod/_user_request_/nope")
_check("unknown path is a 403 Missing Authentication Token like AWS", s == 403, f"{s}")
s, v2 = call(r, "POST", "/v2/apis", {"name": "v", "protocolType": "HTTP"})
_check("v2 ApiEndpoint is on the origin the client reached", v2["apiEndpoint"] == f"http://localhost:9421/apigw/{v2['apiId']}", v2["apiEndpoint"])
print("all passed")
