"""GCP hierarchy, groups, Principal Access Boundary and opaque `ya29.` tokens through the REAL appliance app and the REAL stores
(server.py middleware + gcp_rm Resource Manager store + GCP IAM core store + IAM Credentials core), like test_iam_mesh_gcp_e2e.py.

What the real API serves (folders, Cloud Identity groups + memberships, PAB policies + bindings, service accounts, generateAccessToken)
is driven through it; what it does not serve in this build (an allow policy ON a folder: `/v3/folders/{id}:setIamPolicy` is unknown) is
written straight into the real IAM store slot. The default project has no Resource Manager record (POST /v3/projects is not served),
so its parent chain is given either as a store record (written into the real gcp_rm store) or as the per-space config
(`gcp_iam_hierarchy`), the two ways the adapter supports.
Re-runnable: unique names; every store entry, folder, group, PAB policy and setting is removed afterwards."""
import base64, json, os, sys, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def env():
    from fastapi.testclient import TestClient
    import server
    from core import gcp_project, appliance_stores, app_context
    c = TestClient(server.app)
    pid = gcp_project.DEFAULT_PROJECT_ID
    c.put("/api/iam/gcp/enforcement", json={"space": "off"})
    uid = uuid.uuid4().hex[:8]
    stores = appliance_stores.net_new_core_stores()
    org = c.get("/v3/organizations:search").json()["organizations"][0]["name"]
    folder = c.post("/v3/folders", json={"parent": org, "displayName": "iam-e2e-" + uid}).json()["response"]["name"]
    before = c.post(f"/v1/projects/{pid}:getIamPolicy", json={}).json()
    e = {"c": c, "project": pid, "uid": uid, "org": org, "folder": folder, "bucket": "iam-h-" + uid,
         "rm": stores["gcp_rm"], "iam": stores["gcp_iam"], "ctx": app_context, "cleanup": []}
    assert c.post(f"/storage/v1/b?project={pid}", json={"name": e["bucket"]}).status_code == 200
    yield e
    c.put("/api/iam/gcp/enforcement", json={"space": "off"})
    for fn in reversed(e["cleanup"]):
        try:
            fn()
        except Exception:
            pass
    e["rm"].projects.pop(pid, None)
    e["iam"].gcp_iam_policies.pop(folder, None)
    c.delete(f"/storage/v1/b/{e['bucket']}")
    c.delete(f"/v3/{folder}")
    c.post(f"/v1/projects/{pid}:setIamPolicy", json={"policy": {"bindings": before.get("bindings", [])}})


def _as(who):
    return {"X-Cloudlearn-Principal": who}


def _holder(e):
    sp = e["ctx"].gcp_active_space_dict()
    return sp if sp else e["ctx"].STATE


def _project_record(e, parent):
    e["rm"].projects[e["project"]] = {"name": "projects/123456789012", "projectId": e["project"], "state": "ACTIVE", "parent": parent}


def _bind_project(e, role, member):
    c, pid = e["c"], e["project"]
    cur = c.post(f"/v1/projects/{pid}:getIamPolicy", json={}).json()
    binds = [b for b in cur.get("bindings", []) if member not in b.get("members", [])]
    binds.append({"role": role, "members": [member]})
    r = c.post(f"/v1/projects/{pid}:setIamPolicy", json={"policy": {"bindings": binds}})
    assert r.status_code == 200, r.text


def test_folder_binding_is_inherited_through_the_store_chain_and_the_config_chain(env):
    c, b, uid = env["c"], env["bucket"], env["uid"]
    viewer, stranger = f"user:folder-viewer-{uid}@example.com", f"user:stranger-{uid}@example.com"
    lst = f"/storage/v1/b/{b}/o"
    env["iam"].gcp_iam_policies[env["folder"]] = {"bindings": [{"role": "roles/storage.objectViewer", "members": [viewer]}]}
    assert c.put("/api/iam/gcp/enforcement", json={"space": "enforce"}).status_code == 200

    # no parent chain known (no project record, no config): the folder binding does not reach the project
    assert c.get(lst, headers=_as(viewer)).status_code == 403

    # chain from the Resource Manager store record: project -> folder -> organization
    _project_record(env, {"type": "folder", "id": env["folder"].split("/")[1]})
    assert c.get(lst, headers=_as(viewer)).status_code == 200
    assert c.get(lst, headers=_as(stranger)).status_code == 403
    d = c.delete(f"/storage/v1/b/{b}/o/x-{uid}", headers=_as(viewer))        # objectViewer has no objects.delete
    assert d.status_code == 403 and d.json()["error"]["status"] == "PERMISSION_DENIED"
    env["rm"].projects.pop(env["project"], None)
    assert c.get(lst, headers=_as(viewer)).status_code == 403

    # same chain from the per-space config (the store has no project record)
    h = _holder(env)
    h["gcp_iam_hierarchy"] = {"parents": {f"projects/{env['project']}": env["folder"]}}
    try:
        assert c.get(lst, headers=_as(viewer)).status_code == 200
        assert c.get(lst, headers=_as(stranger)).status_code == 403
    finally:
        h.pop("gcp_iam_hierarchy", None)
    assert c.get(lst, headers=_as(viewer)).status_code == 403


def test_group_membership_from_the_cloud_identity_store_feeds_the_evaluation(env):
    c, b, uid = env["c"], env["bucket"], env["uid"]
    gmail, member, outsider = f"eng-{uid}@example.com", f"user:grp-member-{uid}@example.com", f"user:grp-out-{uid}@example.com"
    lst = f"/storage/v1/b/{b}/o"
    g = c.post("/v1/groups", json={"groupKey": {"id": gmail}}).json()["name"]
    env["cleanup"].append(lambda: c.delete(f"/v1/{g}"))
    assert c.post(f"/v1/{g}/memberships", json={"preferredMemberKey": {"id": member.split(":", 1)[1]}}).status_code == 200
    _bind_project(env, "roles/storage.objectViewer", "group:" + gmail)
    assert c.put("/api/iam/gcp/enforcement", json={"space": "enforce"}).status_code == 200
    assert c.get(lst, headers=_as(member)).status_code == 200
    assert c.get(lst, headers=_as(outsider)).status_code == 403
    # nested: the group becomes a member of a bigger group that holds the binding
    parent_mail = f"all-{uid}@example.com"
    pg = c.post("/v1/groups", json={"groupKey": {"id": parent_mail}}).json()["name"]
    env["cleanup"].append(lambda: c.delete(f"/v1/{pg}"))
    assert c.post(f"/v1/{pg}/memberships", json={"preferredMemberKey": {"id": gmail}}).status_code == 200
    _bind_project(env, "roles/storage.objectViewer", "group:" + parent_mail)
    c.delete(f"/v1/{g}/memberships/" + c.get(f"/v1/{g}/memberships").json()["memberships"][0]["name"].rsplit("/", 1)[1])
    assert c.get(lst, headers=_as(member)).status_code == 403            # membership removed -> access gone


def test_principal_access_boundary_narrows_an_allow_binding(env):
    c, b, uid, org = env["c"], env["bucket"], env["uid"], env["org"]
    who = f"user:pab-{uid}@example.com"
    lst = f"/storage/v1/b/{b}/o"
    _bind_project(env, "roles/storage.objectViewer", who)
    assert c.put("/api/iam/gcp/enforcement", json={"space": "enforce"}).status_code == 200
    assert c.get(lst, headers=_as(who)).status_code == 200
    pol = f"{org}/locations/global/principalAccessBoundaryPolicies/pab-{uid}"
    r = c.post(f"/v3/{org}/locations/global/principalAccessBoundaryPolicies?principalAccessBoundaryPolicyId=pab-{uid}",
               json={"details": {"rules": [{"resources": ["//cloudresourcemanager.googleapis.com/projects/some-other-project"], "effect": "ALLOW"}]}})
    assert r.status_code == 200, r.text
    env["cleanup"].append(lambda: c.delete(f"/v3/{pol}"))
    r = c.post(f"/v3/{org}/locations/global/policyBindings?policyBindingId=pab-{uid}",
               json={"policy": pol, "target": {"principal": "principal://goog/subject/" + who.split(":", 1)[1]}})
    assert r.status_code == 200, r.text
    d = c.get(lst, headers=_as(who))
    assert d.status_code == 403 and d.json()["error"]["status"] == "PERMISSION_DENIED"
    recs = c.get("/api/iam/gcp/audit?limit=5").json()["records"]
    assert any(x["principal"] == who and x["reason"] == "explicit_deny" for x in recs)
    # widen the boundary to this project: access returns
    c.delete(f"/v3/{pol}")
    r = c.post(f"/v3/{org}/locations/global/principalAccessBoundaryPolicies?principalAccessBoundaryPolicyId=pab-{uid}",
               json={"details": {"rules": [{"resources": [f"//cloudresourcemanager.googleapis.com/projects/{env['project']}"], "effect": "ALLOW"}]}})
    assert r.status_code == 200
    r = c.post(f"/v3/{org}/locations/global/policyBindings?policyBindingId=pab-{uid}-2",
               json={"policy": pol, "target": {"principal": "principal://goog/subject/" + who.split(":", 1)[1]}})
    assert r.status_code == 200
    assert c.get(lst, headers=_as(who)).status_code == 200


def test_opaque_access_token_from_iamcredentials_acts_as_its_service_account(env):
    c, b, uid, pid = env["c"], env["bucket"], env["uid"], env["project"]
    sa_a, sa_b = f"tok-a-{uid}@{pid}.iam.gserviceaccount.com", f"tok-b-{uid}@{pid}.iam.gserviceaccount.com"
    for n in (f"tok-a-{uid}", f"tok-b-{uid}"):
        r = c.post(f"/v1/projects/{pid}/serviceAccounts", json={"accountId": n, "serviceAccount": {"displayName": n}})
        assert r.status_code == 200, r.text
        env["cleanup"].append(lambda n=n: c.delete(f"/v1/projects/{pid}/serviceAccounts/{n}@{pid}.iam.gserviceaccount.com"))
    _bind_project(env, "roles/storage.objectViewer", "serviceAccount:" + sa_a)
    toks = {}
    for sa in (sa_a, sa_b):
        r = c.post(f"/v1/projects/-/serviceAccounts/{sa}:generateAccessToken", json={"scope": ["https://www.googleapis.com/auth/cloud-platform"]})
        assert r.status_code == 200, r.text
        toks[sa] = r.json()["accessToken"]
        assert toks[sa].startswith("ya29.")
    lst = f"/storage/v1/b/{b}/o"
    assert c.put("/api/iam/gcp/enforcement", json={"space": "enforce"}).status_code == 200
    assert c.get(lst, headers={"Authorization": "Bearer " + toks[sa_a]}).status_code == 200
    d = c.get(lst, headers={"Authorization": "Bearer " + toks[sa_b]})           # a different service account with no binding
    assert d.status_code == 403 and d.json()["error"]["status"] == "PERMISSION_DENIED"
    recs = c.get("/api/iam/gcp/audit?limit=10").json()["records"]
    assert any(x["principal"] == "serviceAccount:" + sa_b and x["decision"] == "deny" for x in recs)
    # a ya29 token the simulator never issued carries no identity: the project owner (root), as before
    assert c.get(lst, headers={"Authorization": "Bearer ya29.never-issued"}).status_code == 200
