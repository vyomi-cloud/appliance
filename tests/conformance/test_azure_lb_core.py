"""Azure Load Balancer control plane: validation, NIC attachment, derived members, delete guard, backend health.
Run: PYTHONPATH=. python tests/conformance/test_azure_lb_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
    from core import azure_lb_core as lb
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore
    import azure_lb_core as lb  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    Q = {"api-version": "2023-09-01"}
    RG = f"/subscriptions/{SUB}/resourceGroups/lb-rg"
    N = RG + "/providers/Microsoft.Network"
    put = lambda path, body: a.handle("PUT", path, Q, body)
    code = lambda r: (r["body"].get("error") or {}).get("code")
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    put(N + "/virtualNetworks/v1", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "subnets": [{"name": "s1", "properties": {"addressPrefix": "10.0.1.0/24"}}]}})
    put(N + "/publicIPAddresses/pipstd", {"location": "eastus", "sku": {"name": "Standard"}, "properties": {"publicIPAllocationMethod": "Static"}})
    put(N + "/publicIPAddresses/pipbasic", {"location": "eastus", "sku": {"name": "Basic"}, "properties": {"publicIPAllocationMethod": "Dynamic"}})
    L = N + "/loadBalancers/lb1"
    lid = lambda kind, n: f"{L}/{kind}/{n}"
    fe = lambda n="fe1", pip="pipstd": {"name": n, "properties": {"publicIPAddress": {"id": f"{N}/publicIPAddresses/{pip}"}}}
    rule = lambda **kw: {"name": "r1", "properties": {"protocol": "Tcp", "frontendPort": 80, "backendPort": 8080, "frontendIPConfiguration": {"id": lid("frontendIPConfigurations", "fe1")},
                                                      "backendAddressPool": {"id": lid("backendAddressPools", "bp1")}, "probe": {"id": lid("probes", "p1")}, **kw}}
    probe = {"name": "p1", "properties": {"protocol": "Http", "port": 8080, "requestPath": "/health", "intervalInSeconds": 15}}
    body = lambda **kw: {"location": "eastus", "sku": {"name": "Standard"}, "properties": {"frontendIPConfigurations": [fe()], "backendAddressPools": [{"name": "bp1"}], "probes": [probe], "loadBalancingRules": [rule()], **kw}}
    _check("Standard LB with Basic PIP rejected", code(put(L, body(frontendIPConfigurations=[fe(pip="pipbasic")]))) == "FrontendIpSkuMismatch")
    _check("missing PIP rejected", code(put(L, body(frontendIPConfigurations=[fe(pip="nope")]))) == "ReferencedResourceNotFound")
    _check("Http probe needs requestPath", code(put(L, body(probes=[{"name": "p1", "properties": {"protocol": "Http", "port": 80}}]))) == "ProbeRequestPathRequired")
    _check("rule must reference an existing probe", code(put(L, body(loadBalancingRules=[rule(probe={"id": lid("probes", "ghost")})]))) == "ReferencedResourceNotFound")
    _check("Standard rule needs a probe", code(put(L, body(loadBalancingRules=[rule(probe=None)]))) == "RuleRequiresProbe")
    _check("idle timeout range", code(put(L, body(loadBalancingRules=[rule(idleTimeoutInMinutes=60)]))) == "InvalidIdleTimeout")
    r2 = rule(); r2["name"] = "r2"
    _check("duplicate frontend port rejected", code(put(L, body(loadBalancingRules=[rule(), r2]))) == "LoadBalancingRuleConflict")
    _check("HA ports need protocol All", code(put(L, body(loadBalancingRules=[rule(frontendPort=0, backendPort=0)]))) == "InvalidRulePort")
    _check("outbound rules need Standard", code(put(L, {**body(outboundRules=[{"name": "o"}]), "sku": {"name": "Basic"}})) in ("OutboundRulesRequireStandardSku", "FrontendIpSkuMismatch"))
    r = put(L, body())
    _check("valid LB accepted with derived ids", r["status"] in (200, 201) and r["body"]["properties"]["backendAddressPools"][0]["id"].endswith("/backendAddressPools/bp1"))
    _check("sku immutable", code(put(L, {**body(), "sku": {"name": "Basic"}})) == "SkuCannotBeChanged")
    # NIC attachment
    NIC = N + "/networkInterfaces/nic1"
    nic = lambda pool: {"location": "eastus", "properties": {"ipConfigurations": [{"name": "ipc", "properties": {"subnet": {"id": f"{N}/virtualNetworks/v1/subnets/s1"}, "loadBalancerBackendAddressPools": [{"id": pool}]}}]}}
    _check("NIC pool must exist", code(put(NIC, nic(lid("backendAddressPools", "ghost")))) == "ReferencedResourceNotFound")
    r = put(NIC, nic(lid("backendAddressPools", "bp1")))
    _check("NIC joins the pool", r["status"] in (200, 201))
    got = a.handle("GET", L, Q)["body"]
    mem = got["properties"]["backendAddressPools"][0]["properties"]["backendIPConfigurations"]
    _check("LB pool lists the NIC ipConfiguration", len(mem) == 1 and mem[0]["id"].endswith("/nic1/ipConfigurations/ipc"))
    _check("rule lists on frontend + probe", got["properties"]["probes"][0]["properties"]["loadBalancingRules"][0]["id"].endswith("/r1"))
    d = a.handle("DELETE", L, Q)
    _check("LB with members cannot be deleted", d["status"] == 400 and code(d) == "InUseLoadBalancerBackendPool")
    put(NIC, {"location": "eastus", "properties": {"ipConfigurations": [{"name": "ipc", "properties": {"subnet": {"id": f"{N}/virtualNetworks/v1/subnets/s1"}}}]}})
    got = a.handle("GET", L, Q)["body"]
    _check("detaching the NIC empties the pool", got["properties"]["backendAddressPools"][0]["properties"]["backendIPConfigurations"] == [])
    put(NIC, nic(lid("backendAddressPools", "bp1")))
    h = lb.backend_health(a.state, a.state[L.lower()], lambda vm: "running")
    _check("health: member without VM is honest", h and h[0]["state"] == "NoVirtualMachine" and "no health probe" in h[0]["note"].lower())
    _check("empty LB deletes after detach", a.handle("DELETE", NIC, Q)["status"] in (200, 204) and a.handle("DELETE", L, Q)["status"] in (200, 204))
    print("lb core: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
