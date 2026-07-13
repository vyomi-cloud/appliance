"""API Gateway data-plane conformance (v2.7.0, PARITY P4 #15) — host + Pyodide.

Builds a REST API (resources + methods + integrations + deployment) and INVOKES it:
  - a MOCK integration returns its configured response, and
  - an AWS_PROXY integration runs a real `lambda_core` function (with path params +
    body) and maps its {statusCode, headers, body} back to HTTP.
This is the API-Gateway → Lambda synergy: a genuine serverless HTTP API in-core.
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


def run(store=None):
    s = store or types.SimpleNamespace()   # one store holds APIs + Lambda functions

    def call(m, p, b=b""):
        return gw.dispatch(s, m, p, {}, {}, b if isinstance(b, bytes) else json.dumps(b).encode())

    api = json.loads(call("POST", "/restapis", {"name": "myapi"}).body)
    api_id, root = api["id"], api["rootResourceId"]
    _check("CreateRestApi (auto root resource)", bool(api_id) and bool(root))

    # MOCK: GET /ping
    ping = json.loads(call("POST", f"/restapis/{api_id}/resources/{root}", {"pathPart": "ping"}).body)
    call("PUT", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET", {"authorizationType": "NONE"})
    call("PUT", f"/restapis/{api_id}/resources/{ping['id']}/methods/GET/integration",
         {"type": "MOCK", "mockStatus": 200, "mockBody": "pong"})

    # AWS_PROXY (Lambda): POST /users/{id}
    users = json.loads(call("POST", f"/restapis/{api_id}/resources/{root}", {"pathPart": "users"}).body)
    uid = json.loads(call("POST", f"/restapis/{api_id}/resources/{users['id']}", {"pathPart": "{id}"}).body)
    src = ("import json\n"
           "def handler(event, context):\n"
           "    uid = (event.get('pathParameters') or {}).get('id', '?')\n"
           "    data = json.loads(event.get('body') or '{}')\n"
           "    return {'statusCode': 201, 'headers': {'X-Handled-By': 'lambda'},\n"
           "            'body': json.dumps({'user': uid, 'name': data.get('name'), 'method': event['httpMethod']})}\n")
    lam.dispatch(s, "POST", "/2015-03-31/functions", {}, {},
                 json.dumps({"FunctionName": "userFn", "Code": {"Source": src}}).encode())
    call("PUT", f"/restapis/{api_id}/resources/{uid['id']}/methods/POST", {"authorizationType": "NONE"})
    call("PUT", f"/restapis/{api_id}/resources/{uid['id']}/methods/POST/integration",
         {"type": "AWS_PROXY", "uri": "arn:aws:lambda:us-east-1:123:function:userFn/invocations"})

    call("POST", f"/restapis/{api_id}/deployments", {"stageName": "prod"})

    r = gw.invoke(s, api_id, "prod", "GET", "/ping")
    _check("invoke MOCK → 200 pong", r.status == 200 and r.body == b"pong")

    r = gw.invoke(s, api_id, "prod", "POST", "/users/42", body=json.dumps({"name": "alice"}).encode())
    out = json.loads(r.body)
    _check("invoke Lambda-proxy → 201, path params + body flow through",
           r.status == 201 and out == {"user": "42", "name": "alice", "method": "POST"}
           and r.headers.get("X-Handled-By") == "lambda")

    _check("undeployed stage → 403", gw.invoke(s, api_id, "staging", "GET", "/ping").status == 403)
    _check("unknown route → 403", gw.invoke(s, api_id, "prod", "GET", "/nope").status == 403)

    print("\nAPI Gateway data-plane conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
