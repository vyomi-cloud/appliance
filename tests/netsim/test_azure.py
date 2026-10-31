"""Azure translator + evaluator. VNets / NSGs / NICs go through the real ARM engine
(core/azure_arm_core.AzureArm); route tables, public IPs and NAT gateways are not in the ARM
catalog yet, so they are written into ARM state in the exact ARM resource shape.

    PYTHONPATH=. python3 tests/netsim/test_azure.py
"""
from __future__ import annotations

import unittest

from core.azure_arm_core import AzureArm
from core.netsim.evaluate import reach
from core.netsim.from_azure import from_azure

SUB, RG = "s1", "rg"
NET = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Network"
INET = "198.51.100.7"


class Az:
    def __init__(self):
        self.arm = AzureArm()
        self.arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{RG}", {"api-version": "2021-04-01"}, {"location": "eastus"})

    def put(self, path, body):
        r = self.arm.handle("PUT", f"{NET}/{path}", {"api-version": "2023-11-01"}, {"location": "eastus", **body})
        assert r["status"] < 300, r["body"]
        return r["body"]["id"]

    def raw(self, path, props):
        """ARM-shaped resource for types the ARM catalog does not simulate yet."""
        rid = f"{NET}/{path}"
        self.arm.state[rid.lower()] = {"id": rid, "name": path.split("/")[-1], "properties": props}
        return rid

    def vnet(self, name, prefixes, subnets, peerings=()):
        return self.put(f"virtualNetworks/{name}", {"properties": {
            "addressSpace": {"addressPrefixes": prefixes},
            "subnets": [{"name": n, "properties": p} for n, p in subnets.items()],
            "virtualNetworkPeerings": [{"name": f"to-{r.split('/')[-1]}", "properties": {
                "remoteVirtualNetwork": {"id": r}, "peeringState": "Connected"}} for r in peerings]}})

    def nsg(self, name, rules=()):
        return self.put(f"networkSecurityGroups/{name}", {"properties": {"securityRules": [
            {"name": r.pop("name"), "properties": {"sourcePortRange": "*", "destinationAddressPrefix": "*",
                                                   "sourceAddressPrefix": "*", "destinationPortRange": "*",
                                                   "protocol": "*", **r}} for r in rules]}})

    def nic(self, name, subnet_id, ip, nsg=None, pip=None, asgs=()):
        ipc = {"privateIPAddress": ip, "subnet": {"id": subnet_id}}
        if pip:
            ipc["publicIPAddress"] = {"id": pip}
        if asgs:
            ipc["applicationSecurityGroups"] = [{"id": a} for a in asgs]
        props = {"ipConfigurations": [{"name": "ipconfig1", "properties": ipc}]}
        if nsg:
            props["networkSecurityGroup"] = {"id": nsg}
        return self.put(f"networkInterfaces/{name}", {"properties": props}).lower()

    def topo(self):
        return from_azure(self.arm.state)


def sid(vnet, sub):
    return f"{NET}/virtualNetworks/{vnet}/subnets/{sub}"


class AzureTests(unittest.TestCase):
    def setUp(self):
        z = self.z = Az()
        self.nsg_web = z.nsg("nsg-web", [dict(name="ssh", priority=100, direction="Inbound", access="Allow",
                                              protocol="Tcp", destinationPortRange="22", sourceAddressPrefix="VirtualNetwork")])
        z.vnet("vnet1", ["10.50.0.0/16"], {"web": {"addressPrefix": "10.50.1.0/24"},
                                           "app": {"addressPrefix": "10.50.2.0/24", "defaultOutboundAccess": False}})
        self.web = z.nic("web-nic", sid("vnet1", "web"), "10.50.1.4", nsg=self.nsg_web)
        self.app = z.nic("app-nic", sid("vnet1", "app"), "10.50.2.4")          # no NSG at all

    def test_default_rules(self):
        t = self.z.topo()
        # app has no NSG anywhere → everything allowed inside the vnet
        self.assertTrue(reach(t, self.web, self.app, "tcp", 8080).reachable)
        # web NSG: 22 allowed from VirtualNetwork, others hit 65000 AllowVnetInBound (!) — vnet traffic is open by default
        v = reach(t, self.app, self.web, "tcp", 8080)
        self.assertTrue(v.reachable, v.explain())
        self.assertIn("AllowVnetInBound", " ".join(h.detail for h in v.hops))
        # internet → web: no public IP
        self.assertEqual(reach(t, INET, self.web, "tcp", 22).code, "NOT_PUBLIC")

    def test_deny_all_inbound_beats_default_vnet_allow(self):
        z = self.z
        nsg = z.nsg("nsg-lock", [dict(name="deny-vnet", priority=4000, direction="Inbound", access="Deny")])
        self.z.arm.state[sid("vnet1", "app").lower()] = {"id": sid("vnet1", "app"), "name": "app", "properties": {
            "addressPrefix": "10.50.2.0/24", "networkSecurityGroup": {"id": nsg}, "defaultOutboundAccess": False}}
        v = reach(z.topo(), self.web, self.app, "tcp", 8080)
        self.assertEqual((v.reachable, v.code), (False, "INGRESS_DENIED"))
        self.assertIn("deny-vnet", v.reason)

    def test_subnet_nsg_applies_within_subnet(self):
        z = self.z
        nsg = z.nsg("nsg-sub", [dict(name="deny-8080", priority=100, direction="Inbound", access="Deny",
                                     protocol="Tcp", destinationPortRange="8080")])
        z.arm.state[sid("vnet1", "app").lower()] = {"id": sid("vnet1", "app"), "name": "app", "properties": {
            "addressPrefix": "10.50.2.0/24", "networkSecurityGroup": {"id": nsg}}}
        other = z.nic("app2-nic", sid("vnet1", "app"), "10.50.2.5")
        v = reach(z.topo(), other, self.app, "tcp", 8080)
        self.assertEqual((v.reachable, v.code, v.path), (False, "INGRESS_DENIED", "intra-subnet"))

    def test_nic_and_subnet_nsg_both_must_allow(self):
        z = self.z
        sub_nsg = z.nsg("nsg-websub", [dict(name="allow-22", priority=100, direction="Inbound", access="Allow",
                                            protocol="Tcp", destinationPortRange="22"),
                                       dict(name="deny-rest", priority=200, direction="Inbound", access="Deny")])
        z.arm.state[sid("vnet1", "web").lower()] = {"id": sid("vnet1", "web"), "name": "web", "properties": {
            "addressPrefix": "10.50.1.0/24", "networkSecurityGroup": {"id": sub_nsg}}}
        t = z.topo()
        self.assertTrue(reach(t, self.app, self.web, "tcp", 22).reachable)
        v = reach(t, self.app, self.web, "tcp", 80)
        self.assertEqual(v.blocked_by, sub_nsg.lower())          # subnet NSG evaluated first inbound

    def test_internet_egress_public_ip_nat_default_outbound(self):
        z = self.z
        t = z.topo()
        v = reach(t, self.web, INET, "tcp", 443)                 # web subnet: default outbound access
        self.assertEqual((v.reachable, v.path), (True, "internet-via-default-outbound"))
        self.assertEqual(reach(t, self.app, INET, "tcp", 443).code, "NO_PUBLIC_IP")   # private subnet
        ng = z.raw("natGateways/ng1", {})
        z.arm.state[sid("vnet1", "app").lower()] = {"id": sid("vnet1", "app"), "name": "app", "properties": {
            "addressPrefix": "10.50.2.0/24", "defaultOutboundAccess": False, "natGateway": {"id": ng}}}
        self.assertEqual(reach(z.topo(), self.app, INET, "tcp", 443).path, "internet-via-nat")

    def test_inbound_public_ip_and_service_tag_internet(self):
        z = self.z
        pip = z.raw("publicIPAddresses/pip1", {"ipAddress": "20.1.2.3"})
        nsg = z.nsg("nsg-pub", [dict(name="https", priority=100, direction="Inbound", access="Allow", protocol="Tcp",
                                     destinationPortRange="443", sourceAddressPrefix="Internet")])
        pub = z.nic("pub-nic", sid("vnet1", "web"), "10.50.1.9", nsg=nsg, pip=pip)
        t = z.topo()
        self.assertTrue(reach(t, INET, "20.1.2.3", "tcp", 443).reachable)
        self.assertEqual(reach(t, INET, "20.1.2.3", "tcp", 22).code, "INGRESS_DENIED")
        # `Internet` tag does not match vnet sources: 443 from inside is the default AllowVnetInBound
        self.assertTrue(reach(t, self.app, pub, "tcp", 443).reachable)

    def test_udr_none_and_rfc1918_system_none(self):
        z = self.z
        rt = z.raw("routeTables/rt1", {"routes": [{"name": "drop-app", "properties": {
            "addressPrefix": "10.50.2.0/24", "nextHopType": "None"}}]})
        z.arm.state[sid("vnet1", "web").lower()] = {"id": sid("vnet1", "web"), "name": "web", "properties": {
            "addressPrefix": "10.50.1.0/24", "networkSecurityGroup": {"id": self.nsg_web}, "routeTable": {"id": rt}}}
        t = z.topo()
        self.assertEqual(reach(t, self.web, self.app, "tcp", 22).code, "BLACKHOLE_ROUTE")   # UDR more specific
        # an RFC1918 address outside the vnet hits the system "None" route, not the internet
        self.assertEqual(reach(t, self.web, "192.168.10.10", "tcp", 22).code, "BLACKHOLE_ROUTE")

    def test_virtual_appliance_udr(self):
        z = self.z
        fw = z.nic("fw-nic", sid("vnet1", "web"), "10.50.1.100")
        rt = z.raw("routeTables/rt-app", {"routes": [{"name": "to-fw", "properties": {
            "addressPrefix": "0.0.0.0/0", "nextHopType": "VirtualAppliance", "nextHopIpAddress": "10.50.1.100"}}]})
        z.arm.state[sid("vnet1", "app").lower()] = {"id": sid("vnet1", "app"), "name": "app", "properties": {
            "addressPrefix": "10.50.2.0/24", "routeTable": {"id": rt}}}
        self.assertEqual(reach(z.topo(), self.app, INET, "tcp", 443).code, "SOURCE_DEST_CHECK")   # IP forwarding off
        del fw

    def test_asg_and_peering_virtualnetwork_tag(self):
        z = self.z
        asg = z.raw("applicationSecurityGroups/asg-web", {})
        nsg = z.nsg("nsg-db", [dict(name="from-asg", priority=100, direction="Inbound", access="Allow", protocol="Tcp",
                                    destinationPortRange="5432", sourceApplicationSecurityGroups=[{"id": asg}]),
                               dict(name="deny", priority=200, direction="Inbound", access="Deny")])
        z.vnet("vnet2", ["10.60.0.0/16"], {"db": {"addressPrefix": "10.60.1.0/24"}}, peerings=[f"{NET}/virtualNetworks/vnet1"])
        # vnet1 → vnet2 link (both sides required)
        z.vnet("vnet1", ["10.50.0.0/16"], {"web": {"addressPrefix": "10.50.1.0/24"},
                                           "app": {"addressPrefix": "10.50.2.0/24", "defaultOutboundAccess": False}},
               peerings=[f"{NET}/virtualNetworks/vnet2"])
        db = z.nic("db-nic", sid("vnet2", "db"), "10.60.1.4", nsg=nsg)
        web2 = z.nic("web2-nic", sid("vnet1", "web"), "10.50.1.20", asgs=[asg])
        t = z.topo()
        v = reach(t, web2, db, "tcp", 5432)
        self.assertEqual((v.reachable, v.path), (True, "peering"), v.explain())
        self.assertEqual(reach(t, self.web, db, "tcp", 5432).code, "INGRESS_DENIED")   # not in the ASG

    def test_one_sided_peering_is_not_connected(self):
        z = self.z
        z.vnet("vnet2", ["10.60.0.0/16"], {"db": {"addressPrefix": "10.60.1.0/24"}}, peerings=[f"{NET}/virtualNetworks/vnet1"])
        db = z.nic("db-nic", sid("vnet2", "db"), "10.60.1.4")
        self.assertEqual(reach(z.topo(), self.web, db, "tcp", 22).code, "PRIVATE_DEST_VIA_GATEWAY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
