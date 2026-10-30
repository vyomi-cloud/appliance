"""v4 C0d — behaviours the shared Firestore / Compute Engine cores gained when the offline
appliance moved onto them (core/gcp_firestore_core.py, core/gcp_compute_core.py,
core/gcp_compute_instances_core.py).

The retired offline handlers (providers/gcp_services.py, server.py api_gcp_compute_*,
api_gcp_vpc_*) served what the real clients send; the cores now do too: the Compute REST
`/instances/{i}/start` custom-method spelling, `operations/{op}/wait`, the
setDeletionProtection query parameter, the `/compute/beta` prefix, uint64 zone / region /
machine-type ids (gcloud's apitools rejects anything else), four-octet synthetic IPs;
Firestore `updateMask.fieldPaths` + `currentDocument` preconditions on PATCH, `:commit`
(ordered, all-or-none, with field transforms), `:batchGet`, `:beginTransaction` /
`:rollback` and `enum-encoding=int` query operators — what google-cloud-firestore's REST
transport and its high-level Client send. Each is pinned on the in-memory substrate AND
the file-backed (sqlite) substrate (a fresh store instance must see the state).

The last section exercises the appliance upgrade path (core/appliance_stores.py adopting
the pre-v4 gcp_firestore_state / FirestoreEngine SQLite documents / gcp_vpc_state /
gcp_compute_state, once per space) — host only, skipped where the appliance modules
don't import.

Run:  PYTHONPATH=. python3 tests/conformance/test_c0d_legacy_parity_core.py
"""
import json
import os
import tempfile

from core import gcp_compute_core as gcc
from core import gcp_compute_instances_core as gci
from core import gcp_firestore_core as fc
from core.gcp_firestore_core import FirestoreStore
from core.persistent_store import PersistentFirestoreStore, SqliteStateBackend, _PersistentMixin

P = "c0d"
Z = "us-central1-a"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body or b"null")


class PersistentVpcStore(_PersistentMixin, gcc.ComputeStore):
    _STATE_ATTRS = ("networks", "subnetworks", "firewalls", "routes", "addresses", "seq")

    def __init__(self, backend, store_id="vpc"):
        gcc.ComputeStore.__init__(self)
        self._pinit(backend, store_id)


class PersistentVmStore(_PersistentMixin, gci.ComputeStore):
    _STATE_ATTRS = ("instances", "disks", "images", "snapshots", "machine_images", "instance_templates",
                    "instance_groups", "health_checks", "operations", "project_metadata", "seq")

    def __init__(self, backend, store_id="vm"):
        gci.ComputeStore.__init__(self)
        self._pinit(backend, store_id)


# ── Firestore ───────────────────────────────────────────────────────────────
def firestore(make, label):
    st = make()
    D = f"/v1/projects/{P}/databases/(default)/documents"
    base = f"projects/{P}/databases/(default)/documents"

    def fs(m, path, q=None, body=None):
        return fc.dispatch(st, m, D + path, q or {}, {}, json.dumps(body).encode() if body is not None else b"")

    fs("POST", "/users", {"documentId": "a"}, {"fields": {"n": {"integerValue": "1"}, "s": {"stringValue": "x"}}})
    # updateMask.fieldPaths: only named fields change; a masked field absent from the body is removed
    r = fs("PATCH", "/users/a", {"updateMask.fieldPaths": ["n", "gone"]}, {"fields": {"n": {"integerValue": "2"}}})
    _check(f"[{label}] PATCH updateMask merges", _j(r)["fields"] == {"n": {"integerValue": "2"}, "s": {"stringValue": "x"}}, _j(r))
    r = fs("PATCH", "/users/a", {"updateMask.fieldPaths": "s"}, {"fields": {}})
    _check(f"[{label}] PATCH updateMask removes a masked, absent field", "s" not in _j(r)["fields"])
    r = fs("PATCH", "/users/nope", {"currentDocument.exists": "true"}, {"fields": {}})
    _check(f"[{label}] PATCH currentDocument.exists=true on a missing doc → 404", r.status == 404)
    r = fs("PATCH", "/users/a", {"currentDocument.exists": "false"}, {"fields": {}})
    _check(f"[{label}] PATCH currentDocument.exists=false on an existing doc → 409", r.status == 409)

    # :commit — ordered, all-or-none, transforms see earlier writes of the same commit
    name = f"{base}/users/b"
    r = fs("POST", ":commit", body={"writes": [
        {"update": {"name": name, "fields": {"c": {"integerValue": "1"}, "t": {"arrayValue": {"values": [{"stringValue": "a"}]}}}},
         "currentDocument": {"exists": False}},
        {"transform": {"document": name, "fieldTransforms": [
            {"fieldPath": "c", "increment": {"integerValue": "4"}},
            {"fieldPath": "t", "appendMissingElements": {"values": [{"stringValue": "a"}, {"stringValue": "b"}]}},
            {"fieldPath": "ts", "setToServerValue": 1}]}}]})
    _check(f"[{label}] :commit applies writes in order", r.status == 200 and len(_j(r)["writeResults"]) == 2, _j(r))
    got = _j(fs("GET", "/users/b"))["fields"]
    _check(f"[{label}] :commit increment / arrayUnion / server timestamp (int enum)",
           got["c"] == {"integerValue": "5"} and len(got["t"]["arrayValue"]["values"]) == 2 and "timestampValue" in got["ts"], got)
    r = fs("POST", ":commit", body={"writes": [
        {"delete": f"{base}/users/a"},
        {"update": {"name": name, "fields": {}}, "currentDocument": {"exists": False}}]})
    _check(f"[{label}] :commit is all-or-none (failed precondition → nothing applied)",
           r.status == 409 and fs("GET", "/users/a").status == 200)
    r = fs("POST", ":commit", body={"writes": [{"update": {"name": name, "fields": {"z": {"nullValue": None}}},
                                                 "updateMask": {}}]})
    _check(f"[{label}] :commit with an empty updateMask keeps the fields",
           set(_j(fs("GET", "/users/b"))["fields"]) == {"c", "t", "ts"})
    # :batchGet — found / missing, in request order
    got = _j(fs("POST", ":batchGet", body={"documents": [name, f"{base}/users/zz"]}))
    _check(f"[{label}] :batchGet found + missing", "found" in got[0] and got[1]["missing"].endswith("/users/zz"))
    _check(f"[{label}] :beginTransaction / :rollback",
           "transaction" in _j(fs("POST", ":beginTransaction", body={})) and fs("POST", ":rollback", body={}).status == 200)
    # enum-encoding=int operators + direction
    rows = _j(fs("POST", ":runQuery", body={"structuredQuery": {
        "from": [{"collectionId": "users"}],
        "where": {"compositeFilter": {"op": 1, "filters": [
            {"fieldFilter": {"field": {"fieldPath": "c"}, "op": 4, "value": {"integerValue": "5"}}},
            {"unaryFilter": {"field": {"fieldPath": "c"}, "op": 5}}]}},
        "orderBy": [{"field": {"fieldPath": "c"}, "direction": 2}]}}))
    _check(f"[{label}] :runQuery numeric operators", [x["document"]["name"].rsplit("/", 1)[-1] for x in rows if "document" in x] == ["b"], rows)
    if label == "sqlite":
        st2 = make(reload=True)
        _check(f"[{label}] a fresh store sees the committed document",
               _j(fc.dispatch(st2, "GET", D + "/users/b", {}, {}, b""))["fields"]["c"] == {"integerValue": "5"})


# ── Compute Engine: VMs ─────────────────────────────────────────────────────
def compute_vm(make, label):
    st = make()
    C = f"/compute/v1/projects/{P}"

    def cp(m, path, q=None, body=None):
        return gci.dispatch(st, m, C + path, q or {}, {}, json.dumps(body).encode() if body is not None else b"")

    r = cp("POST", f"/zones/{Z}/instances", body={"name": "vm", "machineType": f"zones/{Z}/machineTypes/e2-small",
                                                  "disks": [{"boot": True, "initializeParams": {"diskSizeGb": "10"}}]})
    _check(f"[{label}] insert", r.status == 200, _j(r))
    ip = _j(cp("GET", f"/zones/{Z}/instances/vm"))["networkInterfaces"][0]
    _check(f"[{label}] synthetic IPs have four octets",
           ip["networkIP"].count(".") == 3 and ip["accessConfigs"][0]["natIP"].count(".") == 3, ip)
    # the real REST spelling of custom methods (pre-v4 routes served it; gcloud / google-cloud-compute send it)
    op = _j(cp("POST", f"/zones/{Z}/instances/vm/stop"))
    _check(f"[{label}] instances/{{i}}/stop", _j(cp("GET", f"/zones/{Z}/instances/vm"))["status"] == "TERMINATED")
    _check(f"[{label}] operations/{{op}}/wait", _j(cp("POST", f"/zones/{Z}/operations/{op['name']}/wait"))["status"] == "DONE")
    cp("POST", f"/zones/{Z}/instances/vm:start")
    _check(f"[{label}] instances/{{i}}:start still accepted", _j(cp("GET", f"/zones/{Z}/instances/vm"))["status"] == "RUNNING")
    cp("POST", f"/zones/{Z}/instances/vm/setDeletionProtection", {"deletionProtection": "true"})
    _check(f"[{label}] setDeletionProtection (query param) blocks delete", cp("DELETE", f"/zones/{Z}/instances/vm").status == 400)
    cp("POST", f"/zones/{Z}/instances/vm/setDeletionProtection", {"deletionProtection": "false"})
    zone = _j(cp("GET", f"/zones/{Z}"))
    mt = _j(cp("GET", f"/zones/{Z}/machineTypes/e2-small"))
    _check(f"[{label}] zone / machine-type ids are uint64", zone["id"].isdigit() and mt["id"].isdigit(), (zone["id"], mt["id"]))
    _check(f"[{label}] regional operations + unknown-scope VPC operations report DONE",
           cp("GET", "/regions/us-central1/operations").status == 200
           and _j(cp("POST", "/global/operations/operation-1-abc/wait"))["status"] == "DONE")
    if label == "sqlite":
        st2 = make(reload=True)
        _check(f"[{label}] a fresh store sees the instance",
               _j(gci.dispatch(st2, "GET", C + f"/zones/{Z}/instances/vm", {}, {}, b""))["status"] == "RUNNING")
    _check(f"[{label}] delete", cp("DELETE", f"/zones/{Z}/instances/vm").status == 200)


# ── Compute Engine: VPC ─────────────────────────────────────────────────────
def compute_vpc(make, label):
    st = make()

    def cp(m, path, body=None, ver="v1"):
        return gcc.dispatch(st, m, f"/compute/{ver}/projects/{P}" + path, {}, {}, json.dumps(body).encode() if body is not None else b"")

    _check(f"[{label}] /compute/beta prefix", cp("POST", "/global/networks", {"name": "n"}, ver="beta").status == 200)
    cp("POST", "/regions/us-central1/subnetworks", {"name": "s", "network": f"projects/{P}/global/networks/n", "ipCidrRange": "10.1.0.0/24"})
    cp("POST", "/regions/us-central1/addresses", {"name": "ip"})
    agg = _j(cp("GET", "/aggregated/subnetworks"))["items"]
    _check(f"[{label}] aggregated subnetworks", [s["name"] for s in agg["regions/us-central1"]["subnetworks"]] == ["s"])
    _check(f"[{label}] aggregated addresses", _j(cp("GET", "/aggregated/addresses"))["items"]["regions/us-central1"]["addresses"])
    if label == "sqlite":
        st2 = make(reload=True)
        _check(f"[{label}] a fresh store sees the subnet",
               gcc.dispatch(st2, "GET", f"/compute/v1/projects/{P}/regions/us-central1/subnetworks/s", {}, {}, b"").status == 200)


# ── appliance upgrade path (host only) ───────────────────────────────────────
class _Proxy:
    def __init__(self):
        self.d = {}

    def _target(self):
        return self.d


def upgrade_path():
    try:
        from core import app_context as ctx
        from core import appliance_stores as aps
        from core.vyomi_platform import FirestoreEngine
    except Exception as exc:   # pragma: no cover - Pyodide / no appliance deps
        print(f"  skip upgrade path ({exc})")
        return
    tmp = tempfile.mkdtemp(prefix="c0d-up-")

    class _Kernel:
        def get_active_space(self):
            return {"space_id": "sp-1"}

    class _DbStore:
        db_path = os.path.join(tmp, "legacy.sqlite3")

    eng = FirestoreEngine(_DbStore(), _Kernel())
    eng.create_document(P, "(default)", "users", {"name": {"stringValue": "Ada"}}, "ada")
    eng.create_document(P, "legacydb", "orders/o1/lines", {"q": {"integerValue": "2"}}, "l1")

    class _Platform:
        firestore = eng

    legacy_fs = {"databases": {"legacydb": {"locationId": "us-east1", "createTime": "2025-01-01T00:00:00Z"}},
                 "indexes": {"k": {"project": P, "database": "(default)", "collection": "users", "name": "by-name",
                                   "fields": [{"fieldPath": "name", "order": "ASCENDING"}]}}}
    legacy_vpc = {"networks": {"lnet": {"name": "lnet", "project": P, "mtu": 1500}},
                  "subnetworks": {"lsub": {"name": "lsub", "project": P, "region": "us-east1", "network": "lnet",
                                           "ipCidrRange": "10.9.0.0/24"}},
                  "firewalls": {"lfw": {"name": "lfw", "project": P, "network": "lnet", "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}],
                                        "targetTags": ["ssh"], "sourceRanges": ["0.0.0.0/0"]}},
                  "routes": {"lrt": {"name": "lrt", "project": P, "network": "lnet", "destRange": "0.0.0.0/0", "priority": 900}}}
    legacy_vm = {"instances": {"gce-1": {"instance_id": "gce-1", "name": "lvm", "project": P, "zone": Z, "state": "stopped",
                                         "machine_type": "e2-micro", "attached_disk_names": ["lvm-boot"], "tags": ["ssh"],
                                         "private_ip": "10.1.2.3", "public_ip": "34.1.2.3", "created": "2025-02-02T00:00:00Z"},
                               "gce-2": {"instance_id": "gce-2", "name": "gone", "project": P, "zone": Z, "state": "terminated"}},
                 "disks": {"lvm-boot": {"name": "lvm-boot", "project": P, "zone": Z, "sizeGb": 12, "type": "pd-ssd"},
                           "data": {"name": "data", "project": P, "zone": Z, "sizeGb": 50}},
                 "instance_groups": {"g": {"name": "g", "project": P, "zone": Z, "instances": ["lvm"]}},
                 "images": {"img": {"name": "img", "project": P}},
                 "snapshots": {"snap": {"name": "snap", "project": P, "diskSizeGb": 12}}}
    saved = {k: getattr(ctx, k) for k in ("PLATFORM", "gcp_firestore_state", "gcp_vpc_state", "gcp_compute_state")}
    try:
        ctx.PLATFORM, ctx.gcp_firestore_state, ctx.gcp_vpc_state, ctx.gcp_compute_state = \
            _Platform(), legacy_fs, legacy_vpc, legacy_vm
        fs, vpc, vm = (aps.AppStateFirestoreStore(_Proxy()), aps.AppStateComputeVpcStore(_Proxy()),
                       aps.AppStateComputeVmStore(_Proxy()))
        fs.adopt(P), vpc.adopt(P), vm.adopt(P)
        D = f"/v1/projects/{P}/databases"
        doc = _j(fc.dispatch(fs, "GET", D + "/(default)/documents/users/ada", {}, {}, b""))
        _check("upgrade: FirestoreEngine document adopted", doc["fields"] == {"name": {"stringValue": "Ada"}}, doc)
        nested = fc.dispatch(fs, "GET", D + "/legacydb/documents/orders/o1/lines/l1", {}, {}, b"")
        _check("upgrade: nested-collection document in a second database adopted", nested.status == 200)
        db = _j(fc.dispatch(fs, "GET", D + "/legacydb", {}, {}, b""))
        _check("upgrade: database adopted with its location", db["locationId"] == "us-east1", db)
        idx = _j(fc.dispatch(fs, "GET", D + "/(default)/collectionGroups/users/indexes", {}, {}, b""))
        _check("upgrade: composite index adopted", idx["indexes"][0]["name"].endswith("/indexes/by-name"))
        C = f"/compute/v1/projects/{P}"
        sub = _j(gcc.dispatch(vpc, "GET", C + "/regions/us-east1/subnetworks/lsub", {}, {}, b""))
        _check("upgrade: subnetwork adopted under its network", sub["network"].endswith("/networks/lnet") and sub["gatewayAddress"] == "10.9.0.1", sub)
        fw = _j(gcc.dispatch(vpc, "GET", C + "/global/firewalls/lfw", {}, {}, b""))
        _check("upgrade: firewall adopted", fw["targetTags"] == ["ssh"] and fw["allowed"][0]["ports"] == ["22"])
        _check("upgrade: route adopted", _j(gcc.dispatch(vpc, "GET", C + "/global/routes/lrt", {}, {}, b""))["priority"] == 900)
        net = _j(gcc.dispatch(vpc, "GET", C + "/global/networks/lnet", {}, {}, b""))
        _check("upgrade: network lists its subnet", net["mtu"] == 1500 and net["subnetworks"][0].endswith("/subnetworks/lsub"))
        inst = vm.instances[f"projects/{P}/zones/{Z}/instances/lvm"]
        _check("upgrade: instance adopted (stopped → TERMINATED, runtime linked)",
               inst["status"] == "TERMINATED" and inst["_runtimeId"] == "gce-1" and inst["tags"]["items"] == ["ssh"], inst)
        _check("upgrade: instance boots from its pre-v4 boot disk",
               inst["disks"][0]["source"].endswith("/disks/lvm-boot") and inst["networkInterfaces"][0]["networkIP"] == "10.1.2.3")
        _check("upgrade: terminated instance not adopted", f"projects/{P}/zones/{Z}/instances/gone" not in vm.instances)
        d = _j(gci.dispatch(vm, "GET", C + f"/zones/{Z}/disks/lvm-boot", {}, {}, b""))
        _check("upgrade: disk adopted (size, type, users)", d["sizeGb"] == "12" and d["type"].endswith("/pd-ssd") and d["users"], d)
        g = _j(gci.dispatch(vm, "GET", C + f"/zones/{Z}/instanceGroups/g", {}, {}, b""))
        _check("upgrade: instance group adopted with its member", g["members"] == ["lvm"] and g["size"] == 1, g)
        _check("upgrade: image + snapshot adopted",
               gci.dispatch(vm, "GET", C + "/global/images/img", {}, {}, b"").status == 200
               and gci.dispatch(vm, "GET", C + "/global/snapshots/snap", {}, {}, b"").status == 200)
        # once per space: a record deleted after the upgrade is not resurrected
        gcc.dispatch(vpc, "DELETE", C + "/global/firewalls/lfw", {}, {}, b"")
        fc.dispatch(fs, "DELETE", D + "/(default)/documents/users/ada", {}, {}, b"")
        fs.adopt(P), vpc.adopt(P), vm.adopt(P)
        _check("upgrade: adoption runs once per space (deleted records stay deleted)",
               gcc.dispatch(vpc, "GET", C + "/global/firewalls/lfw", {}, {}, b"").status == 404
               and fc.dispatch(fs, "GET", D + "/(default)/documents/users/ada", {}, {}, b"").status == 404)
        _check("upgrade: the pre-v4 state is left untouched (opt-out still sees it)",
               "lfw" in legacy_vpc["firewalls"] and "gce-1" in legacy_vm["instances"])
    finally:
        for k, v in saved.items():
            setattr(ctx, k, v)


def _persistent(cls, sid):
    be = SqliteStateBackend(":memory:")

    def make(reload=False):
        return cls(be, store_id=sid)
    return make


def _memory(cls):
    def make(reload=False):
        return None if reload else cls()
    return make


def run() -> int:
    print("Firestore:")
    firestore(_memory(FirestoreStore), "mem")
    firestore(_persistent(PersistentFirestoreStore, "fs"), "sqlite")
    print("Compute Engine (VMs):")
    compute_vm(_memory(gci.ComputeStore), "mem")
    compute_vm(_persistent(PersistentVmStore, "vm"), "sqlite")
    print("Compute Engine (VPC):")
    compute_vpc(_memory(gcc.ComputeStore), "mem")
    compute_vpc(_persistent(PersistentVpcStore, "vpc"), "sqlite")
    print("Upgrade path (pre-v4 state → cores):")
    upgrade_path()
    print("\nC0d legacy-parity (Firestore / Compute Engine cores): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
