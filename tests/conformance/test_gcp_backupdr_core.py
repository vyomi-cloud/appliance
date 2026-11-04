"""Backup and DR (backupdr.googleapis.com/v1) on the Compute core: vaults, plans, associations, REAL snapshot backups, restore."""
import json
import time

from core import gcp_backupdr_core as bdr
from core import gcp_compute_instances_core as gce

P, Z, L = "demo-proj", "us-central1-a", "us-central1"
B = "/v1/projects/%s/locations/%s" % (P, L)
store = gce.ComputeStore()


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    print("  ok ", name)


def call(method, path, body=None, q=None, now=None):
    r = bdr.dispatch(store, method, B + path, q or {}, {}, json.dumps(body).encode() if body is not None else b"", now=now)
    return r.status, json.loads(r.body.decode())


def comp(method, path, body=None):
    r = gce.dispatch(store, method, "/compute/v1/projects/%s%s" % (P, path), {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body.decode())


st, _ = comp("POST", "/zones/%s/instances" % Z, {"name": "web1", "machineType": "e2-medium",
             "disks": [{"boot": True, "autoDelete": True, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-12"}}]})
ok("instance created", st == 200)
IRES = "projects/%s/zones/%s/instances/web1" % (P, Z)

st, b = call("POST", "/backupVaults", {"backupMinimumEnforcedRetentionDuration": "60s"}, {"backupVaultId": "v1"})
ok("vault min retention < 1 day rejected", st == 400)
st, b = call("POST", "/backupVaults", {"backupMinimumEnforcedRetentionDuration": "86400s", "description": "prod"}, {"backupVaultId": "v1"})
ok("vault created (LRO done)", st == 200 and b["done"] and b["response"]["state"] == "ACTIVE")
VAULT = b["response"]["name"]
st, b = call("POST", "/backupVaults", {"backupMinimumEnforcedRetentionDuration": "86400s"}, {"backupVaultId": "v1"})
ok("duplicate vault 409", st == 409)
st, b = call("GET", "/backupVaults")
ok("vault list", len(b["backupVaults"]) == 1)

rule = {"ruleId": "daily", "backupRetentionDays": 7, "standardSchedule": {"recurrenceType": "DAILY", "backupWindow": {"startHourOfDay": 2, "endHourOfDay": 6}}}
st, b = call("POST", "/backupPlans", {"resourceType": "compute.googleapis.com/Instance", "backupVault": VAULT, "backupRules": [dict(rule, backupRetentionDays=0)]}, {"backupPlanId": "p1"})
ok("retention 0 rejected", st == 400)
st, b = call("POST", "/backupPlans", {"resourceType": "compute.googleapis.com/Instance", "backupVault": "projects/x/locations/y/backupVaults/none", "backupRules": [rule]}, {"backupPlanId": "p1"})
ok("unknown vault 404", st == 404)
st, b = call("POST", "/backupPlans", {"resourceType": "compute.googleapis.com/Instance", "backupVault": VAULT, "backupRules": [rule]}, {"backupPlanId": "p1"})
ok("plan created", st == 200)
PLAN = b["response"]["name"]

st, b = call("POST", "/backupPlanAssociations", {"resourceType": "compute.googleapis.com/Instance", "resource": "projects/%s/zones/%s/instances/ghost" % (P, Z), "backupPlan": PLAN}, {"backupPlanAssociationId": "a1"})
ok("missing instance 404", st == 404)
t0 = time.time() - 3 * 86400
st, b = call("POST", "/backupPlanAssociations", {"resourceType": "compute.googleapis.com/Instance", "resource": IRES, "backupPlan": PLAN}, {"backupPlanAssociationId": "a1"}, now=t0)
ok("association created", st == 200 and b["response"]["state"] == "ACTIVE")
ASSOC = b["response"]["name"]
DS = b["response"]["dataSource"]
st, b = call("POST", "/backupPlanAssociations", {"resourceType": "compute.googleapis.com/Instance", "resource": IRES, "backupPlan": PLAN}, {"backupPlanAssociationId": "a2"})
ok("double protection 409", st == 409)
st, b = call("DELETE", "/backupPlans/p1")
ok("plan in use cannot be deleted", st == 400 and b["error"]["status"] == "FAILED_PRECONDITION")

snaps_before = len(store.snapshots)
st, b = call("POST", "/backupPlanAssociations/a1:triggerBackup", {"ruleId": "nope"})
ok("unknown rule rejected", st == 400)
st, b = call("POST", "/backupPlanAssociations/a1:triggerBackup", {"ruleId": "daily"})
ok("triggerBackup", st == 200 and b["response"]["backupType"] == "ON_DEMAND")
BK = b["response"]["name"]
ok("REAL snapshot taken", len(store.snapshots) == snaps_before + 1 and any(s.get("labels", {}).get("vyomi-backupdr") == "v1" for s in store.snapshots.values()))
st, b = call("GET", "/backupVaults/v1/dataSources")
ok("data source + backup count", len(b["dataSources"]) == 1 and b["dataSources"][0]["backupCount"] == "2")
st, b = call("GET", "/backupVaults/v1/dataSources/%s/backups" % DS.rsplit("/", 1)[-1])
ok("backups listed", len(b["backups"]) == 2 and b["backups"][0]["gcpBackupPlanInfo"]["backupPlanRuleId"] == "daily")

st, b = call("DELETE", "/backupVaults/v1/dataSources/%s/backups/%s" % (DS.rsplit("/", 1)[-1], BK.rsplit("/", 1)[-1]))
ok("enforced retention blocks delete", st == 400 and "enforced retention" in b["error"]["message"])
st, b = call("DELETE", "/backupVaults/v1")
ok("vault with backups needs force", st == 400)

st, b = call("POST", "/backupVaults/v1/dataSources/%s/backups/%s:restore" % (DS.rsplit("/", 1)[-1], BK.rsplit("/", 1)[-1]),
             {"computeInstanceTargetEnvironment": {"project": P, "zone": Z}, "computeInstanceRestoreProperties": {"name": "web1-restored"}})
ok("restore creates instance", st == 200 and "web1-restored" in b["response"]["instance"] and "projects/%s/zones/%s/instances/web1-restored" % (P, Z) in store.instances)
rd = store.disks["projects/%s/zones/%s/disks/web1-restored" % (P, Z)]
ok("restored disk sourced from the backup snapshot", rd["sourceSnapshot"].rsplit("/", 1)[-1] in bdr._x(store)["backups"][BK]["_snapshots"])
st, b = call("POST", "/backupVaults/v1/dataSources/%s/backups/%s:restore" % (DS.rsplit("/", 1)[-1], BK.rsplit("/", 1)[-1]),
             {"computeInstanceRestoreProperties": {"name": "web1-restored"}})
ok("restore name conflict 409", st == 409)

# scheduled fire: association baseline was 3 days ago, so a daily 02:00 rule is due -> ONE coalesced SCHEDULED backup
n = len(store.snapshots)
st, b = call("GET", "/backupVaults/v1/dataSources/%s/backups" % DS.rsplit("/", 1)[-1])
ok("scheduled backup fired once", sum(1 for x in b["backups"] if x["backupType"] == "SCHEDULED") == 1)

# expiry: far-future tick drops backups past retention and removes their snapshots
st, b = call("DELETE", "/backupPlanAssociations/a1")
ok("association deleted", st == 200)
bdr.tick(store, time.time() + 40 * 86400)
ok("expired backups pruned with their snapshots", not [k for k in store.snapshots if "bdr-" in k] and not bdr._x(store)["backups"])
st, b = call("DELETE", "/backupPlans/p1")
ok("plan deleted", st == 200)
st, b = call("DELETE", "/backupVaults/v1")
ok("vault deleted", st == 200)
print("PASS test_gcp_backupdr_core")
