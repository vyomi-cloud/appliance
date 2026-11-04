"""API Gateway v1 v4-console conformance — the additions made for the v4 console:
GetMethod/DeleteMethod/DeleteIntegration/GetResource/DeleteResource, TestInvokeMethod
(the console's "Test" tab — exercises a method's integration with no deployment
needed), Stage as a first-class resource (separate from Deployment), Account
settings, ApiKey CRUD, UsagePlan + UsagePlanKey (create + associate), and
ClientCertificate CRUD.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_apigateway_console_v4_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json
import types

try:
    from core import apigateway_core as gw, lambda_core as lam
except ImportError:  # pragma: no cover - Pyodide flat layout
    import apigateway_core as gw  # type: ignore
    import lambda_core as lam  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    s = types.SimpleNamespace()

    def call(m, p, b=None):
        from urllib.parse import parse_qsl
        body = b"" if b is None else (b if isinstance(b, bytes) else json.dumps(b).encode())
        path, _, qs = p.partition("?")
        return gw.dispatch(s, m, path, dict(parse_qsl(qs)), {}, body)

    # 1. RestApi CRUD + patch.
    api = json.loads(call("POST", "/restapis", {"name": "v4api", "endpointConfiguration": {"types": ["REGIONAL"]}}).body)
    api_id, root = api["id"], api["rootResourceId"]
    _check("endpointConfiguration stored", api["endpointConfiguration"]["types"] == ["REGIONAL"])
    upd = call("PATCH", f"/restapis/{api_id}", {"patchOperations": [{"op": "replace", "path": "/description", "value": "v4"}]})
    _check("UpdateRestApi patches description", json.loads(upd.body)["description"] == "v4")
    _check("GetRestApi", json.loads(call("GET", f"/restapis/{api_id}").body)["id"] == api_id)

    # 2. Resource: create/get/delete, including child-blocks-delete.
    r1 = json.loads(call("POST", f"/restapis/{api_id}/resources/{root}", {"pathPart": "items"}).body)
    _check("GetResource", json.loads(call("GET", f"/restapis/{api_id}/resources/{r1['id']}").body)["path"] == "/items")
    r2 = json.loads(call("POST", f"/restapis/{api_id}/resources/{r1['id']}", {"pathPart": "{id}"}).body)
    blocked = call("DELETE", f"/restapis/{api_id}/resources/{r1['id']}")
    _check("cannot delete a resource with children", blocked.body.get("__type") == "BadRequestException" if isinstance(blocked.body, dict) else json.loads(blocked.body)["__type"] == "BadRequestException")
    call("DELETE", f"/restapis/{api_id}/resources/{r2['id']}")
    ok = call("DELETE", f"/restapis/{api_id}/resources/{r1['id']}")
    _check("DeleteResource 202 once childless", ok.status == 202)

    # 3. Method / Integration: GET + DELETE, apiKeyRequired.
    ping = json.loads(call("POST", f"/restapis/{api_id}/resources/{root}", {"pathPart": "ping"}).body)
    call("PUT", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET", {"authorizationType": "NONE", "apiKeyRequired": True})
    m = json.loads(call("GET", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET").body)
    _check("GetMethod reflects apiKeyRequired", m["apiKeyRequired"] is True)
    call("PUT", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET/integration",
         {"type": "MOCK", "mockStatus": 200, "mockBody": "pong"})
    _check("GetIntegration", json.loads(call("GET", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET/integration").body)["type"] == "MOCK")
    call("DELETE", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET/integration")
    _check("DeleteIntegration clears it", call("GET", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET/integration").status == 404)
    call("PUT", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET/integration",
         {"type": "MOCK", "mockStatus": 200, "mockBody": "pong"})

    # 4. TestInvokeMethod — works with NO deployment at all (the console's "Test" tab).
    test = json.loads(call("POST", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET", {"pathWithQueryString": "/ping"}).body)
    _check("TestInvokeMethod MOCK (undeployed)", test["status"] == 200 and test["body"] == "pong" and "Mock integration" in test["log"])

    src = ("def handler(event, context):\n"
           "    return {'statusCode': 201, 'body': 'hi ' + (event.get('pathParameters') or {}).get('id', '?')}\n")
    lam.dispatch(s, "POST", "/2015-03-31/functions", {}, {}, json.dumps({"FunctionName": "v4fn", "Code": {"Source": src}}).encode())
    uid = json.loads(call("POST", f"/restapis/{api_id}/resources/{root}", {"pathPart": "{id}"}).body)
    call("PUT", f"/restapis/{api_id}/resources/{uid['id']}/methods/GET", {"authorizationType": "NONE"})
    call("PUT", f"/restapis/{api_id}/resources/{uid['id']}/methods/GET/integration",
         {"type": "AWS_PROXY", "uri": "arn:aws:lambda:us-east-1:123:function:v4fn/invocations"})
    test2 = json.loads(call("POST", f"/restapis/{api_id}/resources/{uid['id']}/methods/GET", {"pathWithQueryString": "/42"}).body)
    _check("TestInvokeMethod AWS_PROXY runs real Lambda", test2["status"] == 201 and test2["body"] == "hi 42")
    call("DELETE", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET")
    _check("DeleteMethod", call("GET", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET").status == 404)

    # 5. Deployment + Stage as separate resources; invoke keys off the Stage.
    dep = json.loads(call("POST", f"/restapis/{api_id}/deployments", {"stageName": "prod", "description": "d1"}).body)
    _check("CreateDeployment", bool(dep["id"]))
    _check("GetDeployment", json.loads(call("GET", f"/restapis/{api_id}/deployments/{dep['id']}").body)["description"] == "d1")
    stages = json.loads(call("GET", f"/restapis/{api_id}/stages").body)["item"]
    _check("deploying with stageName auto-creates the Stage", any(st["stageName"] == "prod" for st in stages))
    r = gw.invoke(s, api_id, "prod", "GET", "/42")
    _check("invoke against the auto-created stage works", r.status == 201 and r.body == b"hi 42")

    dep2 = json.loads(call("POST", f"/restapis/{api_id}/deployments", {}).body)
    stg = json.loads(call("POST", f"/restapis/{api_id}/stages",
                          {"stageName": "staging", "deploymentId": dep2["id"], "variables": {"env": "stg"}}).body)
    _check("CreateStage stores variables + invoke URL", stg["variables"]["env"] == "stg" and stg["stageName"] in stg["invokeUrl"])
    dup = call("POST", f"/restapis/{api_id}/stages", {"stageName": "staging", "deploymentId": dep2["id"]})
    _check("duplicate stage name rejected", dup.status == 409)
    upd_st = json.loads(call("PATCH", f"/restapis/{api_id}/stages/staging",
                             {"patchOperations": [{"op": "replace", "path": "/variables/env", "value": "stage2"},
                                                   {"op": "replace", "path": "/tracingEnabled", "value": "true"}]}).body)
    _check("UpdateStage patches a stage variable + tracing flag", upd_st["variables"]["env"] == "stage2" and upd_st["tracingEnabled"] is True)
    call("DELETE", f"/restapis/{api_id}/stages/staging")
    _check("DeleteStage", call("GET", f"/restapis/{api_id}/stages/staging").status == 404)
    _check("invoke against a deleted stage → 403", gw.invoke(s, api_id, "staging", "GET", "/42").status == 403)

    # 6. Account settings.
    acc = json.loads(call("GET", "/account").body)
    _check("GetAccount defaults", acc["throttleSettings"]["burstLimit"] == 5000)
    acc2 = json.loads(call("PATCH", "/account",
                           {"patchOperations": [{"op": "replace", "path": "/cloudwatchRoleArn", "value": "arn:aws:iam::000000000000:role/apigw-logs"}]}).body)
    _check("UpdateAccount sets cloudwatchRoleArn", acc2["cloudwatchRoleArn"].endswith("apigw-logs"))

    # 7. ApiKey CRUD.
    key = json.loads(call("POST", "/apikeys", {"name": "v4key", "description": "d"}).body)
    _check("CreateApiKey generates a value", len(key["value"]) >= 20)
    listed = json.loads(call("GET", "/apikeys?includeValues=true").body)["item"]
    _check("GetApiKeys includeValues", any(k["id"] == key["id"] and "value" in k for k in listed))
    hidden = json.loads(call("GET", "/apikeys").body)["item"]
    _check("GetApiKeys omits value by default", all("value" not in k for k in hidden))
    call("PATCH", f"/apikeys/{key['id']}", {"patchOperations": [{"op": "replace", "path": "/enabled", "value": "false"}]})
    _check("UpdateApiKey disables it", json.loads(call("GET", f"/apikeys/{key['id']}").body)["enabled"] is False)

    # 8. UsagePlan + UsagePlanKey (create + associate) + apiStages patch.
    plan = json.loads(call("POST", "/usageplans",
                           {"name": "v4plan", "throttle": {"rateLimit": 100.0, "burstLimit": 20}, "quota": {"limit": 1000, "period": "MONTH"}}).body)
    _check("CreateUsagePlan stores throttle+quota", plan["throttle"]["burstLimit"] == 20 and plan["quota"]["period"] == "MONTH")
    call("PATCH", f"/usageplans/{plan['id']}", {"patchOperations": [{"op": "add", "path": "/apiStages", "value": f"{api_id}:prod"}]})
    plan2 = json.loads(call("GET", f"/usageplans/{plan['id']}").body)
    _check("UpdateUsagePlan associates an API stage", {"apiId": api_id, "stage": "prod"} in plan2["apiStages"])
    assoc = json.loads(call("POST", f"/usageplans/{plan['id']}/keys", {"keyId": key["id"], "keyType": "API_KEY"}).body)
    _check("CreateUsagePlanKey associates the key", assoc["id"] == key["id"])
    pk = json.loads(call("GET", f"/usageplans/{plan['id']}/keys").body)["item"]
    _check("GetUsagePlanKeys lists it", any(k["id"] == key["id"] for k in pk))
    call("DELETE", f"/usageplans/{plan['id']}/keys/{key['id']}")
    _check("DeleteUsagePlanKey removes the association", call("GET", f"/usageplans/{plan['id']}/keys").body and
           json.loads(call("GET", f"/usageplans/{plan['id']}/keys").body)["item"] == [])
    call("DELETE", f"/usageplans/{plan['id']}")
    _check("DeleteUsagePlan", call("GET", f"/usageplans/{plan['id']}").status == 404)

    # 9. ClientCertificate CRUD.
    cert = json.loads(call("POST", "/clientcertificates", {"description": "v4 cert"}).body)
    _check("GenerateClientCertificate produces a PEM + expiration", "BEGIN CERTIFICATE" in cert["pemEncodedCertificate"] and cert["expirationDate"])
    call("PATCH", f"/clientcertificates/{cert['clientCertificateId']}",
         {"patchOperations": [{"op": "replace", "path": "/description", "value": "renamed"}]})
    _check("UpdateClientCertificate", json.loads(call("GET", f"/clientcertificates/{cert['clientCertificateId']}").body)["description"] == "renamed")
    call("DELETE", f"/clientcertificates/{cert['clientCertificateId']}")
    _check("DeleteClientCertificate", call("GET", f"/clientcertificates/{cert['clientCertificateId']}").status == 404)

    print("\nRESULT: PASS — API Gateway v4-console additions conform (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
