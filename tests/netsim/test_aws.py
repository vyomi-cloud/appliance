"""AWS translator + evaluator: classic expert gotchas, topologies built via the real vpc_core API.

    PYTHONPATH=. python3 tests/netsim/test_aws.py
"""
from __future__ import annotations

import unittest

from core.netsim.evaluate import reach
from core.netsim.from_aws import from_aws, primary_eni
from tests.netsim.aws_fixture import Aws, classic_two_tier

INET = "198.51.100.7"


def eni(i):
    return primary_eni(i)


class TwoTier(unittest.TestCase):
    def setUp(self):
        self.x = classic_two_tier()
        self.a = self.x["aws"]

    def t(self):
        return from_aws(self.a.store)

    def test_sg_allows_22_only(self):
        t = self.t()
        v = reach(t, eni(self.x["a"]), eni(self.x["b"]), "tcp", 22)
        self.assertTrue(v.reachable, v.explain())
        self.assertEqual(v.path, "intra-network")
        v = reach(t, eni(self.x["a"]), eni(self.x["b"]), "tcp", 80)
        self.assertFalse(v.reachable)
        self.assertEqual(v.code, "INGRESS_DENIED")
        self.assertEqual(v.blocked_by, self.x["app"])

    def test_same_subnet_still_needs_sg(self):
        t = self.t()
        self.assertTrue(reach(t, eni(self.x["a"]), eni(self.x["c"]), "tcp", 22).reachable)
        v = reach(t, eni(self.x["a"]), eni(self.x["c"]), "tcp", 443)
        self.assertEqual((v.reachable, v.code, v.path), (False, "INGRESS_DENIED", "intra-subnet"))

    def test_sg_referencing_sg(self):
        db = self.a.sg(self.x["vpc"], "db")
        self.a.allow_in(db, "tcp", 5432, 5432, src_sg=self.x["web"])
        other = self.a.sg(self.x["vpc"], "other")
        d = self.a.instance(self.x["priv"], [db], "10.213.2.20")
        o = self.a.instance(self.x["pub"], [other], "10.213.1.30")
        t = self.t()
        self.assertTrue(reach(t, eni(self.x["a"]), eni(d), "tcp", 5432).reachable)   # a is in web
        v = reach(t, eni(o), eni(d), "tcp", 5432)                                     # o is not
        self.assertEqual((v.reachable, v.code), (False, "INGRESS_DENIED"))

    def test_nacl_deny_beats_later_allow(self):
        n = self.a.nacl(self.x["vpc"], self.x["priv"])
        self.a.nacl_entry(n, 90, False, "deny", "6", "10.213.1.0/24", 22, 22)
        self.a.nacl_entry(n, 100, False, "allow")
        self.a.nacl_entry(n, 100, True, "allow")
        v = reach(self.t(), eni(self.x["a"]), eni(self.x["b"]), "tcp", 22)
        self.assertEqual((v.reachable, v.code, v.blocked_by), (False, "ACL_INGRESS_DENIED", n))

    def test_nacl_forgetting_ephemeral_return_ports(self):
        n = self.a.nacl(self.x["vpc"], self.x["pub"])
        self.a.nacl_entry(n, 100, False, "allow", "6", "0.0.0.0/0", 22, 22)    # only 22 in
        self.a.nacl_entry(n, 100, True, "allow")                               # all out
        v = reach(self.t(), eni(self.x["a"]), eni(self.x["b"]), "tcp", 22)
        self.assertEqual((v.reachable, v.code), (False, "ACL_RETURN_DENIED"), v.explain())
        # the console's favourite half-fix: 49152-65535 → part of Linux's 32768-60999 still dies
        self.a.nacl_entry(n, 110, False, "allow", "6", "0.0.0.0/0", 49152, 65535)
        v = reach(self.t(), eni(self.x["a"]), eni(self.x["b"]), "tcp", 22)
        self.assertEqual(v.code, "ACL_RETURN_DENIED")
        self.assertIn("32768-49151", v.reason)
        self.assertTrue(reach(self.t(), eni(self.x["a"]), eni(self.x["b"]), "tcp", 22, src_port=50000).reachable)
        self.a.nacl_entry(n, 120, False, "allow", "6", "0.0.0.0/0", 1024, 65535)
        self.assertTrue(reach(self.t(), eni(self.x["a"]), eni(self.x["b"]), "tcp", 22).reachable)

    def test_nacl_does_not_apply_inside_subnet(self):
        n = self.a.nacl(self.x["vpc"], self.x["pub"])        # no entries → deny everything at the boundary
        t = self.t()
        self.assertTrue(reach(t, eni(self.x["a"]), eni(self.x["c"]), "tcp", 22).reachable)
        self.assertEqual(reach(t, eni(self.x["a"]), eni(self.x["b"]), "tcp", 22).code, "ACL_EGRESS_DENIED")
        del n

    def test_public_needs_public_ip(self):
        v = reach(self.t(), eni(self.x["a"]), INET, "tcp", 443)
        self.assertEqual((v.reachable, v.code), (False, "NO_PUBLIC_IP"))
        self.a.eip(self.x["a"])
        v = reach(self.t(), eni(self.x["a"]), INET, "tcp", 443)
        self.assertEqual((v.reachable, v.path), (True, "internet-via-igw"), v.explain())

    def test_more_specific_route_wins(self):
        self.a.eip(self.x["a"])
        nat = self.a.nat(self.x["pub"])
        self.a.route(self.x["pub_rt"], "198.51.100.0/24", NatGatewayId=nat)
        self.a.call("DeleteNatGateway", NatGatewayId=nat)     # route goes blackhole, like AWS
        t = self.t()
        v = reach(t, eni(self.x["a"]), INET, "tcp", 443)
        self.assertEqual((v.reachable, v.code), (False, "BLACKHOLE_ROUTE"), v.explain())
        self.assertTrue(reach(t, eni(self.x["a"]), "203.0.113.9", "tcp", 443).reachable)

    def test_private_subnet_nat_egress_only(self):
        t = self.t()
        self.assertEqual(reach(t, eni(self.x["b"]), INET, "tcp", 443).code, "NO_ROUTE")
        priv_rt = self.a.rtb(self.x["vpc"], self.x["priv"])
        self.a.route(priv_rt, "0.0.0.0/0", GatewayId=self.x["igw"])
        self.assertEqual(reach(self.t(), eni(self.x["b"]), INET, "tcp", 443).code, "NO_PUBLIC_IP")
        self.a.call("DeleteRoute", RouteTableId=priv_rt, DestinationCidrBlock="0.0.0.0/0")
        nat = self.a.nat(self.x["pub"])
        self.a.route(priv_rt, "0.0.0.0/0", NatGatewayId=nat)
        v = reach(self.t(), eni(self.x["b"]), INET, "tcp", 443)
        self.assertEqual((v.reachable, v.path), (True, "internet-via-nat"), v.explain())
        # NAT is egress only: the internet cannot open a connection to b
        self.assertEqual(reach(self.t(), INET, eni(self.x["b"]), "tcp", 22).code, "NOT_PUBLIC")
        # NAT placed in the PRIVATE subnet (no igw route there) is a classic mistake
        bad = self.a.nat(self.x["priv"])
        self.a.call("DeleteRoute", RouteTableId=priv_rt, DestinationCidrBlock="0.0.0.0/0")
        self.a.route(priv_rt, "0.0.0.0/0", NatGatewayId=bad)
        self.assertEqual(reach(self.t(), eni(self.x["b"]), INET, "tcp", 443).code, "NAT_NO_IGW_ROUTE")

    def test_nat_subnet_nacl_applies(self):
        priv_rt = self.a.rtb(self.x["vpc"], self.x["priv"])
        nat = self.a.nat(self.x["pub"])
        self.a.route(priv_rt, "0.0.0.0/0", NatGatewayId=nat)
        n = self.a.nacl(self.x["vpc"], self.x["pub"])
        self.a.nacl_entry(n, 100, False, "allow", "6", "10.213.0.0/16", 443, 443)   # private → NAT
        self.a.nacl_entry(n, 100, True, "allow")
        v = reach(self.t(), eni(self.x["b"]), INET, "tcp", 443)
        self.assertEqual((v.reachable, v.code), (False, "ACL_RETURN_DENIED"), v.explain())
        self.a.nacl_entry(n, 110, False, "allow", "6", "0.0.0.0/0", 1024, 65535)
        self.assertTrue(reach(self.t(), eni(self.x["b"]), INET, "tcp", 443).reachable)

    def test_detached_igw_is_blackhole(self):
        self.a.eip(self.x["a"])
        self.a.call("DetachInternetGateway", InternetGatewayId=self.x["igw"], VpcId=self.x["vpc"])
        self.assertEqual(reach(self.t(), eni(self.x["a"]), INET, "tcp", 443).code, "IGW_DETACHED")

    def test_inbound_from_internet(self):
        pub = self.a.eip(self.x["a"])
        t = self.t()
        self.assertEqual(reach(t, INET, eni(self.x["a"]), "tcp", 22).code, "INGRESS_DENIED")  # 22 only from VPC
        self.a.allow_in(self.x["web"], "tcp", 22, 22, cidr="0.0.0.0/0")
        v = reach(self.t(), INET, pub, "tcp", 22)
        self.assertTrue(v.reachable, v.explain())

    def test_appliance_needs_source_dest_check_off(self):
        priv_rt = self.a.rtb(self.x["vpc"], self.x["priv"])
        # vpc_core's CreateRoute has no InstanceId target yet → write the route as AWS stores it
        self.a.m["route_tables"][priv_rt]["routes"].append({"dest": "0.0.0.0/0", "target": self.x["a"]})
        v = reach(self.t(), eni(self.x["b"]), INET, "tcp", 443)
        self.assertEqual(v.code, "SOURCE_DEST_CHECK")
        self.a.m["instances"][self.x["a"]]["source_dest_check"] = False
        self.a.eip(self.x["a"])
        self.a.allow_in(self.x["web"], "tcp", 443, 443, cidr="10.213.0.0/16")
        v = reach(self.t(), eni(self.x["b"]), INET, "tcp", 443)
        self.assertTrue(v.reachable, v.explain())
        self.assertEqual(v.path, "via-appliance:internet-via-igw")


class Peering(unittest.TestCase):
    def test_non_transitive_and_return_route(self):
        a = Aws()
        v1, v2, v3 = a.vpc("10.1.0.0/16"), a.vpc("10.2.0.0/16"), a.vpc("10.3.0.0/16")
        s1, s2, s3 = a.subnet(v1, "10.1.1.0/24"), a.subnet(v2, "10.2.1.0/24"), a.subnet(v3, "10.3.1.0/24")
        sgs = []
        for v in (v1, v2, v3):
            g = a.sg(v, "all")
            a.allow_in(g, "-1", None, None, cidr="10.0.0.0/8")
            sgs.append(g)
        i1, i2, i3 = (a.instance(s, [g], ip) for s, g, ip in
                      ((s1, sgs[0], "10.1.1.10"), (s2, sgs[1], "10.2.1.10"), (s3, sgs[2], "10.3.1.10")))
        p12, p23 = a.pcx(v1, v2), a.pcx(v2, v3)
        rt1, rt2, rt3 = (a.m["subnets"][s]["route_table"] for s in (s1, s2, s3))
        a.route(rt1, "10.2.0.0/16", VpcPeeringConnectionId=p12)
        t = from_aws(a.store)
        self.assertEqual(reach(t, eni(i1), eni(i2), "tcp", 22).code, "PEERING_NO_RETURN_ROUTE")
        a.route(rt2, "10.1.0.0/16", VpcPeeringConnectionId=p12)
        self.assertTrue(reach(from_aws(a.store), eni(i1), eni(i2), "tcp", 22).reachable)
        # 1 → 3 through 2: send 10.3/16 into p12 — AWS drops it (non-transitive)
        a.route(rt1, "10.3.0.0/16", VpcPeeringConnectionId=p12)
        a.route(rt2, "10.3.0.0/16", VpcPeeringConnectionId=p23)
        v = reach(from_aws(a.store), eni(i1), eni(i3), "tcp", 22)
        self.assertEqual((v.reachable, v.code), (False, "PEERING_NOT_TRANSITIVE"))
        # an unpeered VPC's private IP is not reachable via the internet either
        self.assertEqual(reach(from_aws(a.store), eni(i3), eni(i1), "tcp", 22).code, "NO_ROUTE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
