import os
import requests
from azure.mgmt.apimanagement import ApiManagementClient
from azlab import arm, ENDPOINT, RG

SERVICE = "facilities-apim"
SUBSCRIPTION = "agent-sub"


def apim():
    return arm(ApiManagementClient)


def url(path=""):
    return f"{ENDPOINT}/azure-data/apim/{SERVICE}/{path.lstrip('/')}"


def subscription_key():
    return apim().subscription.list_secrets(RG, SERVICE, SUBSCRIPTION).primary_key


def headers(extra=None):
    h = {"Ocp-Apim-Subscription-Key": subscription_key(), "Content-Type": "application/json"}
    token = os.environ.get("VYOMI_BEARER_TOKEN")           # set from chapter 1 on
    if not token and os.path.exists("token.txt"):          # chapter 1 saves the access token here
        token = open("token.txt").read().strip()
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(extra or {})
    return h


def mcp(method, params=None):
    r = requests.post(url("mcp"), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=headers(), timeout=60)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(f"MCP error: {out['error']}")
    return out["result"]
