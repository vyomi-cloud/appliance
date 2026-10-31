"""Azure networking types + semantics the netsim engine relies on, and Network Watcher answered
by core/netsim — host + Pyodide.

  * Microsoft.Network routeTables / natGateways / publicIPAddresses (allocated ipAddress) /
    applicationSecurityGroups / networkWatchers are real ARM types (PUT/GET/list/DELETE)
  * NIC ipConfigurations get a private IP from their subnet (.4 first; reserved / in-use rejected)
  * networkWatchers/{nw}/ipFlowVerify → access + ruleName (securityRules/… or defaultSecurityRules/…)
  * networkWatchers/{nw}/nextHop → nextHopType / nextHopIpAddress / routeTableId

    PYTHONPATH=. python3 tests/conformance/test_azure_netsim_core.py
"""
try:
    from core.azure_arm_core import AzureArm
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm  # type: ignore

SUB, RG = "00000000-0000-0000-0000-0000000000aa", "net-rg"
RGP = f"/subscriptions/{SUB}/resourceGroups/{RG}"
NET = f"{RGP}/providers/Microsoft.Network"
Q = {"api-version": "2023-11-01"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run():
    arm = AzureArm()
    arm.handle("PUT", RGP, {"api-version": "2021-04-01"}, {"location": "eastus"})

    def call(method, path, body=None, status=None):
        r = arm.handle(method, f"{NET}/{path}", Q, {"location": "eastus", **(body or {})} if method == "PUT" else body)
        if status is not None and r["status"] != status:
            raise AssertionError((method, path, r["status"], r["body"]))
        if status is None and r["status"] >= 300:
            raise AssertionError((method, path, r["status"], r["body"]))
        return r["body"]

    rt = call("PUT", "routeTables/rt1", {"properties": {"routes": [
        {"name": "to-fw", "properties": {"addressPrefix": "0.0.0.0/0", "nextHopType": "VirtualAppliance", "nextHopIpAddress": "10.80.1.100"}}]}})
    _check("routeTables PUT", rt["type"] == "Microsoft.Network/routeTables" and rt["properties"]["routes"][0]["name"] == "to-fw")
    ng = call("PUT", "natGateways/ng1")
    _check("natGateways PUT (Standard sku)", ng["sku"]["name"] == "Standard")
    pip = call("PUT", "publicIPAddresses/pip1")
    _check("publicIPAddresses get an allocated ipAddress", pip["properties"]["ipAddress"].count(".") == 3
           and "__" not in pip["properties"]["ipAddress"])
    asg = call("PUT", "applicationSecurityGroups/asg1")
    _check("applicationSecurityGroups PUT", asg["type"] == "Microsoft.Network/applicationSecurityGroups")
    _check("list routeTables", len(call("GET", "routeTables")["value"]) == 1)

    nsg = call("PUT", "networkSecurityGroups/nsg-web", {"properties": {"securityRules": [
        {"name": "ssh", "properties": {"priority": 100, "direction": "Inbound", "access": "Allow", "protocol": "Tcp",
                                       "sourceAddressPrefix": "VirtualNetwork", "sourcePortRange": "*",
                                       "destinationAddressPrefix": "*", "destinationPortRange": "22"}},
        {"name": "no-5432", "properties": {"priority": 200, "direction": "Inbound", "access": "Deny", "protocol": "Tcp",
                                           "sourceAddressPrefix": "*", "sourcePortRange": "*",
                                           "destinationAddressPrefix": "*", "destinationPortRange": "5432"}}]}})
    call("PUT", "virtualNetworks/vnet1", {"properties": {"addressSpace": {"addressPrefixes": ["10.80.0.0/16"]}, "subnets": [
        {"name": "web", "properties": {"addressPrefix": "10.80.1.0/24", "networkSecurityGroup": {"id": nsg["id"]}}},
        {"name": "app", "properties": {"addressPrefix": "10.80.2.0/24", "routeTable": {"id": rt["id"]}}}]}})
    web_sub, app_sub = f"{NET}/virtualNetworks/vnet1/subnets/web", f"{NET}/virtualNetworks/vnet1/subnets/app"

    def nic(name, sub, **ipc):
        return call("PUT", f"networkInterfaces/{name}", {"properties": {"ipConfigurations": [
            {"name": "ipconfig1", "properties": {"subnet": {"id": sub}, **ipc}}]}})

    n1 = nic("web-nic", web_sub)
    _check("Dynamic NIC gets .4 of its subnet", n1["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"] == "10.80.1.4")
    n2 = nic("web2-nic", web_sub)
    _check("next NIC gets .5", n2["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"] == "10.80.1.5")
    bad = arm.handle("PUT", f"{NET}/networkInterfaces/clash", Q, {"location": "eastus", "properties": {"ipConfigurations": [
        {"name": "c", "properties": {"subnet": {"id": web_sub}, "privateIPAllocationMethod": "Static", "privateIPAddress": "10.80.1.4"}}]}})
    _check("Static address in use rejected (PrivateIPAddressInUse)", bad["status"] == 400 and bad["body"]["error"]["code"] == "PrivateIPAddressInUse")
    bad = arm.handle("PUT", f"{NET}/networkInterfaces/res", Q, {"location": "eastus", "properties": {"ipConfigurations": [
        {"name": "c", "properties": {"subnet": {"id": web_sub}, "privateIPAllocationMethod": "Static", "privateIPAddress": "10.80.1.2"}}]}})
    _check("reserved .2 rejected", bad["status"] == 400)
    app = nic("app-nic", app_sub, privateIPAllocationMethod="Static", privateIPAddress="10.80.2.10",
              publicIPAddress={"id": pip["id"]})
    fw = nic("fw-nic", web_sub, privateIPAllocationMethod="Static", privateIPAddress="10.80.1.100")
    del fw
    arm.handle("PUT", f"{RGP}/providers/Microsoft.Compute/virtualMachines/web-vm", {"api-version": "2023-09-01"},
               {"location": "eastus", "properties": {"networkProfile": {"networkInterfaces": [{"id": n1["id"]}]}}})
    call("PUT", "networkWatchers/NetworkWatcher_eastus")
    vm_id = f"{RGP}/providers/Microsoft.Compute/virtualMachines/web-vm"

    def ipfv(**kw):
        return call("POST", "networkWatchers/NetworkWatcher_eastus/ipFlowVerify", {"targetResourceId": vm_id, **kw})

    r = ipfv(direction="Inbound", protocol="TCP", localPort="22", remotePort="50000", localIPAddress="10.80.1.4", remoteIPAddress="10.80.2.10")
    _check("ipFlowVerify inbound 22 from the vnet → Allow securityRules/ssh", r == {"access": "Allow", "ruleName": "securityRules/ssh"})
    r = ipfv(direction="Inbound", protocol="TCP", localPort="5432", remotePort="50000", localIPAddress="10.80.1.4", remoteIPAddress="10.80.2.10")
    _check("inbound 5432 → Deny securityRules/no-5432", r == {"access": "Deny", "ruleName": "securityRules/no-5432"})
    r = ipfv(direction="Inbound", protocol="TCP", localPort="80", remotePort="50000", localIPAddress="10.80.1.4", remoteIPAddress="203.0.113.9")
    _check("inbound 80 from the internet → Deny defaultSecurityRules/DenyAllInBound",
           r == {"access": "Deny", "ruleName": "defaultSecurityRules/DenyAllInBound"})
    r = ipfv(direction="Inbound", protocol="TCP", localPort="8080", remotePort="50000", localIPAddress="10.80.1.4", remoteIPAddress="10.80.2.10")
    _check("inbound 8080 from the vnet → Allow defaultSecurityRules/AllowVnetInBound",
           r == {"access": "Allow", "ruleName": "defaultSecurityRules/AllowVnetInBound"})
    r = ipfv(direction="Outbound", protocol="TCP", localPort="50000", remotePort="443", localIPAddress="10.80.1.4", remoteIPAddress="203.0.113.9")
    _check("outbound 443 → Allow defaultSecurityRules/AllowInternetOutBound",
           r == {"access": "Allow", "ruleName": "defaultSecurityRules/AllowInternetOutBound"})

    def nh(nic_id, dst):
        return call("POST", "networkWatchers/NetworkWatcher_eastus/nextHop",
                    {"targetResourceId": vm_id, "targetNicResourceId": nic_id, "sourceIPAddress": "", "destinationIPAddress": dst})

    r = nh(n1["id"], "10.80.2.10")
    _check("nextHop inside the vnet → VnetLocal / System Route", r["nextHopType"] == "VnetLocal" and r["routeTableId"] == "System Route")
    _check("nextHop to the internet → Internet", nh(n1["id"], "8.8.8.8")["nextHopType"] == "Internet")
    _check("nextHop RFC1918 outside the vnet → None", nh(n1["id"], "192.168.1.1")["nextHopType"] == "None")
    r = nh(app["id"], "8.8.8.8")
    _check("UDR 0/0 → VirtualAppliance 10.80.1.100 from route table rt1",
           r["nextHopType"] == "VirtualAppliance" and r["nextHopIpAddress"] == "10.80.1.100" and r["routeTableId"].endswith("/routeTables/rt1"))
    miss = arm.handle("POST", f"{NET}/networkWatchers/nope/ipFlowVerify", Q, {"targetResourceId": vm_id})
    _check("unknown network watcher → 404", miss["status"] == 404)

    def cc(**kw):
        return call("POST", "networkWatchers/NetworkWatcher_eastus/connectivityCheck", {"source": {"resourceId": vm_id}, **kw})

    r = cc(destination={"address": "10.80.2.10", "port": 80}, protocol="TCP")
    _check("connectivityCheck inside the vnet (by address) → Reachable",
           r["connectionStatus"] == "Reachable" and r["probesFailed"] == 0)
    r = cc(destination={"resourceId": n2["id"], "port": 5432}, protocol="TCP")
    _check("connectivityCheck to an NSG-denied port (by resourceId) → Unreachable",
           r["connectionStatus"] == "Unreachable" and r["probesFailed"] == 100)
    _check("connectivityCheck records the blocking NSG hop", any(h["type"] == "nsg" and h["issues"] for h in r["hops"]))
    bad = arm.handle("POST", f"{NET}/networkWatchers/NetworkWatcher_eastus/connectivityCheck", Q,
                     {"source": {"resourceId": vm_id}, "destination": {}})
    _check("connectivityCheck missing destination → 400", bad["status"] == 400)
    bad = arm.handle("POST", f"{NET}/networkWatchers/NetworkWatcher_eastus/connectivityCheck", Q,
                     {"source": {"resourceId": "nope"}, "destination": {"address": "10.80.2.10", "port": 80}})
    _check("connectivityCheck unresolvable source → 400", bad["status"] == 400)
    print("\nAzure netsim types + Network Watcher conformance: ALL GREEN")


if __name__ == "__main__":
    run()
    print("RESULT: PASS")
