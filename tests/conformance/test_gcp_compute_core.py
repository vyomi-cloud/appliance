"""GCP Compute Engine networking conformance — native REST API v1.

Proves core/gcp_compute_core.py speaks the same wire a real google-cloud-compute
SDK / gcloud compute client would: networks, subnetworks, firewalls, routes and
addresses (regional + global), round-tripped through dispatch() directly (no HTTP).

Run:  PYTHONPATH=. python3 tests/conformance/test_gcp_compute_core.py
"""
import json

try:
    from core.gcp_compute_core import ComputeStore, dispatch
except ImportError:  # pragma: no cover - Pyodide flat layout
    from gcp_compute_core import ComputeStore, dispatch  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _b(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = ComputeStore()
    project = "demo-proj"

    def call(method, path, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        return dispatch(st, method, f"/compute/v1/projects/{project}{path}", {}, {}, raw)

    # ── networks ──────────────────────────────────────────────────────────
    r = call("POST", "/global/networks", {"name": "default", "autoCreateSubnetworks": False})
    _check("insert network 200", r.status == 200)
    _check("insert network returns operation", _b(r)["kind"] == "compute#operation" and _b(r)["status"] == "DONE")

    r = call("GET", "/global/networks/default")
    _check("get network 200", r.status == 200)
    net = _b(r)
    _check("get network shape", net["name"] == "default" and net["mtu"] == 1460 and net["autoCreateSubnetworks"] is False)

    r = call("GET", "/global/networks")
    _check("list networks includes default", any(n["name"] == "default" for n in _b(r)["items"]))

    r = call("POST", "/global/networks", {"name": "default"})
    _check("duplicate network -> 409 ALREADY_EXISTS", r.status == 409 and _b(r)["error"]["status"] == "ALREADY_EXISTS")

    r = call("POST", "/global/networks", {"name": "Bad_Name!"})
    _check("invalid network name -> 400", r.status == 400)

    # ── subnetworks ──────────────────────────────────────────────────────────
    r = call("POST", "/regions/us-central1/subnetworks",
              {"name": "sub1", "network": "default", "ipCidrRange": "10.0.0.0/24", "privateIpGoogleAccess": True})
    _check("insert subnet 200", r.status == 200)

    r = call("GET", "/regions/us-central1/subnetworks/sub1")
    sub = _b(r)
    _check("subnet gateway derived from CIDR", sub["gatewayAddress"] == "10.0.0.1")
    _check("subnet privateIpGoogleAccess stored", sub["privateIpGoogleAccess"] is True)

    r = call("GET", "/regions/us-central1/subnetworks")
    _check("list subnets includes sub1", any(s["name"] == "sub1" for s in _b(r)["items"]))

    r = call("GET", "/aggregated/subnetworks")
    _check("aggregated subnetworks has region scope", "regions/us-central1" in _b(r)["items"])

    r = call("POST", "/regions/us-central1/subnetworks", {"name": "sub-bad", "network": "nope", "ipCidrRange": "10.1.0.0/24"})
    _check("subnet on unknown network -> 400", r.status == 400)

    # ── firewalls ──────────────────────────────────────────────────────────
    r = call("POST", "/global/firewalls",
              {"name": "allow-ssh", "network": "default", "direction": "INGRESS", "priority": 1000,
               "sourceRanges": ["0.0.0.0/0"], "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}]})
    _check("insert firewall 200", r.status == 200)

    r = call("GET", "/global/firewalls/allow-ssh")
    fw = _b(r)
    _check("firewall allowed stored", fw["allowed"] == [{"IPProtocol": "tcp", "ports": ["22"]}])
    _check("firewall network link", fw["network"].endswith("/networks/default"))

    r = call("GET", "/global/firewalls")
    _check("list firewalls includes allow-ssh", any(f["name"] == "allow-ssh" for f in _b(r)["items"]))

    r = call("POST", "/global/firewalls", {"name": "no-action", "network": "default"})
    _check("firewall without allowed/denied -> 400", r.status == 400)

    # ── routes ──────────────────────────────────────────────────────────────
    r = call("POST", "/global/routes",
              {"name": "default-route", "network": "default", "destRange": "0.0.0.0/0", "nextHopGateway": "default-internet-gateway"})
    _check("insert route 200", r.status == 200)

    r = call("GET", "/global/routes/default-route")
    rt = _b(r)
    _check("route nextHopGateway present", "nextHopGateway" in rt)
    _check("route destRange stored", rt["destRange"] == "0.0.0.0/0")

    r = call("GET", "/global/routes")
    _check("list routes includes default-route", any(x["name"] == "default-route" for x in _b(r)["items"]))

    # ── addresses ──────────────────────────────────────────────────────────
    r = call("POST", "/regions/us-central1/addresses", {"name": "internal-1", "addressType": "INTERNAL"})
    _check("insert regional address 200", r.status == 200)
    r = call("GET", "/regions/us-central1/addresses/internal-1")
    _check("internal address IP in private range", _b(r)["address"].startswith("10.200."))

    r = call("POST", "/global/addresses", {"name": "global-1", "addressType": "EXTERNAL"})
    _check("insert global address 200", r.status == 200)
    r = call("GET", "/global/addresses/global-1")
    _check("global address scope", _b(r)["addressType"] == "EXTERNAL" and "region" not in _b(r))

    r = call("GET", "/aggregated/addresses")
    items = _b(r)["items"]
    _check("aggregated addresses has region + global scope", "regions/us-central1" in items and "global" in items)

    # ── deletes + referential integrity ─────────────────────────────────────
    r = call("DELETE", "/global/networks/default")
    _check("delete network in use -> 400", r.status == 400 and r.status != 200)

    call("DELETE", "/regions/us-central1/subnetworks/sub1")
    call("DELETE", "/global/firewalls/allow-ssh")
    call("DELETE", "/global/routes/default-route")
    r = call("DELETE", "/global/networks/default")
    _check("delete network once unused -> 200", r.status == 200)

    r = call("GET", "/global/networks/default")
    _check("deleted network -> 404", r.status == 404 and _b(r)["error"]["status"] == "NOT_FOUND")

    print("\nRESULT: PASS — GCP Compute Engine networking core conforms to the native REST API v1 wire")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
