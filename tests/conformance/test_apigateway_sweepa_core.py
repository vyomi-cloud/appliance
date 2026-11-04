"""API Gateway sweep A: stage variables in the integration + Lambda event, and canary release
deployments (percentTraffic split, stageVariableOverrides, promote, delete).

Run: PYTHONPATH=. python3 tests/conformance/test_apigateway_sweepa_core.py
"""
import json
import types

try:
    from core import apigateway_core as gw, lambda_core as lam
except ImportError:  # pragma: no cover
    import apigateway_core as gw  # type: ignore
    import lambda_core as lam  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run():
    s = types.SimpleNamespace()

    def call(m, p, b=b""):
        return gw.dispatch(s, m, p, {}, {}, b if isinstance(b, bytes) else json.dumps(b).encode())

    for name, tag in (("fnStable", "stable"), ("fnCanary", "canary")):
        src = ("import json\n"
               "def handler(event, context):\n"
               f"    return {{'statusCode': 200, 'body': json.dumps({{'fn': '{tag}', 'sv': event.get('stageVariables'), 'dep': event['requestContext']['deploymentId']}})}}\n")
        lam.dispatch(s, "POST", "/2015-03-31/functions", {}, {}, json.dumps({"FunctionName": name, "Code": {"Source": src}}).encode())
    api = json.loads(call("POST", "/restapis", {"name": "canapi"}).body)
    aid, root = api["id"], api["rootResourceId"]
    res = json.loads(call("POST", f"/restapis/{aid}/resources/{root}", {"pathPart": "hi"}).body)
    call("PUT", f"/restapis/{aid}/resources/{res['id']}/methods/GET", {"authorizationType": "NONE"})
    call("PUT", f"/restapis/{aid}/resources/{res['id']}/methods/GET/integration",
         {"type": "AWS_PROXY", "uri": "arn:aws:lambda:us-east-1:123456789012:function:${stageVariables.fn}/invocations"})
    d1 = json.loads(call("POST", f"/restapis/{aid}/deployments", {"stageName": "prod", "variables": {"fn": "fnStable", "color": "blue"}}).body)["id"]
    out = json.loads(gw.invoke(s, aid, "prod", "GET", "/hi", lambda_store=s).body)
    _check("stage variable substituted into the Lambda integration URI", out["fn"] == "stable")
    _check("stageVariables + deploymentId reach the Lambda event", out["sv"]["color"] == "blue" and out["dep"] == d1)

    d2 = json.loads(call("POST", f"/restapis/{aid}/deployments",
                         {"stageName": "prod", "canarySettings": {"percentTraffic": 100, "stageVariableOverrides": {"fn": "fnCanary"}}}).body)["id"]
    st = json.loads(call("GET", f"/restapis/{aid}/stages/prod").body)
    _check("stage keeps its live deployment, canary points at the new one", st["deploymentId"] == d1 and st["canarySettings"]["deploymentId"] == d2)
    _check("canary settings returned", st["canarySettings"]["percentTraffic"] == 100.0 and st["canarySettings"]["stageVariableOverrides"] == {"fn": "fnCanary"})
    r = gw.invoke(s, aid, "prod", "GET", "/hi", lambda_store=s)
    out = json.loads(r.body)
    _check("100% canary: request sees the override + canary deployment", out["fn"] == "canary" and out["dep"] == d2 and r.headers.get("x-amzn-apigw-canary") == "true")

    call("PATCH", f"/restapis/{aid}/stages/prod", {"patchOperations": [{"op": "replace", "path": "/canarySettings/percentTraffic", "value": "0"}]})
    out = json.loads(gw.invoke(s, aid, "prod", "GET", "/hi", lambda_store=s).body)
    _check("0% canary: all traffic on the stable deployment", out["fn"] == "stable" and out["dep"] == d1)

    call("PATCH", f"/restapis/{aid}/stages/prod", {"patchOperations": [{"op": "replace", "path": "/canarySettings/percentTraffic", "value": "50"}]})
    hits = sum(1 for _ in range(200) if json.loads(gw.invoke(s, aid, "prod", "GET", "/hi", lambda_store=s).body)["fn"] == "canary")
    _check("50% canary splits traffic (both sides hit)", 40 < hits < 160)
    bad = call("PATCH", f"/restapis/{aid}/stages/prod", {"patchOperations": [{"op": "replace", "path": "/canarySettings/percentTraffic", "value": "150"}]})
    _check("percentTraffic > 100 rejected", bad.status == 400)

    call("PATCH", f"/restapis/{aid}/stages/prod", {"patchOperations": [
        {"op": "replace", "path": "/deploymentId", "value": d2}, {"op": "remove", "path": "/canarySettings"},
        {"op": "replace", "path": "/variables/fn", "value": "fnCanary"}]})
    st = json.loads(call("GET", f"/restapis/{aid}/stages/prod").body)
    _check("promote: stage now on the canary deployment, canary removed", st["deploymentId"] == d2 and not st.get("canarySettings"))
    _check("after promote all traffic uses the promoted variables", json.loads(gw.invoke(s, aid, "prod", "GET", "/hi", lambda_store=s).body)["fn"] == "canary")

    d3 = json.loads(call("POST", f"/restapis/{aid}/deployments", {"stageName": "prod", "canarySettings": {"percentTraffic": 10}}).body)["id"]
    call("POST", f"/restapis/{aid}/deployments", {"stageName": "prod"})
    st = json.loads(call("GET", f"/restapis/{aid}/stages/prod").body)
    _check("a plain deployment to the stage clears the canary", not st.get("canarySettings") and st["deploymentId"] != d3)
    print("\nRESULT: PASS - API Gateway sweep A")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
