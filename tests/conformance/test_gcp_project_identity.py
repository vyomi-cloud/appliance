"""GCP project identity: one project per space, reachable by ID or number.

Pure checks of core/gcp_project (the seam the appliance middleware and Nano's
AwsWireRouter both use) plus the Nano router end to end: Cloud Resource Manager
lists the project, the number and the legacy ids land in the same store as the
ID, and an unknown project gets the real API's error. Runs on host CPython with
PYTHONPATH=wasm/core (the vendored copies Nano loads).

    PYTHONPATH=wasm/core:. pytest -q tests/conformance/test_gcp_project_identity.py
"""
import json

try:
    from core import gcp_project as gp
    from core import nano_persist
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # flat wasm/core layout
    import gcp_project as gp  # type: ignore
    import nano_persist  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore

P = {"projectId": "vyomi-project", "projectNumber": "123456789012", "name": "gcp-default", "createTime": ""}
JSON = {"content-type": "application/json"}


def test_project_id_rules():
    assert gp.valid_project_id("vyomi-project") and gp.valid_project_id("nano-project")
    for bad in ("123456789012", "demo", "Vyomi-project", "1abcdef", "abcdef-", "a" * 31):
        assert not gp.valid_project_id(bad), bad


def test_resolve_id_number_legacy_unknown():
    for v in ("vyomi-project", "123456789012", "projects/123456789012", "cloudlearn", "demo", "gcp-dev", ""):
        assert gp.resolve(v, P) == "vyomi-project", v
    assert gp.resolve("someone-elses-project", P) == ""


def test_normalize_path_and_query():
    path, q, err = gp.normalize_request("/v1/projects/123456789012/topics/t", "", "GET", P)
    assert err is None and path == "/v1/projects/vyomi-project/topics/t"
    path, q, err = gp.normalize_request("/compute/v1/projects/gcp-dev/zones/z/instances", "", "GET", P)
    assert path == "/compute/v1/projects/vyomi-project/zones/z/instances"
    _, q, err = gp.normalize_request("/storage/v1/b", "project=123456789012&alt=json", "GET", P)
    assert err is None and "project=vyomi-project" in q and "alt=json" in q
    _, q, _ = gp.normalize_request("/v3/projects/123456789012/timeSeries", {"parent": "projects/demo"}, "GET", P)
    assert q == {"parent": "projects/vyomi-project"}
    # wildcards, public image projects and storage object paths are left alone
    for path in ("/v1/projects/-/serviceAccounts/a@b.iam.gserviceaccount.com:signBlob",
                 "/compute/v1/projects/debian-cloud/global/images/family/debian-12",
                 "/storage/v1/b/bkt/o/projects/whatever"):
        assert gp.normalize_request(path, "", "GET", P) == (path, "", None)
    # service-account emails of the old project move with it
    path, _, _ = gp.normalize_request("/v1/projects/demo/serviceAccounts/svc@demo.iam.gserviceaccount.com", "", "GET", P)
    assert path == "/v1/projects/vyomi-project/serviceAccounts/svc@vyomi-project.iam.gserviceaccount.com"


def test_unknown_project_errors_match_the_real_apis():
    cases = {
        ("/compute/v1/projects/nope-proj/zones/z/instances", ""): (404, "was not found"),
        ("/v1/projects/nope-proj/topics", ""): (404, "Requested project not found"),
        ("/v1/projects/nope-proj/secrets", ""): (403, "secretmanager.secrets.list"),
        ("/v1/projects/nope-proj", ""): (403, "The caller does not have permission"),
        ("/storage/v1/b", "project=nope-proj"): (403, "storage.buckets.list"),
        ("/v1/projects/nope-proj/locations/us/keyRings", ""): (403, "Permission denied on resource project nope-proj"),
    }
    for (path, query), (code, text) in cases.items():
        _, _, err = gp.normalize_request(path, query, "GET", P)
        assert err and err[0] == code and text in json.dumps(err[1]), path


def test_rewrite_body_and_tree():
    body = json.dumps({"topic": "projects/123456789012/topics/t", "project": "gcp-dev",
                       "member": "serviceAccount:svc@demo.iam.gserviceaccount.com", "data": "demo"}).encode()
    out = json.loads(gp.rewrite_body(body, P))
    assert out == {"topic": "projects/vyomi-project/topics/t", "project": "vyomi-project",
                   "member": "serviceAccount:svc@vyomi-project.iam.gserviceaccount.com", "data": "demo"}
    tree = {"topics": {"projects/demo/topics/a": {"name": "projects/demo/topics/a", "project": "demo"}},
            "buckets": {"demo": {"name": "demo", "project": "123456789012"}}}
    gp.rewrite_tree(tree, {"demo", "123456789012"}, "vyomi-project")
    assert tree == {"topics": {"projects/vyomi-project/topics/a": {"name": "projects/vyomi-project/topics/a",
                                                                   "project": "vyomi-project"}},
                    "buckets": {"demo": {"name": "demo", "project": "vyomi-project"}}}


def _j(r):
    return json.loads(r["body"] or b"{}")


def test_nano_router_resource_manager():
    R = AwsWireRouter()
    pid, num = gp.NANO_PROJECT["projectId"], gp.NANO_PROJECT["projectNumber"]
    lst = R.handle("GET", "/v1/projects", {"filter": "lifecycleState:ACTIVE"}, {}, b"")
    assert lst["status"] == 200 and [p["projectId"] for p in _j(lst)["projects"]] == [pid]
    for ref in (pid, num):
        got = R.handle("GET", f"/v1/projects/{ref}", {}, {}, b"")
        assert got["status"] == 200 and _j(got)["projectNumber"] == num
        v3 = R.handle("GET", f"/v3/projects/{ref}", {}, {}, b"")
        assert v3["status"] == 200 and _j(v3)["name"] == f"projects/{num}" and _j(v3)["projectId"] == pid
    assert R.handle("GET", "/v1/projects/nope-proj", {}, {}, b"")["status"] == 403
    assert [p["projectId"] for p in _j(R.handle("GET", "/v3/projects:search", {}, {}, b""))["projects"]] == [pid]


def test_nano_router_one_store_for_id_number_and_legacy():
    R = AwsWireRouter()
    pid, num = gp.NANO_PROJECT["projectId"], gp.NANO_PROJECT["projectNumber"]
    assert R.handle("PUT", f"/v1/projects/{num}/topics/by-number", {}, JSON, b"{}")["status"] == 200
    assert R.handle("PUT", "/v1/projects/demo/topics/by-legacy", {}, JSON, b"{}")["status"] == 200
    names = {t["name"] for t in _j(R.handle("GET", f"/v1/projects/{pid}/topics", {}, {}, b""))["topics"]}
    assert {f"projects/{pid}/topics/by-number", f"projects/{pid}/topics/by-legacy"} <= names
    R.handle("PUT", f"/v1/projects/{pid}/subscriptions/s1", {}, JSON,
             json.dumps({"topic": f"projects/{num}/topics/by-number"}).encode())
    sub = _j(R.handle("GET", f"/v1/projects/{num}/subscriptions/s1", {}, {}, b""))
    assert sub.get("topic") == f"projects/{pid}/topics/by-number"
    miss = R.handle("GET", "/v1/projects/nope-proj/topics", {}, {}, b"")
    assert miss["status"] == 404 and "Requested project not found" in miss["body"].decode()
    assert R.handle("GET", "/storage/v1/b", {"project": "nope-proj"}, {}, b"")["status"] == 403


def test_nano_snapshot_written_under_old_project_is_migrated():
    R = AwsWireRouter()
    old = AwsWireRouter()
    old.gcp_project = {**gp.NANO_PROJECT, "projectId": "demo-old-proj"}   # what an older build stored
    old.handle("PUT", "/v1/projects/demo-old-proj/topics/legacy-topic", {}, JSON, b"{}")
    snap = json.loads(json.dumps(nano_persist.capture(old)).replace("demo-old-proj", "demo"))
    nano_persist.restore(R, snap)
    names = {t["name"] for t in _j(R.handle("GET", "/v1/projects/nano-project/topics", {}, {}, b""))["topics"]}
    assert "projects/nano-project/topics/legacy-topic" in names


def test_appliance_migration_moves_old_project_data(monkeypatch):
    """migrate_state on a pre-upgrade GCP space: ids assigned (number = active_account),
    every resource stored under the number / legacy ids lands on the project ID."""
    import types
    space = {"space_id": "space-gcp-default", "name": "gcp-default", "provider": "gcp",
             "active_account": "123456789012", "service_states": {
                 "gcp_storage": {"buckets": {"demo": {"name": "demo", "project": "123456789012"},
                                             "b2": {"name": "b2", "project": "gcp-dev"}}},
                 "gcp_pubsub": {"topics": {"t": {"name": "projects/123456789012/topics/t"}}},
                 "gcp_iam": {"service_accounts": {"cloudlearn": {"svc": {"email": "svc@cloudlearn.iam.gserviceaccount.com"}},
                                                  "123456789012": {"other": {"email": "o@123456789012.iam.gserviceaccount.com"}}},
                             "policies": {"cloudlearn": {"bindings": [{"role": "roles/viewer"}]}}},
                 "apigateway": {"cloudlearn": {"apis": {"a1": {"name": "a1"}}}},
                 "s3": {"buckets": {"x": {"project": "cloudlearn"}}}}}   # not GCP state: untouched
    ss = {"spaces": {"space-gcp-default": space}, "active_space_id": "space-gcp-default"}
    fake = types.SimpleNamespace(spaces_state=lambda: ss, active_tenant_id=lambda: "default",
                                 DEFAULT_TENANT_ID="default",
                                 _GCP_IAM_NESTED_COLLECTIONS=["service_accounts", "policies", "users", "groups", "roles"])
    monkeypatch.setattr(gp, "_ctx", lambda: fake)
    assert gp.migrate_state() == 1 and gp.migrate_state() == 0          # idempotent
    assert (space["gcp_project_id"], space["gcp_project_number"]) == ("vyomi-project", "123456789012")
    st = space["service_states"]
    assert {b["project"] for b in st["gcp_storage"]["buckets"].values()} == {"vyomi-project"}
    assert "demo" in st["gcp_storage"]["buckets"]                          # resource names untouched
    assert list(st["gcp_pubsub"]["topics"]["t"].values()) == ["projects/vyomi-project/topics/t"]
    sas = st["gcp_iam"]["service_accounts"]
    assert list(sas) == ["vyomi-project"] and set(sas["vyomi-project"]) == {"svc", "other"}
    assert sas["vyomi-project"]["svc"]["email"] == "svc@vyomi-project.iam.gserviceaccount.com"
    assert list(st["gcp_iam"]["policies"]) == ["vyomi-project"]
    assert list(st["apigateway"]) == ["vyomi-project"]
    assert st["s3"]["buckets"]["x"]["project"] == "cloudlearn"
    assert gp.current()["projectId"] == "vyomi-project" and gp.resolve("123456789012") == "vyomi-project"
