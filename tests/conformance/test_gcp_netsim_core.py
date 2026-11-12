"""GCP VPC semantics the netsim engine relies on + Connectivity Tests answered by core/netsim —
host + Pyodide.

  * every new VPC network gets its default route (0.0.0.0/0 → default-internet-gateway); deleting
    it removes internet egress; it goes away with the network
  * firewall targetServiceAccounts / sourceServiceAccounts are kept (and can't mix with tags)
  * Cloud Router + Cloud NAT (regions/{r}/routers) and network peering (addPeering/removePeering,
    ACTIVE only when both sides peer)
  * default nic subnetwork resolves in the zone's REGION
  * networkmanagement v1 connectivityTests: create (LRO) → reachabilityDetails REACHABLE/UNREACHABLE
    with steps (firewall/route/deliver/drop), rerun, list, delete

    PYTHONPATH=. python3 tests/conformance/test_gcp_netsim_core.py
"""
import json

try:
    from core import gcp_compute_core as net
    from core import gcp_compute_instances_core as vm
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_compute_core as net  # type: ignore
    import gcp_compute_instances_core as vm  # type: ignore

P = "netsim-proj"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run():
    ns, vs = net.ComputeStore(), vm.ComputeStore()

    def call(method, path, body=None, status=200, query=None, prefix="/compute/v1"):
        r = net.dispatch(ns, method, f"{prefix}/projects/{P}/{path}", query, None,
                         json.dumps(body).encode() if body is not None else b"", vm_store=vs)
        if r.status != status:
            raise AssertionError((method, path, r.status, r.body))
        return json.loads(r.body or b"{}")

    def vmcall(method, path, body):
        r = vm.dispatch(vs, method, f"/compute/v1/projects/{P}/{path}", body=json.dumps(body).encode())
        assert r.status < 300, r.body
        return json.loads(r.body)

    call("POST", "global/networks", {"name": "vpc1", "autoCreateSubnetworks": False})
    routes = call("GET", "global/routes").get("items", [])
    _check("new network has its default route to the internet gateway",
           any(r["destRange"] == "0.0.0.0/0" and r.get("nextHopGateway", "").endswith("default-internet-gateway") for r in routes))
    call("POST", "regions/us-central1/subnetworks", {"name": "web", "network": "vpc1", "ipCidrRange": "10.70.1.0/24"})
    call("POST", "regions/europe-west1/subnetworks", {"name": "db", "network": "vpc1", "ipCidrRange": "10.70.2.0/24"})

    fw = call("POST", "global/firewalls", {"name": "sa-db", "network": "vpc1", "sourceRanges": ["10.70.0.0/16"],
                                            "targetServiceAccounts": ["db@p.iam.gserviceaccount.com"],
                                            "allowed": [{"IPProtocol": "tcp", "ports": ["5432"]}]})
    _check("firewall insert returns an operation", fw.get("kind") == "compute#operation")
    _check("targetServiceAccounts kept on the firewall",
           call("GET", "global/firewalls/sa-db").get("targetServiceAccounts") == ["db@p.iam.gserviceaccount.com"])
    call("POST", "global/firewalls", {"name": "bad", "network": "vpc1", "targetTags": ["a"],
                                      "targetServiceAccounts": ["x@y"], "allowed": [{"IPProtocol": "all"}]}, status=400)
    _check("targetTags + targetServiceAccounts together rejected", True)

    def mk(name, zone, sub, ip, sa=None, external=False, tags=()):
        body = {"name": name, "machineType": f"zones/{zone}/machineTypes/e2-small",
                "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}],
                "networkInterfaces": [{"network": f"projects/{P}/global/networks/vpc1",
                                       "subnetwork": f"projects/{P}/regions/{sub[0]}/subnetworks/{sub[1]}", "networkIP": ip,
                                       "accessConfigs": [{"type": "ONE_TO_ONE_NAT"}] if external else []}],
                "tags": {"items": list(tags)}}
        if sa:
            body["serviceAccounts"] = [{"email": sa, "scopes": []}]
        vmcall("POST", f"zones/{zone}/instances", body)
        return f"projects/{P}/zones/{zone}/instances/{name}"

    web = mk("web", "us-central1-a", ("us-central1", "web"), "10.70.1.10", external=True)
    db = mk("db", "europe-west1-b", ("europe-west1", "db"), "10.70.2.10", sa="db@p.iam.gserviceaccount.com")
    batch = mk("batch", "us-central1-a", ("us-central1", "web"), "10.70.1.11")
    default_nic = vmcall("POST", "zones/us-central1-a/instances", {
        "name": "dflt", "machineType": "zones/us-central1-a/machineTypes/e2-small",
        "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}]})
    del default_nic
    nic = json.loads(vm.dispatch(vs, "GET", f"/compute/v1/projects/{P}/zones/us-central1-a/instances/dflt").body)["networkInterfaces"][0]
    _check("default nic subnetwork is in the zone's region", "/regions/us-central1/subnetworks/default" in nic["subnetwork"])

    # Connectivity Tests (networkmanagement v1) — the netsim evaluator
    def ct(tid, src, dst, port, proto="TCP"):
        op = call("POST", "locations/global/connectivityTests", {"source": src, "destination": {**dst, "port": port},
                                                                  "protocol": proto}, query={"testId": tid}, prefix="/v1")
        _check(f"{tid}: create returns a done LRO", op.get("done") is True and op["response"]["name"].endswith(tid))
        return op["response"]["reachabilityDetails"]

    d = ct("web-db", {"instance": web}, {"instance": db}, 5432)
    _check("SA-targeted allow → REACHABLE", d["result"] == "REACHABLE")
    states = [s["state"] for s in d["traces"][0]["steps"]]
    _check("trace: START_FROM_INSTANCE → firewall → route → DELIVER",
           states[0] == "START_FROM_INSTANCE" and "APPLY_INGRESS_FIREWALL_RULE" in states and states[-1] == "DELIVER")
    d = ct("web-db-22", {"instance": web}, {"instance": db}, 22)
    last = d["traces"][0]["steps"][-1]
    _check("implied deny ingress → UNREACHABLE, DROP cause FIREWALL_RULE",
           d["result"] == "UNREACHABLE" and last["state"] == "DROP" and last["drop"]["cause"] == "FIREWALL_RULE")
    d = ct("batch-inet", {"instance": batch}, {"ipAddress": "203.0.113.5"}, 443)
    _check("no external IP, no NAT → NO_EXTERNAL_ADDRESS", d["traces"][0]["steps"][-1]["drop"]["cause"] == "NO_EXTERNAL_ADDRESS")
    call("POST", "regions/us-central1/routers", {"name": "rtr", "network": "vpc1", "nats": [
        {"name": "nat", "sourceSubnetworkIpRangesToNat": "LIST_OF_SUBNETWORKS", "subnetworks": [{"name": "web"}]}]})
    _check("router listed with its NAT", call("GET", "regions/us-central1/routers")["items"][0]["nats"][0]["name"] == "nat")
    rerun = call("POST", "locations/global/connectivityTests/batch-inet:rerun", {}, prefix="/v1")
    _check("Cloud NAT on the subnet → rerun REACHABLE", rerun["response"]["reachabilityDetails"]["result"] == "REACHABLE")
    d = ct("web-inet", {"instance": web}, {"ipAddress": "203.0.113.5"}, 443)
    _check("external IP → internet REACHABLE", d["result"] == "REACHABLE")
    dr = next(r["name"] for r in call("GET", "global/routes")["items"] if r["destRange"] == "0.0.0.0/0")
    call("DELETE", f"global/routes/{dr}")
    rerun = call("POST", "locations/global/connectivityTests/web-inet:rerun", {}, prefix="/v1")
    _check("default route deleted → NO_ROUTE",
           rerun["response"]["reachabilityDetails"]["traces"][0]["steps"][-1]["drop"]["cause"] == "NO_ROUTE")
    _check("tests listed", len(call("GET", "locations/global/connectivityTests", prefix="/v1")["resources"]) == 4)
    call("DELETE", "locations/global/connectivityTests/web-inet", prefix="/v1")
    call("GET", "locations/global/connectivityTests/web-inet", status=404, prefix="/v1")
    _check("test deleted", True)

    # peering: ACTIVE only once both sides peer
    call("POST", "global/networks", {"name": "vpc2", "autoCreateSubnetworks": False})
    call("POST", "global/networks/vpc1/addPeering", {"networkPeering": {"name": "to2", "network": "vpc2", "exchangeSubnetRoutes": True}})
    _check("one-sided peering INACTIVE", call("GET", "global/networks/vpc1")["peerings"][0]["state"] == "INACTIVE")
    call("POST", "global/networks/vpc2/addPeering", {"networkPeering": {"name": "to1", "network": "vpc1", "exchangeSubnetRoutes": True}})
    _check("both sides → ACTIVE", call("GET", "global/networks/vpc1")["peerings"][0]["state"] == "ACTIVE")
    call("POST", "global/networks/vpc2/removePeering", {"name": "to1"})
    _check("peer removed → INACTIVE again", call("GET", "global/networks/vpc1")["peerings"][0]["state"] == "INACTIVE")
    call("DELETE", "regions/us-central1/routers/rtr")
    call("DELETE", "global/networks/vpc2")
    _check("network delete takes its system default route with it",
           not any(r["networkName"] == "vpc2" for r in ns.routes.values()))
    print("\nGCP netsim semantics + Connectivity Tests conformance: ALL GREEN")


if __name__ == "__main__":
    run()
    print("RESULT: PASS")
