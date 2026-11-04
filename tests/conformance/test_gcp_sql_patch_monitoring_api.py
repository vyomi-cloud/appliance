"""Cloud SQL instances.patch (settings merge) and Cloud Monitoring groups.list /
uptimeCheckConfigs.get over the offline REST surface (covers PatchInstance, PatchSettings,
ListGroups, GetUptime)."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
try:
    PROJECT = requests.get(f"{BASE}/api/gcp/catalog", timeout=60).json()["project"]
except Exception:
    PROJECT = "vyomi-project"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


tag = uuid.uuid4().hex[:6]
sql = f"{BASE}/sql/v1beta4/projects/{PROJECT}/instances"
name = f"patch-{tag}"
r = requests.post(sql, json={"name": name, "databaseVersion": "POSTGRES_15", "region": "us-central1",
                             "settings": {"tier": "db-f1-micro"}}, timeout=60)
check("insert instance", r.status_code == 200, r.text[:160])
before = requests.get(f"{sql}/{name}", timeout=60).json()
r = requests.patch(f"{sql}/{name}", json={"settings": {"userLabels": {"env": "test"},
                   "backupConfiguration": {"enabled": True}}}, timeout=60)
check("patch returns UPDATE operation", r.status_code == 200 and r.json().get("operationType") == "UPDATE", r.text[:160])
after = requests.get(f"{sql}/{name}", timeout=60).json()
s = after.get("settings", {})
check("patched fields persisted", s.get("userLabels") == {"env": "test"} and s.get("backupConfiguration", {}).get("enabled") is True, s)
check("untouched settings preserved", s.get("tier") == "db-f1-micro", s)
check("settingsVersion bumped", int(s.get("settingsVersion", 0)) > int(before["settings"].get("settingsVersion", 0)), s)
r = requests.patch(f"{sql}/nope-{tag}", json={"settings": {}}, timeout=60)
check("patch unknown instance -> 404", r.status_code == 404, r.text[:120])
requests.delete(f"{sql}/{name}", timeout=60)

mon = f"{BASE}/v3/projects/{PROJECT}"
r = requests.post(f"{mon}/groups", json={"displayName": f"g-{tag}", "filter": 'resource.type="gce_instance"'}, timeout=60)
check("create group", r.status_code == 200, r.text[:160])
gname = r.json().get("name", "")
r = requests.get(f"{mon}/groups", timeout=60)
check("list groups contains it (field `group`)", any(g["name"] == gname for g in r.json().get("group", [])), r.text[:200])
r = requests.post(f"{mon}/uptimeCheckConfigs", json={"displayName": f"u-{tag}",
    "monitoredResource": {"type": "uptime_url", "labels": {"host": "example.com"}},
    "httpCheck": {"path": "/"}, "period": "60s", "timeout": "10s"}, timeout=60)
check("create uptime check", r.status_code == 200, r.text[:160])
uname = r.json().get("name", "")
r = requests.get(f"{BASE}/v3/{uname}", timeout=60)
check("get uptime check", r.status_code == 200 and r.json().get("name") == uname and r.json().get("displayName") == f"u-{tag}", r.text[:200])
requests.delete(f"{BASE}/v3/{uname}", timeout=60)
requests.delete(f"{BASE}/v3/{gname}", timeout=60)
sys.exit(1 if failed else 0)
