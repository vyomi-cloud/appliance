"""Lambda serverless-invoke conformance (v2.6.0, PARITY P4 #14) — host + Pyodide.

Function lifecycle + a synchronous Invoke that actually runs the registered handler
in a sandboxed Python runtime (no __import__/open/eval); handler exceptions surface
as X-Amz-Function-Error, like real Lambda.
"""
import base64
import json
import types

try:
    from core import lambda_core as lam
except ImportError:  # pragma: no cover - Pyodide flat layout
    import lambda_core as lam  # type: ignore

API = "/2015-03-31/functions"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or types.SimpleNamespace()

    def call(m, p, b=b""):
        return lam.dispatch(s, m, p, {}, {}, b if isinstance(b, bytes) else json.dumps(b).encode())

    src = ("def handler(event, context):\n"
           "    total = sum(event.get('nums', []))\n"
           "    return {'sum': total, 'greeting': 'hello ' + event.get('name', 'world'),\n"
           "            'req': context['function_name']}\n")
    _check("CreateFunction 201",
           call("POST", API, {"FunctionName": "adder", "Runtime": "python3.12",
                              "Handler": "index.handler", "Code": {"Source": src}}).status == 201)

    out = json.loads(call("POST", f"{API}/adder/invocations", {"nums": [1, 2, 3, 4], "name": "alice"}).body)
    _check("Invoke runs the real handler",
           out == {"sum": 10, "greeting": "hello alice", "req": "adder"})

    _check("GetFunction",
           json.loads(call("GET", f"{API}/adder").body)["Configuration"]["FunctionName"] == "adder")
    _check("ListFunctions", len(json.loads(call("GET", API).body)["Functions"]) == 1)

    call("POST", API, {"FunctionName": "boom", "Code": {"Source": "def handler(e, c):\n    return 1 / 0"}})
    r = call("POST", f"{API}/boom/invocations", {})
    _check("handler exception → X-Amz-Function-Error",
           r.headers.get("X-Amz-Function-Error") == "Unhandled" and json.loads(r.body)["errorType"] == "ZeroDivisionError")

    call("POST", API, {"FunctionName": "evil", "Code": {"Source": "def handler(e, c):\n    return open('/etc/passwd').read()"}})
    _check("sandbox blocks open()",
           call("POST", f"{API}/evil/invocations", {}).headers.get("X-Amz-Function-Error") == "Unhandled")

    call("POST", API, {"FunctionName": "b64", "Code": {"ZipFile": base64.b64encode(src.encode()).decode()}})
    _check("base64 ZipFile code path",
           json.loads(call("POST", f"{API}/b64/invocations", {"nums": [5, 5]}).body)["sum"] == 10)

    _check("DeleteFunction 204", call("DELETE", f"{API}/adder").status == 204)

    print("\nLambda serverless-invoke conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
