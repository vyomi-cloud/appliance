"""Azure Load Balancer control plane (Microsoft.Network/loadBalancers), substrate-free (Nano / dev_server / offline ARM).

Real ARM resources with real validation and cross-resource checks, stored in the flat ARM state map used by ``azure_arm_core``
(keyed by lower-cased resource id). Hooks mirror azure_netcfg_core (handles / validate / after_put / before_delete / on_delete).

* ``loadBalancers`` -- sku Basic|Standard (tier Regional|Global), frontendIPConfigurations (a public IP that exists and whose SKU
  matches, or a subnet that exists), backendAddressPools, probes (Tcp / Http / Https; Http(s) need requestPath; interval 5..2147483647,
  probe threshold 1..20), loadBalancingRules (frontend / pool / probe must exist IN this load balancer; ports 1..65534, 0 only with
  protocol All = HA ports; frontend+protocol+port tuple unique per frontend; idle timeout 4..30; Standard rules need a probe),
  inboundNatRules (unique frontend port per frontend), outboundRules (Standard only). Child ids and provisioningState are derived.
* NIC attachment -- ``networkInterfaces`` ipConfigurations ``loadBalancerBackendAddressPools`` / ``loadBalancerInboundNatRules`` must
  name pools / rules that exist; the load balancer's pool then lists its ``backendIPConfigurations`` (derived from the NICs) and a
  load balancer that still has members cannot be deleted. A Standard LB pool member must be in the LB's region.
* ``backend_health(state, lb, vm_power)`` -- per member: the VM behind the NIC and its power state. A probe is NEVER executed: a
  running VM is reported ``VmRunning`` (probe not executed), a stopped one ``VmNotRunning`` -- never a fabricated Up/Down.

NOT modelled (honest limits, see core/capabilities/azure/loadbalancer.json): no traffic is balanced, no health probe packet is sent,
no SNAT / outbound connection is made; cross-region (Global tier) frontends are validated configuration only.
"""
from __future__ import annotations

import re
import uuid

LB = "microsoft.network/loadbalancers"
NIC = "microsoft.network/networkinterfaces"
PIP = "microsoft.network/publicipaddresses"
VNET = "microsoft.network/virtualnetworks"
_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,78}[A-Za-z0-9_])?$")


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def handles(full_type: str) -> bool:
    return (full_type or "").lower() in (LB, NIC)


def _ref_id(v) -> str:
    return str((v or {}).get("id") if isinstance(v, dict) else v or "").lower()


def _child_id(rid: str, kind: str, name: str) -> str:
    return f"{rid}/{kind}/{name}"


def _validate_lb(state, rid, payload, existing, sub, rg):
    p = {**((existing or {}).get("properties") or {}), **((payload or {}).get("properties") or {})}
    sku = ((payload or {}).get("sku") or (existing or {}).get("sku") or {})
    sku_name = sku.get("name") or "Basic"
    if sku_name not in ("Basic", "Standard", "Gateway"):
        return _err(400, "InvalidSku", "Load balancer sku.name must be Basic, Standard or Gateway.")
    if sku.get("tier") not in (None, "Regional", "Global"):
        return _err(400, "InvalidSkuTier", "Load balancer sku.tier must be Regional or Global.")
    if existing and (existing.get("sku") or {}).get("name") not in (None, sku_name):
        return _err(400, "SkuCannotBeChanged", "The SKU of a load balancer cannot be changed after creation.")
    standard = sku_name != "Basic"
    names: dict = {}
    for kind in ("frontendIPConfigurations", "backendAddressPools", "probes", "loadBalancingRules", "inboundNatRules", "outboundRules"):
        seen = set()
        for it in p.get(kind) or []:
            n = (it or {}).get("name")
            if not n or not _NAME.match(str(n)):
                return _err(400, "InvalidResourceName", f"{kind}: every entry needs a valid name (got '{n}').")
            if n.lower() in seen:
                return _err(400, "DuplicateChildName", f"{kind}: name '{n}' is used more than once.")
            seen.add(n.lower())
        names[kind] = seen
    if (p.get("outboundRules") and not standard):
        return _err(400, "OutboundRulesRequireStandardSku", "Outbound rules require a Standard SKU load balancer.")
    loc = ((payload or {}).get("location") or (existing or {}).get("location") or "").lower().replace(" ", "")
    for fe in p.get("frontendIPConfigurations") or []:
        fp = fe.get("properties") or {}
        pip, sn = _ref_id(fp.get("publicIPAddress")), _ref_id(fp.get("subnet"))
        if bool(pip) == bool(sn):
            return _err(400, "InvalidFrontendIPConfiguration", f"Frontend IP configuration '{fe['name']}' must reference exactly one of publicIPAddress or subnet.")
        if pip:
            rec = state.get(pip)
            if rec is None or (rec.get("_type") or "").lower() != PIP:
                return _err(400, "ReferencedResourceNotFound", f"Public IP address {fp['publicIPAddress'].get('id')} referenced by frontend '{fe['name']}' was not found.")
            if ((rec.get("sku") or {}).get("name") or "Basic") != ("Basic" if not standard else "Standard"):
                return _err(400, "FrontendIpSkuMismatch", f"Frontend '{fe['name']}': a {sku_name} load balancer needs a {sku_name} SKU public IP address.")
        else:
            vid, _, sname = sn.rpartition("/subnets/")
            v = state.get(vid)
            if v is None or (v.get("_type") or "").lower() != VNET or not any(str(s.get("name", "")).lower() == sname for s in (v.get("properties") or {}).get("subnets") or []):
                return _err(400, "ReferencedResourceNotFound", f"Subnet {fp['subnet'].get('id')} referenced by frontend '{fe['name']}' was not found.")
    for pr in p.get("probes") or []:
        pp = pr.get("properties") or {}
        proto = pp.get("protocol")
        if proto not in ("Tcp", "Http", "Https"):
            return _err(400, "InvalidProbeProtocol", f"Probe '{pr['name']}': protocol must be Tcp, Http or Https.")
        port = pp.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            return _err(400, "InvalidProbePort", f"Probe '{pr['name']}': port must be between 1 and 65535.")
        if proto in ("Http", "Https") and not pp.get("requestPath"):
            return _err(400, "ProbeRequestPathRequired", f"Probe '{pr['name']}': Http and Https probes require requestPath.")
        if proto == "Tcp" and pp.get("requestPath"):
            return _err(400, "ProbeRequestPathNotAllowed", f"Probe '{pr['name']}': a Tcp probe cannot have a requestPath.")
        iv = pp.get("intervalInSeconds", 15)
        if not isinstance(iv, int) or iv < 5:
            return _err(400, "InvalidProbeInterval", f"Probe '{pr['name']}': intervalInSeconds must be at least 5.")
        th = pp.get("probeThreshold", pp.get("numberOfProbes", 1))
        if not isinstance(th, int) or not 1 <= th <= 20:
            return _err(400, "InvalidProbeThreshold", f"Probe '{pr['name']}': probeThreshold must be between 1 and 20.")
    tuples = set()
    for r in p.get("loadBalancingRules") or []:
        rp = r.get("properties") or {}
        proto = rp.get("protocol")
        if proto not in ("Tcp", "Udp", "All"):
            return _err(400, "InvalidRuleProtocol", f"Rule '{r['name']}': protocol must be Tcp, Udp or All.")
        fport, bport = rp.get("frontendPort"), rp.get("backendPort", rp.get("frontendPort"))
        for lab, v in (("frontendPort", fport), ("backendPort", bport)):
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 65534:
                return _err(400, "InvalidRulePort", f"Rule '{r['name']}': {lab} must be between 0 and 65534.")
        if proto != "All" and (fport == 0 or bport == 0):
            return _err(400, "InvalidRulePort", f"Rule '{r['name']}': port 0 (HA ports) requires protocol All.")
        if proto == "All" and (fport != 0 or bport != 0):
            return _err(400, "HaPortsRequirePortZero", f"Rule '{r['name']}': protocol All is the HA-ports rule and needs frontendPort and backendPort 0.")
        if proto == "All" and not standard:
            return _err(400, "HaPortsRequireStandardSku", f"Rule '{r['name']}': HA ports require a Standard SKU load balancer.")
        it = rp.get("idleTimeoutInMinutes", 4)
        if not isinstance(it, int) or not 4 <= it <= 30:
            return _err(400, "InvalidIdleTimeout", f"Rule '{r['name']}': idleTimeoutInMinutes must be between 4 and 30.")
        fe_id = _ref_id(rp.get("frontendIPConfiguration"))
        if not fe_id or fe_id.rpartition("/")[2] not in names["frontendIPConfigurations"] or not fe_id.startswith(rid.lower() + "/"):
            return _err(400, "ReferencedResourceNotFound", f"Rule '{r['name']}': frontendIPConfiguration does not name a frontend of this load balancer.")
        for key, kind in (("backendAddressPool", "backendAddressPools"), ("probe", "probes")):
            ref = _ref_id(rp.get(key))
            if ref and (ref.rpartition("/")[2] not in names[kind] or not ref.startswith(rid.lower() + "/")):
                return _err(400, "ReferencedResourceNotFound", f"Rule '{r['name']}': {key} does not name an entry of this load balancer.")
        if not _ref_id(rp.get("backendAddressPool")):
            return _err(400, "RuleRequiresBackendPool", f"Rule '{r['name']}': backendAddressPool is required.")
        if not _ref_id(rp.get("probe")) and standard:
            return _err(400, "RuleRequiresProbe", f"Rule '{r['name']}': a rule on a Standard load balancer requires a health probe.")
        t = (fe_id, "tcp" if proto in ("Tcp", "All") else "udp", fport)
        t2 = (fe_id, "udp" if proto in ("Udp", "All") else "tcp", fport)
        if t in tuples or t2 in tuples:
            return _err(400, "LoadBalancingRuleConflict", f"Rule '{r['name']}': frontend port {fport}/{proto} on this frontend is already used by another rule.")
        tuples.add(t)
        tuples.add(t2)
    nat = set()
    for n in p.get("inboundNatRules") or []:
        np_ = n.get("properties") or {}
        fe_id = _ref_id(np_.get("frontendIPConfiguration"))
        if not fe_id or fe_id.rpartition("/")[2] not in names["frontendIPConfigurations"]:
            return _err(400, "ReferencedResourceNotFound", f"NAT rule '{n['name']}': frontendIPConfiguration does not name a frontend of this load balancer.")
        if np_.get("protocol") not in ("Tcp", "Udp", "All"):
            return _err(400, "InvalidRuleProtocol", f"NAT rule '{n['name']}': protocol must be Tcp, Udp or All.")
        for lab in ("frontendPort", "backendPort"):
            v = np_.get(lab)
            if not isinstance(v, int) or not 1 <= v <= 65534:
                if not (lab == "frontendPort" and np_.get("frontendPortRangeStart")):
                    return _err(400, "InvalidRulePort", f"NAT rule '{n['name']}': {lab} must be between 1 and 65534.")
        k = (fe_id, np_.get("protocol"), np_.get("frontendPort"))
        if np_.get("frontendPort") and k in nat:
            return _err(400, "NatRuleConflict", f"NAT rule '{n['name']}': frontend port {np_.get('frontendPort')} is used by another inbound NAT rule.")
        nat.add(k)
        if any((fe_id, np_.get("protocol"), np_.get("frontendPort")) == (t[0], "tcp", t[2]) for t in tuples) and np_.get("protocol") in ("Tcp",):
            return _err(400, "NatRuleConflictsWithRule", f"NAT rule '{n['name']}': frontend port {np_.get('frontendPort')} is already used by a load-balancing rule.")
    return None


def _lb_children_index(state):
    """{pool id (lower): (lb, pool)} and {nat rule id: (lb, rule)} over every load balancer."""
    pools, nats = {}, {}
    for rec in state.values():
        if (rec.get("_type") or "").lower() != LB:
            continue
        rid = (rec.get("id") or "")
        for pl in (rec.get("properties") or {}).get("backendAddressPools") or []:
            pools[_child_id(rid, "backendAddressPools", pl["name"]).lower()] = (rec, pl)
        for nr in (rec.get("properties") or {}).get("inboundNatRules") or []:
            nats[_child_id(rid, "inboundNatRules", nr["name"]).lower()] = (rec, nr)
    return pools, nats


def _validate_nic(state, rid, payload, existing):
    pools, nats = _lb_children_index(state)
    p = (payload or {}).get("properties") or {}
    loc = ((payload or {}).get("location") or (existing or {}).get("location") or "").lower().replace(" ", "")
    for ic in p.get("ipConfigurations") or []:
        ip = ic.get("properties") or {}
        for ref in ip.get("loadBalancerBackendAddressPools") or []:
            e = pools.get(_ref_id(ref))
            if e is None:
                return _err(400, "ReferencedResourceNotFound", f"Load balancer backend address pool {(ref or {}).get('id')} referenced by ipConfiguration '{ic.get('name')}' was not found.")
            lbloc = (e[0].get("location") or "").lower().replace(" ", "")
            if loc and lbloc and loc != lbloc and ((e[0].get("sku") or {}).get("tier") or "Regional") != "Global":
                return _err(400, "LoadBalancerNicRegionMismatch", f"The network interface is in '{loc}' but the load balancer '{e[0].get('name')}' is in '{lbloc}'.")
        for ref in ip.get("loadBalancerInboundNatRules") or []:
            if _ref_id(ref) not in nats:
                return _err(400, "ReferencedResourceNotFound", f"Inbound NAT rule {(ref or {}).get('id')} referenced by ipConfiguration '{ic.get('name')}' was not found.")
    return None


def validate(state, full_type, rid, payload, existing, sub, rg):
    ft = full_type.lower()
    if ft == LB:
        return _validate_lb(state, rid, payload, existing, sub, rg)
    if ft == NIC:
        return _validate_nic(state, rid, payload, existing)
    return None


def _refresh(state):
    """Derive each pool's backendIPConfigurations / each NAT rule's backendIPConfiguration from the NICs that reference them,
    and stamp child ids, resourceGuid, provisioningState on every LB."""
    members: dict = {}
    nat_members: dict = {}
    for rec in state.values():
        if (rec.get("_type") or "").lower() != NIC:
            continue
        for ic in (rec.get("properties") or {}).get("ipConfigurations") or []:
            ip = ic.get("properties") or {}
            icid = f"{rec.get('id')}/ipConfigurations/{ic.get('name')}"
            for ref in ip.get("loadBalancerBackendAddressPools") or []:
                members.setdefault(_ref_id(ref), []).append({"id": icid})
            for ref in ip.get("loadBalancerInboundNatRules") or []:
                nat_members.setdefault(_ref_id(ref), []).append({"id": icid})
    for rec in state.values():
        if (rec.get("_type") or "").lower() != LB:
            continue
        rid, p = rec.get("id") or "", rec.setdefault("properties", {})
        p.setdefault("resourceGuid", str(uuid.uuid4()))
        p["provisioningState"] = "Succeeded"
        for kind in ("frontendIPConfigurations", "backendAddressPools", "probes", "loadBalancingRules", "inboundNatRules", "outboundRules"):
            for it in p.get(kind) or []:
                it["id"] = _child_id(rid, kind, it["name"])
                it["type"] = f"Microsoft.Network/loadBalancers/{kind}"
                it.setdefault("properties", {})["provisioningState"] = "Succeeded"
                it["etag"] = it.get("etag") or 'W/"' + str(uuid.uuid4()) + '"'
        for pl in p.get("backendAddressPools") or []:
            pl["properties"]["backendIPConfigurations"] = members.get(pl["id"].lower(), [])
            pl["properties"]["loadBalancingRules"] = [{"id": r["id"]} for r in p.get("loadBalancingRules") or []
                                                      if _ref_id((r.get("properties") or {}).get("backendAddressPool")) == pl["id"].lower()]
        for nr in p.get("inboundNatRules") or []:
            m = nat_members.get(nr["id"].lower())
            if m:
                nr["properties"]["backendIPConfiguration"] = m[0]
            else:
                nr["properties"].pop("backendIPConfiguration", None)
        for fe in p.get("frontendIPConfigurations") or []:
            fe["properties"]["loadBalancingRules"] = [{"id": r["id"]} for r in p.get("loadBalancingRules") or []
                                                      if _ref_id((r.get("properties") or {}).get("frontendIPConfiguration")) == fe["id"].lower()]
        for pr in p.get("probes") or []:
            pr["properties"]["loadBalancingRules"] = [{"id": r["id"]} for r in p.get("loadBalancingRules") or []
                                                      if _ref_id((r.get("properties") or {}).get("probe")) == pr["id"].lower()]


def after_put(state, rec, payload, prev=None):
    _refresh(state)


def before_delete(state, rec):
    ft = (rec.get("_type") or "").lower()
    if ft == LB:
        for pl in (rec.get("properties") or {}).get("backendAddressPools") or []:
            if (pl.get("properties") or {}).get("backendIPConfigurations"):
                return _err(400, "InUseLoadBalancerBackendPool", f"Load balancer {rec.get('name')} cannot be deleted: backend pool '{pl['name']}' still has network interface members.")
    return None


def on_delete(state, rec):
    if (rec.get("_type") or "").lower() in (LB, NIC):
        _refresh(state)


def backend_health(state: dict, lb: dict, vm_power) -> list:
    """Per pool member: the VM behind the NIC + a state derived ONLY from its power state (no probe packet is ever sent).
    `vm_power(vm_id_lower)` -> a power-state string ('running', 'stopped', 'deallocated', …) or None."""
    _refresh(state)
    nic_vm = {}
    for rec in state.values():
        if (rec.get("_type") or "").lower() == "microsoft.compute/virtualmachines":
            for n in ((rec.get("properties") or {}).get("networkProfile") or {}).get("networkInterfaces") or []:
                nic_vm[_ref_id(n)] = rec
    out = []
    for pl in (lb.get("properties") or {}).get("backendAddressPools") or []:
        for m in (pl.get("properties") or {}).get("backendIPConfigurations") or []:
            nic_id = m["id"].lower().split("/ipconfigurations/")[0]
            vm = nic_vm.get(nic_id)
            pw = vm_power(vm["id"].lower()) if vm and vm_power else None
            running = str(pw or "").lower() in ("running", "vm running", "started")
            out.append({"pool": pl["name"], "networkInterface": m["id"].split("/ipConfigurations/")[0], "virtualMachine": vm.get("name") if vm else None,
                        "powerState": pw, "state": ("VmRunning" if running else "VmNotRunning") if vm else "NoVirtualMachine",
                        "note": "Derived from the VM power state; no health probe packet is sent."})
    return out
