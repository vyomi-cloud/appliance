"""App Service / Function App networking + Deployment Center source validation (Microsoft.Web/sites/...), substrate-free.

Real ARM behaviour on the site record:

* **Regional VNet integration** -- ``virtualNetworkSubnetId`` on the site (create wizard "Enable network injection") and
  ``networkConfig/virtualNetwork`` (GET/PUT/PATCH/DELETE): the subnet must exist, be delegated to
  ``Microsoft.Web/serverFarms``, be at least a /28, live in the app's region, and not be used by a plan other than the
  app's; Free/Shared plans cannot integrate. ``virtualNetworkConnections`` lists the integration as ARM does.
* **Access restrictions** -- ``ipSecurityRestrictions`` / ``scmIpSecurityRestrictions`` in ``config/web``: unique priorities,
  Allow|Deny, CIDR / ``Any`` / ServiceTag / vnet-subnet rules (the subnet needs the ``Microsoft.Web`` service endpoint),
  front-door header rules; the implicit "Allow all"/"Deny all" tail rule and default actions are derived like ARM does.
* **Hybrid connections** -- ``hybridConnectionNamespaces/{ns}/relays/{name}`` validated config (relay ARM URI shape, endpoint
  host/port, per-plan-tier limits). Status stays ``NotConnected``: there is no Hybrid Connection Manager / Azure Relay.
* **Deployment Center sources** -- ``config/web`` ``scmType`` transitions (LocalGit, ExternalGit, GitHubAction, VSTSRM,
  BitbucketGit, None) and container registry settings (``linuxFxVersion`` ``DOCKER|image:tag``, registry app settings).

NOT modelled: no packet leaves the site through a VNet or hybrid connection, access restrictions are not enforced on
inbound requests (there is no site front end), and a ``git push`` to the LocalGit remote has no receiving Kudu.
"""
from __future__ import annotations

import ipaddress
import re

SITES = "microsoft.web/sites"
VNET_OK_TIERS = ("Basic", "Standard", "PremiumV2", "PremiumV3", "Premium", "Isolated", "IsolatedV2", "ElasticPremium", "WorkflowStandard", "FlexConsumption")
HC_LIMITS = {"Basic": 5, "Standard": 25, "PremiumV2": 200, "PremiumV3": 200, "Premium": 200, "ElasticPremium": 200, "Isolated": 200, "IsolatedV2": 200}
SCM_TYPES = ("None", "LocalGit", "GitHub", "GitHubAction", "ExternalGit", "VSTSRM", "BitbucketGit", "BitbucketHg", "Dropbox", "OneDrive", "CodePlexGit", "CodePlexHg", "Tfs")
SERVICE_TAGS = {"AzureCloud", "AzureFrontDoor.Backend", "AzureFrontDoor.FirstParty", "ApiManagement", "AzureActiveDirectory", "AzureMonitor", "Storage", "Sql",
                "AzureTrafficManager", "AzureDevOps", "GitHub", "ActionGroup", "AppService", "AzureConnectors", "LogicApps", "Internet", "VirtualNetwork"}
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_IMAGE = re.compile(r"^DOCKER\|([a-z0-9][a-z0-9.-]*(:\d+)?/)?[a-z0-9._/-]+(:[\w.-]+|@sha256:[0-9a-f]{64})?$", re.I)
_RELAY_URI = re.compile(r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.(Relay|ServiceBus)/namespaces/[^/]+/hybridConnections/[^/]+$", re.I)


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _ok(body=None, status=200):
    return {"status": status, "headers": {}, "body": body, "lro": False}


def _cidr(v):
    try:
        return ipaddress.ip_network(str(v), strict=False)
    except ValueError:
        return None


def _plan(state, rec):
    return state.get(str((rec.get("properties") or {}).get("serverFarmId", "")).lower())


def _tier(state, rec):
    pl = _plan(state, rec)
    return ((pl or {}).get("sku") or {}).get("tier") or ""


def _subnet(state, sid):
    vid, _, name = str(sid).lower().rpartition("/subnets/")
    v = state.get(vid)
    if v is None or str(v.get("_type", "")).lower() != "microsoft.network/virtualnetworks":
        return None, None
    for s in (v.get("properties") or {}).get("subnets") or []:
        if str(s.get("name", "")).lower() == name:
            return s, v
    return None, v


# ── subnet-level checks shared by site create and networkConfig ────────────────────────
def check_integration_subnet(state, rec, subnet_id):
    tier = _tier(state, rec)
    if tier in ("Free", "Shared", "Dynamic"):
        return _err(400, "VnetIntegrationNotSupportedOnPlan", f"Regional VNet integration is not available on the {tier} pricing tier; use Basic or higher.")
    s, v = _subnet(state, subnet_id)
    if s is None:
        return _err(400, "InvalidSubnet" if v is not None else "VirtualNetworkNotFound", f"Subnet {subnet_id} was not found.")
    p = s.get("properties") or {}
    net = _cidr(p.get("addressPrefix") or (p.get("addressPrefixes") or [""])[0])
    if net is not None and net.prefixlen > 28:
        return _err(400, "SubnetTooSmall", f"Subnet {net} is too small for VNet integration; the minimum is a /28 (a /26 is recommended).")
    deleg = [str((d.get("properties") or {}).get("serviceName", "")).lower() for d in p.get("delegations") or []]
    if "microsoft.web/serverfarms" not in deleg:
        return _err(400, "SubnetNotDelegated", f"Subnet {s.get('name')} must be delegated to Microsoft.Web/serverFarms before an app can integrate with it.")
    if str(v.get("location", "")).lower() != str(rec.get("location", "")).lower():
        return _err(400, "VnetRegionMismatch", f"Virtual network {v.get('name')} is in {v.get('location')} but the app is in {rec.get('location')}; regional VNet integration needs the same region.")
    mine = str((rec.get("properties") or {}).get("serverFarmId", "")).lower()
    for r in state.values():
        if isinstance(r, dict) and str(r.get("_type", "")).lower() == SITES and r["id"].lower() != rec["id"].lower():
            if str((r.get("properties") or {}).get("virtualNetworkSubnetId", "")).lower() == str(subnet_id).lower() \
                    and str((r.get("properties") or {}).get("serverFarmId", "")).lower() != mine:
                return _err(400, "SubnetInUseByAnotherPlan", f"Subnet {s.get('name')} is already integrated with another App Service plan; a subnet can serve only one plan.")
    return None


# ── site create / update ───────────────────────────────────────────────────────────────
def validate_site(state, sub, rg, name, rec, payload):
    """Called before a site PUT/PATCH. ``rec`` is None on create."""
    props = (payload or {}).get("properties") or {}
    if props.get("virtualNetworkSubnetId"):
        probe = rec or {"id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites/{name}", "location": (payload or {}).get("location"),
                        "properties": {"serverFarmId": props.get("serverFarmId")}}
        if rec is None:
            probe["location"] = (payload or {}).get("location") or probe["location"]
        e = check_integration_subnet(state, probe, props["virtualNetworkSubnetId"])
        if e:
            return e
    cfg = props.get("siteConfig")
    if cfg:
        return validate_config(state, rec, cfg)
    return None


def after_site(state, rec):
    p = rec.setdefault("properties", {})
    cfg = p.setdefault("siteConfig", {})
    if p.get("virtualNetworkSubnetId"):
        p.setdefault("vnetRouteAllEnabled", False)
        cfg["vnetName"] = str(p["virtualNetworkSubnetId"]).split("/virtualNetworks/")[-1].split("/")[0]
        cfg["vnetRouteAllEnabled"] = bool(p.get("vnetRouteAllEnabled") or cfg.get("vnetRouteAllEnabled"))
    _derive_restrictions(cfg)


# ── config/web ─────────────────────────────────────────────────────────────────────────
def validate_config(state, rec, cfg):
    cfg = cfg or {}
    for key in ("ipSecurityRestrictions", "scmIpSecurityRestrictions"):
        if key in cfg and cfg[key] is not None:
            e = _validate_restrictions(state, cfg[key], key)
            if e:
                return e
    for key in ("ipSecurityRestrictionsDefaultAction", "scmIpSecurityRestrictionsDefaultAction"):
        if cfg.get(key) not in (None, "Allow", "Deny"):
            return _err(400, "InvalidDefaultAction", f"{key} must be Allow or Deny.")
    if cfg.get("scmType") is not None:
        e = _validate_scm(rec, cfg["scmType"])
        if e:
            return e
    fx = cfg.get("linuxFxVersion")
    if fx and str(fx).upper().startswith("DOCKER|") and not _IMAGE.match(fx):
        return _err(400, "InvalidContainerImage", f"linuxFxVersion '{fx}' is not a valid container image reference (DOCKER|[registry/]repo[:tag]).")
    if cfg.get("vnetRouteAllEnabled") and rec is not None and not (rec.get("properties") or {}).get("virtualNetworkSubnetId"):
        return _err(400, "VnetRouteAllRequiresIntegration", "vnetRouteAllEnabled requires the app to be integrated with a virtual network.")
    return None


def _validate_scm(rec, value):
    if value not in SCM_TYPES:
        return _err(400, "InvalidScmType", f"scmType '{value}' is not valid. Allowed: {', '.join(SCM_TYPES)}.")
    if rec is None:
        return None
    cur = ((rec.get("properties") or {}).get("siteConfig") or {}).get("scmType") or "None"
    if value in ("None", cur):
        return None
    if cur != "None":
        return _err(409, "SourceControlAlreadyConfigured", f"A deployment source ({cur}) is already configured; disconnect it (scmType None) before choosing {value}.")
    if value in ("GitHubAction", "ExternalGit", "VSTSRM", "BitbucketGit", "GitHub"):
        return _err(400, "SourceRequiresRepository", f"scmType {value} is set by configuring the repository (PUT sourcecontrols/web), not directly.")
    return None


def _validate_restrictions(state, rules, key):
    if not isinstance(rules, list):
        return _err(400, "InvalidIpSecurityRestrictions", f"{key} must be a list.")
    seen = set()
    for r in rules:
        name = r.get("name") or "(unnamed)"
        if r.get("action") not in ("Allow", "Deny"):
            return _err(400, "InvalidRestrictionAction", f"{key} rule {name}: action must be Allow or Deny.")
        pr = r.get("priority")
        if not isinstance(pr, int) or pr < 1 or pr > 2147483646:
            return _err(400, "InvalidRestrictionPriority", f"{key} rule {name}: priority must be an integer between 1 and 2147483646.")
        if pr in seen:
            return _err(400, "DuplicateRestrictionPriority", f"{key}: priority {pr} is used by more than one rule.")
        seen.add(pr)
        kinds = [k for k in ("ipAddress", "vnetSubnetResourceId") if r.get(k)]
        if len(kinds) != 1 and not r.get("headers"):
            return _err(400, "InvalidRestriction", f"{key} rule {name}: specify exactly one of ipAddress or vnetSubnetResourceId.")
        tag = r.get("tag") or "Default"
        if tag not in ("Default", "XffProxy", "ServiceTag"):
            return _err(400, "InvalidRestrictionTag", f"{key} rule {name}: tag must be Default, XffProxy or ServiceTag.")
        ip = r.get("ipAddress")
        if ip:
            if tag == "ServiceTag":
                if ip not in SERVICE_TAGS:
                    return _err(400, "InvalidServiceTag", f"{key} rule {name}: '{ip}' is not a known service tag.")
            elif ip != "Any" and ip != "Any " and _cidr(ip) is None:
                return _err(400, "InvalidRestrictionIp", f"{key} rule {name}: '{ip}' is not a valid IPv4/IPv6 address or CIDR block.")
        sid = r.get("vnetSubnetResourceId")
        if sid:
            s, v = _subnet(state, sid)
            if s is None:
                return _err(400, "RestrictionSubnetNotFound", f"{key} rule {name}: subnet {sid} was not found.")
            eps = [str(e.get("service", "")).lower() for e in (s.get("properties") or {}).get("serviceEndpoints") or []]
            if "microsoft.web" not in eps:
                return _err(400, "ServiceEndpointRequired", f"{key} rule {name}: subnet {s.get('name')} needs the Microsoft.Web service endpoint enabled.")
        h = r.get("headers") or {}
        for hk, hv in h.items():
            if hk not in ("x-azure-fdid", "x-fd-healthprobe", "x-forwarded-for", "x-forwarded-host"):
                return _err(400, "InvalidRestrictionHeader", f"{key} rule {name}: header '{hk}' is not supported.")
            if hk == "x-azure-fdid" and not all(_GUID.match(str(x)) for x in hv):
                return _err(400, "InvalidFrontDoorId", f"{key} rule {name}: x-azure-fdid values must be Front Door profile GUIDs.")
            if hk == "x-fd-healthprobe" and list(hv) != ["1"]:
                return _err(400, "InvalidRestrictionHeader", f"{key} rule {name}: x-fd-healthprobe only accepts '1'.")
            if len(hv) > 8:
                return _err(400, "TooManyHeaderValues", f"{key} rule {name}: at most 8 values per header.")
        if r.get("headers") and tag != "ServiceTag" and not ip:
            return _err(400, "HeaderRuleRequiresIp", f"{key} rule {name}: header filters must be combined with an address (e.g. the AzureFrontDoor.Backend service tag).")
    if len(rules) > 512:
        return _err(400, "TooManyRestrictions", "At most 512 access restriction rules are supported.")
    return None


def _derive_restrictions(cfg):
    for key, dk in (("ipSecurityRestrictions", "ipSecurityRestrictionsDefaultAction"), ("scmIpSecurityRestrictions", "scmIpSecurityRestrictionsDefaultAction")):
        rules = [r for r in (cfg.get(key) or []) if r.get("priority") != 2147483647]
        if dk not in cfg:
            cfg[dk] = "Allow"
        if not rules:
            cfg[key] = [{"ipAddress": "Any", "action": "Allow", "priority": 2147483647, "name": "Allow all", "description": "Allow all access"}]
        else:
            # ARM appends the implicit tail rule: Deny all when there is an Allow rule, Allow all otherwise
            has_allow = any(r.get("action") == "Allow" for r in rules)
            tail = ({"ipAddress": "Any", "action": "Deny", "priority": 2147483647, "name": "Deny all", "description": "Deny all access"} if has_allow
                    else {"ipAddress": "Any", "action": "Allow", "priority": 2147483647, "name": "Allow all", "description": "Allow all access"})
            cfg[key] = sorted(rules, key=lambda r: r.get("priority", 0)) + [tail]
            if has_allow and cfg[dk] == "Allow":
                cfg[dk] = "Deny"
    cfg.setdefault("scmIpSecurityRestrictionsUseMain", False)


# ── sub-resources ──────────────────────────────────────────────────────────────────────
def handles(rest):
    return rest[0].lower() in ("networkconfig", "virtualnetworkconnections", "hybridconnectionnamespaces", "hybridconnectionrelays", "hybridconnection")


def dispatch(state, rec, rest, method, payload):
    r0 = rest[0].lower()
    props = ((payload or {}).get("properties") if isinstance(payload, dict) else None) or {}
    p = rec.setdefault("properties", {})
    if r0 == "networkconfig":
        if len(rest) < 2 or rest[1].lower() != "virtualnetwork":
            return _err(404, "ResourceTypeNotSupported", f"networkConfig/{rest[1] if len(rest) > 1 else ''} is not supported on sites.")
        if method == "GET":
            return _ok(_vnet_view(rec)) if p.get("virtualNetworkSubnetId") else _err(404, "ResourceNotFound", "The app is not integrated with a virtual network.")
        if method == "DELETE":
            p.pop("virtualNetworkSubnetId", None)
            cfg = p.get("siteConfig") or {}
            cfg.pop("vnetName", None)
            cfg["vnetRouteAllEnabled"] = False
            p["vnetRouteAllEnabled"] = False
            return _ok(None)
        if method in ("PUT", "PATCH"):
            sid = props.get("subnetResourceId") or props.get("virtualNetworkSubnetId")
            if not sid:
                return _err(400, "BadRequest", "properties.subnetResourceId is required.")
            e = check_integration_subnet(state, rec, sid)
            if e:
                return e
            p["virtualNetworkSubnetId"] = sid
            after_site(state, rec)
            return _ok(_vnet_view(rec))
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if r0 == "virtualnetworkconnections":
        sid = p.get("virtualNetworkSubnetId")
        items = [_conn_view(rec, sid)] if sid else []
        if len(rest) == 1:
            return _ok({"value": items}) if method == "GET" else _err(405, "MethodNotAllowed", "Collection supports GET only.")
        hit = next((i for i in items if i["name"].lower() == rest[1].lower()), None)
        if method == "GET":
            return _ok(hit) if hit else _err(404, "ResourceNotFound", f"Virtual network connection '{rest[1]}' was not found.")
        if method == "DELETE":
            return dispatch(state, rec, ["networkConfig", "virtualNetwork"], "DELETE", {}) if hit else _ok(None, 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    # hybrid connections
    hcs = rec.setdefault("_hybridconns", {})
    if r0 == "hybridconnectionrelays" or (r0 == "hybridconnection" and len(rest) == 1):
        return _ok({"value": [_hc_view(rec, h) for h in hcs.values()]}) if method == "GET" else _err(405, "MethodNotAllowed", "Collection supports GET only.")
    if r0 == "hybridconnectionnamespaces":
        if len(rest) != 4 or rest[2].lower() != "relays":
            return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(rest)}' is not supported on sites.")
        ns, name = rest[1], rest[3]
        key = f"{ns}/{name}".lower()
        if method == "GET":
            return _ok(_hc_view(rec, hcs[key])) if key in hcs else _err(404, "ResourceNotFound", f"Hybrid connection '{name}' was not found on this app.")
        if method == "DELETE":
            hcs.pop(key, None)
            return _ok(None)
        if method in ("PUT", "PATCH"):
            uri = str(props.get("relayArmUri") or "")
            if not _RELAY_URI.match(uri):
                return _err(400, "InvalidRelayArmUri", "properties.relayArmUri must be the ARM id of a Relay hybrid connection (…/providers/Microsoft.Relay/namespaces/{ns}/hybridConnections/{name}).")
            if not str(props.get("hostname") or "").strip():
                return _err(400, "EndpointHostRequired", "properties.hostname (the on-premises endpoint host) is required.")
            port = props.get("port")
            if not isinstance(port, int) or port < 1 or port > 65535:
                return _err(400, "InvalidEndpointPort", "properties.port must be between 1 and 65535.")
            if not props.get("sendKeyName"):
                return _err(400, "SendKeyRequired", "properties.sendKeyName (a Send-claim authorization rule on the relay) is required.")
            tier = _tier(state, rec)
            limit = HC_LIMITS.get(tier)
            if limit is None:
                return _err(400, "HybridConnectionsNotSupportedOnPlan", f"Hybrid connections require a Basic or higher plan (this plan is {tier or 'unknown'}).")
            pid = str(p.get("serverFarmId", "")).lower()
            total = sum(len(r.get("_hybridconns") or {}) for r in state.values() if isinstance(r, dict) and str(r.get("_type", "")).lower() == SITES
                        and str((r.get("properties") or {}).get("serverFarmId", "")).lower() == pid)
            if key not in hcs and total >= limit:
                return _err(409, "HybridConnectionLimitReached", f"The {tier} plan supports at most {limit} hybrid connections; remove one first.")
            hcs[key] = {"name": name, "namespace": ns, "relayName": uri.rsplit("/", 1)[-1], "relayArmUri": uri, "hostname": props["hostname"], "port": port,
                        "sendKeyName": props["sendKeyName"], "serviceBusNamespace": f"{ns}.servicebus.windows.net"}
            return _ok(_hc_view(rec, hcs[key]), 200)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(rest)}' is not supported on sites.")


def _vnet_view(rec):
    sid = rec["properties"]["virtualNetworkSubnetId"]
    return {"id": f"{rec['id']}/networkConfig/virtualNetwork", "name": "virtualNetwork", "type": "Microsoft.Web/sites/networkConfig",
            "properties": {"subnetResourceId": sid, "swiftSupported": True, "isSwift": True,
                           "vnetRouteAllEnabled": bool((rec["properties"].get("siteConfig") or {}).get("vnetRouteAllEnabled"))}}


def _conn_view(rec, sid):
    vnet = str(sid).split("/virtualNetworks/")[-1].split("/")[0]
    return {"id": f"{rec['id']}/virtualNetworkConnections/{vnet}", "name": vnet, "type": "Microsoft.Web/sites/virtualNetworkConnections",
            "properties": {"vnetResourceId": str(sid).rsplit("/subnets/", 1)[0], "isSwift": True, "certThumbprint": None,
                           "resyncRequired": False, "dnsServers": None}}


def _hc_view(rec, h):
    return {"id": f"{rec['id']}/hybridConnectionNamespaces/{h['namespace']}/relays/{h['name']}", "name": h["name"],
            "type": "Microsoft.Web/sites/hybridConnectionNamespaces/relays",
            "properties": {"serviceBusNamespace": h["serviceBusNamespace"], "relayName": h["relayName"], "relayArmUri": h["relayArmUri"],
                           "hostname": h["hostname"], "port": h["port"], "sendKeyName": h["sendKeyName"], "sendKeyValue": None,
                           "serviceBusSuffix": ".servicebus.windows.net"}}
