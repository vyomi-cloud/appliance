"""GCP VPC Flow Logs from the LOGICAL evaluator (the Nano path; also works offline) -- host + Pyodide.

Nano has no packets, so flow records come from flows you submit to the shared netsim evaluator:
(Vyomi) POST /compute/v1/projects/{p}/global/vyomiFlows:send  -> firewalls/routes/NAT are evaluated, a delivered flow
is written to Cloud Logging as compute.googleapis.com%2Fvpc_flows for every reporter whose subnet has logConfig.enable,
honouring aggregationInterval, flowSampling, metadata and filterExpr. Denied flows write nothing.

    PYTHONPATH=. python3 tests/conformance/test_gcp_vpc_flow_logs_evaluated.py
"""
import json

try:
    from core import gcp_compute_core as net
    from core import gcp_compute_instances_core as vm
    from core import gcp_logging_core as lg
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_compute_core as net  # type: ignore
    import gcp_compute_instances_core as vm  # type: ignore
    import gcp_logging_core as lg  # type: ignore

P = "flow-proj"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run():
    ns, vs, ls = net.ComputeStore(), vm.ComputeStore(), lg.LoggingStore()
    ns.logging_store = ls

    def call(method, path, body=None, status=200):
        r = net.dispatch(ns, method, f"/compute/v1/projects/{P}/{path}", {}, None,
                         json.dumps(body).encode() if body is not None else b"", vm_store=vs)
        if r.status != status:
            raise AssertionError((method, path, r.status, r.body))
        return json.loads(r.body or b"{}")

    def mk(name, sub, ip):
        body = {"name": name, "machineType": "zones/us-central1-a/machineTypes/e2-small",
                "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
                "networkInterfaces": [{"network": f"projects/{P}/global/networks/vpc1",
                                       "subnetwork": f"projects/{P}/regions/us-central1/subnetworks/{sub}", "networkIP": ip}],
                "tags": {"items": ["app"]}}
        r = vm.dispatch(vs, "POST", f"/compute/v1/projects/{P}/zones/us-central1-a/instances", body=json.dumps(body).encode())
        assert r.status < 300, r.body

    call("POST", "global/networks", {"name": "vpc1", "autoCreateSubnetworks": False})
    call("POST", "regions/us-central1/subnetworks", {"name": "logged", "network": "vpc1", "ipCidrRange": "10.80.1.0/24",
                                                     "logConfig": {"enable": True, "aggregationInterval": "INTERVAL_1_MIN", "flowSampling": 0.5}})
    call("POST", "regions/us-central1/subnetworks", {"name": "plain", "network": "vpc1", "ipCidrRange": "10.80.2.0/24"})
    call("POST", "global/firewalls", {"name": "allow-8080", "network": "vpc1", "sourceRanges": ["10.80.0.0/16"],
                                      "allowed": [{"IPProtocol": "tcp", "ports": ["8080"]}]})
    mk("a", "logged", "10.80.1.10")
    mk("b", "logged", "10.80.1.11")
    mk("c", "plain", "10.80.2.10")

    sub = call("GET", "regions/us-central1/subnetworks/logged")
    _check("logConfig round-trips with interval/sampling/metadata",
           sub["logConfig"]["enable"] and sub["logConfig"]["aggregationInterval"] == "INTERVAL_1_MIN" and sub["logConfig"]["flowSampling"] == 0.5)
    _check("a subnet created without logConfig reports enable=false", call("GET", "regions/us-central1/subnetworks/plain")["logConfig"]["enable"] is False)
    call("POST", "regions/us-central1/subnetworks", {"name": "bad", "network": "vpc1", "ipCidrRange": "10.80.3.0/24",
                                                     "logConfig": {"enable": True, "flowSampling": 2}}, status=400)
    _check("flowSampling outside 0..1 is rejected", True)

    def inst(n):
        return {"instance": f"projects/{P}/zones/us-central1-a/instances/{n}"}

    def send(src, dst, port, **kw):
        return call("POST", "global/vyomiFlows:send", {"source": inst(src), "destination": {**inst(dst), "port": port}, "protocol": "TCP", **kw})

    r = send("a", "b", 8080, packets=100, bytes=60000)
    _check("allowed flow is ACCEPT", r["result"] == "ACCEPT")
    _check("both reporters (SRC and DEST) logged, both in the logged subnet", sorted(x["reporter"] for x in r["records"]) == ["DEST", "SRC"] and r["logged"] == 2)
    rec = r["records"][0]
    _check("sampling 0.5 halves packets and bytes", rec["packets_sent"] == "50" and rec["bytes_sent"] == "30000")
    _check("record carries the 5-tuple + VM/VPC metadata",
           rec["connection"] == {"src_ip": "10.80.1.10", "dest_ip": "10.80.1.11", "src_port": 49152, "dest_port": 8080, "protocol": 6}
           and rec["src_instance"]["vm_name"] == "a" and rec["dest_vpc"]["subnetwork_name"] == "logged")
    _check("1-minute aggregation window", rec["end_time"] > rec["start_time"] and rec["start_time"].endswith(":00Z") and rec["end_time"].endswith(":00Z"))
    ents = json.loads(lg.list_entries(ls, {"resourceNames": [f"projects/{P}"],
                                           "filter": 'logName="projects/%s/logs/compute.googleapis.com%%2Fvpc_flows"' % P}).body)
    _check("entries are in Cloud Logging under vpc_flows", len(ents.get("entries", [])) == 2)

    r = send("c", "a", 8080)
    _check("flow from a non-logged subnet to a logged one: only DEST reports", r["result"] == "ACCEPT" and [x["reporter"] for x in r["records"]] == ["DEST"])
    r = send("a", "b", 9999)
    _check("flow denied by the implied ingress rule is DROP and writes nothing", r["result"] == "DROP" and r["logged"] == 0 and r["records"] == [])
    r = send("a", "b", 8080, packets=1)
    _check("a flow that does not survive sampling logs nothing", r["result"] == "ACCEPT" and r["logged"] == 0)

    call("PATCH", "regions/us-central1/subnetworks/logged", {"logConfig": {"enable": True, "metadata": "EXCLUDE_ALL_METADATA", "flowSampling": 1.0,
                                                                          "filterExpr": "inIpRange(connection.src_ip, '10.80.1.0/24')"}})
    r = send("a", "b", 8080, packets=10, bytes=1000)
    _check("EXCLUDE_ALL_METADATA drops instance/vpc fields, sampling 1.0 keeps all packets",
           r["logged"] == 2 and "src_instance" not in r["records"][0] and r["records"][0]["packets_sent"] == "10")
    call("PATCH", "regions/us-central1/subnetworks/logged", {"logConfig": {"enable": True, "flowSampling": 1.0,
                                                                          "filterExpr": "inIpRange(connection.src_ip, '192.168.0.0/16')"}})
    r = send("a", "b", 8080)
    _check("filterExpr that does not match suppresses the record", r["result"] == "ACCEPT" and r["logged"] == 0)
    call("PATCH", "regions/us-central1/subnetworks/logged", {"logConfig": {"enable": True, "filterExpr": "connection.src_port > 10"}}, status=400)
    _check("unsupported CEL in filterExpr is rejected, not silently ignored", True)
    call("PATCH", "regions/us-central1/subnetworks/logged", {"logConfig": {"enable": False}})
    r = send("a", "b", 8080)
    _check("flow logs disabled -> no records", r["logged"] == 0)

    print("\nRESULT: PASS -- VPC flow logs from the logical evaluator")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
