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

    # LogType=Tail → LogResult; invocation lines reach the CloudWatch Logs sink (/aws/lambda/<fn>)
    sunk = []
    s._log_sink = lambda g, st, lines: sunk.append((g, lines))
    logsrc = "def handler(e, c):\n    print('LOGLINE-ABC')\n    return {'statusCode': 200, 'headers': {'content-type': 'text/plain'}, 'body': 'hello url'}\n"
    call("POST", API, {"FunctionName": "logger", "Code": {"Source": logsrc}})
    r = lam.dispatch(s, "POST", f"{API}/logger/invocations", {}, {"X-Amz-Log-Type": "Tail"}, b"{}")
    tail = base64.b64decode(r.headers.get("X-Amz-Log-Result", "")).decode()
    _check("LogType=Tail returns START/stdout/REPORT in X-Amz-Log-Result",
           "START RequestId" in tail and "LOGLINE-ABC" in tail and "REPORT RequestId" in tail)
    _check("invocation lines are sunk to /aws/lambda/<fn>",
           sunk and sunk[-1][0] == "/aws/lambda/logger" and any("LOGLINE-ABC" in ln for ln in sunk[-1][1]))

    # Function URL config + public invoke path
    U = "/2021-10-31/functions/logger/url"
    mk = lam.dispatch(s, "POST", U, {}, {"Host": "h.example:9000"}, json.dumps({"AuthType": "NONE"}).encode())
    cfg = json.loads(mk.body)
    _check("CreateFunctionUrlConfig 201 with a FunctionUrl on the caller's origin",
           mk.status == 201 and cfg["FunctionUrl"].startswith("http://h.example:9000/lambda-url/") and cfg["AuthType"] == "NONE")
    _check("duplicate CreateFunctionUrlConfig 409", lam.dispatch(s, "POST", U, {}, {}, b'{"AuthType":"NONE"}').status == 409)
    _check("GetFunctionUrlConfig round-trips", json.loads(lam.dispatch(s, "GET", U, {}, {"Host": "h.example:9000"}, b"").body)["FunctionUrl"] == cfg["FunctionUrl"])
    uid = cfg["FunctionUrl"].rstrip("/").rsplit("/", 1)[-1]
    ur = lam.url_invoke(s, uid, "GET", "", {}, {}, b"")
    _check("Function URL invoke maps {statusCode, body} to HTTP", ur.status == 200 and ur.body == b"hello url" and ur.media_type == "text/plain")
    _check("DeleteFunctionUrlConfig 204", lam.dispatch(s, "DELETE", U, {}, {}, b"").status == 204)
    _check("deleted Function URL no longer invokes", lam.url_invoke(s, uid, "GET", "", {}, {}, b"").status == 404)
    # A REAL zip archive (what boto3 sends), custom handler module, context attributes, captured logs.
    import io, zipfile
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("app.py", "def h(event, context):\n    print('LOGLINE', event['n'])\n"
                             "    return {'n2': event['n'] * 2, 'fn': context.function_name}\n")
    call("POST", API, {"FunctionName": "zipfn", "Handler": "app.h",
                       "Code": {"ZipFile": base64.b64encode(zb.getvalue()).decode()}})
    r = lam.dispatch(s, "POST", f"{API}/zipfn/invocations", {}, {"x-amz-log-type": "Tail"}, b'{"n": 21}')
    _check("real zip: uploaded handler runs", json.loads(r.body) == {"n2": 42, "fn": "zipfn"})
    _check("LogType=Tail returns the captured print",
           "LOGLINE 21" in base64.b64decode(r.headers["X-Amz-Log-Result"]).decode())
    _check("InvocationType=Event -> 202",
           lam.dispatch(s, "POST", f"{API}/zipfn/invocations", {}, {"x-amz-invocation-type": "Event"}, b'{"n": 1}').status == 202)

    _check("DeleteFunction 204", call("DELETE", f"{API}/adder").status == 204)

    print("\nLambda serverless-invoke conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
