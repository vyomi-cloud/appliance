"""Compute Engine guest data plane on Nano: OS info, guest attributes and serial output come from the running in-browser VM.

The page-side guest agent (wasm/vm/nano-vm-host.js) reads os-release / uname / /proc over the VM's ttyS0 and reports it with the
same `Annotate` path that already stamps the VM's ssh port on the instance record (`rec.update(ann)` in
wasm/providers/registry.py). This test applies that exact update to the instance record and checks the core serves it through
the real API verbs; the browser-side probe itself is exercised by the Playwright harness, not here. Screenshot stays unsupported.

    PYTHONPATH=. python3 tests/conformance/test_gcp_compute_nano_guest.py
"""
import json

try:
    from core import gcp_compute_instances_core as gce
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_compute_instances_core as gce  # type: ignore

P, Z = "guest-proj", "us-central1-a"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError((name, detail))
    print(f"  ok  {name}")


def run():
    st = gce.ComputeStore()

    def call(method, path, body=None, query=None):
        return gce.dispatch(st, method, f"/compute/v1/projects/{P}/zones/{Z}/{path}", query=query, body=json.dumps(body).encode() if body is not None else b"")

    body = lambda r: json.loads(r.body or b"{}")
    r = call("POST", "instances", {"name": "vm1", "machineType": f"zones/{Z}/machineTypes/e2-small",
                                   "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}]})
    _check("instance created", r.status == 200)
    inst = st.instances[f"projects/{P}/zones/{Z}/instances/vm1"]

    _check("before any guest report: OS info is the declared image (source=image)", body(call("GET", "instances/vm1:osInfo")).get("source") == "image")
    r = call("GET", "instances/vm1/getGuestAttributes")
    _check("no agent -> getGuestAttributes FAILED_PRECONDITION", r.status == 400 and body(r)["error"]["status"] == "FAILED_PRECONDITION")
    _check("screenshot still honestly unsupported", call("GET", "instances/vm1/screenshot").status == 400)

    # == the page-side agent's report, applied the way registry._vms_annotate does (rec.update(ann)) ==
    inst.update({"_guest": {"prettyName": "Alpine Linux v3.19", "id": "alpine", "version": "3.19.1", "hostname": "vm1", "kernel": "Linux 6.6.1-vyomi i686",
                            "architecture": "i686", "uptimeSeconds": 42.5, "memoryKb": 510000, "reportedAt": "2026-11-07T10:00:00Z"},
                 "_serial": "Welcome to Alpine Linux 3.19\nKernel 6.6.1 on an i686 (/dev/ttyS0)\nvm1 login: ", "_serialBase": 0})

    r = call("GET", "instances/vm1/getGuestAttributes")
    _check("guest attributes need enable-guest-attributes=TRUE (404 like GCE)", r.status == 404)
    call("POST", "instances/vm1:setMetadata", {"items": [{"key": "enable-guest-attributes", "value": "TRUE"}]})
    r = body(call("GET", "instances/vm1/getGuestAttributes", query={"queryPath": "vyomi/"}))
    got = {i["key"]: i["value"] for i in r["queryValue"]["items"]}
    _check("attributes come from the running guest", got["hostname"] == "vm1" and got["os-release"] == "Alpine Linux v3.19" and got["kernel"].startswith("Linux 6.6.1"), got)
    r = body(call("GET", "instances/vm1/getGuestAttributes", query={"variableKey": "vyomi/architecture"}))
    _check("variableKey lookup", r["variableValue"] == "i686")
    _check("unknown key 404", call("GET", "instances/vm1/getGuestAttributes", query={"variableKey": "vyomi/nope"}).status == 404)

    oi = body(call("GET", "instances/vm1:osInfo"))
    _check("OS info source=guest with kernel/arch/uptime from the VM", oi["source"] == "guest" and oi["prettyName"] == "Alpine Linux v3.19" and oi["kernel"].startswith("Linux 6.6.1")
           and oi["architecture"] == "i686" and oi["uptimeSeconds"] == 42.5, oi)

    sp = body(call("GET", "instances/vm1/serialPort"))
    _check("serial output is the VM's real console text", sp["contents"].startswith("Welcome to Alpine Linux") and sp["start"] == "0" and sp["next"] == str(len(inst["_serial"])), sp)
    inst["_serial"] += "root\n"
    sp2 = body(call("GET", "instances/vm1/serialPort", query={"start": sp["next"]}))
    _check("start cursor returns only new bytes", sp2["contents"] == "root\n" and sp2["next"] == str(len(inst["_serial"])), sp2)
    inst.update({"_serial": "tail\n", "_serialBase": 1000})
    sp3 = body(call("GET", "instances/vm1/serialPort", query={"start": "10"}))
    _check("a cursor older than the kept tail snaps to the tail start", sp3["start"] == "1000" and sp3["contents"] == "tail\n", sp3)

    call("POST", "instances/vm1:stop")
    _check("stopped instance: no guest data is served", call("GET", "instances/vm1/getGuestAttributes").status == 400
           and body(call("GET", "instances/vm1:osInfo"))["source"] == "image")
    print("\nRESULT: PASS -- Compute Engine guest data plane on Nano (OS info, guest attributes, serial)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
