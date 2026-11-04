"""Azure data-plane NETWORK ACCESS evaluation (substrate-independent, pure Python, Pyodide-loadable).

Storage accounts and SQL servers have network rules that only matter to a caller with a network identity:
public network access, IP firewall rules, virtual network (service-endpoint) rules and private endpoints. A
browser console / SDK talking to the simulator has no real source network, so the caller DECLARES one with
request headers (like a request arriving through a specific path):

  x-vyomi-source-ip         the caller's public (or private) source address
  x-vyomi-source-subnet     ARM id of the subnet the caller sits in (service endpoint path)
  x-vyomi-private-endpoint  ARM id of the private endpoint the call arrives through
  x-vyomi-trusted-service   "1" = a trusted Azure service (honours networkAcls.bypass AzureServices)

No header = a caller with no declared network identity: the pre-existing behaviour is kept (only
publicNetworkAccess=Disabled blocks; allow-lists are NOT applied) and the capability text says so. With any
header the full rule set is enforced and a failing request gets the cloud's own 403.
"""
from __future__ import annotations

import ipaddress

_HDRS = ("x-vyomi-source-ip", "x-vyomi-source-subnet", "x-vyomi-private-endpoint", "x-vyomi-trusted-service")


def caller_context(headers: dict | None):
    h = {(k or "").lower(): v for k, v in (headers or {}).items()}
    ctx = {k.replace("x-vyomi-", "").replace("-", "_"): str(h[k]).strip() for k in _HDRS if h.get(k)}
    return ctx or None


def _ip_in_rule(ip: str, rule: str) -> bool:
    rule = (rule or "").strip()
    try:
        a = ipaddress.ip_address(ip)
        if "/" in rule:
            return a in ipaddress.ip_network(rule, strict=False)
        if "-" in rule:
            lo, hi = (ipaddress.ip_address(x.strip()) for x in rule.split("-", 1))
            return lo <= a <= hi
        return a == ipaddress.ip_address(rule)
    except ValueError:
        return False


def _pe_reaches(state: dict, pe_id: str, target_id: str) -> tuple:
    pe = state.get((pe_id or "").lower())
    if not pe or (pe.get("_type") or "").lower() != "microsoft.network/privateendpoints":
        return False, f"private endpoint {pe_id} does not exist"
    for key in ("privateLinkServiceConnections", "manualPrivateLinkServiceConnections"):
        for c in (pe.get("properties") or {}).get(key) or []:
            cp = c.get("properties") or {}
            if str(cp.get("privateLinkServiceId") or "").lower() == target_id.lower():
                st = (cp.get("privateLinkServiceConnectionState") or {}).get("status", "Pending")
                if st == "Approved":
                    return True, ""
                return False, f"private endpoint connection is {st}, not Approved"
    return False, f"private endpoint {pe_id} has no connection to this resource"


def _subnet_has_endpoint(state: dict, subnet_id: str, service: str) -> bool:
    sid = (subnet_id or "").lower()
    vnet_id, _, name = sid.rpartition("/subnets/")
    vnet = state.get(vnet_id)
    for s in ((vnet or {}).get("properties") or {}).get("subnets") or []:
        if str(s.get("name", "")).lower() == name:
            eps = (s.get("properties") or {}).get("serviceEndpoints") or []
            return any(str((e.get("service") if isinstance(e, dict) else e) or "").lower() == service.lower() for e in eps)
    return False


def check(state: dict, target_id: str, kind: str, props: dict, ctx: dict | None):
    """-> None when allowed, else (http_status, error_code, message).
    kind: 'storage' | 'sql'. `props` is the target's ARM properties."""
    pna = props.get("publicNetworkAccess")
    ctx = ctx or {}
    if ctx.get("private_endpoint"):
        ok, why = _pe_reaches(state, ctx["private_endpoint"], target_id)
        if ok:
            return None                       # private path: public access setting and firewalls do not apply
        return 403, "AuthorizationFailure", f"This request was made through a private endpoint that cannot reach this resource: {why}."
    if pna == "Disabled":
        return 403, "AuthorizationFailure" if kind == "storage" else "PublicNetworkAccessDisabled", \
            "Public network access is disabled for this resource; only a private endpoint can reach it."
    if not ctx:
        return None                           # undeclared caller: allow-lists are not applied (see module docstring)
    ip, subnet = ctx.get("source_ip"), ctx.get("source_subnet")
    if kind == "storage":
        acls = props.get("networkAcls") or {}
        if acls.get("defaultAction", "Allow") != "Deny":
            return None
        if ctx.get("trusted_service") and "AzureServices" in str(acls.get("bypass") or ""):
            return None
        if ip and any(_ip_in_rule(ip, r.get("value", "")) for r in acls.get("ipRules") or []):
            return None
        if subnet and any(str(r.get("id", "")).lower() == subnet.lower() for r in acls.get("virtualNetworkRules") or []) \
                and _subnet_has_endpoint(state, subnet, "Microsoft.Storage"):
            return None
        return 403, "AuthorizationFailure", "This request is not authorized to perform this operation: the storage account firewall (networkAcls defaultAction=Deny) has no IP or virtual network rule matching the caller."
    # SQL: server-level firewall is default-deny
    server_id = target_id.lower()
    rules = [r for r in state.values() if (r.get("_type") or "").lower() == "microsoft.sql/servers/firewallrules" and (r.get("id") or "").lower().startswith(server_id + "/")]
    if ip and not ip.startswith("10."):
        for r in rules:
            p = r.get("properties") or {}
            lo, hi = p.get("startIpAddress"), p.get("endIpAddress")
            try:
                if lo and hi and ipaddress.ip_address(lo) <= ipaddress.ip_address(ip) <= ipaddress.ip_address(hi):
                    return None
            except ValueError:
                continue
    if ctx.get("trusted_service") and any((r.get("properties") or {}).get("startIpAddress") == "0.0.0.0" and (r.get("properties") or {}).get("endIpAddress") == "0.0.0.0" for r in rules):
        return None                           # the 'Allow Azure services and resources' rule
    if subnet:
        for r in state.values():
            if (r.get("_type") or "").lower() == "microsoft.sql/servers/virtualnetworkrules" and (r.get("id") or "").lower().startswith(server_id + "/") \
                    and str((r.get("properties") or {}).get("virtualNetworkSubnetId", "")).lower() == subnet.lower() and _subnet_has_endpoint(state, subnet, "Microsoft.Sql"):
                return None
    return 403, "ClientIpNotAllowed", f"Client with IP address '{ip or 'unknown'}' is not allowed to access the server. The SQL server firewall has no matching IP or virtual network rule."


def find_arm(state: dict | None, full_type: str, id_suffix: str):
    """The ARM record whose key/id ends with `id_suffix` (and whose _type matches when it has one); its 'id' is
    filled from the state key when the record carries none."""
    want = "/" + id_suffix.lower()
    for key, rec in (state or {}).items():
        rid = (rec.get("id") or key)
        if rid.lower().endswith(want) and (not rec.get("_type") or rec["_type"].lower() == full_type):
            return rec if rec.get("id") else {**rec, "id": key}
    return None
