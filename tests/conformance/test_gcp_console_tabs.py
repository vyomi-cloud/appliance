"""GCP console resource-detail tabs show THIS resource's real data, offline and in Nano.

Each test creates a resource through the console's own create path, drives the tab's
reads/writes (`/api/gcp/sub/{service}/{op}/{name}`) and checks what comes back is the
resource's backend state — a write persists and is visible to the next read (reopening
the tab), invalid input gets the real API's error.

  nano     — in-process: the Nano backend (wasm/providers registry + gcp_core_adapter
             over the cores), the exact code the browser runs. Always runs.
  offline  — the appliance at VYOMI_BASE_URL (skipped when it isn't reachable).
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE = os.environ.get("VYOMI_BASE_URL", "http://127.0.0.1:9000").rstrip("/")


class NanoClient:
    mode = "nano"

    def __init__(self):
        from wasm.backends.store import Backends
        from wasm import providers as P
        self.P, self.B = P, Backends()
        self.project = "nano-project"

    def _d(self, op, params):
        out = self.P.dispatch(self.B, "gcp", "_resource", op, params=params)
        out = out if isinstance(out, dict) else {}
        if "__http" in out:
            return out["__http"]["status"], out["__http"]["body"]
        return (404 if out.get("ok") is False else 200), out

    def create(self, svc, body):
        return self._d("Create", {"service": svc, "body": body})

    def get(self, svc, name):
        return self._d("Get", {"service": svc, "name": name})

    def delete(self, svc, name):
        return self._d("Delete", {"service": svc, "name": name})

    def sub(self, svc, op, name, body=None):
        p = {"service": svc, "name": name}
        if body is not None:
            p["body"] = body
        return self._d(op[0].upper() + op[1:], p)


class OfflineClient:
    mode = "offline"

    def __init__(self):
        import requests
        self.s = requests.Session()
        self.cat = self.s.get(BASE + "/api/gcp/catalog", timeout=10).json()
        self.project = self.cat["project"]

    def _fill(self, tpl, name=""):
        return (tpl.replace("{project}", self.cat["project"]).replace("{region}", self.cat["region"])
                .replace("{zone}", self.cat["zone"]).replace("{name}", name))

    def _svc(self, key):
        return next(s for s in self.cat["services"] if s["key"] == key)

    def _j(self, r):
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}

    def create(self, svc, body):
        s = self._svc(svc)
        return self._j(self.s.request(s.get("create_method") or "POST", BASE + self._fill(s["collection_path"]), json=body, timeout=30))

    def get(self, svc, name):
        return self._j(self.s.get(BASE + self._fill(self._svc(svc)["resource_path"], name), timeout=30))

    def delete(self, svc, name):
        return self._j(self.s.delete(BASE + self._fill(self._svc(svc)["resource_path"], name), timeout=30))

    def sub(self, svc, op, name, body=None):
        from urllib.parse import quote
        url = "%s/api/gcp/sub/%s/%s/%s" % (BASE, svc, op, quote(name, safe=""))
        r = self.s.post(url, json=body, timeout=30) if body is not None else self.s.get(url, timeout=30)
        return self._j(r)


def _offline_up():
    try:
        import requests
        return requests.get(BASE + "/api/gcp/catalog", timeout=3).ok
    except Exception:
        return False


@pytest.fixture(scope="module", params=["nano", "offline"])
def c(request):
    if request.param == "nano":
        return NanoClient()
    if not _offline_up():
        pytest.skip("offline appliance not reachable at %s" % BASE)
    return OfflineClient()


def uid(prefix):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:6])


def _wait(fn, ok, tries=20):
    for _ in range(tries):
        v = fn()
        if ok(v):
            return v
        time.sleep(0.3)
    return v


# ── universal tabs ────────────────────────────────────────────────────────────
def test_permissions_tab_reads_and_writes_the_project_policy(c):
    member = "user:%s@example.com" % uid("dev")
    st, out = c.sub("iam", "grantAccess", c.project, {"member": member, "role": "roles/viewer"})
    assert st == 200 and out["ok"]
    st, pol = c.sub("iam", "getProjectPolicy", c.project)
    assert any(b["role"] == "roles/viewer" and member in b["members"] for b in pol["bindings"])
    st, bad = c.sub("iam", "grantAccess", c.project, {"member": "nobody", "role": "roles/viewer"})
    assert st == 400 and bad["code"] == "INVALID_ARGUMENT"
    st, _ = c.sub("iam", "revokeAccess", c.project, {"member": member, "role": "roles/viewer"})
    assert st == 200
    st, pol = c.sub("iam", "getProjectPolicy", c.project)
    assert not any(member in b["members"] for b in pol["bindings"])


# ── Compute Engine ────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def vm(c):
    name = uid("tabvm")
    st, _ = c.create("compute", {"name": name, "machineType": "e2-medium"})
    assert st == 200
    _wait(lambda: c.sub("compute", "getNetworking", name), lambda r: r[0] == 200)
    return name


def test_compute_networking_tab_is_the_instance_nics(c, vm):
    st, out = c.sub("compute", "getNetworking", vm)
    assert st == 200
    nics = out["item"]["networkInterfaces"]
    assert nics and nics[0]["name"] == "nic0" and nics[0]["networkIP"].startswith("10.")
    assert nics[0]["network"].rstrip("/").rsplit("/", 1)[-1] == "default"


def test_compute_metadata_and_startup_script_persist(c, vm):
    items = [{"key": "env", "value": "dev"}, {"key": "startup-script", "value": "#! /bin/bash\necho hi"}]
    st, _ = c.sub("compute", "setMetadata", vm, {"items": items})
    assert st == 200
    st, out = c.sub("compute", "getMetadata", vm)
    got = {i["key"]: i["value"] for i in out["item"]["metadata"]["items"]}
    assert got == {"env": "dev", "startup-script": "#! /bin/bash\necho hi"}
    # the instance's own GET (the API/SDK view) carries the same metadata
    st, inst = c.get("compute", vm)
    assert {i["key"] for i in inst["metadata"]["items"]} == {"env", "startup-script"}
    st, bad = c.sub("compute", "setMetadata", vm, {"items": [{"key": "bad key!", "value": "x"}]})
    assert st == 400


def test_compute_scheduling_validates_like_gce(c, vm):
    st, bad = c.sub("compute", "setScheduling", vm, {"provisioningModel": "SPOT"})
    assert st == 400 and "OnHostMaintenance" in bad["message"]
    st, out = c.sub("compute", "setScheduling", vm,
                    {"provisioningModel": "SPOT", "onHostMaintenance": "TERMINATE", "automaticRestart": False})
    assert st == 200
    st, out = c.sub("compute", "getScheduling", vm)
    s = out["item"]["scheduling"]
    assert s["provisioningModel"] == "SPOT" and s["onHostMaintenance"] == "TERMINATE" and s["automaticRestart"] is False


def test_compute_disks_and_snapshots(c, vm):
    disk = uid("data")
    st, _ = c.sub("compute", "attachDisk", vm, {"name": disk, "sizeGb": 20, "type": "pd-ssd"})
    assert st == 200
    st, out = c.sub("compute", "listDisks", vm)
    d = next(x for x in out["items"] if x["name"] == disk)
    assert d["sizeGb"] == "20" and d["type"] == "pd-ssd" and not d["boot"]
    boot = next(x for x in out["items"] if x["boot"])
    st, bad = c.sub("compute", "detachDisk", vm, {"name": boot["name"]})
    assert st == 400
    snap = uid("snap")
    st, _ = c.sub("compute", "createSnapshot", vm, {"name": snap, "sourceDisk": disk})
    assert st == 200
    st, out = c.sub("compute", "listSnapshots", vm)
    assert [x["sourceDisk"] for x in out["items"] if x["name"] == snap] == [disk]
    st, _ = c.sub("compute", "deleteSnapshot", vm, {"name": snap})
    st, out = c.sub("compute", "listSnapshots", vm)
    assert snap not in [x["name"] for x in out["items"]]
    st, _ = c.sub("compute", "detachDisk", vm, {"name": disk})
    assert st == 200
    st, out = c.sub("compute", "listDisks", vm)
    assert disk not in [x["name"] for x in out["items"]]


def test_compute_labels_tab(c, vm):
    st, _ = c.sub("compute", "setLabels", vm, {"labels": {"team": "core"}})
    assert st == 200
    st, out = c.sub("compute", "getLabels", vm)
    assert out["item"]["labels"] == {"team": "core"}
    st, bad = c.sub("compute", "setLabels", vm, {"labels": {"Team": "x"}})
    assert st == 400


# ── Cloud Storage ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def bucket(c):
    name = uid("tabbkt")
    st, _ = c.create("storage", {"name": name})
    assert st == 200
    return name


def test_storage_lifecycle_tab_round_trips_rules(c, bucket):
    rules = [{"action": {"type": "Delete"}, "condition": {"age": 30}},
             {"action": {"type": "SetStorageClass", "storageClass": "COLDLINE"}, "condition": {"age": 90, "matchesPrefix": ["logs/"]}}]
    st, _ = c.sub("storage", "setLifecycle", bucket, {"rule": rules})
    assert st == 200
    st, out = c.sub("storage", "getLifecycle", bucket)
    got = out["item"]["lifecycle"]["rule"]
    assert [r["action"]["type"] for r in got] == ["Delete", "SetStorageClass"] and got[1]["condition"]["matchesPrefix"] == ["logs/"]
    # the bucket's own GET (SDK view) carries the same lifecycle config
    st, b = c.get("storage", bucket)
    assert len(b["lifecycle"]["rule"]) == 2
    st, bad = c.sub("storage", "setLifecycle", bucket, {"rule": [{"action": {"type": "Explode"}, "condition": {"age": 1}}]})
    assert st == 400


def test_storage_encryption_tab(c, bucket):
    key = "projects/%s/locations/global/keyRings/ring/cryptoKeys/k1" % c.project
    st, _ = c.sub("storage", "setEncryption", bucket, {"defaultKmsKeyName": key})
    assert st == 200
    st, out = c.sub("storage", "getEncryption", bucket)
    assert out["item"]["encryption"]["defaultKmsKeyName"] == key
    st, bad = c.sub("storage", "setEncryption", bucket, {"defaultKmsKeyName": "not-a-key"})
    assert st == 400
    st, _ = c.sub("storage", "setEncryption", bucket, {"defaultKmsKeyName": ""})
    st, out = c.sub("storage", "getEncryption", bucket)
    assert "encryption" not in out["item"]


def test_storage_retention_versioning_soft_delete(c, bucket):
    st, _ = c.sub("storage", "setRetention", bucket, {"retentionPeriod": "86400"})
    assert st == 200
    st, _ = c.sub("storage", "setVersioning", bucket, {"enabled": True})
    st, _ = c.sub("storage", "setSoftDelete", bucket, {"retentionDurationSeconds": 604800})
    assert st == 200
    st, out = c.sub("storage", "getRetention", bucket)
    it = out["item"]
    assert it["retentionPolicy"]["retentionPeriod"] == "86400" and it["retentionPolicy"]["isLocked"] is False
    assert it["versioning"]["enabled"] is True and it["softDeletePolicy"]["retentionDurationSeconds"] == "604800"
    st, bad = c.sub("storage", "setSoftDelete", bucket, {"retentionDurationSeconds": 3600})
    assert st == 400
    st, _ = c.sub("storage", "lockRetention", bucket, {})
    assert st == 200
    st, bad = c.sub("storage", "setRetention", bucket, {"retentionPeriod": None})
    assert st == 403
    st, bad = c.sub("storage", "setRetention", bucket, {"retentionPeriod": "60"})
    assert st == 403
    st, _ = c.sub("storage", "setRetention", bucket, {"retentionPeriod": "172800"})
    assert st == 200
    st, out = c.sub("storage", "getRetention", bucket)
    assert out["item"]["retentionPolicy"] == {**out["item"]["retentionPolicy"], "retentionPeriod": "172800", "isLocked": True}


def test_storage_config_and_labels(c, bucket):
    st, _ = c.sub("storage", "setStorageClass", bucket, {"storageClass": "NEARLINE"})
    assert st == 200
    st, out = c.sub("storage", "getConfiguration", bucket)
    assert out["item"]["storageClass"] == "NEARLINE" and out["item"]["name"] == bucket
    st, _ = c.sub("storage", "setLabels", bucket, {"labels": {"env": "dev"}})
    st, out = c.sub("storage", "getLabels", bucket)
    assert out["item"]["labels"] == {"env": "dev"}


def test_storage_retention_blocks_object_delete_in_the_engine():
    from core import gcp_storage_core as gcs
    from core.object_store import InMemoryObjectStore
    st = InMemoryObjectStore()
    call = lambda m, p, q=None, b=b"", h=None: gcs.dispatch(st, m, p, q or {}, h or {}, b)
    assert call("POST", "/storage/v1/b", b=json.dumps({"name": "b1"}).encode()).status == 200
    assert call("POST", "/upload/storage/v1/b/b1/o", {"uploadType": "media", "name": "o1"}, b"hi").status == 200
    assert call("PATCH", "/storage/v1/b/b1", b=json.dumps({"retentionPolicy": {"retentionPeriod": "3600"}}).encode()).status == 200
    r = call("DELETE", "/storage/v1/b/b1/o/o1")
    assert r.status == 403 and b"retention policy" in r.body
    assert call("POST", "/upload/storage/v1/b/b1/o", {"uploadType": "media", "name": "o1"}, b"again").status == 403
    assert call("PATCH", "/storage/v1/b/b1", b=json.dumps({"retentionPolicy": None}).encode()).status == 200
    assert call("DELETE", "/storage/v1/b/b1/o/o1").status == 204


# ── Cloud SQL ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def sqli(c):
    name = uid("tabsql")
    st, _ = c.create("cloudsql", {"name": name, "databaseVersion": "POSTGRES_15", "tier": "db-f1-micro"})
    assert st == 200
    _wait(lambda: c.sub("cloudsql", "getFlags", name), lambda r: r[0] == 200)
    return name


def test_cloudsql_databases_tab(c, sqli):
    st, _ = c.sub("cloudsql", "createDatabase", sqli, {"name": "appdb"})
    assert st == 200
    st, dup = c.sub("cloudsql", "createDatabase", sqli, {"name": "appdb"})
    assert st == 409
    st, out = c.sub("cloudsql", "listDatabases", sqli)
    assert "appdb" in [d["name"] for d in out["items"]]
    st, _ = c.sub("cloudsql", "deleteDatabase", sqli, {"name": "appdb"})
    st, out = c.sub("cloudsql", "listDatabases", sqli)
    assert "appdb" not in [d["name"] for d in out["items"]]


def test_cloudsql_users_tab(c, sqli):
    st, out = c.sub("cloudsql", "listUsers", sqli)
    assert st == 200 and out["items"], "the instance's admin user is listed"
    st, _ = c.sub("cloudsql", "createUser", sqli, {"name": "app_user", "password": "s3cret!", "type": "BUILT_IN"})
    assert st == 200
    st, bad = c.sub("cloudsql", "createUser", sqli, {"name": "nopass", "type": "BUILT_IN"})
    assert st == 400
    st, out = c.sub("cloudsql", "listUsers", sqli)
    assert "app_user" in [u["name"] for u in out["items"]]
    st, _ = c.sub("cloudsql", "setUserPassword", sqli, {"name": "app_user", "password": "n3w"})
    assert st == 200
    st, _ = c.sub("cloudsql", "deleteUser", sqli, {"name": "app_user"})
    st, out = c.sub("cloudsql", "listUsers", sqli)
    assert "app_user" not in [u["name"] for u in out["items"]]


def test_cloudsql_backups_tab(c, sqli):
    st, _ = c.sub("cloudsql", "createBackup", sqli, {"description": "before-migration"})
    assert st == 200
    st, out = c.sub("cloudsql", "listBackups", sqli)
    b = next(x for x in out["items"] if x["description"] == "before-migration")
    assert b["type"] == "ON_DEMAND" and b["status"] == "SUCCESSFUL"
    st, _ = c.sub("cloudsql", "setBackupConfig", sqli, {"enabled": True, "startTime": "03:00", "pointInTimeRecoveryEnabled": True, "retainedBackups": 14})
    assert st == 200
    st, out = c.sub("cloudsql", "getBackupConfig", sqli)
    cfg = out["item"]["settings"]["backupConfiguration"]
    assert cfg["enabled"] and cfg["startTime"] == "03:00" and cfg["backupRetentionSettings"]["retainedBackups"] == 14
    st, bad = c.sub("cloudsql", "setBackupConfig", sqli, {"startTime": "03:30"})
    assert st == 400
    st, _ = c.sub("cloudsql", "deleteBackup", sqli, {"id": b["id"]})
    st, out = c.sub("cloudsql", "listBackups", sqli)
    assert b["id"] not in [x["id"] for x in out["items"]]


def test_cloudsql_replicas_tab(c, sqli):
    rep = uid("rep")
    st, _ = c.sub("cloudsql", "createReplica", sqli, {"name": rep})
    assert st == 200
    st, out = c.sub("cloudsql", "listReplicas", sqli)
    assert [r["name"] for r in out["items"]] == [rep]
    st, inst = c.get("cloudsql", rep)
    assert inst.get("masterInstanceName", sqli) == sqli
    st, _ = c.sub("cloudsql", "promoteReplica", sqli, {"name": rep})
    assert st == 200
    st, out = c.sub("cloudsql", "listReplicas", sqli)
    assert out["items"] == []


def test_cloudsql_connectivity_flags_insights(c, sqli):
    st, _ = c.sub("cloudsql", "addAuthorizedNetwork", sqli, {"name": "office", "value": "203.0.113.0/24"})
    assert st == 200
    st, bad = c.sub("cloudsql", "addAuthorizedNetwork", sqli, {"name": "lan", "value": "10.0.0.0/8"})
    assert st == 400 and "private" in bad["message"].lower()
    st, _ = c.sub("cloudsql", "setIpConfig", sqli, {"sslMode": "ENCRYPTED_ONLY"})
    st, out = c.sub("cloudsql", "getConnectivity", sqli)
    ip = out["item"]["settings"]["ipConfiguration"]
    assert ip["sslMode"] == "ENCRYPTED_ONLY" and [n["value"] for n in ip["authorizedNetworks"]] == ["203.0.113.0/24"]
    st, _ = c.sub("cloudsql", "setFlags", sqli, {"flags": [{"name": "max_connections", "value": "200"}, {"name": "log_connections", "value": "on"}]})
    assert st == 200
    st, out = c.sub("cloudsql", "getFlags", sqli)
    assert {f["name"]: f["value"] for f in out["item"]["settings"]["databaseFlags"]} == {"max_connections": "200", "log_connections": "on"}
    st, bad = c.sub("cloudsql", "setFlags", sqli, {"flags": [{"name": "max_connections", "value": "5"}]})
    assert st == 400
    st, bad = c.sub("cloudsql", "setFlags", sqli, {"flags": [{"name": "innodb_lock_wait_timeout", "value": "5"}]})
    assert st == 400   # a MySQL flag on a Postgres instance
    st, _ = c.sub("cloudsql", "setInsights", sqli, {"queryInsightsEnabled": True, "queryStringLength": 2048})
    st, out = c.sub("cloudsql", "getInsights", sqli)
    assert out["item"]["settings"]["insightsConfig"] == {**out["item"]["settings"]["insightsConfig"], "queryInsightsEnabled": True, "queryStringLength": 2048}
    st, out = c.sub("cloudsql", "listOperations", sqli)
    assert "UPDATE" in [o["operationType"] for o in out["items"]]
    st, _ = c.sub("cloudsql", "setLabels", sqli, {"labels": {"tier": "gold"}})
    st, out = c.sub("cloudsql", "getLabels", sqli)
    assert out["item"]["labels"] == {"tier": "gold"}


# ── Pub/Sub ───────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def topic(c):
    name = uid("tabtopic")
    st, _ = c.create("pubsub", {"name": name})
    assert st == 200
    yield name
    for sub in (c.sub("pubsub", "listSubscriptions", name)[1].get("items") or []):
        c.sub("pubsub", "deleteSubscription", name, {"name": sub["name"]})
    c.delete("pubsub", name)


def test_pubsub_subscriptions_and_messages(c, topic):
    sub = uid("tabsub")
    st, _ = c.sub("pubsub", "createSubscription", topic, {"name": sub, "ackDeadlineSeconds": 20})
    assert st == 200
    st, bad = c.sub("pubsub", "createSubscription", topic, {"name": "goog-x", "ackDeadlineSeconds": 20})
    assert st == 400
    st, out = c.sub("pubsub", "listSubscriptions", topic)
    s = next(x for x in out["items"] if x["name"] == sub)
    assert s["ackDeadlineSeconds"] == 20 and s["deliveryType"] == "Pull"
    st, out = c.sub("pubsub", "publishMessage", topic, {"data": "hello tabs", "attributes": {"origin": "test"}})
    assert st == 200 and out["messageIds"]
    got = _wait(lambda: c.sub("pubsub", "pullMessages", topic, {"subscription": sub, "maxMessages": 5, "ack": True}),
                lambda r: r[0] == 200 and r[1]["items"])
    assert got[1]["items"][0]["data"] == "hello tabs" and "origin=test" in got[1]["items"][0]["attributes"]
    st, out = c.sub("pubsub", "pullMessages", topic, {"subscription": sub, "maxMessages": 5, "ack": True})
    assert out["items"] == []      # acknowledged messages are gone
    st, _ = c.sub("pubsub", "deleteSubscription", topic, {"name": sub})
    st, out = c.sub("pubsub", "listSubscriptions", topic)
    assert sub not in [x["name"] for x in out["items"]]


def test_pubsub_schema_tab_enforces_the_schema(c, topic):
    sid = uid("TabSchema")
    avro = json.dumps({"type": "record", "name": "Ev", "fields": [{"name": "id", "type": "string"}]})
    st, bad = c.sub("pubsub", "createSchema", topic, {"name": sid, "type": "AVRO", "definition": "{not json"})
    assert st == 400
    st, _ = c.sub("pubsub", "createSchema", topic, {"name": sid, "type": "AVRO", "definition": avro})
    assert st == 200
    st, out = c.sub("pubsub", "listSchemas", topic)
    full = next(x["name"] for x in out["items"] if x["name"].endswith("/" + sid))
    st, _ = c.sub("pubsub", "setSchema", topic, {"schema": full, "encoding": "JSON"})
    assert st == 200
    st, out = c.sub("pubsub", "getSchema", topic)
    assert out["item"]["schemaSettings"]["schema"] == full and out["item"]["schema"]["type"] == "AVRO"
    st, bad = c.sub("pubsub", "publishMessage", topic, {"data": json.dumps({"other": 1})})
    assert st == 400
    st, ok = c.sub("pubsub", "publishMessage", topic, {"data": json.dumps({"id": "a1"})})
    assert st == 200
    st, _ = c.sub("pubsub", "setSchema", topic, {"schema": ""})
    st, out = c.sub("pubsub", "getSchema", topic)
    assert not out["item"].get("schemaSettings")


def test_pubsub_encryption_and_labels(c, topic):
    key = "projects/%s/locations/global/keyRings/r/cryptoKeys/k" % c.project
    st, _ = c.sub("pubsub", "setEncryption", topic, {"kmsKeyName": key})
    assert st == 200
    st, out = c.sub("pubsub", "getEncryption", topic)
    assert out["item"]["kmsKeyName"] == key
    st, topic_get = c.get("pubsub", topic)
    assert topic_get["kmsKeyName"] == key       # the topic's own GET reports the CMEK key
    st, bad = c.sub("pubsub", "setEncryption", topic, {"kmsKeyName": "bogus"})
    assert st == 400
    st, _ = c.sub("pubsub", "setLabels", topic, {"labels": {"team": "events"}})
    st, out = c.sub("pubsub", "getLabels", topic)
    assert out["item"]["labels"] == {"team": "events"}


# ── VPC network ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def nets(c):
    auto, custom = uid("tabauto"), uid("tabcust")
    assert c.create("vpc", {"name": auto, "autoCreateSubnetworks": True})[0] == 200
    assert c.create("vpc", {"name": custom, "autoCreateSubnetworks": False})[0] == 200
    yield auto, custom
    for n in (auto, custom):
        c.delete("vpc", n)


def test_vpc_subnets_tab(c, nets):
    auto, custom = nets
    st, out = c.sub("vpc", "listSubnets", auto)
    regions = {s["region"]: s["ipCidrRange"] for s in out["items"]}
    assert regions["us-central1"] == "10.128.0.0/20" and len(regions) >= 15      # auto mode: one /20 per region
    st, out = c.sub("vpc", "listSubnets", custom)
    assert out["items"] == []
    st, _ = c.sub("vpc", "createSubnet", custom, {"name": "app", "region": "us-east1", "ipCidrRange": "10.20.0.0/24"})
    assert st == 200
    st, bad = c.sub("vpc", "createSubnet", custom, {"name": "app2", "region": "us-east1", "ipCidrRange": "10.20.0.128/25"})
    assert st == 400 and "conflicts" in bad["message"]
    st, out = c.sub("vpc", "listSubnets", custom)
    s = out["items"][0]
    assert (s["name"], s["region"], s["ipCidrRange"], s["gatewayAddress"]) == ("app", "us-east1", "10.20.0.0/24", "10.20.0.1")
    st, _ = c.sub("vpc", "setPrivateGoogleAccess", custom, {"name": "app", "region": "us-east1", "enabled": True})
    st, out = c.sub("vpc", "listSubnets", custom)
    assert out["items"][0]["privateIpGoogleAccess"] is True
    st, bad = c.sub("vpc", "deleteSubnet", auto, {"name": auto, "region": "us-central1"})
    assert st == 400                                                               # auto-created subnets stay


def test_vpc_firewalls_routes_flowlogs(c, nets):
    auto, custom = nets
    fwn, rtn = uid("allow-web"), uid("to-vpn")
    st, _ = c.sub("vpc", "createFirewall", custom, {"name": fwn, "direction": "INGRESS", "action": "allow",
                                                    "rules": "tcp:80,443", "ranges": "0.0.0.0/0", "targetTags": "web", "priority": 900})
    assert st == 200
    st, bad = c.sub("vpc", "createFirewall", custom, {"name": "bad", "rules": "icmp:22"})
    assert st == 400
    st, out = c.sub("vpc", "listFirewalls", custom)
    fw = next(f for f in out["items"] if f["name"] == fwn)
    assert fw["allowed"] == [{"IPProtocol": "tcp", "ports": ["80", "443"]}] and fw["targetTags"] == ["web"] and fw["priority"] == 900
    st, _ = c.sub("vpc", "setFirewallDisabled", custom, {"name": fwn, "disabled": True})
    st, out = c.sub("vpc", "listFirewalls", custom)
    assert next(f for f in out["items"] if f["name"] == fwn)["disabled"] is True
    st, _ = c.sub("vpc", "deleteFirewall", custom, {"name": fwn})
    st, out = c.sub("vpc", "createRoute", custom, {"name": rtn, "destRange": "192.0.2.0/24", "nextHopType": "ip", "nextHop": "10.20.0.5"})
    assert st == 200
    st, out = c.sub("vpc", "listRoutes", custom)
    types = {r["name"]: r["type"] for r in out["items"]}
    assert types[rtn] == "Static route" and "Subnet route" in types.values() and "Default route" in types.values()
    st, bad = c.sub("vpc", "deleteRoute", custom, {"name": next(n for n, t in types.items() if t == "Subnet route")})
    assert st == 400
    assert c.sub("vpc", "deleteRoute", custom, {"name": rtn})[0] == 200
    st, _ = c.sub("vpc", "setFlowLogs", custom, {"name": "app", "region": "us-east1", "enable": True, "aggregationInterval": "INTERVAL_30_SEC", "flowSampling": 0.25})
    assert st == 200
    st, out = c.sub("vpc", "listFlowLogs", custom)
    fl = out["items"][0]
    assert fl["enable"] and fl["aggregationInterval"] == "INTERVAL_30_SEC" and fl["flowSampling"] == 0.25


def test_vpc_peering_goes_active_when_both_sides_connect(c, nets):
    auto, custom = nets
    st, bad = c.sub("vpc", "addPeering", auto, {"name": "self", "peerNetwork": auto})
    assert st == 400
    st, out = c.sub("vpc", "addPeering", custom, {"name": "to-auto", "peerNetwork": auto})
    assert st == 200 and out["state"] == "INACTIVE"
    st, out = c.sub("vpc", "addPeering", auto, {"name": "to-custom", "peerNetwork": custom})
    assert st == 200 and out["state"] == "ACTIVE"
    st, out = c.sub("vpc", "listPeerings", custom)
    assert out["items"][0]["state"] == "ACTIVE"
    st, _ = c.sub("vpc", "removePeering", auto, {"name": "to-custom"})
    st, out = c.sub("vpc", "listPeerings", custom)
    assert out["items"][0]["state"] == "INACTIVE"
    c.sub("vpc", "removePeering", custom, {"name": "to-auto"})
