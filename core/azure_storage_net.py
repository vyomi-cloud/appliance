"""Storage account network rules (Networking blade): validation + data-plane enforcement.

ARM side (`validate_network_properties`): the shape real Azure enforces on
`properties.networkAcls` (defaultAction, bypass, ipRules, virtualNetworkRules,
resourceAccessRules) and `properties.customDomain`.

Data-plane side (`network_denied`): with `defaultAction: Deny` a request is admitted only when
  * its caller IP matches an ipRule (IP or CIDR) — the caller IP is `x-vyomi-client-ip`,
    defaulting to 127.0.0.1 (the simulator-local caller; the console's "Add your client IP"
    adds exactly that),
  * it names a subnet in a virtualNetworkRule via `x-vyomi-source-subnet` (the caller concept a
    simulator has for "traffic from this subnet"),
  * it carries `x-vyomi-azure-service` and `bypass` lists AzureServices, or
  * it carries `x-vyomi-resource-id` matching a resourceAccessRules resourceId.
No network identity beyond those headers exists, so nothing else can match.
"""
from __future__ import annotations

import ipaddress
import re

_PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
_FQDN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
_BYPASS = {"None", "Logging", "Metrics", "AzureServices"}


def _bad(msg: str, code: str = "InvalidNetworkAclsIpRule"):
    return (400, code, msg)


def validate_network_properties(props: dict, state: dict | None = None):
    """Returns (status, code, message) or None."""
    acls = props.get("networkAcls")
    if acls is not None:
        if not isinstance(acls, dict):
            return _bad("networkAcls must be an object.", "BadRequest")
        da = acls.get("defaultAction", "Allow")
        if da not in ("Allow", "Deny"):
            return _bad(f"networkAcls.defaultAction '{da}' is invalid; use Allow or Deny.", "BadRequest")
        bp = acls.get("bypass", "AzureServices")
        for tok in [t.strip() for t in str(bp).split(",") if t.strip()]:
            if tok not in _BYPASS:
                return _bad(f"networkAcls.bypass value '{tok}' is invalid.", "BadRequest")
        for r in acls.get("ipRules") or []:
            v = (r or {}).get("value", "")
            try:
                net = ipaddress.ip_network(v, strict=False)
            except ValueError:
                return _bad(f"The IP rule '{v}' is not a valid IPv4 address or CIDR range.")
            if net.version != 4:
                return _bad(f"The IP rule '{v}' must be an IPv4 address or CIDR range.")
            if "/" in v and net.prefixlen in (31, 32):
                return _bad(f"The IP rule '{v}' uses a /{net.prefixlen} range, which is not allowed; use a single address.")
            if any(net.subnet_of(p) for p in _PRIVATE):
                return _bad(f"The IP rule '{v}' is in a private address range, which cannot be used in firewall rules.")
        for r in acls.get("virtualNetworkRules") or []:
            rid = (r or {}).get("id", "")
            m = re.match(r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Network/virtualNetworks/([^/]+)/subnets/([^/]+)$", rid, re.I)
            if not m:
                return _bad(f"The virtual network rule id '{rid}' is not a subnet resource id.", "BadRequest")
            if state is not None and rid.lower() not in {k.lower() for k in state} and not _subnet_exists(state, m.group(1), m.group(2)):
                return _bad(f"Subnet '{m.group(2)}' of virtual network '{m.group(1)}' does not exist.", "InvalidResourceReference")
        for r in acls.get("resourceAccessRules") or []:
            if not (r or {}).get("resourceId") or not (r or {}).get("tenantId"):
                return _bad("resourceAccessRules entries require resourceId and tenantId.", "BadRequest")
    cd = props.get("customDomain")
    if cd and (cd or {}).get("name"):
        name = (cd or {}).get("name", "")
        if not _FQDN.match(name or ""):
            return _bad(f"The custom domain name '{name}' is not a valid domain name.", "BadRequest")
    kp = props.get("keyPolicy")
    if kp is not None:
        d = (kp or {}).get("keyExpirationPeriodInDays")
        if not isinstance(d, int) or isinstance(d, bool) or not 1 <= d <= 9999:
            return _bad("keyPolicy.keyExpirationPeriodInDays must be an integer between 1 and 9999.", "BadRequest")
    rp = props.get("routingPreference")
    if rp:
        if rp.get("routingChoice", "MicrosoftRouting") not in ("MicrosoftRouting", "InternetRouting"):
            return _bad("routingPreference.routingChoice must be MicrosoftRouting or InternetRouting.", "BadRequest")
    return None


def _subnet_exists(state: dict, vnet: str, subnet: str) -> bool:
    for rec in state.values():
        if isinstance(rec, dict) and rec.get("_type", "").lower() == "microsoft.network/virtualnetworks" \
                and rec.get("name", "").lower() == vnet.lower():
            for s in (rec.get("properties") or {}).get("subnets") or []:
                if (s.get("name") or "").lower() == subnet.lower():
                    return True
    return False


def network_denied(props: dict, headers: dict) -> bool:
    acls = props.get("networkAcls") or {}
    if acls.get("defaultAction") != "Deny":
        return False
    ip = (headers.get("x-vyomi-client-ip") or "127.0.0.1").strip()
    try:
        addr = ipaddress.ip_address(ip)
        for r in acls.get("ipRules") or []:
            if addr in ipaddress.ip_network(r.get("value", ""), strict=False):
                return False
    except ValueError:
        pass
    sub = (headers.get("x-vyomi-source-subnet") or "").lower()
    if sub and any((r.get("id") or "").lower() == sub for r in acls.get("virtualNetworkRules") or []):
        return False
    bypass = [t.strip() for t in str(acls.get("bypass", "AzureServices")).split(",")]
    if headers.get("x-vyomi-azure-service") and "AzureServices" in bypass:
        return False
    rid = (headers.get("x-vyomi-resource-id") or "").lower()
    if rid and any((r.get("resourceId") or "").lower() == rid for r in acls.get("resourceAccessRules") or []):
        return False
    return True
