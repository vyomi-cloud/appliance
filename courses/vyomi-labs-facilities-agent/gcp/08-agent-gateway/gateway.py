import gcp

BASE = f"/v1/{gcp.PARENT}"
GATEWAY = "facilities-gateway"
MCP_SERVER = "facilities-tools"


def api(method, path, body=None, expect=(200, 201, 204)):
    r = gcp.authed_session().request(method, gcp.ENDPOINT + path, json=body, timeout=120)
    if r.status_code not in expect:
        raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def mcp(url, method, params=None):
    """One MCP request (JSON-RPC 2.0 over streamable HTTP)."""
    r = gcp.authed_session().post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, timeout=60)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(f"MCP error: {out['error']}")
    return out["result"]
