"""GCP Compute Engine extension core: recommender, instance + snapshot schedules, instant
snapshots, async replication, multi-NIC, NEGs, reservations, sole-tenant nodes, storage pools.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_compute_ext_core.py"""
import json
from datetime import timedelta

try:
    from core import gcp_compute_instances_core as gce
    from core import gcp_compute_ext_core as ext
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_compute_instances_core as gce  # type: ignore
    import gcp_compute_ext_core as ext  # type: ignore

P, Z, R = "demo", "us-central1-a", "us-central1"
B = "/compute/v1/projects/%s" % P
S = gce.ComputeStore()


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    print("  ok ", name)


def call(method, path, body=None, status=200):
    path, _, qs = path.partition("?")
    q = dict(kv.split("=", 1) for kv in qs.split("&")) if qs else {}
    r = gce.dispatch(S, method, path, q, {}, json.dumps(body).encode() if body is not None else b"")
    j = json.loads(r.body.decode() or "{}")
    assert r.status == status, "%s %s -> %s %s" % (method, path, r.status, j)
    return j


def inst(name, **kw):
    return call("POST", B + "/zones/%s/instances" % Z, dict({"name": name, "machineType": "e2-medium",
                "disks": [{"boot": True, "initializeParams": {"diskSizeGb": "10"}}]}, **kw))


# ── resource policies: validation + instance schedule engine ───────────────
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "bad"}, 400)
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "bad", "instanceSchedulePolicy": {"vmStartSchedule": {"schedule": "nope"}}}, 400)
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "weekdays", "instanceSchedulePolicy": {
    "vmStartSchedule": {"schedule": "0 8 * * *"}, "vmStopSchedule": {"schedule": "0 18 * * *"}, "timeZone": "UTC"}})
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "weekdays"}, 409)
inst("vm1")
call("POST", B + "/zones/%s/instances/vm1/addResourcePolicies" % Z, {"resourcePolicies": ["projects/%s/regions/%s/resourcePolicies/weekdays" % (P, R)]})
ok("policy attached", "weekdays" in json.dumps(call("GET", B + "/zones/%s/instances/vm1" % Z)["resourcePolicies"]))
call("DELETE", B + "/regions/%s/resourcePolicies/weekdays" % R, status=400)  # in use
now = ext._now()
day = now.replace(hour=12, minute=0, second=0, microsecond=0)
S.ext["sched"] = {"lastTick": ext._iso(day.replace(hour=7, minute=0))}
ext.tick(S, day.replace(hour=9, minute=0))
ok("start fire @08:00 keeps it RUNNING", S.instances["projects/%s/zones/%s/instances/vm1" % (P, Z)]["status"] == "RUNNING")
ext.tick(S, day.replace(hour=19, minute=0))
ok("stop fire @18:00 stops the VM", S.instances["projects/%s/zones/%s/instances/vm1" % (P, Z)]["status"] == "TERMINATED")
ext.tick(S, day.replace(hour=19, minute=0) + timedelta(hours=13))
ok("next start fire restarts it", S.instances["projects/%s/zones/%s/instances/vm1" % (P, Z)]["status"] == "RUNNING")

# ── snapshot schedules + retention ─────────────────────────────────────────
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "hourly", "snapshotSchedulePolicy": {
    "schedule": {"hourlySchedule": {"hoursInCycle": 5, "startTime": "00:00"}}}}, 400)
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "hourly", "snapshotSchedulePolicy": {
    "schedule": {"hourlySchedule": {"hoursInCycle": 4, "startTime": "00:00"}},
    "retentionPolicy": {"maxRetentionDays": 1}, "snapshotProperties": {"labels": {"auto": "yes"}}}})
call("POST", B + "/zones/%s/disks" % Z, {"name": "data1", "sizeGb": "20", "resourcePolicies": ["projects/%s/regions/%s/resourcePolicies/hourly" % (P, R)]})
call("POST", B + "/zones/%s/disks/data1/addResourcePolicies" % Z, {"resourcePolicies": ["projects/%s/regions/%s/resourcePolicies/weekdays" % (P, R)]}, 400)  # wrong type
pol = S.ext["resourcePolicies"]["projects/%s/regions/%s/resourcePolicies/hourly" % (P, R)]
pol["creationTimestamp"] = ext._iso(now - timedelta(days=3))
S.ext["sched"]["lastTick"] = ext._iso(now - timedelta(hours=9))
ext.tick(S, now)
snaps = [s for s in S.snapshots.values() if s.get("autoCreated")]
ok("hourly(4h) schedule produced snapshots for the 9h window", 2 <= len(snaps) <= 3)
ok("snapshots carry labels + policy link", all(s["labels"] == {"auto": "yes"} and "hourly" in s["sourceSnapshotSchedulePolicy"] for s in snaps))
old = next(iter(S.snapshots.values()))
old["creationTimestamp"] = ext._iso(now - timedelta(days=3))
ext.tick(S, now + timedelta(minutes=1))
ok("retention (1 day) pruned the expired snapshot", old["name"] not in {s["name"] for s in S.snapshots.values()})
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "daily", "snapshotSchedulePolicy": {"schedule": {"dailySchedule": {"daysInCycle": 1, "startTime": "04:00"}}}})
call("POST", B + "/zones/%s/disks/data1/addResourcePolicies" % Z, {"resourcePolicies": ["projects/%s/regions/%s/resourcePolicies/daily" % (P, R)]}, 400)  # one schedule only
ok("weekly fires land on the named weekday", all(t.strftime("%A").upper() == "MONDAY" for t in ext.snapshot_fires(
    {"weeklySchedule": {"dayOfWeekSchedules": [{"day": "MONDAY", "startTime": "02:00"}]}}, now - timedelta(days=60), now - timedelta(days=30), now)))

# ── instant snapshots ──────────────────────────────────────────────────────
call("POST", B + "/zones/%s/instantSnapshots" % Z, {"name": "is1", "sourceDisk": "zones/%s/disks/nope" % Z}, 404)
call("POST", B + "/zones/%s/instantSnapshots" % Z, {"name": "is1", "sourceDisk": "zones/%s/disks/data1" % Z})
call("POST", B + "/zones/%s/disks" % Z, {"name": "restored", "sourceInstantSnapshot": "zones/%s/instantSnapshots/is1" % Z})
ok("disk restored from instant snapshot takes its size", call("GET", B + "/zones/%s/disks/restored" % Z)["sizeGb"] == "20")
ok("aggregatedList instantSnapshots", "zones/%s" % Z in call("GET", B + "/aggregated/instantSnapshots")["items"])

# ── async replication + consistency group ──────────────────────────────────
call("POST", B + "/zones/us-east1-b/disks", {"name": "data1-dr", "sizeGb": "20"})
call("POST", B + "/zones/%s/disks/data1/startAsyncReplication" % Z, {"asyncSecondaryDisk": "projects/%s/zones/%s/disks/restored" % (P, Z)}, 400)  # same region
call("POST", B + "/zones/%s/disks/data1/startAsyncReplication" % Z, {"asyncSecondaryDisk": "projects/%s/zones/us-east1-b/disks/data1-dr" % P})
ok("replication pair listed", ext.replication_pairs(S, P)[0]["secondary"] == "data1-dr")
call("DELETE", B + "/zones/%s/disks/data1" % Z, status=400)
call("POST", B + "/zones/%s/disks/data1/stopAsyncReplication" % Z, {})
ok("stop clears both sides", not ext.replication_pairs(S, P))
call("POST", B + "/regions/%s/resourcePolicies" % R, {"name": "cg", "diskConsistencyGroupPolicy": {}})
call("POST", B + "/zones/%s/disks/restored/addResourcePolicies" % Z, {"resourcePolicies": ["projects/%s/regions/%s/resourcePolicies/cg" % (P, R)]})
ok("consistency group lists its disk", call("GET", B + "/regions/%s/resourcePolicies/cg" % R)["_display"]["attachedDisks"] == ["restored"])

# ── multi NIC ──────────────────────────────────────────────────────────────
inst("multi", networkInterfaces=[{"network": "default"}, {"network": "net-b", "subnetwork": "sub-b"}])
nics = call("GET", B + "/zones/%s/instances/multi" % Z)["networkInterfaces"]
ok("two NICs named nic0/nic1 with distinct IPs", [n["name"] for n in nics] == ["nic0", "nic1"] and nics[0]["networkIP"] != nics[1]["networkIP"])
call("POST", B + "/zones/%s/instances" % Z, {"name": "dup", "networkInterfaces": [{"network": "default"}, {"network": "default"}],
     "disks": [{"boot": True, "initializeParams": {}}]}, 400)

# ── NEGs ───────────────────────────────────────────────────────────────────
call("POST", B + "/zones/%s/networkEndpointGroups" % Z, {"name": "neg1", "networkEndpointType": "INTERNET_IP_PORT"}, 400)
call("POST", B + "/zones/%s/networkEndpointGroups" % Z, {"name": "neg1", "network": "default", "subnetwork": "default", "defaultPort": 8080})
call("POST", B + "/zones/%s/networkEndpointGroups/neg1/attachNetworkEndpoints" % Z, {"networkEndpoints": [{"instance": "vm1"}]})
call("POST", B + "/zones/%s/networkEndpointGroups/neg1/attachNetworkEndpoints" % Z, {"networkEndpoints": [{"instance": "vm1"}]}, 400)
call("POST", B + "/zones/%s/networkEndpointGroups/neg1/attachNetworkEndpoints" % Z, {"networkEndpoints": [{"instance": "ghost"}]}, 404)
ne = call("POST", B + "/zones/%s/networkEndpointGroups/neg1/listNetworkEndpoints" % Z, {})["items"]
ok("endpoint carries instance IP + default port", ne[0]["networkEndpoint"]["port"] == 8080 and ne[0]["networkEndpoint"]["ipAddress"])
ok("size reflects endpoints", call("GET", B + "/zones/%s/networkEndpointGroups/neg1" % Z)["size"] == 1)
call("POST", B + "/zones/%s/networkEndpointGroups/neg1/detachNetworkEndpoints" % Z, {"networkEndpoints": [{"instance": "vm1", "port": 8080}]})
call("POST", B + "/global/networkEndpointGroups", {"name": "gneg", "networkEndpointType": "INTERNET_FQDN_PORT", "defaultPort": 443})
call("POST", B + "/global/networkEndpointGroups/gneg/attachNetworkEndpoints", {"networkEndpoints": [{"fqdn": "example.com"}]})
ok("aggregated NEGs span zonal + global", set(call("GET", B + "/aggregated/networkEndpointGroups")["items"]) == {"zones/%s" % Z, "global"})
call("POST", B + "/regions/%s/networkEndpointGroups" % R, {"name": "srv", "networkEndpointType": "SERVERLESS"}, 400)
call("POST", B + "/regions/%s/networkEndpointGroups" % R, {"name": "srv", "networkEndpointType": "SERVERLESS", "cloudRun": {"service": "hello"}})

# ── reservations ───────────────────────────────────────────────────────────
call("POST", B + "/zones/%s/reservations" % Z, {"name": "res1", "specificReservation": {"count": "2", "instanceProperties": {"machineType": "nope"}}}, 400)
call("POST", B + "/zones/%s/reservations" % Z, {"name": "res1", "specificReservation": {"count": "2", "instanceProperties": {"machineType": "e2-medium"}}})
ok("running e2-medium VMs consume the reservation", int(call("GET", B + "/zones/%s/reservations/res1" % Z)["specificReservation"]["inUseCount"]) == 2)  # vm1 + multi
call("POST", B + "/zones/%s/reservations/res1/resize" % Z, {"specificSkuCount": "1"}, 400)
call("POST", B + "/zones/%s/reservations/res1/resize" % Z, {"specificSkuCount": "5"})
inst("nores", reservationAffinity={"consumeReservationType": "NO_RESERVATION"})
ok("NO_RESERVATION doesn't consume", int(call("GET", B + "/zones/%s/reservations/res1" % Z)["specificReservation"]["inUseCount"]) == 2)
inst("spec", reservationAffinity={"consumeReservationType": "SPECIFIC_RESERVATION", "key": "compute.googleapis.com/reservation-name", "values": ["res1"]})
ok("SPECIFIC_RESERVATION consumes", int(call("GET", B + "/zones/%s/reservations/res1" % Z)["specificReservation"]["inUseCount"]) == 3)
call("POST", B + "/zones/%s/instances" % Z, {"name": "badres", "disks": [{"boot": True, "initializeParams": {}}],
     "reservationAffinity": {"consumeReservationType": "SPECIFIC_RESERVATION", "values": ["ghost"]}}, 404)
call("DELETE", B + "/zones/%s/reservations/res1" % Z, status=400)

# ── sole-tenant nodes ──────────────────────────────────────────────────────
call("POST", B + "/regions/%s/nodeTemplates" % R, {"name": "nt", "nodeType": "bogus"}, 400)
call("POST", B + "/regions/%s/nodeTemplates" % R, {"name": "nt", "nodeType": "c2-node-60-240"})
call("POST", B + "/zones/%s/nodeGroups?initialNodeCount=1" % Z, {"name": "ng", "nodeTemplate": "regions/%s/nodeTemplates/nt" % R})
aff = {"nodeAffinities": [{"key": ext.NODE_AFFINITY_KEY, "operator": "IN", "values": ["ng"]}]}
inst("st1", machineType="e2-medium", scheduling=aff)
nodes = call("GET", B + "/zones/%s/nodeGroups/ng" % Z)["_display"]["nodes"]
ok("VM placed on the node", nodes[0]["instances"] == ["st1"])
call("POST", B + "/zones/%s/instances" % Z, {"name": "huge", "machineType": "e2-medium", "scheduling": aff, "disks": [{"boot": True, "initializeParams": {}}]}
     , 200 if gce.MACHINE_SHAPES["e2-medium"]["vcpu"] * 2 <= 60 else 400)
call("POST", B + "/zones/%s/nodeGroups/ng/addNodes" % Z, {"additionalNodeCount": 1})
ok("group grew to 2 nodes", call("GET", B + "/zones/%s/nodeGroups/ng" % Z)["size"] == 2)
call("DELETE", B + "/zones/%s/nodeGroups/ng" % Z, status=400)
call("DELETE", B + "/regions/%s/nodeTemplates/nt" % R, status=400)
ok("nodeTypes catalog", len(call("GET", B + "/zones/%s/nodeTypes" % Z)["items"]) >= 4)

# ── storage pools ──────────────────────────────────────────────────────────
call("POST", B + "/zones/%s/storagePools" % Z, {"name": "sp", "storagePoolType": "hyperdisk-balanced", "poolProvisionedCapacityGb": "100"}, 400)
call("POST", B + "/zones/%s/storagePools" % Z, {"name": "sp", "storagePoolType": "hyperdisk-balanced", "poolProvisionedCapacityGb": "10240",
     "poolProvisionedIops": "10000", "poolProvisionedThroughput": "1024"})
call("POST", B + "/zones/%s/disks" % Z, {"name": "hd1", "sizeGb": "6000", "type": "hyperdisk-balanced", "storagePool": "zones/%s/storagePools/sp" % Z})
call("POST", B + "/zones/%s/disks" % Z, {"name": "hd2", "sizeGb": "6000", "type": "hyperdisk-balanced", "storagePool": "zones/%s/storagePools/sp" % Z}, 400)  # over capacity
call("POST", B + "/zones/%s/disks" % Z, {"name": "hd3", "sizeGb": "10", "type": "pd-ssd", "storagePool": "zones/%s/storagePools/sp" % Z}, 400)       # wrong type
sp = call("GET", B + "/zones/%s/storagePools/sp" % Z)
ok("pool accounts its disks", sp["status"]["totalProvisionedDiskCapacityGb"] == "6000" and sp["status"]["diskCount"] == "1")
call("DELETE", B + "/zones/%s/storagePools/sp" % Z, status=400)

# ── recommender ────────────────────────────────────────────────────────────
RB = "/v1/projects/%s/locations/%s/recommenders" % (P, Z)
recs = call("GET", RB + "/google.compute.disk.IdleResourceRecommender/recommendations")["recommendations"]
names = {r["targetResources"][0].split("/")[-1] for r in recs}
ok("idle-disk recs cover unattached disks only", {"data1", "restored", "hd1"} <= names and not any(n in names for n in ("vm1", "multi")))
r0 = next(r for r in recs if r["targetResources"][0].endswith("/hd1"))
ok("cost projection is negative USD (savings)", r0["primaryImpact"]["category"] == "COST" and int(r0["primaryImpact"]["costProjection"]["cost"]["units"]) < 0)
c = call("POST", "%s/google.compute.disk.IdleResourceRecommender/recommendations/%s:markClaimed" % (RB, r0["name"].rsplit("/", 1)[1]), {"etag": r0["etag"]})
ok("markClaimed → CLAIMED", c["stateInfo"]["state"] == "CLAIMED")
call("POST", "%s/google.compute.disk.IdleResourceRecommender/recommendations/%s:markDismissed" % (RB, r0["name"].rsplit("/", 1)[1]), {"etag": r0["etag"]}, 409)  # stale etag
act = call("GET", RB + "/google.compute.disk.IdleResourceRecommender/recommendations")["recommendations"]
ok("filter state ACTIVE drops the claimed one", all(x["name"] != r0["name"] for x in
   [y for y in call("GET", RB + "/google.compute.disk.IdleResourceRecommender/recommendations")["recommendations"] if y["stateInfo"]["state"] == "ACTIVE"]))
call("DELETE", B + "/zones/%s/disks/hd1" % Z)
ok("rec disappears when the disk is deleted", all(not x["targetResources"][0].endswith("/hd1") for x in
   call("GET", RB + "/google.compute.disk.IdleResourceRecommender/recommendations")["recommendations"]))
ur = call("GET", RB + "/vyomi.compute.reservation.UnusedReservationRecommender/recommendations")
ok("no unused-reservation rec while VMs consume it", not ur.get("recommendations"))
call("GET", RB + "/nope.Recommender/recommendations", status=404)
print("PASS test_gcp_compute_ext_core")
