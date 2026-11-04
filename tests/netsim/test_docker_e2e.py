"""REAL-PACKET end-to-end test: evaluator verdict == what the kernel actually does.

An AWS topology is built through the real vpc_core EC2 API, translated (from_aws), compiled
(enforce.py) into Docker networks (one per subnet, real CIDRs) + an nftables table applied
by a netd sidecar in the Docker host netns. Instances are `netsim-test-*` containers on
those networks with their model IPs, each running a tiny TCP server that echoes the peer
address it sees. A third network plays "the internet" (203.0.113.0/24).

For every case: mutate the AWS state via the EC2 API → re-translate → re-apply (atomic,
idempotent) → evaluate reach() → open a real TCP connection (pinned source port) →
assert verdict.reachable == connection succeeded.

Skipped when Docker or nft-in-host-netns is unavailable. Everything it creates is named
netsim-test-* (and nft table vyomi_netsimtest) and is removed at the end.

    PYTHONPATH=. python3 tests/netsim/test_docker_e2e.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest

from core.netsim.enforce import DockerEnforcer
from core.netsim.evaluate import reach
from core.netsim.flowlogs import FlowLogCollector
from core.netsim.from_aws import from_aws, primary_eni
from tests.netsim.aws_fixture import classic_two_tier
from tests.netsim.test_azure import Az, sid as az_sid
from tests.netsim.test_gcp import Gcp

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPACE = "netsimtest"
PFX = "netsim-test-"
NETD = "netsim-test-netd"
NETD_IMAGE = "netsim-test-netd:latest"
NODE_IMAGE = os.environ.get("NETSIM_NODE_IMAGE", "python:3-alpine")
INET_NET, INET_CIDR, INET_IP = "netsim-test-inet", "203.0.113.0/24", "203.0.113.10"
PORTS = (22, 80, 443, 5432, 8080)

SERVER = f"""
import socket, threading
def serve(port):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port)); s.listen(64)
    while True:
        c, a = s.accept()
        try: c.sendall(f"{{port}} {{a[0]}}\\n".encode())
        finally: c.close()
for p in {PORTS!r}:
    threading.Thread(target=serve, args=(p,), daemon=True).start()
threading.Event().wait()
"""

CLIENT = """
import socket, sys
host, port, sport = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", sport)); s.settimeout(2.0)
try:
    s.connect((host, port)); print("OK", s.recv(100).decode().strip())
except Exception as e:
    print("FAIL", type(e).__name__)
"""


def sh(*args, check=True, input_=None):
    p = subprocess.run(list(args), capture_output=True, text=True, input=input_)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:5])}: {p.stderr.strip()}")
    return p


def docker_ok() -> str | None:
    if not shutil.which("docker"):
        return "docker CLI not found"
    if sh("docker", "info", check=False).returncode != 0:
        return "docker daemon unavailable"
    p = sh("docker", "run", "--rm", "--network", "host", "--cap-add", "NET_ADMIN", "alpine:3",
           "sh", "-c", "apk add -q --no-cache nftables >/dev/null 2>&1; nft list tables >/dev/null", check=False)
    if p.returncode != 0:
        return f"nft in the host netns unavailable: {p.stderr.strip()[:200]}"
    return None


SKIP = docker_ok()


@unittest.skipIf(SKIP is not None, SKIP or "")
class DockerE2E(unittest.TestCase):
    results: list = []

    @classmethod
    def setUpClass(cls):
        cls.cleanup()
        sh("docker", "build", "-q", "-t", NETD_IMAGE, os.path.join(ROOT, "docker", "netd"))
        x = cls.x = classic_two_tier()
        a = cls.a = x["aws"]
        cls.public_ip = a.eip(x["a"])
        x["other"] = a.sg(x["vpc"], "other")
        a.allow_in(x["other"], "tcp", 22, 22, cidr="10.213.0.0/16")
        x["d"] = a.instance(x["pub"], [x["other"]], "10.213.1.12")
        cls.enf = DockerEnforcer(SPACE, prefix=PFX, netd_name=NETD, netd_image=NETD_IMAGE, inbound_dnat=True)
        plan = cls.enf.apply(from_aws(a.store))
        assert not [w for w in plan.warnings if "outside its subnet" in w], plan.warnings
        cls.nodes = {}
        topo = from_aws(a.store)
        for key in ("a", "b", "c", "d"):
            eni = primary_eni(x[key])
            name = f"{PFX}{key}"
            sh("docker", "run", "-d", "--name", name, *cls.enf.run_args(topo, eni), "--label", "netsim-test=1",
               NODE_IMAGE, "python3", "-c", SERVER)
            cls.nodes[key] = name
        sh("docker", "network", "create", "--subnet", INET_CIDR, "-o", "com.docker.network.bridge.enable_ip_masquerade=false", "--label", "netsim-test=1", INET_NET)
        sh("docker", "run", "-d", "--name", f"{PFX}inet", "--network", INET_NET, "--ip", INET_IP,
           "--label", "netsim-test=1", NODE_IMAGE, "python3", "-c", SERVER)
        cls.nodes["inet"] = f"{PFX}inet"
        time.sleep(1.5)

    @classmethod
    def cleanup(cls):
        for c in sh("docker", "ps", "-aq", "--filter", "name=^netsim-test-", check=False).stdout.split():
            sh("docker", "rm", "-f", c, check=False)
        for n in sh("docker", "network", "ls", "--format", "{{.Name}}", check=False).stdout.split():
            if n.startswith("netsim-test-"):
                sh("docker", "network", "rm", n, check=False)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.enf.teardown(remove_networks=False, remove_netd=False)
        except Exception as e:                   # noqa: BLE001
            print("teardown:", e, file=sys.stderr)
        sh("docker", "rm", "-f", NETD, check=False)
        cls.cleanup()
        sh("docker", "rmi", NETD_IMAGE, check=False)
        cls.print_table()

    # ── helpers ──
    def probe(self, src_key, dst_ip, port, sport):
        out = sh("docker", "exec", self.nodes[src_key], "python3", "-c", CLIENT, dst_ip, str(port), str(sport)).stdout.strip()
        return out.startswith("OK"), out

    def case(self, label, src_key, dst, port, sport=None, expect=None, public=False):
        sport = sport or 40001 + len(type(self).results)      # unique 5-tuple per case → precise evidence
        topo = from_aws(self.a.store)
        self.enf.apply(topo)
        x = self.x
        src = INET_IP if src_key == "inet" else primary_eni(x[src_key])
        if dst == "inet":
            dst_ip, dst_ref = INET_IP, INET_IP
        else:
            dst_ref = primary_eni(x[dst])
            dst_ip = topo.interfaces[dst_ref].public_ip if public else topo.interfaces[dst_ref].ip
        v = reach(topo, src, dst_ref if src_key != "inet" else dst_ip, "tcp", port, src_port=sport)
        ok, raw = self.probe(src_key, dst_ip, port, sport)
        row = {"case": label, "flow": f"{src_key}->{dst}:{port}", "evaluator": "ALLOW" if v.reachable else f"BLOCK {v.code}",
               "packets": "ALLOW" if ok else "BLOCK", "seen": raw, "match": v.reachable == ok,
               "src_ip": INET_IP if src_key == "inet" else topo.interfaces[src].ip,
               "dst_ip": dst_ip if dst == "inet" else topo.interfaces[dst_ref].ip,   # nft sees post-DNAT addresses
               "sport": sport, "dport": port}
        type(self).results.append(row)
        self.assertEqual(v.reachable, ok, f"{label}: evaluator={v.explain()}\nprobe={raw}")
        if expect is not None:
            self.assertEqual(v.reachable, expect, f"{label}: unexpected verdict {v.explain()}")
        return v, raw

    @classmethod
    def print_table(cls):
        if not cls.results:
            return
        print("\n| # | case | flow | evaluator | real packets | nft evidence | match |\n|---|---|---|---|---|---|---|")
        for n, r in enumerate(cls.results, 1):
            print(f"| {n} | {r['case']} | {r['flow']} | {r['evaluator']} | {r['packets']} ({r['seen']}) | "
                  f"{r.get('evidence', '-')} | {'yes' if r['match'] else 'NO'} |")
        path = os.environ.get("NETSIM_E2E_JSON")
        if path:
            with open(path, "w") as f:
                json.dump(cls.results, f, indent=1)

    # ── the cases (one ordered scenario) ──
    def test_scenario(self):
        x, a = self.x, self.a
        # 1 security groups
        self.case("SG allows tcp/22 from VPC", "a", "b", 22, expect=True)
        self.case("SG has no tcp/80 rule", "a", "b", 80, expect=False)
        self.case("SG enforced inside one subnet", "a", "c", 22, expect=True)
        self.case("same subnet, port not in SG", "a", "c", 443, expect=False)
        a.allow_in(x["app"], "tcp", 5432, 5432, src_sg=x["web"])
        self.case("SG references SG (member)", "a", "b", 5432, expect=True)
        self.case("SG references SG (non-member)", "d", "b", 5432, expect=False)
        # 2 NACL deny before allow
        n = a.nacl(x["vpc"], x["priv"])
        a.nacl_entry(n, 90, False, "deny", "6", "10.213.1.0/24", 22, 22)
        a.nacl_entry(n, 100, False, "allow")
        a.nacl_entry(n, 100, True, "allow")
        self.case("NACL rule 90 deny tcp/22", "a", "b", 22, expect=False)
        self.case("NACL rule 100 allow (5432)", "a", "b", 5432, expect=True)
        default_nacl = a.m["vpcs"][x["vpc"]]["default_nacl"]
        a.call("AssociateNetworkAcl", NetworkAclId=default_nacl, SubnetId=x["priv"])
        # 3 NACL forgetting the ephemeral return range
        n2 = a.nacl(x["vpc"], x["pub"])
        a.nacl_entry(n2, 100, False, "allow", "6", "0.0.0.0/0", 22, 22)
        a.nacl_entry(n2, 100, True, "allow")
        self.case("NACL lacks ephemeral inbound (reply dropped)", "a", "b", 22, expect=False)
        a.nacl_entry(n2, 110, False, "allow", "6", "0.0.0.0/0", 32768, 60999)
        self.case("NACL allows ephemeral inbound", "a", "b", 22, expect=True)
        a.call("AssociateNetworkAcl", NetworkAclId=default_nacl, SubnetId=x["pub"])
        # 4 internet via IGW: public IP required, route required
        _, seen = self.case("public subnet + EIP → internet", "a", "inet", 443, expect=True)
        self.assertNotIn("10.213.", seen, "internet saw a private source address (no NAT)")
        self.case("public subnet, no public IP → internet", "c", "inet", 443, expect=False)
        a.call("DeleteRoute", RouteTableId=x["pub_rt"], DestinationCidrBlock="0.0.0.0/0")
        self.case("no route to 0.0.0.0/0", "a", "inet", 443, expect=False)
        a.route(x["pub_rt"], "0.0.0.0/0", GatewayId=x["igw"])
        # 4b inbound to the public IP (1:1 DNAT like an IGW) — ingress rules still decide
        self.case("internet → EIP:22, SG allows 22 only from the VPC", "inet", "a", 22, expect=False, public=True)
        a.allow_in(x["web"], "tcp", 22, 22, cidr="0.0.0.0/0")
        _, seen = self.case("internet → EIP:22 after SG allows 0.0.0.0/0", "inet", "a", 22, expect=True, public=True)
        self.assertIn(INET_IP, seen, "instance should see the real internet source address")
        # 5 private subnet: no NAT → blocked; NAT → allowed (egress only)
        self.case("private subnet without NAT → internet", "b", "inet", 443, expect=False)
        nat = a.nat(x["pub"])
        priv_rt = a.rtb(x["vpc"], x["priv"])
        a.route(priv_rt, "0.0.0.0/0", NatGatewayId=nat)
        _, seen = self.case("private subnet via NAT gateway → internet", "b", "inet", 443, expect=True)
        self.assertNotIn("10.213.", seen, "internet saw the private source address")
        self.case("internet → private instance (NAT is egress-only)", "inet", "b", 22, expect=False)
        # flow logs from the real counters
        acc, rej = self.enf.flow_sets()
        col = FlowLogCollector(from_aws(a.store))
        col.ingest(acc, rej)
        recs = col.aws_records()
        type(self).flow_sample = recs[:6]
        print("\nAWS flow-log records (sample):\n" + "\n".join(recs[:6]))
        self.assertTrue(any(r.endswith("ACCEPT OK") for r in recs))
        self.assertTrue(any(r.endswith("REJECT OK") for r in recs))
        # evidence that OUR table made each decision (not Docker's isolation): every blocked case's
        # tuple (either direction — a NACL can kill the reply) is in `rejects`; every allowed one in `flows`
        def has(flows, r):
            return any((f["src"], f["dst"], f["sport"], f["dport"]) in (
                (r["src_ip"], r["dst_ip"], r["sport"], r["dport"]), (r["dst_ip"], r["src_ip"], r["dport"], r["sport"]))
                for f in flows)
        for r in type(self).results:
            if r["packets"] == "BLOCK":
                self.assertTrue(has(rej, r), f"blocked case not dropped by vyomi table: {r}")
                r["evidence"] = "rejects set"
            else:
                self.assertTrue(has(acc, r), f"allowed case missing from flows: {r}")
                r["evidence"] = "flows set"


INET2_NET, INET2_CIDR, INET2_IP = "netsim-test-inet2", "198.51.100.0/24", "198.51.100.10"


@unittest.skipIf(SKIP is not None, SKIP or "")
class MultiCloudE2E(unittest.TestCase):
    """The SAME enforcer driven by the GCP and Azure translators: priority-ordered stateful
    firewalls (deny-wins ties, target tags) and NSGs (default 65000 vnet allow, subnet NSG inside
    a subnet, default outbound access) — evaluator == packets."""
    results: list = []

    @classmethod
    def setUpClass(cls):
        DockerE2E.cleanup()
        sh("docker", "build", "-q", "-t", NETD_IMAGE, os.path.join(ROOT, "docker", "netd"))
        sh("docker", "network", "create", "--subnet", INET2_CIDR, "--label", "netsim-test=1", INET2_NET)
        sh("docker", "run", "-d", "--name", f"{PFX}inet2", "--network", INET2_NET, "--ip", INET2_IP,
           "--label", "netsim-test=1", NODE_IMAGE, "python3", "-c", SERVER)
        cls.enfs = []

    @classmethod
    def tearDownClass(cls):
        for e in cls.enfs:
            try:
                e.teardown(remove_networks=False)
            except Exception as ex:              # noqa: BLE001
                print("teardown:", ex, file=sys.stderr)
        sh("docker", "rm", "-f", NETD, check=False)
        DockerE2E.cleanup()
        sh("docker", "rmi", NETD_IMAGE, check=False)
        if cls.results:
            print("\n| # | cloud | case | flow | evaluator | real packets | match |\n|---|---|---|---|---|---|---|")
            for n, r in enumerate(cls.results, 1):
                print(f"| {n} | {r['cloud']} | {r['case']} | {r['flow']} | {r['evaluator']} | {r['packets']} ({r['seen']}) | "
                      f"{'yes' if r['match'] else 'NO'} |")

    def run_cloud(self, cloud, space, topo_fn, nodes, cases):
        enf = DockerEnforcer(space, prefix=PFX, netd_name=NETD, netd_image=NETD_IMAGE)
        type(self).enfs.append(enf)
        topo = topo_fn()
        enf.apply(topo)
        names = {}
        for key, iface in nodes.items():
            names[key] = f"{PFX}{space}-{key}"
            sh("docker", "run", "-d", "--name", names[key], *enf.run_args(topo, iface), "--label", "netsim-test=1",
               NODE_IMAGE, "python3", "-c", SERVER)
        names["inet"] = f"{PFX}inet2"
        time.sleep(1.5)
        for n, (label, mutate, src, dst, port, expect) in enumerate(cases):
            if mutate:
                mutate()
            topo = topo_fn()
            enf.apply(topo)
            dst_ip = INET2_IP if dst == "inet" else topo.interfaces[nodes[dst]].ip
            sport = 41001 + len(type(self).results)
            v = reach(topo, nodes[src], nodes[dst] if dst != "inet" else dst_ip, "tcp", port, src_port=sport)
            out = sh("docker", "exec", names[src], "python3", "-c", CLIENT, dst_ip, str(port), str(sport)).stdout.strip()
            ok = out.startswith("OK")
            type(self).results.append({"cloud": cloud, "case": label, "flow": f"{src}->{dst}:{port}",
                                       "evaluator": "ALLOW" if v.reachable else f"BLOCK {v.code}",
                                       "packets": "ALLOW" if ok else "BLOCK", "seen": out, "match": ok == v.reachable})
            self.assertEqual(v.reachable, ok, f"{cloud} {label}: {v.explain()}\nprobe={out}")
            self.assertEqual(v.reachable, expect, f"{cloud} {label}: unexpected verdict {v.explain()}")

    def test_gcp(self):
        g = Gcp()
        g.network("vpc1")
        g.subnet("vpc1", "web-us", "us-central1", "10.214.1.0/24")
        g.subnet("vpc1", "db-eu", "europe-west1", "10.214.2.0/24")
        web = g.vm("web", "us-central1-a", "vpc1", "us-central1", "web-us", "10.214.1.10", tags=["web"], external=True)
        db = g.vm("db", "europe-west1-b", "vpc1", "europe-west1", "db-eu", "10.214.2.10", tags=["db"])
        batch = g.vm("batch", "us-central1-a", "vpc1", "us-central1", "web-us", "10.214.1.11")

        def fw(**b):
            return lambda: g.fw(network="vpc1", **b)
        self.run_cloud("gcp", "netsimgcp", g.topo, {"web": web, "db": db, "batch": batch}, [
            ("implied deny ingress", None, "web", "db", 5432, False),
            ("sourceTags web → targetTags db", fw(name="db-from-web", direction="INGRESS", sourceTags=["web"],
                                                   targetTags=["db"], allowed=[{"IPProtocol": "tcp", "ports": ["5432"]}]),
             "web", "db", 5432, True),
            ("untagged source", None, "batch", "db", 5432, False),
            ("priority tie: deny wins", lambda: (fw(name="tie-a", direction="INGRESS", priority=900, sourceRanges=["10.0.0.0/8"],
                                                    allowed=[{"IPProtocol": "tcp", "ports": ["22"]}])(),
                                                 fw(name="tie-d", direction="INGRESS", priority=900, sourceRanges=["10.0.0.0/8"],
                                                    denied=[{"IPProtocol": "tcp", "ports": ["22"]}])()),
             "web", "db", 22, False),
            ("lower number beats the deny", fw(name="better", direction="INGRESS", priority=800,
                                               sourceRanges=["10.214.1.10/32"], allowed=[{"IPProtocol": "tcp", "ports": ["22"]}]),
             "web", "db", 22, True),
            ("external IP → internet (implied allow egress)", None, "web", "inet", 443, True),
            ("no external IP, no Cloud NAT", None, "batch", "inet", 443, False),
        ])

    def test_azure(self):
        z = Az()
        nsg_web = z.nsg("nsg-web", [dict(name="ssh", priority=100, direction="Inbound", access="Allow", protocol="Tcp",
                                         destinationPortRange="22", sourceAddressPrefix="VirtualNetwork")])
        z.vnet("vnet1", ["10.215.0.0/16"], {"web": {"addressPrefix": "10.215.1.0/24"},
                                            "app": {"addressPrefix": "10.215.2.0/24", "defaultOutboundAccess": False}})
        web = z.nic("web-nic", az_sid("vnet1", "web"), "10.215.1.4", nsg=nsg_web)
        app = z.nic("app-nic", az_sid("vnet1", "app"), "10.215.2.4")
        app2 = z.nic("app2-nic", az_sid("vnet1", "app"), "10.215.2.5")

        def add_deny_5432():
            z.nsg("nsg-web", [dict(name="ssh", priority=100, direction="Inbound", access="Allow", protocol="Tcp",
                                   destinationPortRange="22", sourceAddressPrefix="VirtualNetwork"),
                              dict(name="deny-5432", priority=300, direction="Inbound", access="Deny", protocol="Tcp",
                                   destinationPortRange="5432")])

        def subnet_nsg():
            nsg = z.nsg("nsg-app-subnet", [dict(name="deny-8080", priority=100, direction="Inbound", access="Deny",
                                                protocol="Tcp", destinationPortRange="8080")])
            z.arm.state[az_sid("vnet1", "app").lower()] = {"id": az_sid("vnet1", "app"), "name": "app", "properties": {
                "addressPrefix": "10.215.2.0/24", "defaultOutboundAccess": False, "networkSecurityGroup": {"id": nsg}}}
        self.run_cloud("azure", "netsimaz", z.topo, {"web": web, "app": app, "app2": app2}, [
            ("NIC NSG allows 22 from VirtualNetwork", None, "app", "web", 22, True),
            ("default 65000 AllowVnetInBound", None, "app", "web", 5432, True),
            ("explicit deny priority 300", add_deny_5432, "app", "web", 5432, False),
            ("subnet NSG applies inside the subnet", subnet_nsg, "app2", "app", 8080, False),
            ("subnet NSG: other ports via defaults", None, "app2", "app", 22, True),
            ("default outbound access → internet", None, "web", "inet", 443, True),
            ("private subnet (defaultOutboundAccess=false)", None, "app", "inet", 443, False),
        ])


if __name__ == "__main__":
    if SKIP:
        print("SKIP:", SKIP)
    unittest.main(verbosity=2)
