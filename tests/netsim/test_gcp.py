"""GCP translator + evaluator, topologies built through the real Compute REST cores.

    PYTHONPATH=. python3 tests/netsim/test_gcp.py
"""
from __future__ import annotations

import json
import unittest

from core import gcp_compute_core as net_core
from core import gcp_compute_instances_core as inst_core
from core.netsim.evaluate import reach
from core.netsim.from_gcp import from_gcp

P = "proj1"
INET = "198.51.100.7"


class Gcp:
    def __init__(self):
        self.net = net_core.ComputeStore()
        self.inst = inst_core.ComputeStore()

    def call(self, method, path, body=None):
        r = net_core.dispatch(self.net, method, f"/compute/v1/projects/{P}/{path}", body=json.dumps(body or {}).encode())
        assert r.status < 300, r.body
        return r

    def network(self, name):
        self.call("POST", "global/networks", {"name": name, "autoCreateSubnetworks": False})

    def subnet(self, net, name, region, cidr):
        self.call("POST", f"regions/{region}/subnetworks", {"name": name, "network": net, "ipCidrRange": cidr})

    def fw(self, **body):
        self.call("POST", "global/firewalls", body)

    def route(self, **body):
        self.call("POST", "global/routes", body)

    def vm(self, name, zone, net, region, subnet, ip, tags=(), sa=None, external=False):
        ni = {"network": f"projects/{P}/global/networks/{net}",
              "subnetwork": f"projects/{P}/regions/{region}/subnetworks/{subnet}", "networkIP": ip,
              "accessConfigs": [{"type": "ONE_TO_ONE_NAT"}] if external else []}
        body = {"name": name, "machineType": f"zones/{zone}/machineTypes/e2-small",
                "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
                "networkInterfaces": [ni], "tags": {"items": list(tags)}}
        if sa:
            body["serviceAccounts"] = [{"email": sa, "scopes": []}]
        r = inst_core.dispatch(self.inst, "POST", f"/compute/v1/projects/{P}/zones/{zone}/instances",
                               body=json.dumps(body).encode())
        assert r.status < 300, r.body
        return f"projects/{P}/zones/{zone}/instances/{name}/nic0"

    def topo(self, **kw):
        return from_gcp(self.net, self.inst, P, **kw)


class GcpTests(unittest.TestCase):
    def setUp(self):
        g = self.g = Gcp()
        g.network("vpc1")
        g.subnet("vpc1", "web-us", "us-central1", "10.10.1.0/24")
        g.subnet("vpc1", "db-eu", "europe-west1", "10.20.1.0/24")     # global VPC: other region, same network
        self.web = g.vm("web", "us-central1-a", "vpc1", "us-central1", "web-us", "10.10.1.10", tags=["web"], external=True)
        self.db = g.vm("db", "europe-west1-b", "vpc1", "europe-west1", "db-eu", "10.20.1.10", tags=["db"],
                       sa="db@proj1.iam.gserviceaccount.com")
        self.batch = g.vm("batch", "us-central1-a", "vpc1", "us-central1", "web-us", "10.10.1.11")

    def test_implied_deny_ingress_allow_egress(self):
        t = self.g.topo()
        v = reach(t, self.web, self.db, "tcp", 5432)
        self.assertEqual((v.reachable, v.code), (False, "INGRESS_DENIED"))
        self.assertIn("implied-deny-ingress", v.reason)
        self.assertTrue(reach(t, self.web, INET, "tcp", 443).reachable)      # implied allow egress + external IP

    def test_target_tag_and_source_tag(self):
        self.g.fw(name="db-from-web", network="vpc1", direction="INGRESS", priority=1000,
                  sourceTags=["web"], targetTags=["db"], allowed=[{"IPProtocol": "tcp", "ports": ["5432"]}])
        t = self.g.topo()
        v = reach(t, self.web, self.db, "tcp", 5432)
        self.assertTrue(v.reachable, v.explain())
        self.assertEqual(v.path, "intra-network")                           # cross-region, one global VPC
        self.assertFalse(reach(t, self.batch, self.db, "tcp", 5432).reachable)   # no `web` tag
        self.assertFalse(reach(t, self.db, self.web, "tcp", 5432).reachable)     # target is db only

    def test_target_service_account(self):
        self.g.fw(name="sa-rule", network="vpc1", direction="INGRESS", sourceRanges=["10.0.0.0/8"],
                  targetServiceAccounts=["db@proj1.iam.gserviceaccount.com"], allowed=[{"IPProtocol": "tcp", "ports": ["5432"]}])
        t = self.g.topo()
        self.assertTrue(reach(t, self.batch, self.db, "tcp", 5432).reachable)
        self.assertEqual(reach(t, self.db, self.web, "tcp", 5432).code, "INGRESS_DENIED")   # web runs as another SA

    def test_priority_tie_deny_wins(self):
        for action in ("allowed", "denied"):
            self.g.fw(**{"name": f"tie-{action}", "network": "vpc1", "direction": "INGRESS", "priority": 900,
                         "sourceRanges": ["10.0.0.0/8"], action: [{"IPProtocol": "tcp", "ports": ["22"]}]})
        v = reach(self.g.topo(), self.web, self.db, "tcp", 22)
        self.assertEqual((v.reachable, v.code), (False, "INGRESS_DENIED"))
        self.assertIn("tie-denied", v.reason)
        # a strictly better priority allow wins over the deny
        self.g.fw(name="better", network="vpc1", direction="INGRESS", priority=800, sourceRanges=["10.10.1.10/32"],
                  allowed=[{"IPProtocol": "tcp", "ports": ["22"]}])
        self.assertTrue(reach(self.g.topo(), self.web, self.db, "tcp", 22).reachable)

    def test_egress_deny_rule(self):
        self.g.fw(name="no-internet", network="vpc1", direction="EGRESS", priority=1000, destinationRanges=["0.0.0.0/0"],
                  denied=[{"IPProtocol": "all"}])
        self.g.fw(name="internal-ok", network="vpc1", direction="EGRESS", priority=900, destinationRanges=["10.0.0.0/8"],
                  allowed=[{"IPProtocol": "all"}])
        self.g.fw(name="allow-internal-in", network="vpc1", direction="INGRESS", sourceRanges=["10.0.0.0/8"],
                  allowed=[{"IPProtocol": "all"}])
        t = self.g.topo()
        self.assertEqual(reach(t, self.web, INET, "tcp", 443).code, "EGRESS_DENIED")
        self.assertTrue(reach(t, self.web, self.db, "tcp", 22).reachable)

    def test_external_ip_or_cloud_nat(self):
        t = self.g.topo()
        self.assertEqual(reach(t, self.batch, INET, "tcp", 443).code, "NO_PUBLIC_IP")
        self.g.call("POST", "regions/us-central1/routers", {"name": "r1", "network": "vpc1", "nats": [
            {"name": "nat1", "sourceSubnetworkIpRangesToNat": "ALL_SUBNETWORKS_ALL_IP_RANGES"}]})
        t = self.g.topo()
        v = reach(t, self.batch, INET, "tcp", 443)
        self.assertEqual((v.reachable, v.path), (True, "internet-via-nat"))
        self.assertEqual(reach(t, self.db, INET, "tcp", 443).code, "NO_PUBLIC_IP")   # NAT is regional

    def test_tagged_route_and_priority(self):
        # a more specific blackhole-ish route only for tagged instances: next hop instance without canIpForward
        self.g.route(name="via-batch", network="vpc1", destRange="0.0.0.0/0", priority=500, tags=["web"],
                     nextHopInstance=f"projects/{P}/zones/us-central1-a/instances/batch")
        t = self.g.topo()
        self.assertEqual(reach(t, self.web, INET, "tcp", 443).code, "SOURCE_DEST_CHECK")   # canIpForward off
        self.assertTrue(reach(t, self.web, self.batch, "tcp", 22).code != "SOURCE_DEST_CHECK")
        self.assertEqual(reach(t, self.db, INET, "tcp", 443).code, "NO_PUBLIC_IP")          # untagged: default route

    def test_default_route_deleted_means_no_internet(self):
        name = next(r["name"] for r in self.g.net.routes.values() if r.get("_system") and r["networkName"] == "vpc1")
        self.g.call("DELETE", f"global/routes/{name}")
        self.assertEqual(reach(self.g.topo(), self.web, INET, "tcp", 443).code, "NO_ROUTE")

    def test_one_sided_peering_inactive(self):
        g = self.g
        g.network("vpc2")
        g.subnet("vpc2", "s2", "us-central1", "10.30.1.0/24")
        x2 = g.vm("x2", "us-central1-a", "vpc2", "us-central1", "s2", "10.30.1.10")
        g.call("POST", "global/networks/vpc1/addPeering", {"networkPeering": {"name": "p", "network": "vpc2"}})
        self.assertFalse(reach(g.topo(), self.web, x2, "tcp", 22).reachable)

    def test_peering_exchanges_routes_non_transitive(self):
        g = self.g
        g.network("vpc2")
        g.subnet("vpc2", "s2", "us-central1", "10.30.1.0/24")
        g.network("vpc3")
        g.subnet("vpc3", "s3", "us-central1", "10.40.1.0/24")
        x2 = g.vm("x2", "us-central1-a", "vpc2", "us-central1", "s2", "10.30.1.10")
        x3 = g.vm("x3", "us-central1-a", "vpc3", "us-central1", "s3", "10.40.1.10")
        for n in ("vpc1", "vpc2", "vpc3"):
            g.fw(name=f"in-{n}", network=n, direction="INGRESS", sourceRanges=["10.0.0.0/8"], allowed=[{"IPProtocol": "all"}])
        for a, b in (("vpc1", "vpc2"), ("vpc2", "vpc1"), ("vpc2", "vpc3"), ("vpc3", "vpc2")):
            g.call("POST", f"global/networks/{a}/addPeering", {"networkPeering": {"name": f"{a}-{b}", "network": b,
                                                                                "exchangeSubnetRoutes": True}})
        t = g.topo()
        v = reach(t, self.web, x2, "tcp", 22)
        self.assertEqual((v.reachable, v.path), (True, "peering"), v.explain())
        v = reach(t, self.web, x3, "tcp", 22)
        self.assertFalse(v.reachable)
        self.assertEqual(v.code, "PRIVATE_DEST_VIA_GATEWAY")    # 10.40/16 not exchanged into vpc1 → default route


if __name__ == "__main__":
    unittest.main(verbosity=2)
