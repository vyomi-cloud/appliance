"""GCP Compute Engine control-plane conformance — the GCP analogue of test_rds_core.py /
test_gcp_cloudsql_core.py, but for `compute.googleapis.com/v1`.

Same test runs on host CPython and under Pyodide/WASM and must be green on both. Asserts
the native **Compute Engine REST API v1** wire semantics under
`/compute/v1/projects/{project}/...`: instance create (RUNNING, boot disk auto-created and
attached) / start / stop / suspend / resume / reset / delete, disk create / createSnapshot /
delete (in-use protection), image / machineImage / instanceTemplate / instanceGroup /
healthCheck CRUD, zone/region/machineType/operations catalogs, project metadata, and the
Google JSON error shape `{"error":{...,"status":"NOT_FOUND"}}` — proving google-cloud-compute
/ gcloud compute can drive the control plane unchanged.

The data plane (a real guest OS to SSH into) is out of scope for this core — no tier models
it, exactly like the Kubernetes API server behind a GKE cluster endpoint.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_compute_instances_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core import gcp_compute_instances_core as gce
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_compute_instances_core as gce  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


PROJECT = "demo-proj"
ZONE = "us-central1-a"
BASE = "/compute/v1/projects/%s" % PROJECT


def _call(store, method, path, body=None):
    b = json.dumps(body).encode() if body is not None else b""
    return gce.dispatch(store, method, BASE + path, {}, {"content-type": "application/json"}, b)


def run() -> int:
    st = gce.ComputeStore()

    # 1. zones / regions / machine types catalogs
    zl = _call(st, "GET", "/zones")
    _check("zones 200", zl.status == 200)
    _check("zones kind", _jbody(zl)["kind"] == "compute#zoneList")
    _check("zones has us-central1-a", any(z["name"] == ZONE for z in _jbody(zl)["items"]))
    rl = _call(st, "GET", "/regions")
    _check("regions has us-central1", any(r["name"] == "us-central1" for r in _jbody(rl)["items"]))
    mt = _call(st, "GET", "/zones/%s/machineTypes/e2-medium" % ZONE)
    _check("machine type 200", mt.status == 200 and _jbody(mt)["guestCpus"] == 2)

    # 2. insert instance -> 200, RUNNING, boot disk auto-created + attached, external IP assigned
    r = _call(st, "POST", "/zones/%s/instances" % ZONE, {
        "name": "web-1", "machineType": "e2-medium",
        "disks": [{"boot": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12", "diskSizeGb": 10}}],
        "labels": {"env": "prod"},
    })
    _check("insert instance 200", r.status == 200)
    op = _jbody(r)
    _check("insert instance op DONE", op["status"] == "DONE" and op["operationType"] == "insert")

    g = _call(st, "GET", "/zones/%s/instances/web-1" % ZONE)
    inst = _jbody(g)
    _check("get instance 200", g.status == 200)
    _check("instance RUNNING", inst["status"] == "RUNNING")
    _check("instance machineType echoed", inst["machineType"].endswith("/machineTypes/e2-medium"))
    _check("instance has external IP", bool(inst["networkInterfaces"][0]["accessConfigs"][0]["natIP"]))
    _check("instance labels echoed", inst["labels"]["env"] == "prod")

    bootname = inst["disks"][0]["source"].rsplit("/", 1)[-1]
    bd = _call(st, "GET", "/zones/%s/disks/%s" % (ZONE, bootname))
    _check("boot disk auto-created", bd.status == 200)
    _check("boot disk in use by instance", "web-1" in _jbody(bd)["users"][0])

    # 2b. duplicate instance -> 409
    dup = _call(st, "POST", "/zones/%s/instances" % ZONE, {"name": "web-1", "machineType": "e2-medium",
                                                            "disks": [{"boot": True, "initializeParams": {}}]})
    _check("duplicate instance 409", dup.status == 409 and _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 2c. invalid machine type -> 400
    bad = _call(st, "POST", "/zones/%s/instances" % ZONE, {"name": "web-2", "machineType": "not-a-real-type",
                                                            "disks": [{"boot": True, "initializeParams": {}}]})
    _check("invalid machine type 400", bad.status == 400 and _jbody(bad)["error"]["status"] == "INVALID_ARGUMENT")

    # 3. lifecycle: stop -> TERMINATED, start -> RUNNING, suspend -> SUSPENDED, resume -> RUNNING, reset
    stop = _call(st, "POST", "/zones/%s/instances/web-1:stop" % ZONE)
    _check("stop 200", stop.status == 200)
    _check("stopped state", _jbody(_call(st, "GET", "/zones/%s/instances/web-1" % ZONE))["status"] == "TERMINATED")
    bad_start_twice = _call(st, "POST", "/zones/%s/instances/web-1:stop" % ZONE)
    _check("stop while stopped -> 400", bad_start_twice.status == 400)
    start = _call(st, "POST", "/zones/%s/instances/web-1:start" % ZONE)
    _check("start 200", start.status == 200)
    _check("started state", _jbody(_call(st, "GET", "/zones/%s/instances/web-1" % ZONE))["status"] == "RUNNING")
    susp = _call(st, "POST", "/zones/%s/instances/web-1:suspend" % ZONE)
    _check("suspend 200", susp.status == 200)
    _check("suspended state", _jbody(_call(st, "GET", "/zones/%s/instances/web-1" % ZONE))["status"] == "SUSPENDED")
    resume = _call(st, "POST", "/zones/%s/instances/web-1:resume" % ZONE)
    _check("resume 200", resume.status == 200)
    reset = _call(st, "POST", "/zones/%s/instances/web-1:reset" % ZONE)
    _check("reset 200", reset.status == 200)

    # 4. setLabels round-trips
    sl = _call(st, "POST", "/zones/%s/instances/web-1:setLabels" % ZONE, {"labels": {"env": "staging"}})
    _check("setLabels 200", sl.status == 200)
    _check("label updated", _jbody(_call(st, "GET", "/zones/%s/instances/web-1" % ZONE))["labels"]["env"] == "staging")

    # 5. standalone disk + createSnapshot + in-use delete protection
    dr = _call(st, "POST", "/zones/%s/disks" % ZONE, {"name": "data-1", "sizeGb": 50, "type": "pd-ssd"})
    _check("insert disk 200", dr.status == 200)
    ld = _call(st, "GET", "/zones/%s/disks" % ZONE)
    _check("list disks has both", sorted(d["name"] for d in _jbody(ld)["items"]) == sorted([bootname, "data-1"]))

    snap = _call(st, "POST", "/zones/%s/disks/data-1:createSnapshot" % ZONE, {"name": "snap-1"})
    _check("createSnapshot 200", snap.status == 200)
    ls = _call(st, "GET", "/global/snapshots")
    _check("snapshot listed", any(s["name"] == "snap-1" for s in _jbody(ls)["items"]))
    _check("snapshot sourceDisk", _jbody(ls)["items"][0]["sourceDisk"].endswith("/disks/data-1"))

    inuse_del = _call(st, "DELETE", "/zones/%s/instances/web-1" % ZONE)  # boot disk still has autoDelete, instance not protected
    _check("delete instance 200", inuse_del.status == 200)
    _check("boot disk auto-deleted with instance", _call(st, "GET", "/zones/%s/disks/%s" % (ZONE, bootname)).status == 404)
    _check("standalone disk survives", _call(st, "GET", "/zones/%s/disks/data-1" % ZONE).status == 200)

    deld = _call(st, "DELETE", "/zones/%s/disks/data-1" % ZONE)
    _check("delete disk 200", deld.status == 200)
    missing = _call(st, "GET", "/zones/%s/disks/data-1" % ZONE)
    _check("deleted disk 404", missing.status == 404 and _jbody(missing)["error"]["status"] == "NOT_FOUND")

    # 6. deletionProtection blocks delete
    _call(st, "POST", "/zones/%s/instances" % ZONE, {
        "name": "web-3", "machineType": "e2-medium", "deletionProtection": True,
        "disks": [{"boot": True, "initializeParams": {"sourceImage": "debian-12"}}],
    })
    protected_del = _call(st, "DELETE", "/zones/%s/instances/web-3" % ZONE)
    _check("deletionProtection blocks delete", protected_del.status == 400
           and _jbody(protected_del)["error"]["status"] == "FAILED_PRECONDITION")

    # 7. image from disk, machine image from instance
    _call(st, "POST", "/zones/%s/disks" % ZONE, {"name": "src-disk", "sizeGb": 10})
    img = _call(st, "POST", "/global/images", {"name": "custom-img", "sourceDisk": "src-disk", "family": "custom"})
    _check("insert image 200", img.status == 200)
    _check("image listed", any(i["name"] == "custom-img" for i in _jbody(_call(st, "GET", "/global/images"))["items"]))

    mi = _call(st, "POST", "/global/machineImages", {"name": "mi-1", "sourceInstance": "web-3"})
    _check("insert machine image 200", mi.status == 200)
    _check("machine image listed", any(m["name"] == "mi-1" for m in _jbody(_call(st, "GET", "/global/machineImages"))["items"]))
    mi_bad = _call(st, "POST", "/global/machineImages", {"name": "mi-ghost", "sourceInstance": "ghost"})
    _check("machine image from missing instance 400", mi_bad.status == 400)

    # 8. instance template
    tpl = _call(st, "POST", "/global/instanceTemplates", {"name": "tpl-1", "properties": {"machineType": "n2-standard-2"}})
    _check("insert template 200", tpl.status == 200)
    _check("template listed", _jbody(_call(st, "GET", "/global/instanceTemplates"))["items"][0]["properties"]["machineType"] == "n2-standard-2")
    delt = _call(st, "DELETE", "/global/instanceTemplates/tpl-1")
    _check("delete template 200", delt.status == 200)

    # 9. instance group: insert, addInstances, listInstances, removeInstances
    grp = _call(st, "POST", "/zones/%s/instanceGroups" % ZONE, {"name": "grp-1"})
    _check("insert group 200", grp.status == 200)
    add = _call(st, "POST", "/zones/%s/instanceGroups/grp-1:addInstances" % ZONE, {"instances": [{"instance": "web-3"}]})
    _check("addInstances 200", add.status == 200)
    glist = _jbody(_call(st, "GET", "/zones/%s/instanceGroups" % ZONE))["items"]
    _check("group size updated", glist[0]["size"] == 1)
    rem = _call(st, "POST", "/zones/%s/instanceGroups/grp-1:removeInstances" % ZONE, {"instances": [{"instance": "web-3"}]})
    _check("removeInstances 200", rem.status == 200)
    glist2 = _jbody(_call(st, "GET", "/zones/%s/instanceGroups" % ZONE))["items"]
    _check("group size back to 0", glist2[0]["size"] == 0)

    # 10. health check
    hc = _call(st, "POST", "/global/healthChecks", {"name": "hc-1", "type": "HTTP", "httpHealthCheck": {"port": 8080, "requestPath": "/healthz"}})
    _check("insert health check 200", hc.status == 200)
    hcl = _jbody(_call(st, "GET", "/global/healthChecks"))["items"]
    _check("health check port echoed", hcl[0]["httpHealthCheck"]["port"] == 8080)
    bad_hc = _call(st, "POST", "/global/healthChecks", {"name": "hc-2", "type": "NOPE"})
    _check("invalid health check type 400", bad_hc.status == 400)

    # 11. operations: zone-scoped, global-scoped, and aggregated across both
    zone_ops = _jbody(_call(st, "GET", "/zones/%s/operations" % ZONE))["items"]
    _check("zone operations non-empty and zone-scoped", len(zone_ops) > 0 and all("zone" in o for o in zone_ops))
    global_ops = _jbody(_call(st, "GET", "/global/operations"))["items"]
    _check("global operations only carry global mutations", len(global_ops) > 0 and all("zone" not in o for o in global_ops))
    agg_ops = _jbody(_call(st, "GET", "/aggregated/operations"))["items"]["global"]["operations"]
    _check("aggregated operations is the union", len(agg_ops) == len(zone_ops) + len(global_ops))

    # 12. project metadata (setCommonInstanceMetadata round-trip)
    before = _jbody(_call(st, "GET", ""))
    _check("project metadata starts empty", before["commonInstanceMetadata"]["items"] == [])
    setm = _call(st, "POST", "/setCommonInstanceMetadata", {"items": [{"key": "ssh-keys", "value": "alice:ssh-rsa AAAA"}]})
    _check("setCommonInstanceMetadata 200", setm.status == 200)
    after = _jbody(_call(st, "GET", ""))
    _check("project metadata round-trips", after["commonInstanceMetadata"]["items"][0]["value"] == "alice:ssh-rsa AAAA")

    # 13. aggregatedList across zones for instances/disks
    agg = _jbody(_call(st, "GET", "/aggregated/instances"))
    _check("aggregated instances kind", agg["kind"] == "compute#instanceAggregatedList")
    _check("aggregated instances has web-3", any("web-3" in i["name"] for z in agg["items"].values() for i in z.get("instances", [])))

    print("\nRESULT: PASS — GCP Compute Engine control-plane core conforms "
          "(native Compute Engine REST v1 wire) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
