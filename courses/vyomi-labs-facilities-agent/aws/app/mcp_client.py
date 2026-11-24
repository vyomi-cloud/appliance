import json
import os
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def call(gateway_id, method, params=None):
    # The simulator serves the gateway data plane under its own endpoint. On real AWS use the gatewayUrl returned by GetGateway.
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    url = os.environ["AWS_ENDPOINT_URL"].rstrip("/") + "/gateways/" + gateway_id + "/mcp"
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    req = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "bedrock-agentcore", region).add_auth(req)
    r = urllib.request.Request(url, data=body.encode(), headers=dict(req.headers.items()), method="POST")
    with urllib.request.urlopen(r, timeout=60) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError("MCP error: " + str(out["error"]))
    return out["result"]
