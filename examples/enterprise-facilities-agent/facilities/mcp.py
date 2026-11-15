"""Minimal MCP-over-HTTP client for an AgentCore Gateway with AWS_IAM inbound auth (JSON-RPC, SigV4 service `bedrock-agentcore`)."""
import json, os, urllib.request
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def call(ctx, gateway_id, method, params=None, url=None):
    # on real AWS `url` is the gateway's gatewayUrl; the simulator serves the same data plane under its own endpoint
    url = url or f"{ctx.endpoint}/gateways/{gateway_id}/mcp"
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    req = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "bedrock-agentcore", ctx.region).add_auth(req)
    r = urllib.request.Request(url, data=body.encode(), headers=dict(req.headers.items()), method="POST")
    with urllib.request.urlopen(r, timeout=60) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(f"MCP error: {out['error']}")
    return out["result"]
