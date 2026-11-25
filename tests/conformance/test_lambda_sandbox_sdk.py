"""Lambda sandbox: real course handlers (import os, json, time, boto3) run in-process on Nano, and the sandbox stays closed everywhere else.

Needs botocore (the same pure-Python serialisers Nano ships as botocore-lite); skipped without it.
  * No transport registered (appliance / plain Python): `import boto3` and `import os` are refused exactly as before.
  * With the in-process transport: boto3 clients talk ONLY to the router; os is a proxy (environ/getenv/getpid/path helpers, no filesystem);
    sys/subprocess/socket/io/importlib/urllib.request/open/eval/exec stay refused; endpoint_url cannot redirect a call.
"""
import base64
import io
import json
import sys
import zipfile

try:
    import botocore  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: botocore not installed")
    raise SystemExit(0)

try:
    from core import lambda_core as lc, lambda_sdk, nano_registry
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover
    import lambda_core as lc  # type: ignore
    import lambda_sdk, nano_registry  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _fn(src, env=None, name="f"):
    return {"name": name, "source": src, "handler": "index.handler", "env": env or {}, "runtime": "python3.12", "memory_size": 128}


def _out(src, env=None):
    return lc._sandbox_run(_fn(src, env), {"k": 1}, {})


def run():
    lambda_sdk.set_transport(None)
    for mod in ("boto3", "os", "sys", "subprocess", "socket", "io", "importlib", "urllib.request", "botocore.exceptions"):
        o = _out(f"import {mod}\ndef handler(e, c): return 1")
        _check(f"no transport: import {mod} refused", (not o["ok"]) and "not available in the Lambda sandbox" in o["error"])

    router = AwsWireRouter(stores=nano_registry.get())

    def transport(m, p, q, h, b):
        r = router.handle(m, p, q, h, b)
        body = r.get("body") or b""
        return int(r.get("status") or 200), {str(k): str(v) for k, v in (r.get("headers") or {}).items()}, (body.encode() if isinstance(body, str) else bytes(body))
    lambda_sdk.set_transport(transport)

    # the real course shape: os.environ + boto3 dynamodb
    boto3 = lambda_sdk.make_boto3()
    ddb = boto3.client("dynamodb")
    ddb.create_table(TableName="assets", KeySchema=[{"AttributeName": "asset_id", "KeyType": "HASH"}],
                     AttributeDefinitions=[{"AttributeName": "asset_id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
    ddb.put_item(TableName="assets", Item={"asset_id": {"S": "B-12"}, "kind": {"S": "boiler"}})
    src = ("import os\nimport boto3\n\ndef handler(event, context):\n"
           "    d = boto3.client('dynamodb')\n"
           "    it = d.get_item(TableName=os.environ['ASSETS_TABLE'], Key={'asset_id': {'S': event['asset_id']}}).get('Item')\n"
           "    return {'found': bool(it), 'kind': it['kind']['S'], 'fn': os.getenv('AWS_LAMBDA_FUNCTION_NAME'), 'pid': os.getpid(), 'p': os.path.join('a', 'b')}\n")
    o = lc._sandbox_run(_fn(src, {"ASSETS_TABLE": "assets"}), {"asset_id": "B-12"}, {})
    _check("handler with os + boto3 runs against the store", o["ok"] and o["result"]["found"] and o["result"]["kind"] == "boiler")
    _check("os.environ carries function env + AWS_LAMBDA_FUNCTION_NAME", o["result"]["fn"] == "f" and o["result"]["p"] == "a/b")
    _check("os.getpid is a fake constant", o["result"]["pid"] == 4242)

    o = _out("import boto3\nfrom botocore.exceptions import ClientError\n\ndef handler(e, c):\n"
             "    try:\n        boto3.client('dynamodb').get_item(TableName='nope', Key={'a': {'S': 'x'}})\n    except ClientError as ex:\n"
             "        return {'code': ex.response['Error']['Code']}\n    return {'code': 'none'}\n")
    _check("botocore ClientError is catchable with its response", o["ok"] and o["result"]["code"] == "ResourceNotFoundException")

    # Lambda -> Lambda invoke returns a readable Payload stream
    inner = _fn("def handler(e, c):\n    return {'x': e['n'] * 2}\n", name="inner")
    lc._functions(nano_registry.get()["compute"])["inner"] = {**inner, "arn": lc._fn_arn("inner"), "invocations": [], "layers": [], "versions": {}, "aliases": {}}
    lam = boto3.client("lambda")
    r = lam.invoke(FunctionName="inner", Payload=json.dumps({"n": 21}))
    _check("lambda.invoke Payload is a stream with read()", json.loads(r["Payload"].read()) == {"x": 42})

    # what must stay closed
    for bad, why in (("import sys", "sys"), ("import subprocess", "subprocess"), ("import socket", "socket"), ("import io", "io"), ("import importlib", "importlib"),
                     ("import urllib.request", "urllib.request"), ("import boto3.session", "boto3 submodule"), ("import botocore.httpsession", "botocore.httpsession"),
                     ("import zipfile", "zipfile")):
        o = _out(f"{bad}\ndef handler(e, c): return 1")
        _check(f"still refused: {why}", (not o["ok"]) and "not available in the Lambda sandbox" in o["error"])
    for expr in ("open('/etc/passwd')", "eval('1')", "exec('x=1')", "__import__('os').listdir('/')", "compile('1','x','eval')"):
        o = _out(f"import os\ndef handler(e, c):\n    return {expr}\n")
        _check(f"still refused: {expr.split('(')[0]}", not o["ok"] or (expr.startswith("__import__") and False))
    o = _out("import os\ndef handler(e, c):\n    return [n for n in ('listdir','system','popen','remove','open','environb','execv') if hasattr(os, n)]\n")
    _check("os proxy exposes no filesystem/process call", o["ok"] and o["result"] == [])
    o = _out("import boto3\ndef handler(e, c):\n    return boto3.client('s3', endpoint_url='http://169.254.169.254').list_buckets()['Buckets']\n")
    _check("endpoint_url is ignored: the call still lands in the in-process store", o["ok"] and isinstance(o["result"], list))

    # classes + typed errors now work (handlers define small helpers)
    o = _out("class A:\n    def __init__(self): self.v = 3\n\ndef handler(e, c):\n    try:\n        raise RuntimeError('boom')\n    except RuntimeError as ex:\n        return {'v': A().v, 'm': str(ex)}\n")
    _check("class statements + RuntimeError work", o["ok"] and o["result"] == {"v": 3, "m": "boom"})
    lambda_sdk.set_transport(None)
    print("LAMBDA SANDBOX SDK OK")


if __name__ == "__main__":
    run()
