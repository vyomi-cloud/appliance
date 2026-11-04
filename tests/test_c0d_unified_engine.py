"""v4 C0d — the offline appliance serves native Firestore and Compute Engine (VPC + VMs)
through the shared conformance cores, over ONE state shared with the classic console
paths, durably; a Compute instance's real runtime record follows the core's lifecycle.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway state file,
like tests/test_c0b_unified_engine.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0d-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

P = "c0d-proj"
Z = "us-central1-a"
CV = f"/compute/v1/projects/{P}"


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _first_route(path: str, method: str):
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "query_string": b"", "headers": []}
    for r in server.app.routes:
        m, _ = r.matches(scope)
        if m == Match.FULL:
            return r
    return None


def test_route_precedence(client):
    mod = "routes.gcp_firestore_compute_unified"
    for path, method in (("/v1/projects/p/databases", "POST"), ("/v1/projects/p/databases/(default)/documents/c/d", "GET"),
                         ("/v1/projects/p/databases/(default)/documents:commit", "POST"),
                         ("/firestore/v1/projects/p/databases", "GET"), ("/api/gcp/firestore/v1/projects/p/databases", "POST"),
                         ("/api/gcp/dynamodb/tables", "GET"),
                         (f"/compute/v1/projects/p/zones/{Z}/instances", "POST"),
                         ("/compute/v1/projects/p/aggregated/subnetworks", "GET"),
                         ("/compute/beta/projects/p/global/networks", "GET"),
                         (f"/api/gcp/compute/v1/projects/p/zones/{Z}/instances/x/start", "POST"),
                         ("/api/gcp/vpc/networks", "GET")):
        r = _first_route(path, method)
        assert r is not None and r.endpoint.__module__ == mod, (path, r and r.endpoint)
    # untouched neighbours keep their handlers
    assert _first_route("/v1/projects/p/secrets", "GET").endpoint.__name__ == "_secrets"
    assert _first_route("/api/gcp/compute/instances/i-1/connect-info", "GET").endpoint.__module__ != mod


def test_firestore_admin_and_documents_native_and_classic_share_state(client):
    db = _u("db")
    r = client.post(f"/_wire/v1/projects/{P}/databases?databaseId={db}", json={"locationId": "nam5"})
    assert r.status_code == 200, r.text                       # was 405 (the S3 catch-all) pre-C0d
    assert any(d["name"].endswith("/" + db) for d in client.get(f"/v1/projects/{P}/databases").json()["databases"])
    # classic console: body `name` creates a document, plain JSON values are typed
    base = f"/firestore/v1/projects/{P}/databases/{db}/documents"
    r = client.post(f"{base}/notes", json={"name": "n1", "fields": {"title": "hi", "n": 3}})
    assert r.status_code == 200, r.text
    native = client.get(f"/v1/projects/{P}/databases/{db}/documents/notes/n1").json()
    assert native["fields"] == {"title": {"stringValue": "hi"}, "n": {"integerValue": "3"}}
    # native write → classic root list (pre-v4 contract: every document + kind)
    client.post(f"/v1/projects/{P}/databases/{db}/documents/other?documentId=o1", json={"fields": {"x": {"booleanValue": True}}})
    root = client.get(f"/api/gcp/firestore/v1/projects/{P}/databases/{db}/documents").json()
    assert root["kind"] == "firestore#documents" and {d["name"].rsplit("/", 1)[-1] for d in root["documents"]} == {"n1", "o1"}
    # classic PATCH replaces the document (native PATCH with updateMask merges)
    client.patch(f"{base}/notes/n1", json={"fields": {"title": {"stringValue": "new"}}})
    assert client.get(f"/v1/projects/{P}/databases/{db}/documents/notes/n1").json()["fields"] == {"title": {"stringValue": "new"}}
    client.patch(f"/v1/projects/{P}/databases/{db}/documents/notes/n1?updateMask.fieldPaths=n",
                 json={"fields": {"n": {"integerValue": "9"}}})
    assert set(client.get(f"/v1/projects/{P}/databases/{db}/documents/notes/n1").json()["fields"]) == {"title", "n"}
    # :commit + :batchGet (the high-level google-cloud-firestore Client's RPCs)
    name = f"projects/{P}/databases/{db}/documents/notes/n2"
    r = client.post(f"/v1/projects/{P}/databases/{db}/documents:commit", json={"writes": [
        {"update": {"name": name, "fields": {"a": {"integerValue": "1"}}}, "currentDocument": {"exists": False}},
        {"transform": {"document": name, "fieldTransforms": [{"fieldPath": "a", "increment": {"integerValue": "4"}}]}}]})
    assert r.status_code == 200 and len(r.json()["writeResults"]) == 2, r.text
    got = client.post(f"/v1/projects/{P}/databases/{db}/documents:batchGet", json={"documents": [name, name + "x"]}).json()
    assert got[0]["found"]["fields"]["a"] == {"integerValue": "5"} and got[1]["missing"].endswith("n2x")
    # :runQuery with numeric enums (enum-encoding=int, as google-cloud-firestore's REST transport sends)
    rows = client.post(f"/v1/projects/{P}/databases/{db}/documents:runQuery", json={"structuredQuery": {
        "from": [{"collectionId": "notes"}],
        "where": {"fieldFilter": {"field": {"fieldPath": "a"}, "op": 3, "value": {"integerValue": "2"}}}}}).json()
    assert [r["document"]["name"].rsplit("/", 1)[-1] for r in rows if "document" in r] == ["n2"]
    # the /api/gcp/dynamodb alias reads the same documents
    items = client.get(f"/api/gcp/dynamodb/tables/notes/items?project={P}&database={db}").json()
    assert {d["name"].rsplit("/", 1)[-1] for d in items["documents"]} == {"n1", "n2"}
    # classic delete keeps its {done,name} shape; gone natively
    assert client.delete(f"/api/gcp/firestore/v1/projects/{P}/databases/{db}").json() == {
        "done": True, "name": f"projects/{P}/databases/{db}"}
    assert client.get(f"/v1/projects/{P}/databases/{db}").status_code == 404


def test_compute_vpc_native_and_classic_share_state(client):
    net, sub = _u("net"), _u("sub")
    assert client.post(f"/api/gcp/vpc/networks?project={P}", json={"name": net}).status_code == 200
    r = client.post(f"/_wire{CV}/regions/us-central1/subnetworks", json={"name": sub, "network": net, "ipCidrRange": "10.5.0.0/24"})
    assert r.status_code == 200, r.text
    agg = client.get(f"/_wire{CV}/aggregated/subnetworks").json()   # was 404 pre-C0d
    assert sub in [s["name"] for s in agg["items"]["regions/us-central1"]["subnetworks"]]
    assert client.post(f"/compute/beta/projects/{P}/regions/us-central1/addresses", json={"name": _u("ip")}).status_code == 200
    assert client.get(f"/_wire{CV}/aggregated/addresses").json()["items"]["regions/us-central1"]["addresses"]
    fw = _u("fw")
    client.post(f"/api/gcp/compute/v1/projects/{P}/global/firewalls",
                json={"name": fw, "network": net, "allowed": [{"IPProtocol": "tcp", "ports": ["80"]}], "targetTags": ["web"]})
    assert client.get(f"{CV}/global/firewalls/{fw}").json()["targetTags"] == ["web"]
    from routes import gcp_firestore_compute_unified as gfc
    with _gcp():                                                              # (as the console request does)
        assert any(r["name"] == fw for r in gfc.firewall_rules())             # VPC enforcement reads the core
    assert net in [n["name"] for n in client.get(f"/api/gcp/vpc/vpcs?project={P}").json()["items"]]


def test_compute_instance_lifecycle_drives_the_runtime_record(client):
    from core.app_context import gcp_compute_state
    vm = _u("vm")
    r = client.post(f"/api/gcp/compute/v1/projects/{P}/zones/{Z}/instances", json={"name": vm, "machineType": "e2-small"})
    assert r.status_code == 200, r.text                       # classic {name, machineType}: boot disk made for it
    inst = client.get(f"/_wire{CV}/zones/{Z}/instances/{vm}").json()
    assert inst["status"] == "RUNNING" and inst["disks"][0]["boot"]
    from core import appliance_stores as aps
    with _gcp():
        rid = aps.gcp_compute_vm_store().instances[f"projects/{P}/zones/{Z}/instances/{vm}"]["_runtimeId"]
        rec = gcp_compute_state["instances"][rid]
        assert rec["name"] == vm and rec["machine_type"] == "e2-small"
    # the real Compute REST spelling (`/{name}/stop`) and the console's (`:start`) both work
    assert client.post(f"{CV}/zones/{Z}/instances/{vm}/stop").status_code == 200
    assert client.get(f"{CV}/zones/{Z}/instances/{vm}").json()["status"] == "TERMINATED"
    with _gcp():
        assert gcp_compute_state["instances"][rid]["state"] == "stopped"
    assert client.post(f"{CV}/zones/{Z}/instances/{vm}:start").status_code == 200
    with _gcp():
        assert gcp_compute_state["instances"][rid]["state"] in ("pending", "running")
    client.post(f"{CV}/zones/{Z}/instances/{vm}/setTags", json={"items": ["web"]})
    with _gcp():
        assert gcp_compute_state["instances"][rid]["tags"] == ["web"]
    # gcloud polls operations.wait
    op = client.post(f"{CV}/zones/{Z}/instances/{vm}/reset").json()
    assert client.post(f"{CV}/zones/{Z}/operations/{op['name']}/wait").json()["status"] == "DONE"
    assert client.delete(f"{CV}/zones/{Z}/instances/{vm}").status_code == 200
    assert client.get(f"{CV}/zones/{Z}/instances/{vm}").status_code == 404
    with _gcp():
        assert rid not in gcp_compute_state["instances"]          # terminated + dropped


class _gcp:
    """Resolve the space-scoped proxies as a GCP request would."""

    def __enter__(self):
        from core.app_context import REQUEST_PROVIDER
        self._t = REQUEST_PROVIDER.set("gcp")

    def __exit__(self, *a):
        from core.app_context import REQUEST_PROVIDER
        REQUEST_PROVIDER.reset(self._t)


def test_state_is_durable_in_the_kernel_store(client):
    db, net, vm = _u("dur"), _u("durnet"), _u("durvm")
    client.post(f"/v1/projects/{P}/databases?databaseId={db}", json={})
    client.post(f"/v1/projects/{P}/databases/{db}/documents/c?documentId=d", json={"fields": {"v": {"stringValue": "x"}}})
    client.post(f"{CV}/global/networks", json={"name": net})
    client.post(f"{CV}/zones/{Z}/instances", json={"name": vm, "machineType": "e2-micro",
                                                   "disks": [{"boot": True, "initializeParams": {"diskSizeGb": "10"}}]})
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    found = {"docs": {}, "dbs": {}, "nets": {}, "vms": {}}
    for sp in (state.get("spaces") or {}).get("spaces", {}).values():
        ss = sp.get("service_states") or {}
        found["docs"].update((ss.get("gcp_gcp_firestore_engine") or {}).get("documents") or {})
        found["dbs"].update((ss.get("gcp_gcp_firestore_engine") or {}).get("databases") or {})
        found["nets"].update((ss.get("gcp_gcp_compute_vpc") or {}).get("networks") or {})
        found["vms"].update((ss.get("gcp_gcp_compute_vm") or {}).get("instances") or {})
    assert found["docs"][f"{db}/c/d"]["fields"] == {"v": {"stringValue": "x"}}
    assert db in found["dbs"]
    assert f"{P}/{net}" in found["nets"]
    assert found["vms"][f"projects/{P}/zones/{Z}/instances/{vm}"]["_runtimeId"]


def test_console_summary_and_inventory_read_the_cores(client):
    s = client.get(f"/api/gcp/console/summary?project={P}").json()["services"]
    assert s["gcp-compute"] >= 1 and s["gcp-vpc"] >= 1
    from routes import gcp_firestore_compute_unified as gfc
    spaces = server._spaces_state().get("spaces", {})
    inv = {}
    for sp in spaces.values():
        for k, v in gfc.inventory(sp).items():
            inv.setdefault(k, {}).update(v)
    assert inv[("vpc", "network")] and inv[("firestore", "database")]


def test_legacy_opt_out_restores_the_pre_v4_handlers(monkeypatch):
    from core import wire_ingress
    from fastapi import FastAPI
    from routes import gcp_firestore_compute_unified as gfc
    for env in ({"VYOMI_UNIFIED_INGRESS_SERVICES": "s3,dynamodb,gcs"}, {"VYOMI_LEGACY_WIRE": "1"}):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert not wire_ingress.is_unified("gcp_firestore") and not wire_ingress.is_unified("gcp_compute")
        assert gfc.register(FastAPI()) == []
        for k in env:
            monkeypatch.delenv(k)
    assert gfc.register(FastAPI()) == ["gcp_firestore", "gcp_compute"]
    # a whole appliance booted opted out serves the pre-v4 handlers on these paths
    code = ("import server\nfrom starlette.routing import Match\n"
            "def first(p, m):\n"
            "    sc={'type':'http','path':p,'method':m,'root_path':'','query_string':b'','headers':[]}\n"
            "    return next(r for r in server.app.routes if r.matches(sc)[0]==Match.FULL)\n"
            f"print(first('/compute/v1/projects/p/zones/{Z}/instances','POST').endpoint.__module__,"
            "first('/firestore/v1/projects/p/databases','GET').endpoint.__module__)\n")
    env = dict(os.environ, VYOMI_LEGACY_WIRE="1", PYTHONDONTWRITEBYTECODE="1",
               CLOUDLEARN_STATE_FILE=str(_TEST_DIR / "optout.sqlite3"),
               CLOUDLEARN_LEGACY_STATE_FILE=str(_TEST_DIR / "optout.pkl"))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300,
                         cwd=str(Path(__file__).resolve().parents[1]))
    mods = out.stdout.strip().splitlines()[-1].split()
    assert "gcp_firestore_compute_unified" not in " ".join(mods), out.stdout + out.stderr
    assert mods[0].startswith("providers.") and mods[1].startswith("providers."), mods
