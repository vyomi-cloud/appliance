"""Pure checks on the nftables compiler + flow-log formatter (no Docker needed).

    PYTHONPATH=. python3 tests/netsim/test_enforce_compile.py
"""
from __future__ import annotations

import unittest

from core.netsim.enforce import compile_plan, table_name
from core.netsim.flowlogs import FlowLogCollector, parse_nft_set
from core.netsim.from_aws import from_aws, primary_eni
from core.netsim.model import Topology
from tests.netsim.aws_fixture import classic_two_tier


class Compile(unittest.TestCase):
    def setUp(self):
        self.x = classic_two_tier()
        self.a = self.x["aws"]

    def plan(self):
        return compile_plan(from_aws(self.a.store), "Space-1")

    def test_atomic_idempotent_header_and_table(self):
        p = self.plan()
        self.assertEqual(p.table, "vyomi_Space_1")
        self.assertEqual(table_name("a/b c"), "vyomi_a_b_c")
        head = p.nft.splitlines()[:3]
        self.assertEqual(head, ["table inet vyomi_Space_1", "delete table inet vyomi_Space_1", "table inet vyomi_Space_1 {"])
        self.assertEqual(p.nft, self.plan().nft.replace(p.nft, p.nft))      # deterministic for same state

    def test_masquerade_only_where_internet_path_exists(self):
        p = self.plan()
        post = p.nft.split("chain postrouting")[1]
        self.assertNotIn("masquerade", post)                   # nobody has a public IP / NAT yet
        self.a.eip(self.x["a"])
        post = self.plan().nft.split("chain postrouting")[1]
        self.assertIn("ip saddr 10.213.1.10 ip daddr != @model masquerade", post)
        self.assertNotIn("10.213.1.11", post)                  # same subnet, no public IP
        self.assertNotIn("10.213.2.10", post)                  # private subnet

    def test_nacl_chain_is_ordered_and_stateless(self):
        n = self.a.nacl(self.x["vpc"], self.x["priv"])
        self.a.nacl_entry(n, 200, False, "allow")
        self.a.nacl_entry(n, 90, False, "deny", "6", "10.213.1.0/24", 22, 22)
        nft = self.plan().nft
        chain = [c for c in nft.split("  chain ") if c.startswith("acl_s1_in")][0]
        i90, i200 = chain.index("#90"), chain.index("#200")
        self.assertLess(i90, i200)
        self.assertIn("ip saddr 10.213.1.0/24 meta l4proto tcp th dport 22 counter goto deny", chain)
        fwd = nft.split("chain forward")[1].split("chain pass")[0]
        self.assertLess(fwd.index("jump acl_s1_in"), fwd.index("ct state established"))   # ACL sees replies too

    def test_sg_reference_compiles_to_member_ips(self):
        db = self.a.sg(self.x["vpc"], "db")
        self.a.allow_in(db, "tcp", 5432, 5432, src_sg=self.x["web"])
        self.a.instance(self.x["priv"], [db], "10.213.2.20")
        nft = self.plan().nft
        # web members 10.213.1.10 + .11, collapsed into one prefix; d (sg db) is not a member
        self.assertIn("ip saddr 10.213.1.10/31 meta l4proto tcp th dport 5432 counter return", nft)
        self.assertNotIn("172.31.", nft.split("chain forward")[1].split("chain pass")[0])  # empty default VPC not enforced

    def test_networks_only_for_used_subnets(self):
        p = self.plan()
        self.assertEqual(sorted(n["cidr"] for n in p.networks), ["10.213.1.0/24", "10.213.2.0/24"])
        self.assertTrue(all(len(n["bridge"]) <= 15 and n["gateway"].endswith(".1") for n in p.networks))

    def test_roundtrip_dict(self):
        t = from_aws(self.a.store)
        t2 = Topology.from_dict(t.to_dict())
        self.assertEqual(compile_plan(t, "s").nft, compile_plan(t2, "s").nft)


class FlowLogs(unittest.TestCase):
    def test_parse_and_aws_format(self):
        x = classic_two_tier()
        topo = from_aws(x["aws"].store)
        js = {"nftables": [{"metainfo": {"version": "1.1.6"}}, {"set": {"family": "inet", "name": "flows", "table": "vyomi_s",
              "elem": [{"elem": {"val": {"concat": ["10.213.1.10", "10.213.2.10", "tcp", 40001, 22]},
                                 "timeout": 900, "expires": 899, "counter": {"packets": 4, "bytes": 216}}}]}}]}
        rows = parse_nft_set(js)
        self.assertEqual(rows, [{"src": "10.213.1.10", "dst": "10.213.2.10", "proto": 6, "sport": 40001, "dport": 22,
                                 "packets": 4, "bytes": 216}])
        col = FlowLogCollector(topo, account_id="111122223333")
        col.ingest(rows, [], now=1000)
        recs = col.aws_records()
        self.assertEqual(recs[0], f"2 111122223333 {primary_eni(x['a'])} 10.213.1.10 10.213.2.10 40001 22 6 4 216 940 1000 ACCEPT OK")
        self.assertEqual(len(recs), 2)                       # logged on both ENIs
        rows[0]["packets"], rows[0]["bytes"] = 6, 300
        self.assertEqual(col.ingest(rows, [], now=1060)[0]["packets"], 2)    # deltas per window
        self.assertTrue(col.azure_tuples()[0].startswith("1000,10.213.1.10,10.213.2.10,40001,22,T,O,A,C,4,216"))
        self.assertEqual(col.gcp_records()[0]["reporter"], "SRC")


if __name__ == "__main__":
    unittest.main(verbosity=2)
