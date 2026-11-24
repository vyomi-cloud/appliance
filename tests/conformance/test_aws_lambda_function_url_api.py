"""API: a Lambda Function URL (AuthType NONE) answers a plain HTTP request with the handler's
response. Regression: GET /lambda-url/<id>/ returned 500 (KeyError 'function_name') because the
legacy route read a key the shared Lambda engine's records do not have."""
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
import zipfile

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(name, ok, detail=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if not ok and detail else ""))
    failed = failed or not ok


name = "fnurl-" + uuid.uuid4().hex[:8]
z = io.BytesIO()
with zipfile.ZipFile(z, "w") as f:
    f.writestr("lambda_function.py", "def lambda_handler(e, c):\n    return {'statusCode': 201, 'headers': {'content-type': 'text/plain', 'x-demo': 'yes'}, 'body': 'hi from url ' + e['requestContext']['http']['method']}\n")
try:
    s, b = call("POST", "/2015-03-31/functions", {"FunctionName": name, "Runtime": "python3.12", "Role": "arn:aws:iam::123456789012:role/r",
                                                  "Handler": "lambda_function.lambda_handler", "Code": {"ZipFile": base64.b64encode(z.getvalue()).decode()}})
    check("CreateFunction", s in (200, 201), f"{s} {b[:120]}")
    s, b = call("POST", f"/2021-10-31/functions/{name}/url", {"AuthType": "NONE"})
    check("CreateFunctionUrlConfig", s == 201, f"{s} {b[:120]}")
    url = json.loads(b).get("FunctionUrl", "") if s == 201 else ""
    path = "/lambda-url/" + url.split("/lambda-url/")[-1] if "/lambda-url/" in url else "/lambda-url/missing/"
    s, b = call("GET", path)
    check("Function URL GET returns the handler's body", s == 201 and b == b"hi from url GET", f"{s} {b[:120]}")
    s, b = call("POST", path + "sub/path", {"a": 1})
    check("Function URL POST on a sub-path reaches the handler", s == 201 and b == b"hi from url POST", f"{s} {b[:120]}")
    s, b = call("GET", "/lambda-url/does-not-exist/")
    check("Unknown Function URL id is 404, not 5xx", s == 404, f"{s} {b[:120]}")
finally:
    call("DELETE", f"/2015-03-31/functions/{name}")
sys.exit(1 if failed else 0)
