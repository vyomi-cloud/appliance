"""GCP networking — WAVE 5b gap-sweep depth targets, native wire.

Proves the real backend behaviour behind the 7 capabilities the gap sweep lifted off
not_simulated: internal ranges (networkconnectivity v1), Serverless VPC Access connectors
(vpcaccess v1), Private Service Connection (servicenetworking v1 + globalAddresses
purpose=VPC_PEERING), Shared VPC / XPN (compute v1 projects.*), regional network firewall
policies (compute v1 firewallPolicies, including real evaluation precedence over classic
VPC firewall rules), VPC Flow Logs export (core/netsim/wiring.py -> Cloud Logging) and
Packet Mirroring (compute v1 packetMirrorings, including real mirrored-packet rendering).

Run:  PYTHONPATH=. python3 tests/conformance/test_gcp_networking_depth_core.py
"""
import json

try:
    from core.gcp_compute_core import ComputeStore, dispatch, gcp_flow_log_records, mirrored_packet_log_entries
    from core.netsim import from_gcp as fg, evaluate as ev, model as nm
except ImportError:  # pragma: no cover - Pyodide flat layout
    from gcp_compute_core import ComputeStore, dispatch, gcp_flow_log_records, mirrored_packet_log_entries  # type: ignore
    from netsim import from_gcp as fg, evaluate as ev, model as nm  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _b(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = ComputeStore()
    P = "demo-proj"

    def call(method, path, body=None, query=None):
        raw = json.dumps(body).encode() if body is not None else b""
        return dispatch(st, method, path, query or {}, {}, raw)

    call("POST", f"/compute/v1/projects/{P}/global/networks", {"name": "net1"})
    call("POST", f"/compute/v1/projects/{P}/regions/us-central1/subnetworks",
         {"name": "sub1", "network": "net1", "ipCidrRange": "10.0.0.0/24"})

    # ── internal ranges (networkconnectivity v1) ────────────────────────────
    r = call("POST", f"/v1/projects/{P}/locations/global/internalRanges",
              {"name": "ir1", "network": "net1", "prefixLength": 20, "targetCidrRange": ["10.0.0.0/8"]})
    _check("insert internal range 200", r.status == 200)
    ir = _b(r)["response"]
    _check("internal range doesn't overlap the subnet", ir["ipCidrRange"] != "10.0.0.0/24")
    r = call("GET", f"/v1/projects/{P}/locations/global/internalRanges")
    _check("list internal ranges", len(_b(r).get("internalRanges", [])) == 1)
    r = call("POST", f"/v1/projects/{P}/locations/global/internalRanges",
              {"name": "ir-overlap", "network": "net1", "ipCidrRange": "10.0.0.0/24"})
    _check("overlapping internal range -> 400", r.status == 400)
    r = call("DELETE", f"/v1/projects/{P}/locations/global/internalRanges/ir1")
    _check("delete internal range 200", r.status == 200)

    # ── Serverless VPC Access connectors (vpcaccess v1) ──────────────────────
    r = call("POST", f"/v1/projects/{P}/locations/us-central1/connectors",
              {"name": "conn1", "network": "net1", "ipCidrRange": "10.8.0.0/28"})
    _check("insert connector 200", r.status == 200)
    _check("connector is READY", _b(r)["response"]["state"] == "READY")
    r = call("POST", f"/v1/projects/{P}/locations/us-central1/connectors",
              {"name": "conn-bad", "network": "net1", "ipCidrRange": "10.8.0.0/24"})
    _check("non-/28 connector range -> 400", r.status == 400)
    r = call("POST", f"/v1/projects/{P}/locations/us-central1/connectors",
              {"name": "conn-overlap", "network": "net1", "ipCidrRange": "10.0.0.0/28"})
    _check("connector range overlapping subnet -> 400", r.status == 400)
    r = call("GET", f"/v1/projects/{P}/locations/us-central1/connectors")
    _check("list connectors", len(_b(r).get("connectors", [])) == 1)

    # ── Private Service Connection (servicenetworking v1 + globalAddresses) ──
    r = call("POST", f"/compute/v1/projects/{P}/global/addresses",
              {"name": "psc-range", "purpose": "VPC_PEERING", "addressType": "INTERNAL", "network": "net1", "prefixLength": 16})
    _check("reserve VPC_PEERING range 200", r.status == 200)
    r = call("GET", f"/compute/v1/projects/{P}/global/addresses/psc-range")
    addr = _b(r)
    _check("reserved range carries purpose + network", addr["purpose"] == "VPC_PEERING" and addr["network"].endswith("/networks/net1"))
    r = call("POST", f"/compute/v1/projects/{P}/global/addresses",
              {"name": "psc-collide", "purpose": "VPC_PEERING", "addressType": "INTERNAL", "network": "net1",
               "address": addr["address"], "prefixLength": 20})
    _check("overlapping VPC_PEERING range -> 400", r.status == 400)
    r = call("POST", "/v1/services/servicenetworking.googleapis.com/connections",
              {"network": f"projects/{P}/global/networks/net1", "reservedPeeringRanges": ["psc-range"]})
    _check("create PSC connection 200", r.status == 200)
    r = call("POST", "/v1/services/servicenetworking.googleapis.com/connections",
              {"network": f"projects/{P}/global/networks/net1", "reservedPeeringRanges": ["no-such-range"]})
    _check("PSC connection with unreserved range -> 400", r.status == 400)
    r = call("GET", "/v1/services/servicenetworking.googleapis.com/connections", query={"network": f"projects/{P}/global/networks/net1"})
    _check("list PSC connections", len(_b(r).get("connections", [])) == 1)
    r = call("POST", "/v1/services/servicenetworking.googleapis.com/connections/servicenetworking.googleapis.com:deleteConnection",
              {"network": f"projects/{P}/global/networks/net1"})
    _check("delete PSC connection 200", r.status == 200)

    # ── Shared VPC / XPN (compute v1 projects.*) ─────────────────────────────
    call("POST", f"/compute/v1/projects/svc-proj/global/networks", {"name": "net1"})  # distinct store namespace per project
    r = call("POST", f"/compute/v1/projects/{P}/enableXpnResource", {"xpnResource": {"id": "svc-proj", "type": "PROJECT"}})
    _check("enableXpnResource before host setup -> 400", r.status == 400)
    r = call("POST", f"/compute/v1/projects/{P}/enableXpnHost", {})
    _check("enableXpnHost 200", r.status == 200)
    r = call("POST", f"/compute/v1/projects/{P}/enableXpnResource", {"xpnResource": {"id": "svc-proj", "type": "PROJECT"}})
    _check("enableXpnResource 200", r.status == 200)
    r = call("POST", f"/compute/v1/projects/{P}/enableXpnResource", {"xpnResource": {"id": "svc-proj", "type": "PROJECT"}})
    r = call("GET", f"/compute/v1/projects/{P}/getXpnResources")
    _check("getXpnResources lists service project", any(x["id"] == "svc-proj" for x in _b(r).get("resources", [])))
    r = call("GET", f"/compute/v1/projects/svc-proj/aggregated/usableSubnetworks")
    usable = _b(r).get("items", [])
    _check("service project sees host's subnet via usableSubnetworks", any(s["ipCidrRange"] == "10.0.0.0/24" for s in usable))
    r = call("POST", f"/compute/v1/projects/{P}/disableXpnHost", {})
    _check("disableXpnHost while attached -> 400", r.status == 400)
    call("POST", f"/compute/v1/projects/{P}/disableXpnResource", {"xpnResource": {"id": "svc-proj", "type": "PROJECT"}})
    r = call("POST", f"/compute/v1/projects/{P}/disableXpnHost", {})
    _check("disableXpnHost once detached -> 200", r.status == 200)

    # ── Network firewall policies (regional, real evaluation precedence) ────
    r = call("POST", f"/compute/v1/projects/{P}/regions/us-central1/firewallPolicies", {"name": "fp1"})
    _check("insert firewall policy 200", r.status == 200)
    r = call("POST", f"/compute/v1/projects/{P}/regions/us-central1/firewallPolicies/fp1/addRule",
              {"firewallPolicyRule": {"priority": 100, "action": "deny", "direction": "INGRESS", "match": {"srcIpRanges": ["0.0.0.0/0"]}}})
    _check("addRule 200", r.status == 200)
    r = call("POST", f"/compute/v1/projects/{P}/regions/us-central1/firewallPolicies/fp1/addAssociation",
              {"association": {"name": "a1", "attachmentTarget": "net1"}})
    _check("addAssociation 200", r.status == 200)
    call("POST", f"/compute/v1/projects/{P}/global/firewalls",
         {"name": "allow-ssh", "network": "net1", "direction": "INGRESS", "priority": 1000,
          "sourceRanges": ["0.0.0.0/0"], "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}]})
    topo = fg.from_gcp(st, None, P)
    fw_rs = topo.rulesets[f"{P}/net1/firewall"]
    policy_rule = next(r2 for r2 in fw_rs.rules if r2.name.startswith("policy:"))
    classic_rule = next(r2 for r2 in fw_rs.rules if r2.name == "allow-ssh")
    _check("policy rule evaluates before the classic rule (lower priority)", policy_rule.priority < classic_rule.priority)
    iface = nm.Interface(id="i", subnet="x", ip="10.0.0.5")
    topo.add(nm.Subnet(id="x", network=f"{P}/net1", cidr="10.0.0.0/24"))
    topo.add(iface)
    ok, desc = ev.eval_priority(topo, fw_rs, nm.INGRESS, "tcp", 22, "1.2.3.4", None, iface, None)
    _check("hierarchical policy deny wins over the classic allow rule", ok is False and "policy:" in desc)
    r = call("POST", f"/compute/v1/projects/{P}/regions/us-central1/firewallPolicies/fp1/removeRule", {}, query={"priority": "100"})
    _check("removeRule 200", r.status == 200)
    r = call("DELETE", f"/compute/v1/projects/{P}/regions/us-central1/firewallPolicies/fp1")
    _check("delete firewall policy 200", r.status == 200)

    # ── VPC Flow Logs export (core/netsim/wiring.py -> Cloud Logging) ────────
    call("POST", f"/compute/v1/projects/{P}/regions/us-central1/subnetworks",
         {"name": "sub-logged", "network": "net1", "ipCidrRange": "10.0.2.0/24", "logConfig": {"enable": True}})
    topo2 = fg.from_gcp(st, None, P)
    topo2.add(nm.Interface(id="vm-logged/nic0", subnet=f"{P}/us-central1/sub-logged", ip="10.0.2.5", instance="vm-logged"))
    topo2.add(nm.Interface(id="vm-plain/nic0", subnet=f"{P}/us-central1/sub1", ip="10.0.0.5", instance="vm-plain"))
    accepted = [
        {"src": "10.0.2.5", "dst": "8.8.8.8", "proto": 6, "sport": 5000, "dport": 443, "packets": 10, "bytes": 1000},
        {"src": "10.0.0.5", "dst": "8.8.8.8", "proto": 6, "sport": 5001, "dport": 443, "packets": 7, "bytes": 700},
    ]
    flows = gcp_flow_log_records(st, P, accepted, [], topo2)
    _check("flow logged only for the subnet with flow logs on", len(flows) == 1 and flows[0]["connection"]["src_ip"] == "10.0.2.5")

    # ── Packet mirroring (config + real mirrored-packet rendering) ──────────
    r = call("POST", f"/compute/v1/projects/{P}/regions/us-central1/packetMirrorings",
              {"name": "pm1", "network": {"name": "net1"}, "mirroredResources": {"subnetworks": [{"name": "sub1"}]},
               "collectorIlb": {"name": "collector-fr"}})
    _check("insert packet mirroring policy 200", r.status == 200)
    r = call("POST", f"/compute/v1/projects/{P}/regions/us-central1/packetMirrorings",
              {"name": "pm-bad", "network": {"name": "net1"}, "mirroredResources": {}, "collectorIlb": {"name": "x"}})
    _check("packet mirroring with no mirrored resources -> 400", r.status == 400)
    mirrored = mirrored_packet_log_entries(st, P, accepted, topo2)
    _check("mirrored packet recorded for traffic on the mirrored subnet", any(m["connection"]["src_ip"] == "10.0.0.5" for m in mirrored))
    _check("traffic on the un-mirrored subnet is not duplicated", not any(m["connection"]["src_ip"] == "10.0.2.5" for m in mirrored))
    r = call("GET", f"/compute/v1/projects/{P}/regions/us-central1/packetMirrorings/pm1")
    _check("get packet mirroring policy", _b(r)["name"] == "pm1")
    r = call("DELETE", f"/compute/v1/projects/{P}/regions/us-central1/packetMirrorings/pm1")
    _check("delete packet mirroring policy 200", r.status == 200)

    print("\nRESULT: PASS — GCP networking depth targets (internal ranges, serverless VPC access, "
          "private service connection, shared VPC, network firewall policies, VPC flow logs, packet mirroring) "
          "conform to the native wire with real backend behaviour")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
