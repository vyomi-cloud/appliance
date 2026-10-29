# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure ARM resource-model extensions shared by the offline ARM dispatcher
(``providers/azure_services.handle_arm``) and Nano's ``core/azure_arm_core.AzureArm``.

Substrate-free (stdlib only) so the SAME file runs on the appliance and under
Pyodide. Everything lives in the shared flat ARM state map (lower-cased resource
id → record), so it is space-scoped and persisted by the existing seams.

What it models (real ARM shapes, so the portal-style blades and the native SDKs
read the same data):

  * **Management locks** — ``Microsoft.Authorization/locks`` at subscription,
    resource-group and resource scope (``{scope}/providers/Microsoft.Authorization/
    locks/{name}``), and their enforcement: a ``CanNotDelete`` lock rejects DELETE,
    a ``ReadOnly`` lock rejects every write (PUT/PATCH/DELETE/POST) on the locked
    scope and everything under it with ``409 ScopeLocked``.
  * **Managed identity** — the ``identity`` block of any resource (system and user
    assigned; principal/tenant/client ids are allocated on enable) and the
    ``{scope}/providers/Microsoft.ManagedIdentity/identities/default`` read.
  * **Resource health** — ``{scope}/providers/Microsoft.ResourceHealth/
    availabilityStatuses/current``, derived from the resource's own state
    (provisioning state, VM power state, app running state).
  * **Role assignments at a scope** — ``{scope}/providers/Microsoft.Authorization/
    roleAssignments`` (GET lists the assignments that apply, inherited ones included;
    PUT creates one at that scope).
  * **Other extension resources** (``diagnosticSettings``, …) — plain CRUD at scope.
  * **Network interfaces + public IPs** — ``Microsoft.Network/networkInterfaces`` /
    ``publicIPAddresses`` with private-IP allocation from the referenced subnet,
    public-IP allocation, and the NIC↔VM / NIC↔NSG / PIP↔NIC back-references.
  * **VM auto-shutdown** — ``Microsoft.DevTestLab/schedules`` (``shutdown-computevm-{vm}``).
  * **VM run commands** — ``virtualMachines/{vm}/runCommands/{name}`` (managed run
    command, executed on PUT and recorded with its instance view) and the
    ``virtualMachines/{vm}/runCommand`` action. Execution goes through an optional
    ``executor(vm_record, script) -> (exit_code, stdout, stderr) | None`` supplied by
    the host (the appliance execs in the VM's container); with no guest runtime the
    run is recorded as failed — no output is invented.
  * **VM restore points** — ``Microsoft.Compute/restorePointCollections/{c}/restorePoints/{p}``
    capturing the source VM's configuration.

``route(...)`` returns ``None`` when the request is not one of these, else
``{"status","headers","body","scope","type","name"}`` (``scope`` = the resource id
whose activity log the operation belongs to).
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import ipaddress
import uuid
from urllib.parse import quote

TENANT_ID = "00000000-0000-0000-0000-000000000000"   # the simulator's Entra tenant (Key Vault default)
LOCK_LEVELS = ("CanNotDelete", "ReadOnly")

LOCK_T = "Microsoft.Authorization/locks"
RA_T = "Microsoft.Authorization/roleAssignments"
NIC_T = "Microsoft.Network/networkInterfaces"
PIP_T = "Microsoft.Network/publicIPAddresses"
SCHED_T = "Microsoft.DevTestLab/schedules"
RUNCMD_T = "Microsoft.Compute/virtualMachines/runCommands"
RPC_T = "Microsoft.Compute/restorePointCollections"
RP_T = "Microsoft.Compute/restorePointCollections/restorePoints"
VM_T = "microsoft.compute/virtualmachines"

# Resource types this module owns outright (not in the console catalog).
OWNED_TYPES = {t.lower() for t in (LOCK_T, NIC_T, PIP_T, SCHED_T, RPC_T, RP_T, RUNCMD_T)}


# ── helpers ──────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ok(body=None, status=200, scope="", typ="", name=""):
    return {"status": status, "headers": {}, "body": body, "scope": scope, "type": typ, "name": name}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "scope": "", "type": "", "name": ""}


def _view(rec):
    return {k: v for k, v in rec.items() if not str(k).startswith("_")}


def _rg_of(rid: str):
    parts = rid.split("/")
    for i, p in enumerate(parts):
        if p.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def scope_id(sub: str, rg, after) -> str:
    s = f"/subscriptions/{sub}"
    if rg:
        s += f"/resourceGroups/{rg}"
    if after:
        s += "/providers/" + "/".join(after)
    return s


def _type_of_scope(after) -> str:
    """``[ns, t1, n1, t2, n2]`` → ``ns/t1/t2``."""
    if not after:
        return ""
    return "/".join([after[0]] + [after[i] for i in range(1, len(after), 2)])


def _under(rid: str, scope: str) -> bool:
    r, s = rid.lower().rstrip("/"), scope.lower().rstrip("/")
    return r == s or r.startswith(s + "/")


def _of_type(state, typ):
    t = typ.lower()
    return [r for r in list(state.values()) if isinstance(r, dict) and str(r.get("_type", "")).lower() == t]


def _new_rec(rid, name, typ, location=None, scope=None):
    rec = {"id": rid, "name": name, "type": typ, "properties": {},
           "_type": typ, "_sub": rid.split("/")[2] if rid.count("/") >= 2 else "",
           "_rg": _rg_of(rid), "_created": _now()}
    if location is not None:
        rec["location"] = location
    if scope is not None:
        rec["_scope"] = scope
    return rec


def _payload_props(payload):
    p = (payload or {}).get("properties")
    return p if isinstance(p, dict) else {}


# ── locks ────────────────────────────────────────────────────────────────────
def locks_at(state, rid: str):
    """Locks that apply to ``rid``: on it or on any scope above it."""
    return [r for r in _of_type(state, LOCK_T) if _under(rid, r.get("_scope", ""))]


def lock_conflict(state, rid: str, method: str):
    """409 ScopeLocked error when a lock forbids ``method`` on ``rid``, else None.
    Lock management itself is never blocked by locks."""
    m = (method or "").upper()
    if m not in ("PUT", "PATCH", "DELETE", "POST"):
        return None
    if "/providers/microsoft.authorization/locks" in rid.lower():
        return None
    blocking = []
    for lk in locks_at(state, rid):
        lvl = (lk.get("properties") or {}).get("level", "")
        if lvl == "ReadOnly" or (lvl == "CanNotDelete" and m == "DELETE"):
            blocking.append(lk.get("_scope", ""))
    if not blocking:
        return None
    op = "delete" if m == "DELETE" else "write"
    scopes = ",".join(f"'{s}'" for s in dict.fromkeys(blocking))
    return _err(409, "ScopeLocked",
                f"The scope '{rid}' cannot perform {op} operation because following scope(s) are locked: "
                f"{scopes}. Please remove the lock and try again.")


def _locks(state, method, scope, rest, payload):
    # rest = ["locks"] or ["locks", name]
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in locks_at(state, scope)]})
    name = rest[1]
    rid = f"{scope}/providers/{LOCK_T}/{name}"
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        if not rec:
            return _err(404, "LockNotFound", f"The lock '{name}' could not be found.")
        return _ok(_view(rec))
    if method == "DELETE":
        rec = state.pop(key, None)
        return _ok(None, 200 if rec else 204, scope, LOCK_T, name)
    if method in ("PUT", "PATCH"):
        props = _payload_props(payload)
        old = state.get(key)
        level = props.get("level", (old or {}).get("properties", {}).get("level"))
        if level not in LOCK_LEVELS:
            return _err(400, "LockLevelInvalid",
                        f"The lock level '{level}' is invalid. Allowed values: {', '.join(LOCK_LEVELS)}.")
        notes = props.get("notes", (old or {}).get("properties", {}).get("notes", ""))
        if notes and len(str(notes)) > 512:
            return _err(400, "LockNotesTooLong", "Lock notes can be at most 512 characters.")
        rec = old or _new_rec(rid, name, LOCK_T, scope=scope)
        rec["properties"] = {"level": level, "notes": notes or "",
                             "owners": props.get("owners", (old or {}).get("properties", {}).get("owners", []))}
        state[key] = rec
        return _ok(_view(rec), 200 if old else 201, scope, LOCK_T, name)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── managed identity ─────────────────────────────────────────────────────────
_ID_TYPES = {"none": "None", "systemassigned": "SystemAssigned", "userassigned": "UserAssigned",
             "systemassigned,userassigned": "SystemAssigned, UserAssigned"}


def validate_identity(payload):
    idn = (payload or {}).get("identity")
    if idn is None:
        return None
    if not isinstance(idn, dict):
        return _err(400, "InvalidIdentity", "identity must be an object.")
    t = str(idn.get("type") or "None").replace(" ", "").lower()
    if t not in _ID_TYPES:
        return _err(400, "InvalidIdentityType",
                    f"The identity type '{idn.get('type')}' is invalid. Allowed: None, SystemAssigned, "
                    "UserAssigned, 'SystemAssigned, UserAssigned'.")
    if "userassigned" in t and not isinstance(idn.get("userAssignedIdentities"), dict):
        return _err(400, "InvalidIdentity", "userAssignedIdentities is required for a UserAssigned identity.")
    return None


def apply_identity(rec: dict, payload) -> None:
    """Apply ``payload.identity`` to ``rec`` the way ARM does: enabling a system-assigned
    identity allocates its service principal (principalId) in the tenant; disabling it
    drops the principal; user-assigned identities get their principal/client ids."""
    idn = (payload or {}).get("identity")
    if not isinstance(idn, dict):
        return
    t = _ID_TYPES.get(str(idn.get("type") or "None").replace(" ", "").lower(), "None")
    cur = rec.get("identity") if isinstance(rec.get("identity"), dict) else {}
    out = {"type": t}
    if "SystemAssigned" in t:
        out["principalId"] = cur.get("principalId") or str(uuid.uuid4())
        out["tenantId"] = cur.get("tenantId") or TENANT_ID
    if "UserAssigned" in t:
        uai = dict(cur.get("userAssignedIdentities") or {})
        for k, v in (idn.get("userAssignedIdentities") or {}).items():
            if v is None:
                uai.pop(k, None)
            else:
                uai.setdefault(k, {"principalId": str(uuid.uuid4()), "clientId": str(uuid.uuid4())})
        out["userAssignedIdentities"] = uai
    rec["identity"] = out


def _identity_default(parent_rec, scope):
    idn = parent_rec.get("identity") or {}
    if "SystemAssigned" not in str(idn.get("type", "")):
        return _err(404, "NotFound", f"No system-assigned identity is enabled on '{scope}'.")
    pid = idn.get("principalId")
    return _ok({"id": f"{scope}/providers/Microsoft.ManagedIdentity/identities/default", "name": "default",
                "type": "Microsoft.ManagedIdentity/identities", "location": parent_rec.get("location"),
                "properties": {"tenantId": idn.get("tenantId", TENANT_ID), "principalId": pid,
                               "clientId": str(uuid.uuid5(uuid.NAMESPACE_URL, "client:" + str(pid)))}})


# ── resource health ──────────────────────────────────────────────────────────
def availability(rec: dict) -> dict:
    """Resource Health availability status derived from the resource's own state."""
    p = rec.get("properties") or {}
    t = str(rec.get("_type") or rec.get("type") or "").lower()
    state, summary, reason = "Available", "There aren't any known Azure platform problems affecting this resource.", ""
    prov = str(p.get("provisioningState") or "")
    if prov.lower() == "failed":
        state, summary, reason = "Unavailable", "The last operation on this resource failed to provision it.", "Unplanned"
    elif t == VM_T:
        rt = p.get("runtime") if isinstance(p.get("runtime"), dict) else {}
        power = str(rt.get("containerStatus") or str(p.get("powerState") or "").replace("PowerState/", "") or "running").lower()
        if power in ("stopped", "deallocated", "exited", "stopping", "deallocating"):
            state = "Unavailable"
            summary = (f"This virtual machine is {power} as requested by an authorized user or process. "
                       "It will be available again after it is started.")
            reason = "Customer Initiated"
        else:
            summary = "There aren't any known Azure platform problems affecting this virtual machine."
    elif t == "microsoft.web/sites" and str(p.get("state", "")).lower() == "stopped":
        state, summary, reason = "Unavailable", "This app is stopped as requested by an authorized user.", "Customer Initiated"
    elif t == "microsoft.app/containerapps" and str(p.get("runningStatus", "")).lower() == "stopped":
        state, summary, reason = "Unavailable", "This container app is stopped as requested by an authorized user.", "Customer Initiated"
    elif t == "microsoft.sql/servers" and p.get("state") and str(p.get("state")).lower() != "ready":
        state, summary, reason = "Unavailable", f"This server is {p.get('state')}.", "Unplanned"
    elif str(p.get("status", "")).lower() in ("disabled", "suspended"):
        state, summary, reason = "Unavailable", f"This resource is {p.get('status')}.", "Customer Initiated"
    ts = rec.get("_changed") or rec.get("_created") or _now()
    out = {"availabilityState": state, "summary": summary, "reportedTime": _now(), "occuredTime": ts,
           "detailedStatus": "", "reasonChronicity": "Persistent"}
    if reason:
        out["reasonType"] = reason
    return out


def _health(parent_rec, scope, rest):
    body = {"id": f"{scope}/providers/Microsoft.ResourceHealth/availabilityStatuses/current", "name": "current",
            "type": "Microsoft.ResourceHealth/AvailabilityStatuses", "location": parent_rec.get("location"),
            "properties": availability(parent_rec)}
    if len(rest) == 1:
        return _ok({"value": [body]})
    if rest[1].lower() != "current":
        return _err(404, "NotFound", "Only the 'current' availability status is available.")
    return _ok(body)


# ── role assignments at a scope ──────────────────────────────────────────────
def _role_assignments(state, method, scope, rest, payload):
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        out = []
        for r in _of_type(state, RA_T):
            sc = (r.get("properties") or {}).get("scope") or r.get("_scope") or \
                r.get("id", "").rsplit("/providers/Microsoft.Authorization/roleAssignments/", 1)[0]
            # atScope + inherited: assignments at this scope or above it, and those below it.
            if _under(scope, sc) or _under(sc, scope):
                out.append(_view(r))
        return _ok({"value": out})
    name = rest[1]
    rid = f"{scope}/providers/{RA_T}/{name}"
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        return _ok(_view(rec)) if rec else _err(404, "RoleAssignmentNotFound", f"Role assignment '{name}' not found.")
    if method == "DELETE":
        rec = state.pop(key, None)
        return _ok(_view(rec) if rec else None, 200 if rec else 204, scope, RA_T, name)
    if method == "PUT":
        props = _payload_props(payload)
        if not props.get("roleDefinitionId") or not props.get("principalId"):
            return _err(400, "InvalidRoleAssignment", "properties.roleDefinitionId and properties.principalId are required.")
        rec = state.get(key) or _new_rec(rid, name, RA_T, scope=scope)
        rec["properties"] = {"roleDefinitionId": props["roleDefinitionId"], "principalId": props["principalId"],
                             "principalType": props.get("principalType", "User"), "scope": scope,
                             "description": props.get("description", ""), "createdOn": rec.get("_created")}
        state[key] = rec
        return _ok(_view(rec), 201, scope, RA_T, name)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── generic extension resources (diagnosticSettings, …) ─────────────────────
def _generic_ext(state, method, scope, ns, rest, payload):
    typ = ns + "/" + rest[0]
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _of_type(state, typ)
                              if str(r.get("_scope", "")).lower() == scope.lower()]})
    name = rest[1]
    rid = f"{scope}/providers/{typ}/{name}"
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Resource '{rid}' not found.")
    if method == "DELETE":
        rec = state.pop(key, None)
        return _ok(None, 200 if rec else 204, scope, typ, name)
    if method in ("PUT", "PATCH"):
        old = state.get(key)
        rec = old or _new_rec(rid, name, typ, scope=scope)
        props = dict(rec.get("properties") or {}) if method == "PATCH" else {}
        props.update(_payload_props(payload))
        rec["properties"] = props
        state[key] = rec
        return _ok(_view(rec), 200 if old else 201, scope, typ, name)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── networking: NICs + public IPs ────────────────────────────────────────────
def _find_subnet(state, subnet_id: str):
    """(vnet_rec, subnet_dict, prefix) for a subnet id, or (None, None, None)."""
    sid = str(subnet_id or "")
    if "/subnets/" not in sid.lower():
        return None, None, None
    i = sid.lower().rindex("/subnets/")
    vnet_id, sname = sid[:i], sid[i + len("/subnets/"):].strip("/")
    vnet = state.get(vnet_id.lower())
    if not vnet:
        return None, None, None
    for s in (vnet.get("properties") or {}).get("subnets") or []:
        if isinstance(s, dict) and str(s.get("name", "")).lower() == sname.lower():
            return vnet, s, (s.get("properties") or {}).get("addressPrefix") or s.get("addressPrefix")
    child = state.get(sid.lower())
    if child:
        return vnet, child, (child.get("properties") or {}).get("addressPrefix")
    return vnet, None, None


def _used_private_ips(state, exclude_key=""):
    used = set()
    for r in _of_type(state, NIC_T):
        if r.get("id", "").lower() == exclude_key:
            continue
        for ipc in (r.get("properties") or {}).get("ipConfigurations") or []:
            ip = (ipc.get("properties") or {}).get("privateIPAddress")
            if ip:
                used.add(ip)
    return used


def _alloc_private_ip(state, prefix, exclude_key=""):
    net = ipaddress.ip_network(str(prefix), strict=False)
    used = _used_private_ips(state, exclude_key)
    # Azure reserves the first four addresses and the last one of every subnet.
    for n, host in enumerate(net.hosts()):
        if n < 3:
            continue
        if str(host) == str(net.broadcast_address - 0):
            break
        if str(host) not in used:
            return str(host)
    return None


def _alloc_public_ip(state, seed: str):
    used = {(r.get("properties") or {}).get("ipAddress") for r in _of_type(state, PIP_T)}
    h = hashlib.sha256(seed.encode()).digest()
    for k in range(256):
        ip = f"20.{(h[0] + k) % 200 + 20}.{h[1]}.{(h[2] + k) % 250 + 4}"
        if ip not in used:
            return ip
    return None


def _mac(seed: str) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()[:10].upper()
    return "00-0D-3A-" + "-".join(h[i:i + 2] for i in range(0, 6, 2))


def _pip(state, method, sub, rg, after, payload):
    if len(after) == 2:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _of_type(state, PIP_T)
                              if rg is None or str(r.get("_rg") or "").lower() == rg.lower()]})
    name = after[2]
    rid = scope_id(sub, rg, after[:3])
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Resource '{rid}' not found.")
    if method == "DELETE":
        rec = state.get(key)
        if rec and (rec.get("properties") or {}).get("ipConfiguration"):
            return _err(400, "PublicIPAddressInUse",
                        f"Public IP address {rid} can not be deleted since it is still allocated to resource "
                        f"{rec['properties']['ipConfiguration'].get('id')}.")
        state.pop(key, None)
        return _ok(None, 200 if rec else 204, rid, PIP_T, name)
    if method in ("PUT", "PATCH"):
        old = state.get(key)
        rec = old or _new_rec(rid, name, PIP_T, location=(payload or {}).get("location") or "eastus")
        props = rec.setdefault("properties", {})
        pp = _payload_props(payload)
        sku = (payload or {}).get("sku") if isinstance((payload or {}).get("sku"), dict) else (rec.get("sku") or {"name": "Standard", "tier": "Regional"})
        rec["sku"] = {"name": sku.get("name", "Standard"), "tier": sku.get("tier", "Regional")}
        method_ = pp.get("publicIPAllocationMethod") or props.get("publicIPAllocationMethod") or \
            ("Static" if rec["sku"]["name"] == "Standard" else "Dynamic")
        if rec["sku"]["name"] == "Standard" and method_ != "Static":
            return _err(400, "StandardSkuPublicIPAddressesNotAllowedWithDynamicAllocation",
                        "Standard sku public IP addresses must use Static allocation.")
        props.update({k: v for k, v in pp.items() if k not in ("ipAddress", "ipConfiguration")})
        props["publicIPAllocationMethod"] = method_
        props.setdefault("publicIPAddressVersion", "IPv4")
        props.setdefault("idleTimeoutInMinutes", 4)
        props.setdefault("resourceGuid", str(uuid.uuid4()))
        if not props.get("ipAddress"):
            props["ipAddress"] = _alloc_public_ip(state, rid.lower())
        dns = props.get("dnsSettings") if isinstance(props.get("dnsSettings"), dict) else None
        if dns and dns.get("domainNameLabel"):
            dns["fqdn"] = f"{dns['domainNameLabel']}.{rec.get('location', 'eastus')}.cloudapp.azure.com"
        props["provisioningState"] = "Succeeded"
        if isinstance((payload or {}).get("tags"), dict):
            rec["tags"] = dict(payload["tags"])
        rec.setdefault("tags", {})
        state[key] = rec
        return _ok(_view(rec), 200 if old else 201, rid, PIP_T, name)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _set_backref_list(rec, field, rid, add: bool):
    props = rec.setdefault("properties", {})
    lst = [x for x in props.get(field) or [] if str(x.get("id", "")).lower() != rid.lower()]
    if add:
        lst.append({"id": rid})
    props[field] = lst


def _nic(state, method, sub, rg, after, payload):
    if len(after) == 2:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _of_type(state, NIC_T)
                              if rg is None or str(r.get("_rg") or "").lower() == rg.lower()]})
    name = after[2]
    rid = scope_id(sub, rg, after[:3])
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Resource '{rid}' not found.")
    if method == "DELETE":
        rec = state.get(key)
        if rec and (rec.get("properties") or {}).get("virtualMachine"):
            return _err(400, "NicInUse",
                        f"Network Interface {rid} is used by existing resource "
                        f"{rec['properties']['virtualMachine'].get('id')}. In order to delete the network interface, "
                        "it must be dissociated from the resource.")
        if rec:
            _nic_unlink(state, rec)
            state.pop(key, None)
        return _ok(None, 200 if rec else 204, rid, NIC_T, name)
    if method in ("PUT", "PATCH"):
        old = state.get(key)
        pp = _payload_props(payload)
        ipcs_in = pp.get("ipConfigurations")
        if ipcs_in is None and old:
            ipcs_in = old["properties"].get("ipConfigurations")
        if not isinstance(ipcs_in, list) or not ipcs_in:
            return _err(400, "NetworkInterfaceMustHaveAtLeastOneIpConfiguration",
                        f"Network interface {rid} must have one or more IP configurations.")
        nsg_ref = pp.get("networkSecurityGroup", (old or {}).get("properties", {}).get("networkSecurityGroup"))
        if nsg_ref and not state.get(str(nsg_ref.get("id", "")).lower()):
            return _err(400, "InvalidResourceReference",
                        f"Resource {nsg_ref.get('id')} referenced by resource {rid} was not found.")
        new_ipcs = []
        for n, ipc in enumerate(ipcs_in):
            ip_props = dict(ipc.get("properties") or {})
            sub_id = (ip_props.get("subnet") or {}).get("id")
            vnet, subnet, prefix = _find_subnet(state, sub_id)
            if not subnet or not prefix:
                return _err(400, "InvalidResourceReference",
                            f"Resource {sub_id} referenced by resource {rid} was not found.")
            pip_id = (ip_props.get("publicIPAddress") or {}).get("id")
            if pip_id:
                pip = state.get(pip_id.lower())
                if not pip:
                    return _err(400, "InvalidResourceReference",
                                f"Resource {pip_id} referenced by resource {rid} was not found.")
                other = (pip.get("properties") or {}).get("ipConfiguration")
                if other and not str(other.get("id", "")).lower().startswith(key + "/"):
                    return _err(400, "PublicIPAddressInUse",
                                f"Public IP address {pip_id} is already allocated to {other.get('id')}.")
            alloc = ip_props.get("privateIPAllocationMethod") or "Dynamic"
            ip = ip_props.get("privateIPAddress") if alloc == "Static" else None
            if alloc == "Static":
                if not ip or ipaddress.ip_address(ip) not in ipaddress.ip_network(prefix, strict=False):
                    return _err(400, "PrivateIPAddressNotInSubnet",
                                f"IP address {ip} does not belong to subnet {sub_id}.")
                if ip in _used_private_ips(state, key):
                    return _err(400, "PrivateIPAddressInUse", f"IP address {ip} is already in use.")
            else:
                prev = None
                for oc in (old or {}).get("properties", {}).get("ipConfigurations") or []:
                    if oc.get("name") == ipc.get("name") and (oc.get("properties") or {}).get("subnet", {}).get("id", "").lower() == str(sub_id).lower():
                        prev = (oc.get("properties") or {}).get("privateIPAddress")
                ip = prev or _alloc_private_ip(state, prefix, key)
                if not ip:
                    return _err(400, "SubnetIsFull", f"Subnet {sub_id} has no free IP addresses.")
            ipc_name = ipc.get("name") or f"ipconfig{n + 1}"
            ip_props.update({"privateIPAddress": ip, "privateIPAllocationMethod": alloc,
                             "privateIPAddressVersion": "IPv4", "provisioningState": "Succeeded",
                             "primary": n == 0 if "primary" not in ip_props else ip_props["primary"]})
            new_ipcs.append({"id": f"{rid}/ipConfigurations/{ipc_name}", "name": ipc_name,
                             "type": "Microsoft.Network/networkInterfaces/ipConfigurations",
                             "properties": ip_props})
        if old:
            _nic_unlink(state, old)
        rec = old or _new_rec(rid, name, NIC_T, location=(payload or {}).get("location") or "eastus")
        props = rec.setdefault("properties", {})
        props.update({k: v for k, v in pp.items() if k not in ("ipConfigurations", "virtualMachine", "macAddress")})
        props["ipConfigurations"] = new_ipcs
        if nsg_ref:
            props["networkSecurityGroup"] = {"id": nsg_ref["id"]}
        else:
            props.pop("networkSecurityGroup", None)
        props.setdefault("resourceGuid", str(uuid.uuid4()))
        props.setdefault("enableAcceleratedNetworking", False)
        props.setdefault("enableIPForwarding", False)
        props["macAddress"] = props.get("macAddress") or _mac(key)
        props["provisioningState"] = "Succeeded"
        if isinstance((payload or {}).get("tags"), dict):
            rec["tags"] = dict(payload["tags"])
        rec.setdefault("tags", {})
        state[key] = rec
        _nic_link(state, rec)
        return _ok(_view(rec), 200 if old else 201, rid, NIC_T, name)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _nic_link(state, nic):
    rid = nic["id"]
    nsg = (nic.get("properties") or {}).get("networkSecurityGroup")
    if nsg and state.get(nsg["id"].lower()):
        _set_backref_list(state[nsg["id"].lower()], "networkInterfaces", rid, True)
    for ipc in nic["properties"].get("ipConfigurations") or []:
        pip_id = ((ipc.get("properties") or {}).get("publicIPAddress") or {}).get("id")
        if pip_id and state.get(pip_id.lower()):
            state[pip_id.lower()].setdefault("properties", {})["ipConfiguration"] = {"id": ipc["id"]}


def _nic_unlink(state, nic):
    rid = nic["id"]
    nsg = (nic.get("properties") or {}).get("networkSecurityGroup")
    if nsg and state.get(str(nsg.get("id", "")).lower()):
        _set_backref_list(state[nsg["id"].lower()], "networkInterfaces", rid, False)
    for ipc in (nic.get("properties") or {}).get("ipConfigurations") or []:
        pip_id = ((ipc.get("properties") or {}).get("publicIPAddress") or {}).get("id")
        pip = state.get(str(pip_id or "").lower())
        if pip and str(((pip.get("properties") or {}).get("ipConfiguration") or {}).get("id", "")).lower().startswith(rid.lower() + "/"):
            pip["properties"].pop("ipConfiguration", None)


# ── VM hooks (network profile ↔ NIC back-references) ─────────────────────────
def _nic_refs(vm_props):
    np_ = (vm_props or {}).get("networkProfile") or {}
    return [r for r in np_.get("networkInterfaces") or [] if isinstance(r, dict) and r.get("id")]


def validate_vm(state, rid: str, payload):
    """400 when the VM's networkProfile references a NIC that doesn't exist or is
    attached to another VM (as ARM does), else None."""
    for ref in _nic_refs(_payload_props(payload)):
        nic = state.get(ref["id"].lower())
        if not nic:
            return _err(400, "NotFound", f"Network interface '{ref['id']}' not found.")
        owner = (nic.get("properties") or {}).get("virtualMachine")
        if owner and owner.get("id", "").lower() != rid.lower():
            return _err(409, "NicInUse", f"Network interface '{ref['id']}' is attached to {owner.get('id')}.")
    return validate_identity(payload)


def after_vm_upsert(state, vm):
    refs = {r["id"].lower() for r in _nic_refs(vm.get("properties"))}
    for nic in _of_type(state, NIC_T):
        k = nic["id"].lower()
        owner = (nic.get("properties") or {}).get("virtualMachine")
        if k in refs:
            nic["properties"]["virtualMachine"] = {"id": vm["id"]}
        elif owner and owner.get("id", "").lower() == vm["id"].lower():
            nic["properties"].pop("virtualMachine", None)


def on_delete(state, rec):
    """Cascade a resource delete the way ARM does: child and extension resources
    under it go with it; a VM releases its NICs (deleting those whose deleteOption is
    Delete, with their public IPs likewise) and its auto-shutdown schedule."""
    if not isinstance(rec, dict):
        return
    rid = str(rec.get("id", ""))
    low = rid.lower()
    for k in [k for k in list(state.keys()) if str(k).startswith(low + "/")]:
        state.pop(k, None)
    if str(rec.get("_type", "")).lower() == VM_T:
        for ref in _nic_refs(rec.get("properties")):
            nic = state.get(ref["id"].lower())
            if not nic:
                continue
            nic["properties"].pop("virtualMachine", None)
            if str(ref.get("properties", {}).get("deleteOption", ref.get("deleteOption", ""))).lower() == "delete":
                pips = [((c.get("properties") or {}).get("publicIPAddress") or {}) for c in nic["properties"].get("ipConfigurations") or []]
                _nic_unlink(state, nic)
                state.pop(ref["id"].lower(), None)
                for p in pips:
                    if p.get("id") and str(p.get("properties", {}).get("deleteOption", p.get("deleteOption", ""))).lower() == "delete":
                        state.pop(p["id"].lower(), None)
        for s in _of_type(state, SCHED_T):
            if str((s.get("properties") or {}).get("targetResourceId", "")).lower() == low:
                state.pop(s["id"].lower(), None)


# ── VM auto-shutdown (DevTestLab global schedules) ───────────────────────────
def _schedules(state, method, sub, rg, after, payload):
    if len(after) == 2:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _of_type(state, SCHED_T)
                              if rg is None or str(r.get("_rg") or "").lower() == rg.lower()]})
    name = after[2]
    rid = scope_id(sub, rg, after[:3])
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The schedule '{name}' was not found.")
    if method == "DELETE":
        rec = state.pop(key, None)
        tgt = (rec or {}).get("properties", {}).get("targetResourceId", rid)
        return _ok(None, 200 if rec else 204, tgt, SCHED_T, name)
    if method in ("PUT", "PATCH"):
        old = state.get(key)
        pp = _payload_props(payload)
        props = dict((old or {}).get("properties") or {}) if method == "PATCH" else {}
        props.update(pp)
        task = props.get("taskType") or "ComputeVmShutdownTask"
        tgt = props.get("targetResourceId")
        if not tgt or not state.get(str(tgt).lower()):
            return _err(400, "InvalidTargetResource", f"Target resource '{tgt}' was not found.")
        t = str((props.get("dailyRecurrence") or {}).get("time") or "")
        if len(t) != 4 or not t.isdigit() or int(t[:2]) > 23 or int(t[2:]) > 59:
            return _err(400, "InvalidScheduleTime", "dailyRecurrence.time must be HHmm (24-hour), e.g. 1900.")
        st = props.get("status") or "Enabled"
        if st not in ("Enabled", "Disabled"):
            return _err(400, "InvalidStatus", "status must be Enabled or Disabled.")
        ns = dict(props.get("notificationSettings") or {})
        ns.setdefault("status", "Disabled")
        ns.setdefault("timeInMinutes", 30)
        props.update({"status": st, "taskType": task, "dailyRecurrence": {"time": t},
                      "timeZoneId": props.get("timeZoneId") or "UTC", "notificationSettings": ns,
                      "targetResourceId": tgt, "provisioningState": "Succeeded",
                      "createdDate": (old or {}).get("properties", {}).get("createdDate") or _now()})
        rec = old or _new_rec(rid, name, SCHED_T, location=(payload or {}).get("location") or "eastus")
        rec["properties"] = props
        rec.setdefault("tags", {})
        state[key] = rec
        return _ok(_view(rec), 200 if old else 201, tgt, SCHED_T, name)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── VM run commands ──────────────────────────────────────────────────────────
def _vm_power(vm):
    p = vm.get("properties") or {}
    rt = p.get("runtime") if isinstance(p.get("runtime"), dict) else {}
    return str(rt.get("containerStatus") or str(p.get("powerState") or "").replace("PowerState/", "") or "running").lower()


def _script_of(src):
    if isinstance(src.get("script"), list):
        return "\n".join(str(x) for x in src["script"])
    if src.get("script"):
        return str(src["script"])
    cid = str(src.get("commandId") or "")
    if cid == "ifconfig":
        return "ip addr"
    return ""


def _execute(vm, script, executor):
    start = _now()
    res = None
    if executor is not None:
        try:
            res = executor(vm, script)
        except Exception as exc:                       # executor failure = failed run, recorded
            return {"executionState": "Failed", "executionMessage": f"Execution failed: {str(exc)[:300]}",
                    "exitCode": -1, "output": "", "error": str(exc)[:2000], "startTime": start, "endTime": _now()}
    if res is None:
        return {"executionState": "Failed", "exitCode": -1, "output": "", "error": "",
                "executionMessage": ("The VM guest agent is not reachable: this virtual machine has no guest "
                                     "runtime (it is metadata-only in this simulator), so the script was not run."),
                "startTime": start, "endTime": _now()}
    code, out, err = res
    return {"executionState": "Succeeded" if code == 0 else "Failed",
            "executionMessage": "" if code == 0 else f"Script exited with code {code}.",
            "exitCode": code, "output": out or "", "error": err or "", "startTime": start, "endTime": _now()}


def _run_commands(state, method, vm_rid, vm, rest, payload, executor):
    # rest = ["runCommands"] or ["runCommands", name]
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_view(r) for r in _of_type(state, RUNCMD_T) if r["id"].lower().startswith(vm_rid.lower() + "/")]
        items.sort(key=lambda r: (r.get("properties") or {}).get("instanceView", {}).get("startTime", ""), reverse=True)
        return _ok({"value": items})
    name = rest[1]
    rid = f"{vm_rid}/runCommands/{name}"
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Run command '{name}' not found.")
    if method == "DELETE":
        rec = state.pop(key, None)
        return _ok(None, 200 if rec else 204, vm_rid, RUNCMD_T, name)
    if method in ("PUT", "PATCH"):
        pp = _payload_props(payload)
        src = pp.get("source") if isinstance(pp.get("source"), dict) else {}
        script = _script_of(src)
        if not script.strip():
            return _err(400, "InvalidParameter", "properties.source must carry a script or a commandId.")
        if _vm_power(vm) not in ("running", "starting"):
            return _err(409, "OperationNotAllowed",
                        "Run command can't be executed because the VM is not running. Start the VM and try again.")
        old = state.get(key)
        rec = old or _new_rec(rid, name, RUNCMD_T, location=vm.get("location"))
        iv = _execute(vm, script, executor)
        rec["properties"] = {"source": src, "parameters": pp.get("parameters") or [],
                             "asyncExecution": bool(pp.get("asyncExecution", False)),
                             "timeoutInSeconds": int(pp.get("timeoutInSeconds") or 0),
                             "provisioningState": "Succeeded" if iv["executionState"] == "Succeeded" else "Failed",
                             "instanceView": iv}
        rec.setdefault("tags", {})
        state[key] = rec
        return _ok(_view(rec), 200 if old else 201, vm_rid, RUNCMD_T, name)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def instance_view(vm, executor=None):
    """``virtualMachines/{vm}/instanceView``: provisioning + power state and the VM
    agent status. The agent is Ready only when the VM has a guest runtime the host
    can reach (``executor`` answers for this VM)."""
    p = vm.get("properties") or {}
    power = _vm_power(vm)
    os_p = p.get("osProfile") or {}
    img = ((p.get("storageProfile") or {}).get("imageReference") or {})
    rt = p.get("runtime") if isinstance(p.get("runtime"), dict) else {}
    guest = bool(rt.get("containerName")) and executor is not None
    now = _now()
    agent = {"vmAgentVersion": "2.11.1.4" if guest else "Unknown",
             "statuses": [{"code": "ProvisioningState/succeeded", "level": "Info", "displayStatus": "Ready",
                           "message": "Guest Agent is running", "time": now}] if guest else
                         [{"code": "ProvisioningState/Unavailable", "level": "Warning", "displayStatus": "Not Ready",
                           "message": "VM agent is unresponsive: this VM has no guest runtime in the simulator (metadata-only).",
                           "time": now}]}
    prov = str(p.get("provisioningState") or "Succeeded").lower()
    return {"computerName": os_p.get("computerName") or vm.get("name"),
            "osName": " ".join(x for x in (img.get("offer"), img.get("sku")) if x) or None,
            "vmAgent": agent, "hyperVGeneration": "V2",
            "statuses": [{"code": "ProvisioningState/" + prov, "level": "Info", "displayStatus": "Provisioning " + prov,
                          "time": vm.get("_changed") or vm.get("_created") or now},
                         {"code": "PowerState/" + power, "level": "Info", "displayStatus": "VM " + power}]}


def _run_command_action(vm_rid, vm, payload, executor):
    script = _script_of(payload or {})
    if not script.strip():
        return _err(400, "InvalidParameter", "commandId and script are required.")
    if _vm_power(vm) not in ("running", "starting"):
        return _err(409, "OperationNotAllowed",
                    "Run command can't be executed because the VM is not running. Start the VM and try again.")
    iv = _execute(vm, script, executor)
    ok = iv["executionState"] == "Succeeded"
    msg = (f"Enable succeeded: \n[stdout]\n{iv['output']}\n[stderr]\n{iv['error']}" if iv["exitCode"] != -1
           else iv["executionMessage"])
    return _ok({"value": [{"code": "ProvisioningState/succeeded" if ok else "ProvisioningState/failed",
                           "level": "Info" if ok else "Error",
                           "displayStatus": "Provisioning succeeded" if ok else "Provisioning failed",
                           "message": msg}]}, 200, vm_rid, "Microsoft.Compute/virtualMachines/runCommand", vm.get("name", ""))


# ── VM restore points ────────────────────────────────────────────────────────
def _restore_points(state, method, sub, rg, after, payload):
    # after = [Microsoft.Compute, restorePointCollections, c?, restorePoints?, p?]
    if len(after) == 2:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_rpc_view(state, r) for r in _of_type(state, RPC_T)
                              if rg is None or str(r.get("_rg") or "").lower() == rg.lower()]})
    cname = after[2]
    crid = scope_id(sub, rg, after[:3])
    ckey = crid.lower()
    if len(after) == 3:
        if method == "GET":
            rec = state.get(ckey)
            return _ok(_rpc_view(state, rec)) if rec else _err(404, "ResourceNotFound", f"Restore point collection '{cname}' not found.")
        if method == "DELETE":
            rec = state.pop(ckey, None)
            for k in [k for k in list(state.keys()) if str(k).startswith(ckey + "/")]:
                state.pop(k, None)
            src = (rec or {}).get("properties", {}).get("source", {}).get("id", crid)
            return _ok(None, 200 if rec else 204, src, RPC_T, cname)
        if method in ("PUT", "PATCH"):
            old = state.get(ckey)
            src = (_payload_props(payload).get("source") or {}).get("id") or (old or {}).get("properties", {}).get("source", {}).get("id")
            vm = state.get(str(src or "").lower())
            if not vm:
                return _err(400, "InvalidParameter", f"Source resource '{src}' was not found.")
            rec = old or _new_rec(crid, cname, RPC_T, location=(payload or {}).get("location") or vm.get("location"))
            rec["properties"] = {"source": {"id": vm["id"], "location": vm.get("location")},
                                 "restorePointCollectionId": (old or {}).get("properties", {}).get("restorePointCollectionId") or str(uuid.uuid4()),
                                 "provisioningState": "Succeeded"}
            rec.setdefault("tags", {})
            state[ckey] = rec
            return _ok(_rpc_view(state, rec), 200 if old else 201, vm["id"], RPC_T, cname)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if len(after) < 4 or after[3].lower() != "restorepoints":
        return _err(404, "ResourceTypeNotSupported", "Unknown restore point collection child.")
    coll = state.get(ckey)
    if not coll:
        return _err(404, "ParentResourceNotFound", f"Restore point collection '{cname}' not found.")
    src_id = coll["properties"]["source"]["id"]
    if len(after) == 4:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": _rps_of(state, ckey)})
    pname = after[4]
    rid = f"{crid}/restorePoints/{pname}"
    key = rid.lower()
    if method == "GET":
        rec = state.get(key)
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"Restore point '{pname}' not found.")
    if method == "DELETE":
        rec = state.pop(key, None)
        return _ok(None, 200 if rec else 204, src_id, RP_T, pname)
    if method == "PUT":
        if state.get(key):
            return _err(409, "Conflict", f"Restore point '{pname}' already exists; restore points are immutable.")
        vm = state.get(src_id.lower())
        if not vm:
            return _err(400, "InvalidParameter", f"Source VM '{src_id}' no longer exists.")
        vp = vm.get("properties") or {}
        rec = _new_rec(rid, pname, RP_T)
        rec["properties"] = {
            "consistencyMode": _payload_props(payload).get("consistencyMode") or "CrashConsistent",
            "timeCreated": _now(), "provisioningState": "Succeeded",
            "sourceMetadata": {"vmId": vp.get("vmId"), "location": vm.get("location"),
                               "hardwareProfile": vp.get("hardwareProfile") or {},
                               "storageProfile": {"osDisk": (vp.get("storageProfile") or {}).get("osDisk") or {},
                                                  "dataDisks": (vp.get("storageProfile") or {}).get("dataDisks") or []},
                               "osProfile": {k: v for k, v in (vp.get("osProfile") or {}).items() if k != "adminPassword"}},
        }
        state[key] = rec
        return _ok(_view(rec), 201, src_id, RP_T, pname)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _rps_of(state, ckey):
    out = [_view(r) for r in _of_type(state, RP_T) if r["id"].lower().startswith(ckey + "/")]
    out.sort(key=lambda r: r["properties"].get("timeCreated", ""), reverse=True)
    return out


def _rpc_view(state, rec):
    v = _view(rec)
    v["properties"] = dict(v.get("properties") or {})
    v["properties"]["restorePoints"] = _rps_of(state, rec["id"].lower())
    return v


# ── storage accounts: keys, account SAS, geo-replication / failover ──────────
STORAGE_T = "microsoft.storage/storageaccounts"
# Azure region pairs (the secondary of a geo-redundant account).
PAIRED_REGIONS = {"eastus": "westus", "westus": "eastus", "eastus2": "centralus", "centralus": "eastus2",
                  "westus2": "westcentralus", "westcentralus": "westus2", "northcentralus": "southcentralus",
                  "southcentralus": "northcentralus", "westus3": "eastus", "northeurope": "westeurope",
                  "westeurope": "northeurope", "uksouth": "ukwest", "ukwest": "uksouth",
                  "southeastasia": "eastasia", "eastasia": "southeastasia", "centralindia": "southindia",
                  "southindia": "centralindia", "japaneast": "japanwest", "japanwest": "japaneast",
                  "australiaeast": "australiasoutheast", "australiasoutheast": "australiaeast"}
GEO_SKUS = ("standard_grs", "standard_ragrs", "standard_gzrs", "standard_ragzrs")
SAS_VERSION = "2022-11-02"


def _initial_storage_keys(account: str):
    # Same derivation the appliance data plane hands SDKs (core/azure_dataplane.storage_keys),
    # so a connection string built from listKeys works against it unchanged.
    seed = hashlib.sha256(("cloudlearn-azure-" + account).encode()).digest()
    return [base64.b64encode(seed).decode(), base64.b64encode(seed[::-1]).decode()]


def _storage_fill(rec):
    """Fields ARM reports on every storage account, kept consistent with its sku."""
    p = rec.setdefault("properties", {})
    name = rec.get("name", "")
    now = _now()
    if not isinstance(rec.get("_keys"), list) or len(rec["_keys"]) != 2:
        rec["_keys"] = _initial_storage_keys(name)
        p["keyCreationTime"] = {"key1": rec.get("_created") or now, "key2": rec.get("_created") or now}
    p.setdefault("creationTime", rec.get("_created") or now)
    p.setdefault("publicNetworkAccess", "Enabled")
    p.setdefault("minimumTlsVersion", "TLS1_2")
    p.setdefault("allowSharedKeyAccess", True)
    p.setdefault("supportsHttpsTrafficOnly", True)
    acl = p.setdefault("networkAcls", {})
    acl.setdefault("defaultAction", "Allow")
    acl.setdefault("bypass", "AzureServices")
    acl.setdefault("ipRules", [])
    acl.setdefault("virtualNetworkRules", [])
    enc = p.setdefault("encryption", {})
    enc.setdefault("keySource", "Microsoft.Storage")
    enc.setdefault("requireInfrastructureEncryption", False)
    svcs = enc.setdefault("services", {})
    for svc in ("blob", "file", "queue", "table"):
        svcs.setdefault(svc, {"enabled": True, "keyType": "Account", "lastEnabledTime": rec.get("_created") or now})
    loc = str(rec.get("location") or "eastus").lower()
    sku = str((rec.get("sku") or {}).get("name") or "Standard_LRS").lower()
    p["primaryLocation"] = loc
    p["statusOfPrimary"] = "available"
    if sku in GEO_SKUS:
        p["secondaryLocation"] = PAIRED_REGIONS.get(loc, "westus")
        p["statusOfSecondary"] = "available"
    else:
        p.pop("secondaryLocation", None)
        p.pop("statusOfSecondary", None)


def after_upsert(state, rec, payload=None) -> None:
    """Type-specific fields ARM computes on write (called by both dispatchers)."""
    t = str(rec.get("_type") or "").lower()
    p = rec.setdefault("properties", {})
    if t == STORAGE_T:
        _storage_fill(rec)
    elif t == STORAGE_T + "/fileservices/shares":
        p.setdefault("shareQuota", 5120)
        p.setdefault("accessTier", "TransactionOptimized")
        p.setdefault("enabledProtocols", "SMB")
        if payload is not None:
            p["lastModifiedTime"] = _now()
    elif t == STORAGE_T + "/tableservices/tables":
        p["tableName"] = rec.get("name")
    elif t == STORAGE_T + "/encryptionscopes":
        p.setdefault("source", "Microsoft.Storage")
        p.setdefault("state", "Enabled")
        p.setdefault("creationTime", rec.get("_created") or _now())
        if payload is not None:
            p["lastModifiedTime"] = _now()


def _storage_keys_view(rec):
    p = rec.get("properties") or {}
    kct = p.get("keyCreationTime") or {}
    return {"keys": [{"keyName": f"key{i + 1}", "value": v, "permissions": "FULL",
                      "creationTime": kct.get(f"key{i + 1}")} for i, v in enumerate(rec["_keys"])]}


def _account_sas(rec, body):
    b = body or {}
    ss, srt, sp, se = (str(b.get(k) or "") for k in ("signedServices", "signedResourceTypes", "signedPermission", "signedExpiry"))
    if not (ss and srt and sp and se):
        return _err(400, "InvalidValuesForRequestParameters",
                    "signedServices, signedResourceTypes, signedPermission and signedExpiry are required.")
    if set(ss) - set("bfqt") or set(srt) - set("sco") or set(sp) - set("rwdlacuptfix"):
        return _err(400, "InvalidValuesForRequestParameters",
                    "signedServices must use b,f,q,t; signedResourceTypes s,c,o; signedPermission r,w,d,l,a,c,u,p,t,f,i,x.")
    st, sip = str(b.get("signedStart") or ""), str(b.get("signedIp") or "")
    if st and se <= st:
        return _err(400, "InvalidValuesForRequestParameters", "signedExpiry must be after signedStart.")
    spr = str(b.get("signedProtocol") or "https,http")
    if spr not in ("https", "https,http"):
        return _err(400, "InvalidValuesForRequestParameters", "signedProtocol must be https or https,http.")
    key_name = str(b.get("keyToSign") or "key1")
    if key_name not in ("key1", "key2"):
        return _err(400, "InvalidValuesForRequestParameters", "keyToSign must be key1 or key2.")
    if (rec.get("properties") or {}).get("allowSharedKeyAccess") is False:
        return _err(403, "KeyBasedAuthenticationNotPermitted",
                    "Key based authentication is not permitted on this storage account (allowSharedKeyAccess is false).")
    key = rec["_keys"][int(key_name[-1]) - 1]
    ses = str(b.get("signedEncryptionScope") or "")
    to_sign = "\n".join([rec.get("name", ""), sp, ss, srt, st, se, sip, spr, SAS_VERSION, ses, ""])
    sig = base64.b64encode(hmac.new(base64.b64decode(key), to_sign.encode("utf-8"), hashlib.sha256).digest()).decode()
    parts = [("sv", SAS_VERSION), ("ss", ss), ("srt", srt), ("sp", sp), ("se", se)]
    if st:
        parts.append(("st", st))
    if sip:
        parts.append(("sip", sip))
    parts.append(("spr", spr))
    if ses:
        parts.append(("ses", ses))
    parts.append(("sig", sig))
    return _ok({"accountSasToken": "&".join(f"{k}={quote(v, safe='')}" for k, v in parts)})


def _storage_action(state, rid, rec, action, payload):
    a = action.lower()
    if a == "listkeys":
        return _ok(_storage_keys_view(rec))
    if a == "regeneratekey":
        kn = str((payload or {}).get("keyName") or "")
        if kn not in ("key1", "key2"):
            return _err(400, "InvalidValuesForRequestParameters", "keyName must be key1 or key2.")
        i = int(kn[-1]) - 1
        rec["_keys"][i] = base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes + uuid.uuid4().bytes + uuid.uuid4().bytes).decode()
        rec.setdefault("properties", {}).setdefault("keyCreationTime", {})[kn] = _now()
        return _ok(_storage_keys_view(rec), 200, rid, "Microsoft.Storage/storageAccounts/regenerateKey", rec.get("name", ""))
    if a == "listaccountsas":
        return _account_sas(rec, payload)
    if a == "failover":
        p = rec.setdefault("properties", {})
        sku = str((rec.get("sku") or {}).get("name") or "").lower()
        if sku not in GEO_SKUS or not p.get("secondaryLocation"):
            return _err(400, "FailoverNotSupported",
                        "Account failover is only supported for geo-redundant (GRS, RA-GRS, GZRS, RA-GZRS) accounts.")
        new_primary = p["secondaryLocation"]
        rec["location"] = new_primary
        rec["sku"] = dict(rec.get("sku") or {}, name="Standard_ZRS" if "gzrs" in sku else "Standard_LRS")
        p["lastGeoFailoverTime"] = _now()
        _storage_fill(rec)
        return _ok(None, 200, rid, "Microsoft.Storage/storageAccounts/failover", rec.get("name", ""))
    return None


# ── entry ────────────────────────────────────────────────────────────────────
def route(state, method, sub, rg, after, payload=None, query=None, executor=None):
    """Serve the request if it is one this module models, else None.
    ``after`` = the path segments after the first ``/providers/``."""
    method = (method or "GET").upper()
    if len(after) < 2:
        return None
    low = [a.lower() for a in after]
    # Extension resource: {resource}/providers/{ns}/{type}[/{name}]
    j = next((i for i in range(2, len(low)) if low[i] == "providers"), None)
    if j is not None:
        parent_after, ext = after[:j], after[j + 1:]
        if len(ext) < 2:
            return _err(400, "BadRequest", "Missing extension resource type.")
        scope = scope_id(sub, rg, parent_after)
        parent = state.get(scope.lower())
        if parent is None:
            return _err(404, "ParentResourceNotFound", f"Resource '{scope}' not found.")
        ns, rest = ext[0], ext[1:]
        nsl, t0 = ns.lower(), rest[0].lower()
        if nsl == "microsoft.authorization" and t0 == "locks":
            return _locks(state, method, scope, rest, payload)
        if nsl == "microsoft.authorization" and t0 == "roleassignments":
            return _role_assignments(state, method, scope, rest, payload)
        if nsl == "microsoft.resourcehealth" and t0 == "availabilitystatuses":
            return _health(parent, scope, rest) if method == "GET" else _err(405, "MethodNotAllowed", "GET only.")
        if nsl == "microsoft.managedidentity" and t0 == "identities":
            return _identity_default(parent, scope) if method == "GET" else _err(405, "MethodNotAllowed", "GET only.")
        return _generic_ext(state, method, scope, ns, rest, payload)
    # Locks at subscription / resource-group scope.
    if low[0] == "microsoft.authorization" and low[1] == "locks":
        return _locks(state, method, scope_id(sub, rg, []), after[1:], payload)
    if low[0] == "microsoft.network" and low[1] == "networkinterfaces" and len(after) <= 3:
        return _nic(state, method, sub, rg, after, payload)
    if low[0] == "microsoft.network" and low[1] == "publicipaddresses" and len(after) <= 3:
        return _pip(state, method, sub, rg, after, payload)
    if low[0] == "microsoft.devtestlab" and low[1] == "schedules" and len(after) <= 3:
        return _schedules(state, method, sub, rg, after, payload)
    if low[0] == "microsoft.storage" and low[1] == "storageaccounts" and len(after) == 4 and method == "POST":
        rid = scope_id(sub, rg, after[:3])
        rec = state.get(rid.lower())
        if rec is None:
            return _err(404, "ResourceNotFound", f"Storage account '{after[2]}' not found.")
        _storage_fill(rec)
        r = _storage_action(state, rid, rec, after[3], payload)
        if r is not None:
            return r
    if low[0] == "microsoft.compute" and low[1] == "restorepointcollections":
        return _restore_points(state, method, sub, rg, after, payload)
    if low[0] == "microsoft.compute" and low[1] == "virtualmachines" and len(after) == 4 \
            and low[3] == "instanceview":
        vm_rid = scope_id(sub, rg, after[:3])
        vm = state.get(vm_rid.lower())
        if vm is None:
            return _err(404, "ResourceNotFound", f"Virtual machine '{after[2]}' not found.")
        return _ok(instance_view(vm, executor)) if method == "GET" else _err(405, "MethodNotAllowed", "GET only.")
    if low[0] == "microsoft.compute" and low[1] == "virtualmachines" and len(after) >= 4 \
            and low[3] in ("runcommands", "runcommand"):
        vm_rid = scope_id(sub, rg, after[:3])
        vm = state.get(vm_rid.lower())
        if vm is None:
            return _err(404, "ParentResourceNotFound", f"Virtual machine '{after[2]}' not found.")
        if low[3] == "runcommand":
            if method != "POST":
                return _err(405, "MethodNotAllowed", "POST only.")
            return _run_command_action(vm_rid, vm, payload, executor)
        return _run_commands(state, method, vm_rid, vm, after[3:], payload, executor)
    return None


def target_id(sub, rg, after) -> str:
    """The resource id a request acts on (used for lock checks)."""
    return scope_id(sub, rg, after)


def mark_changed(rec) -> None:
    """Remember when a resource's state last changed (Resource Health 'occured time')."""
    if isinstance(rec, dict):
        rec["_changed"] = _now()
