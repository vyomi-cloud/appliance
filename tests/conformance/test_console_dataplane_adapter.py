"""Console data-plane integration conformance (v2.9.0).

Proves the SPA/console dispatch chain (registry → provider handlers →
dataplane_adapter → the REAL v2.5.0–2.8.0 cores) drives every net-new service —
NOT the generic name-only catalog CRUD it used before. Includes the cross-service
flows the console must preserve: EventBridge→SQS delivery and API-Gateway→Lambda.

Runs on host (repo layout). The console backend (nano-boot.js) loads the same
providers package in Pyodide.
"""
import sys
import os

# repo root on path so `wasm.providers` + `core` resolve (mirrors the Pyodide FS).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from wasm.backends.store import Backends       # noqa: E402
from wasm import providers as P                 # noqa: E402


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run():
    B = Backends()

    def d(prov, svc, op, params=None):
        return P.dispatch(B, prov, svc, op, params=params or {})

    # ── Lambda: create + sandboxed invoke ─────────────────────────────────
    _check("aws/lambda/CreateFunction",
           d("aws", "lambda", "CreateFunction",
             {"name": "greet", "code": "def handler(e,c):\n    return {'n': e.get('n',0)+1}"})["ok"])
    _check("aws/lambda/Invoke runs the real function",
           d("aws", "lambda", "Invoke", {"name": "greet", "payload": {"n": 41}})["result"] == {"n": 42})

    # ── API Gateway: MOCK endpoint + invoke ───────────────────────────────
    d("aws", "apigateway", "CreateApi", {"name": "api1", "path": "ping", "method": "GET", "mockBody": "pong"})
    aid = d("aws", "apigateway", "ListApis")["apis"][0]["id"]
    _check("aws/apigateway MOCK invoke → pong",
           d("aws", "apigateway", "Invoke", {"id": aid, "stage": "prod", "method": "GET", "path": "/ping"})["body"] == "pong")

    # ── API Gateway → Lambda proxy (cross-service) ───────────────────────
    d("aws", "lambda", "CreateFunction",
      {"name": "proxyFn", "code": "import json\ndef handler(e,c):\n    return {'statusCode':201,'body':json.dumps({'hi':json.loads(e.get('body') or '{}').get('name','?')})}"})
    d("aws", "apigateway", "CreateApi", {"name": "api2", "path": "g", "method": "POST", "lambdaTarget": "proxyFn"})
    lid = [a for a in d("aws", "apigateway", "ListApis")["apis"] if a["name"] == "api2"][0]["id"]
    import json
    r = d("aws", "apigateway", "Invoke", {"id": lid, "stage": "prod", "method": "POST", "path": "/g", "body": '{"name":"bob"}'})
    _check("aws/apigateway → Lambda proxy → 201", r["statusCode"] == 201 and json.loads(r["body"]) == {"hi": "bob"})

    # ── VPC: topology + reachability analyzer ────────────────────────────
    v = d("aws", "vpc", "CreateVpc", {"cidr": "10.0.0.0/16"})["id"]
    d("aws", "vpc", "CreateSubnet", {"vpcId": v, "cidr": "10.0.1.0/24"})
    d("aws", "vpc", "CreateSubnet", {"vpcId": v, "cidr": "10.0.2.0/24"})
    sg = d("aws", "vpc", "CreateSecurityGroup", {"vpcId": v})["id"]
    dbsg = d("aws", "vpc", "CreateSecurityGroup", {"vpcId": v})["id"]
    ep = {"sourceIp": "10.0.1.5", "sourceSgs": [sg], "destIp": "10.0.2.5", "destSgs": [dbsg], "port": 5432}
    _check("aws/vpc/Analyze blocked by default", not d("aws", "vpc", "Analyze", ep)["reachable"])
    d("aws", "vpc", "Authorize", {"sgId": dbsg, "port": 5432, "sourceSg": sg})
    _check("aws/vpc/Analyze reachable after authorize", d("aws", "vpc", "Analyze", ep)["reachable"])

    # ── EventBridge → SQS (cross-service, shared store) ──────────────────
    d("aws", "sqs", "CreateQueue", {"name": "evq"})
    d("aws", "eventbridge", "CreateRule", {"name": "r1", "pattern": {"source": ["app"]}, "targetQueue": "evq"})
    d("aws", "eventbridge", "PutEvent", {"source": "app", "detail": {"k": 1}})
    _check("aws/eventbridge PutEvent → console SQS queue", bool(d("aws", "sqs", "Receive", {"name": "evq"}).get("messages")))

    # ── Azure Service Bus: send/receive ──────────────────────────────────
    d("azure", "servicebus", "CreateTopic", {"name": "orders"})
    d("azure", "servicebus", "CreateSubscription", {"topic": "orders", "name": "billing"})
    d("azure", "servicebus", "Send", {"topic": "orders", "message": "m1"})
    _check("azure/servicebus send→receive",
           d("azure", "servicebus", "Receive", {"topic": "orders", "subscription": "billing"})["message"] == "m1")

    # ── Azure SQL: real query ────────────────────────────────────────────
    d("azure", "azuresql", "CreateServer", {"name": "s"})
    d("azure", "azuresql", "CreateDatabase", {"server": "s", "name": "db"})
    d("azure", "azuresql", "Query", {"server": "s", "database": "db", "sql": "CREATE TABLE t(x int)"})
    d("azure", "azuresql", "Query", {"server": "s", "database": "db", "sql": "INSERT INTO t VALUES (5)"})
    _check("azure/azuresql/Query real SQL",
           d("azure", "azuresql", "Query", {"server": "s", "database": "db", "sql": "SELECT x FROM t"})["rows"] == [[5]])

    # ── Azure RBAC: checkAccess ──────────────────────────────────────────
    d("azure", "azurerbac", "CreateAssignment", {"principalId": "u", "role": "Reader", "scope": "/subscriptions/S"})
    _check("azure/azurerbac read Allowed",
           d("azure", "azurerbac", "CheckAccess", {"principalId": "u", "action": "x/read", "scope": "/subscriptions/S"})["decision"] == "Allowed")
    _check("azure/azurerbac write NotAllowed",
           d("azure", "azurerbac", "CheckAccess", {"principalId": "u", "action": "x/write", "scope": "/subscriptions/S"})["decision"] == "NotAllowed")

    print("\nConsole data-plane integration: ALL GREEN — the dashboard drives all 7 net-new "
          "services via the real cores (registry→handlers→adapter→cores).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
