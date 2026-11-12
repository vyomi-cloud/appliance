# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Microsoft Graph / Entra ID extensions on top of core/azure_graph_core.GraphStore (pure Python, Nano + offline).

Real engines, not records:
  * Licenses            subscribedSkus with prepaid units; users/{id}/assignLicense consumes them (usageLocation required,
                        no free units -> 400), consumedUnits is COMPUTED from the users' assignedLicenses; licenseDetails.
  * Conditional Access  identity/conditionalAccess/policies + namedLocations (CIDR match) + a rule engine
                        (`evaluate`, the "What If" tool) that the ROPC token endpoint ENFORCES: block -> AADSTS53003,
                        MFA/device controls -> AADSTS50076/53000 (no interactive flow exists to satisfy them), and the
                        sign-in log row carries the real conditionalAccessStatus.
  * Custom security attributes   attributeSets + definitions (type, collection, predefined values); user assignments
                        are validated against the definitions.
  * BitLocker keys      informationProtection/bitlocker/recoveryKeys escrow store: keys are generated in the real BitLocker
                        recovery-password format (8 groups of 6 digits, each divisible by 11); every key READ is audited.
                        There is NO disk encryption behind it -- the key is escrowed, it unlocks nothing.
  * Administrative units  members (users/groups/devices) add/list/remove.
  * Per-user MFA        users/{id}/authentication/requirements perUserMfaState, enforced by the ROPC grant.
  * $batch              the Graph JSON batch endpoint (what the portal's bulk create/delete/invite uses).
Handlers return (status, obj|None); core/azure_graph_core wraps them in its Response.
"""
from __future__ import annotations

import ipaddress
import random
import uuid

SKUS = [
    {"skuId": "078d2b04-f1bd-4111-bbd4-b4b1b354cef4", "skuPartNumber": "AAD_PREMIUM", "prepaid": 100,
     "servicePlans": ["AAD_PREMIUM", "MFA_PREMIUM", "ADALLOM_S_DISCOVERY"]},
    {"skuId": "84a661c4-e949-4bd2-a560-ed7766fcaf2b", "skuPartNumber": "AAD_PREMIUM_P2", "prepaid": 25,
     "servicePlans": ["AAD_PREMIUM", "AAD_PREMIUM_P2", "MFA_PREMIUM"]},
    {"skuId": "6fd2c87f-b296-42f0-b197-1e91e994b900", "skuPartNumber": "ENTERPRISEPACK", "prepaid": 50,
     "servicePlans": ["EXCHANGE_S_ENTERPRISE", "SHAREPOINTENTERPRISE", "TEAMS1"]},
]
CA_STATES = ("enabled", "disabled", "enabledForReportingButNotEnforced")
GRANTS = ("block", "mfa", "compliantDevice", "domainJoinedDevice", "approvedApplication", "compliantApplication", "passwordChange")


def _guid():
    return str(uuid.uuid4())


def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(status, code, msg):
    return status, {"error": {"code": code, "message": msg}}


def _bucket(store, name, default):
    if not hasattr(store, name):
        setattr(store, name, default)
    return getattr(store, name)


# ── licenses ────────────────────────────────────────────────────────────────
def _consumed(store, sku_id):
    return sum(1 for u in store.users.values() for l in u.get("assignedLicenses") or [] if l.get("skuId") == sku_id)


def sku_view(store, s):
    n = _consumed(store, s["skuId"])
    return {"id": f"{store.organization['id']}_{s['skuId']}", "skuId": s["skuId"], "skuPartNumber": s["skuPartNumber"],
            "appliesTo": "User", "capabilityStatus": "Enabled", "consumedUnits": n,
            "prepaidUnits": {"enabled": s["prepaid"], "suspended": 0, "warning": 0},
            "servicePlans": [{"servicePlanName": p, "provisioningStatus": "Success", "appliesTo": "User"} for p in s["servicePlans"]]}


def assign_license(store, uid, body):
    u = store.users.get(uid)
    if not u:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    adds = [a.get("skuId") for a in body.get("addLicenses") or []]
    rems = list(body.get("removeLicenses") or [])
    known = {s["skuId"]: s for s in SKUS}
    for sid in adds + rems:
        if sid not in known:
            return _err(400, "Request_BadRequest", f"License {sid} does not correspond to a valid company SKU.")
    have = {l["skuId"] for l in u.get("assignedLicenses") or []}
    new_adds = [s for s in adds if s not in have]
    if new_adds and not u.get("usageLocation"):
        return _err(400, "Request_BadRequest", "License assignment failed because the user's usageLocation is not set. A usage location is required.")
    for sid in new_adds:
        if _consumed(store, sid) >= known[sid]["prepaid"]:
            return _err(400, "Request_BadRequest", f"License assignment failed because there are no available licenses for SKU {known[sid]['skuPartNumber']}.")
    cur = [l for l in u.get("assignedLicenses") or [] if l["skuId"] not in rems]
    for sid in new_adds:
        cur.append({"skuId": sid, "disabledPlans": []})
    u["assignedLicenses"] = cur
    store.audit("Change user license", "UserManagement", u["displayName"])
    return 200, {k: v for k, v in u.items() if not k.startswith("_")}


def license_details(store, uid):
    u = store.users.get(uid)
    if not u:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    by = {s["skuId"]: s for s in SKUS}
    return 200, {"value": [{"id": _guid(), "skuId": l["skuId"], "skuPartNumber": by[l["skuId"]]["skuPartNumber"],
                            "servicePlans": [{"servicePlanName": p, "provisioningStatus": "Success"} for p in by[l["skuId"]]["servicePlans"]]}
                           for l in u.get("assignedLicenses") or [] if l["skuId"] in by]}


# ── conditional access ─────────────────────────────────────────────────────
def _policies(store):
    return _bucket(store, "ca_policies", {})


def _locations(store):
    return _bucket(store, "ca_locations", {})


def _validate_policy(body):
    st = body.get("state", "disabled")
    if st not in CA_STATES:
        return f"state must be one of {', '.join(CA_STATES)}."
    if not body.get("displayName"):
        return "displayName is required."
    gc = body.get("grantControls") or {}
    for c in gc.get("builtInControls") or []:
        if c not in GRANTS:
            return f"Unknown grant control '{c}'."
    if "block" in (gc.get("builtInControls") or []) and len(gc.get("builtInControls") or []) > 1:
        return "'block' cannot be combined with other grant controls."
    if gc.get("operator") not in (None, "AND", "OR"):
        return "grantControls.operator must be AND or OR."
    return None


def ca_policy(store, method, rest, body):
    pol = _policies(store)
    if not rest:
        if method == "GET":
            return 200, {"value": list(pol.values())}
        if method == "POST":
            bad = _validate_policy(body)
            if bad:
                return _err(400, "Request_BadRequest", bad)
            pid = _guid()
            pol[pid] = {"id": pid, "createdDateTime": _now(), "modifiedDateTime": None, "state": "disabled", "conditions": {},
                        "grantControls": None, "sessionControls": None, **{k: v for k, v in body.items() if k != "id"}}
            store.audit("Add conditional access policy", "Policy", body["displayName"])
            return 201, pol[pid]
    elif len(rest) == 1:
        p = pol.get(rest[0])
        if p is None:
            return _err(404, "Request_ResourceNotFound", f"Resource '{rest[0]}' does not exist.")
        if method == "GET":
            return 200, p
        if method == "PATCH":
            merged = {**p, **{k: v for k, v in body.items() if k != "id"}}
            bad = _validate_policy(merged)
            if bad:
                return _err(400, "Request_BadRequest", bad)
            p.update(merged, modifiedDateTime=_now())
            store.audit("Update conditional access policy", "Policy", p["displayName"])
            return 204, None
        if method == "DELETE":
            pol.pop(rest[0])
            store.audit("Delete conditional access policy", "Policy", p["displayName"])
            return 204, None
    return _err(405, "Request_UnsupportedQuery", method)


def named_location(store, method, rest, body):
    locs = _locations(store)
    if not rest:
        if method == "GET":
            return 200, {"value": list(locs.values())}
        if method == "POST":
            if not body.get("displayName"):
                return _err(400, "Request_BadRequest", "displayName is required.")
            kind = body.get("@odata.type", "#microsoft.graph.ipNamedLocation")
            if kind.endswith("ipNamedLocation"):
                for r in body.get("ipRanges") or []:
                    try:
                        ipaddress.ip_network(r.get("cidrAddress", ""), strict=False)
                    except ValueError:
                        return _err(400, "Request_BadRequest", f"'{r.get('cidrAddress')}' is not a valid CIDR range.")
            lid = _guid()
            locs[lid] = {"id": lid, "@odata.type": kind, "createdDateTime": _now(), **{k: v for k, v in body.items() if k != "id"}}
            return 201, locs[lid]
    elif len(rest) == 1:
        if rest[0] not in locs:
            return _err(404, "Request_ResourceNotFound", f"Resource '{rest[0]}' does not exist.")
        if method == "GET":
            return 200, locs[rest[0]]
        if method == "DELETE":
            used = [p["displayName"] for p in _policies(store).values()
                    if rest[0] in ((p.get("conditions") or {}).get("locations") or {}).get("includeLocations", [])
                    + ((p.get("conditions") or {}).get("locations") or {}).get("excludeLocations", [])]
            if used:
                return _err(400, "Request_BadRequest", f"The named location is referenced by policy '{used[0]}'.")
            locs.pop(rest[0])
            return 204, None
    return _err(405, "Request_UnsupportedQuery", method)


def _in_location(store, ip, loc_id):
    if loc_id == "All":
        return True
    if loc_id == "AllTrusted":
        return any(_in_location(store, ip, i) for i, l in _locations(store).items() if l.get("isTrusted"))
    loc = _locations(store).get(loc_id)
    if not loc or not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(r["cidrAddress"], strict=False) for r in loc.get("ipRanges") or [])


def _user_in(store, user, sel, which):
    inc, exc = sel.get("include" + which) or [], sel.get("exclude" + which) or []
    return inc, exc


def _match_policy(store, pol, ctx):
    """-> (applies: bool, reasons: [str]).  Each condition explains why it did/did not match."""
    c = pol.get("conditions") or {}
    why = []
    users = c.get("users") or {}
    uid = ctx["user"]["id"] if ctx.get("user") else None
    groups = {gid for gid, m in store.group_members.items() if uid in m}
    is_guest = bool(ctx.get("user")) and ctx["user"].get("userType") == "Guest"
    inc_u, exc_u = users.get("includeUsers") or [], users.get("excludeUsers") or []
    inc_g, exc_g = users.get("includeGroups") or [], users.get("excludeGroups") or []
    included = ("All" in inc_u or uid in inc_u or (is_guest and "GuestsOrExternalUsers" in inc_u) or bool(groups & set(inc_g)))
    if not (inc_u or inc_g):
        included = False
    excluded = (uid in exc_u or bool(groups & set(exc_g)) or (is_guest and "GuestsOrExternalUsers" in exc_u))
    if not included:
        return False, ["user is not in the policy's included users/groups"]
    if excluded:
        return False, ["user is excluded by the policy"]
    why.append("user matched")
    apps = c.get("applications") or {}
    inc_a, exc_a = apps.get("includeApplications") or [], apps.get("excludeApplications") or []
    if inc_a and not ("All" in inc_a or ctx.get("appId") in inc_a):
        return False, ["target application not included"]
    if ctx.get("appId") in exc_a:
        return False, ["target application is excluded"]
    why.append("application matched")
    loc = c.get("locations") or {}
    if loc.get("includeLocations"):
        if not any(_in_location(store, ctx.get("ip"), l) for l in loc["includeLocations"]):
            return False, [f"IP {ctx.get('ip')} is not in an included location"]
        if any(_in_location(store, ctx.get("ip"), l) for l in loc.get("excludeLocations") or []):
            return False, [f"IP {ctx.get('ip')} is in an excluded location"]
        why.append("location matched")
    plat = c.get("platforms") or {}
    if plat.get("includePlatforms"):
        p = ctx.get("platform") or "unknown"
        if not ("all" in plat["includePlatforms"] or p in plat["includePlatforms"]) or p in (plat.get("excludePlatforms") or []):
            return False, [f"platform '{p}' not targeted"]
        why.append("platform matched")
    for key, cx in (("userRiskLevels", "userRisk"), ("signInRiskLevels", "signInRisk")):
        if c.get(key) and (ctx.get(cx) or "none") not in c[key]:
            return False, [f"{key} does not include '{ctx.get(cx) or 'none'}'"]
    if c.get("clientAppTypes") and "all" not in c["clientAppTypes"] and (ctx.get("clientAppType") or "browser") not in c["clientAppTypes"]:
        return False, ["client app type not targeted"]
    return True, why


def evaluate(store, ctx):
    """Conditional Access 'What If'.  ctx: user (record), appId, ip, platform, userRisk, signInRisk, clientAppType."""
    results, controls, op_all, blocked = [], set(), True, False
    for pol in _policies(store).values():
        state = pol.get("state", "disabled")
        if state == "disabled":
            results.append({"id": pol["id"], "displayName": pol["displayName"], "state": state, "applied": False, "reasons": ["policy is disabled"]})
            continue
        ok, why = _match_policy(store, pol, ctx)
        enforced = ok and state == "enabled"
        results.append({"id": pol["id"], "displayName": pol["displayName"], "state": state, "applied": enforced, "reportOnly": ok and not enforced, "reasons": why,
                        "grantControls": (pol.get("grantControls") or {}).get("builtInControls") if ok else None})
        if enforced:
            gc = pol.get("grantControls") or {}
            ctl = gc.get("builtInControls") or []
            if "block" in ctl:
                blocked = True
            controls.update(c for c in ctl if c != "block")
    applied = [r for r in results if r["applied"]]
    return {"policies": results, "result": "block" if blocked else ("requireControls" if controls else "allow"),
            "requiredControls": sorted(controls), "appliedPolicies": [r["displayName"] for r in applied]}


def what_if(store, body):
    u = store.users.get(body.get("userId") or "") or next((x for x in store.users.values() if x["userPrincipalName"].lower() == str(body.get("userPrincipalName", "")).lower()), None)
    if u is None:
        return _err(404, "Request_ResourceNotFound", "The user was not found.")
    return 200, evaluate(store, {"user": u, "appId": body.get("appId") or "All", "ip": body.get("ipAddress"),
                                 "platform": body.get("devicePlatform"), "userRisk": body.get("userRiskLevel"),
                                 "signInRisk": body.get("signInRiskLevel"), "clientAppType": body.get("clientAppType")})


def enforce_signin(store, user, app_id, ip="127.0.0.1"):
    """-> None (proceed) or (aadsts_code, message, status_label) for the ROPC grant. Also covers per-user MFA."""
    if (user.get("_mfa_state") or "disabled") == "enforced":
        return 50076, "AADSTS50076: Due to a configuration change made by your administrator, you must use multi-factor authentication to access this resource (per-user MFA is enforced).", "failure"
    if not _policies(store):
        return None
    r = evaluate(store, {"user": user, "appId": app_id, "ip": ip, "platform": None, "clientAppType": "other"})
    if r["result"] == "block":
        return 53003, f"AADSTS53003: Access has been blocked by Conditional Access policies ({', '.join(r['appliedPolicies'])}).", "failure"
    if r["result"] == "requireControls":
        code = 50076 if "mfa" in r["requiredControls"] else 53000
        return code, f"AADSTS{code}: Conditional Access requires {', '.join(r['requiredControls'])}, which cannot be satisfied by the password grant (no interactive flow).", "failure"
    return None


# ── custom security attributes ─────────────────────────────────────────────
def csa_sets(store, method, rest, body):
    sets = _bucket(store, "csa_sets", {})
    if not rest:
        if method == "GET":
            return 200, {"value": list(sets.values())}
        if method == "POST":
            sid = body.get("id") or ""
            if not sid.replace("_", "").isalnum() or len(sid) > 32:
                return _err(400, "Request_BadRequest", "Attribute set name must be alphanumeric/underscore, up to 32 characters.")
            if sid in sets:
                return _err(409, "Request_Conflict", f"Attribute set '{sid}' already exists.")
            sets[sid] = {"id": sid, "description": body.get("description"), "maxAttributesPerSet": int(body.get("maxAttributesPerSet") or 25)}
            return 201, sets[sid]
    elif len(rest) == 1:
        if rest[0] not in sets:
            return _err(404, "Request_ResourceNotFound", f"Attribute set '{rest[0]}' does not exist.")
        if method == "GET":
            return 200, sets[rest[0]]
        if method == "PATCH":
            sets[rest[0]].update({k: v for k, v in body.items() if k in ("description", "maxAttributesPerSet")})
            return 204, None
    return _err(405, "Request_UnsupportedQuery", method)


def csa_defs(store, method, rest, body):
    defs = _bucket(store, "csa_defs", {})
    sets = _bucket(store, "csa_sets", {})
    if not rest:
        if method == "GET":
            return 200, {"value": list(defs.values())}
        if method == "POST":
            s, n = body.get("attributeSet"), body.get("name")
            if s not in sets:
                return _err(400, "Request_BadRequest", f"Attribute set '{s}' does not exist.")
            if not n or body.get("type") not in ("String", "Integer", "Boolean"):
                return _err(400, "Request_BadRequest", "name and type (String, Integer, Boolean) are required.")
            if sum(1 for d in defs.values() if d["attributeSet"] == s) >= sets[s]["maxAttributesPerSet"]:
                return _err(400, "Request_BadRequest", f"Attribute set '{s}' is full.")
            did = f"{s}_{n}"
            if did in defs:
                return _err(409, "Request_Conflict", f"Attribute definition '{did}' already exists.")
            defs[did] = {"id": did, "attributeSet": s, "name": n, "description": body.get("description"), "type": body["type"],
                         "isCollection": bool(body.get("isCollection")), "isSearchable": body.get("isSearchable", True),
                         "status": body.get("status", "Available"), "usePreDefinedValuesOnly": bool(body.get("usePreDefinedValuesOnly")),
                         "allowedValues": [{"id": v if isinstance(v, str) else v.get("id"), "isActive": True} for v in body.get("allowedValues") or []]}
            return 201, defs[did]
    elif len(rest) == 1:
        d = defs.get(rest[0])
        if d is None:
            return _err(404, "Request_ResourceNotFound", f"Attribute definition '{rest[0]}' does not exist.")
        if method == "GET":
            return 200, d
        if method == "PATCH":
            d.update({k: v for k, v in body.items() if k in ("description", "status", "usePreDefinedValuesOnly")})
            return 204, None
    return _err(405, "Request_UnsupportedQuery", method)


def csa_apply(store, user, csa):
    """Validate + merge a PATCH users/{id} customSecurityAttributes payload.  -> error tuple or None."""
    defs = _bucket(store, "csa_defs", {})
    cur = user.setdefault("_csa", {})
    for sname, vals in (csa or {}).items():
        for aname, v in (vals or {}).items():
            if aname.startswith("@") or aname.endswith("@odata.type"):
                continue
            d = defs.get(f"{sname}_{aname}")
            if d is None:
                return _err(400, "Request_BadRequest", f"Custom security attribute '{sname}_{aname}' is not defined.")
            if d["status"] != "Available":
                return _err(400, "Request_BadRequest", f"Attribute '{d['id']}' is deprecated and cannot be assigned.")
            if v is None:
                cur.get(sname, {}).pop(aname, None)
                continue
            items = v if isinstance(v, list) else [v]
            if isinstance(v, list) != d["isCollection"]:
                return _err(400, "Request_BadRequest", f"Attribute '{d['id']}' {'requires' if d['isCollection'] else 'does not accept'} a collection value.")
            pyt = {"String": str, "Integer": int, "Boolean": bool}[d["type"]]
            for it in items:
                if not isinstance(it, pyt) or (d["type"] == "Integer" and isinstance(it, bool)):
                    return _err(400, "Request_BadRequest", f"Attribute '{d['id']}' expects {d['type']} values.")
                if d["usePreDefinedValuesOnly"] and it not in [a["id"] for a in d["allowedValues"] if a["isActive"]]:
                    return _err(400, "Request_BadRequest", f"'{it}' is not an allowed value for '{d['id']}'.")
            cur.setdefault(sname, {})[aname] = v
    for s in [s for s, m in cur.items() if not m]:
        cur.pop(s)
    return None


def csa_view(user):
    return {s: {"@odata.type": "#microsoft.graph.customSecurityAttributeValue", **m} for s, m in (user.get("_csa") or {}).items()}


# ── BitLocker recovery keys ───────────────────────────────────────────────
def new_recovery_password(rng=random.SystemRandom()):
    """48 digits as 8 groups of 6; each group is a multiple of 11 below 720896 (the real BitLocker recovery-password rule)."""
    return "-".join(f"{rng.randrange(0, 65536) * 11:06d}" for _ in range(8))


def valid_recovery_password(p):
    g = str(p).split("-")
    return len(g) == 8 and all(len(x) == 6 and x.isdigit() and int(x) % 11 == 0 and int(x) < 720896 for x in g)


def bitlocker(store, method, rest, body, query):
    keys = _bucket(store, "bitlocker_keys", {})
    view = lambda k: {x: v for x, v in k.items() if x != "key"}
    if not rest:
        if method == "GET":
            flt = (query or {}).get("$filter", "")
            did = flt.split("eq")[-1].strip().strip("'") if "deviceId" in flt else None
            return 200, {"value": [view(k) for k in keys.values() if not did or k["deviceId"] == did]}
        if method == "POST":   # Vyomi escrow action: what a joined/encrypted device's OS client does (no real disk behind it)
            dev = store.devices.get(body.get("deviceObjectId") or "") or next((d for d in store.devices.values() if d["deviceId"] == body.get("deviceId")), None)
            if dev is None:
                return _err(404, "Request_ResourceNotFound", "The device does not exist; register it first.")
            pw = body.get("key") or new_recovery_password()
            if not valid_recovery_password(pw):
                return _err(400, "Request_BadRequest", "key is not a valid BitLocker recovery password (8 groups of 6 digits, each divisible by 11).")
            kid = _guid()
            keys[kid] = {"id": kid, "createdDateTime": _now(), "volumeType": body.get("volumeType", "operatingSystemVolume"),
                         "deviceId": dev["deviceId"], "deviceObjectId": dev["id"], "key": pw}
            store.audit("Escrow BitLocker recovery key", "Device", dev["displayName"])
            return 201, view(keys[kid])
    elif len(rest) == 1:
        k = keys.get(rest[0])
        if k is None:
            return _err(404, "Request_ResourceNotFound", f"Resource '{rest[0]}' does not exist.")
        if method == "GET":
            if "key" in str((query or {}).get("$select", "")):
                store.audit("Read BitLocker key", "KeyManagement", next((d["displayName"] for d in store.devices.values() if d["deviceId"] == k["deviceId"]), k["deviceId"]))
                return 200, dict(k)
            return 200, view(k)
        if method == "DELETE":
            keys.pop(rest[0])
            store.audit("Delete BitLocker key", "KeyManagement", k["deviceId"])
            return 204, None
    return _err(405, "Request_UnsupportedQuery", method)


# ── administrative unit members ───────────────────────────────────────────
def au_members(store, auid, method, rest, body):
    au = store.administrative_units.get(auid)
    if au is None:
        return _err(404, "Request_ResourceNotFound", f"Resource '{auid}' does not exist.")
    mem = au.setdefault("_members", [])
    if method == "GET" and not rest:
        out = []
        for mid in mem:
            o = store.users.get(mid) or store.groups.get(mid) or store.devices.get(mid)
            if o:
                t = "user" if mid in store.users else "group" if mid in store.groups else "device"
                out.append({"@odata.type": f"#microsoft.graph.{t}", "id": mid, "displayName": o.get("displayName")})
        return 200, {"value": out}
    if method == "POST" and rest == ["$ref"]:
        mid = str(body.get("@odata.id", "")).rstrip("/").rsplit("/", 1)[-1]
        if not (mid in store.users or mid in store.groups or mid in store.devices):
            return _err(404, "Request_ResourceNotFound", f"Resource '{mid}' does not exist.")
        if mid not in mem:
            mem.append(mid)
        store.audit("Add member to administrative unit", "AdministrativeUnit", au["displayName"])
        return 204, None
    if method == "DELETE" and len(rest) == 2 and rest[1] == "$ref":
        if rest[0] in mem:
            mem.remove(rest[0])
        store.audit("Remove member from administrative unit", "AdministrativeUnit", au["displayName"])
        return 204, None
    return _err(405, "Request_UnsupportedQuery", method)


# ── per-user MFA ─────────────────────────────────────────────────────────
def mfa_requirements(store, uid, method, body):
    u = store.users.get(uid)
    if u is None:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    if method == "GET":
        return 200, {"perUserMfaState": u.get("_mfa_state", "disabled")}
    if method == "PATCH":
        s = body.get("perUserMfaState")
        if s not in ("disabled", "enabled", "enforced"):
            return _err(400, "Request_BadRequest", "perUserMfaState must be disabled, enabled or enforced.")
        u["_mfa_state"] = s
        store.audit("Update per-user MFA", "UserManagement", u["displayName"])
        return 204, None
    return _err(405, "Request_UnsupportedQuery", method)
