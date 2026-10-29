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
