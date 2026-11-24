"""Mesh end-to-end for GCP: the REAL appliance app (server.py middleware + GCP IAM core store + GCS handler) with the faithful-IAM gate.
The allow policy is set through the real GCP IAM API (projects/{p}:setIamPolicy), the deny policy through the IAM v2 deny API, enforcement
through /api/iam/gcp/enforcement, requests come from different principals (X-Cloudlearn-Principal and a bearer token with an email claim).
Re-runnable: unique bucket/principal names; the project policy and enforcement settings are restored afterwards."""
import base64, json, os, sys, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
pytest.importorskip("fastapi")

SVC = "storage.googleapis.com"


def _jwt(**claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return enc({"alg": "none", "typ": "JWT"}) + "." + enc(claims) + ".sig"


@pytest.fixture(scope="module")
def env():
    from fastapi.testclient import TestClient
    import server
    from core import gcp_project
    c = TestClient(server.app)
    pid = gcp_project.DEFAULT_PROJECT_ID
    c.put("/api/iam/gcp/enforcement", json={"space": "off"})
    before = c.post(f"/v1/projects/{pid}:getIamPolicy", json={}).json()
    uid = uuid.uuid4().hex[:8]
    e = {"c": c, "project": pid, "bucket": "iam-e2e-" + uid, "viewer": f"user:viewer-{uid}@example.com",
         "other": f"user:other-{uid}@example.com", "uid": uid}
    assert c.post(f"/storage/v1/b?project={pid}", json={"name": e["bucket"]}).status_code == 200
    yield e
    c.put("/api/iam/gcp/enforcement", json={"space": "off"})
    c.delete(f"/v2/policies/{_ap(pid)}/denypolicies/deny-{uid}")
    c.delete(f"/storage/v1/b/{e['bucket']}")
    c.post(f"/v1/projects/{pid}:setIamPolicy", json={"policy": {"bindings": before.get("bindings", [])}})


def _ap(pid):
    return f"cloudresourcemanager.googleapis.com%2Fprojects%2F{pid}"


def _as(who, **kw):
    return {"X-Cloudlearn-Principal": who, **kw}


def _put_settings(c, **doc):
    r = c.put("/api/iam/gcp/enforcement", json=doc)
    assert r.status_code == 200, r.text


def test_gcp_enforcement_through_the_real_server(env):
    c, pid, b = env["c"], env["project"], env["bucket"]
    lst, dele = f"/storage/v1/b/{b}/o", f"/storage/v1/b/{b}/o/obj-{env['uid']}"

    # allow policy through the real IAM API: the viewer gets roles/storage.objectViewer on the project
    cur = c.post(f"/v1/projects/{pid}:getIamPolicy", json={}).json()
    binds = [x for x in cur.get("bindings", []) if env["viewer"] not in x.get("members", [])]
    binds.append({"role": "roles/storage.objectViewer", "members": [env["viewer"]]})
    r = c.post(f"/v1/projects/{pid}:setIamPolicy", json={"policy": {"bindings": binds}})
    assert r.status_code == 200 and any(env["viewer"] in x["members"] for x in r.json()["bindings"]), r.text

    # off (default): nothing changes for anyone
    assert c.get(lst, headers=_as(env["other"])).status_code == 200

    _put_settings(c, space="enforce")
    assert c.get(lst, headers=_as(env["viewer"])).status_code == 200            # objectViewer includes storage.objects.list
    den = c.delete(dele, headers=_as(env["viewer"]))                              # ... but not storage.objects.delete
    assert den.status_code == 403
    err = den.json()["error"]
    assert err["code"] == 403 and err["status"] == "PERMISSION_DENIED"
    assert err["message"] == f"Permission 'storage.objects.delete' denied on resource '//{SVC}/projects/_/buckets/{b}/objects/obj-{env['uid']}' (or it may not exist)."
    no = c.get(lst, headers=_as(env["other"]))                                    # no binding at all
    assert no.status_code == 403 and no.json()["error"]["status"] == "PERMISSION_DENIED"

    # bearer token with an email claim identifies the same principal
    tok = _jwt(email=env["viewer"].split(":", 1)[1])
    assert c.get(lst, headers={"Authorization": "Bearer " + tok}).status_code == 200
    assert c.delete(dele, headers={"Authorization": "Bearer " + tok}).status_code == 403
    assert c.get(lst, headers={"Authorization": "Bearer " + _jwt(email=env["other"].split(":", 1)[1])}).status_code == 403

    # no identity at all = the project owner (root); the strict setting rejects it
    assert c.get(lst).status_code == 200
    _put_settings(c, space="enforce", unknownPrincipal="deny")
    assert c.get(lst).status_code == 403
    _put_settings(c, space="enforce")

    # audit never blocks, and records the would-deny with the same shape
    _put_settings(c, space="audit")
    assert c.get(lst, headers=_as(env["other"])).status_code == 200
    recs = c.get("/api/iam/gcp/audit?limit=20").json()["records"]
    assert any(r["action"] == "storage.objects.list" and r["mode"] == "audit" and r["decision"] == "would_deny"
               and r["principal"] == env["other"] for r in recs)

    # per-service off beats space enforce (service key = the API host the map reports)
    _put_settings(c, space="enforce", services={SVC: "off"})
    assert c.get(lst, headers=_as(env["other"])).status_code == 200
    # resource-level enforce beats service off
    _put_settings(c, space="off", services={SVC: "off"}, resources={f"//{SVC}/projects/_/buckets/{b}": "enforce"})
    assert c.get(lst, headers=_as(env["other"])).status_code == 403

    # deny policy (IAM v2) beats the allow: the viewer is explicitly denied storage.objects.list
    _put_settings(c, space="enforce")
    body = {"displayName": "deny list", "rules": [{"denyRule": {"deniedPrincipals": ["principal://goog/subject/" + env["viewer"].split(":", 1)[1]],
                                                                "deniedPermissions": [f"{SVC}/objects.list"]}}]}
    r = c.post(f"/v2/policies/{_ap(pid)}/denypolicies?policyId=deny-{env['uid']}", json=body)
    assert r.status_code == 200, r.text
    d = c.get(lst, headers=_as(env["viewer"]))
    assert d.status_code == 403 and d.json()["error"]["status"] == "PERMISSION_DENIED"
    recs = c.get("/api/iam/gcp/audit?limit=5").json()["records"]
    assert any(r["reason"] == "explicit_deny" and r["principal"] == env["viewer"] for r in recs)
    assert c.delete(f"/v2/policies/{_ap(pid)}/denypolicies/deny-{env['uid']}").status_code == 200
    assert c.get(lst, headers=_as(env["viewer"])).status_code == 200            # deny removed -> allowed again

    assert c.get("/_wire/api/iam/gcp/enforcement").status_code == 200           # the console's address works too


def test_gcp_legacy_enforce_iam_flag_still_works(env):
    """Back-compat: space['enforce_iam'] with no explicit faithful settings = space enforce, unmapped requests allowed."""
    from core import app_context
    c = env["c"]
    _put_settings(c, space="off")
    sp = app_context.gcp_active_space_dict()
    if not isinstance(sp, dict) or not sp:
        pytest.skip("no active space record to hold the legacy flag in this process")
    sp["enforce_iam"] = True
    try:
        lst = f"/storage/v1/b/{env['bucket']}/o"
        assert c.get(lst, headers=_as(env["other"])).status_code == 403
        assert c.get(lst, headers=_as(env["viewer"])).status_code == 200
    finally:
        sp.pop("enforce_iam", None)


def test_gcp_request_shapes_the_real_app_serves_are_mapped():
    """Shapes the live app produces that the request map used to miss: media download and the IAM v2 deny-policy API (decoded path)."""
    from core.iam_engine import map_gcp
    g = map_gcp.required("GET", "/download/storage/v1/b/b1/o/o1?alt=media")
    assert [x["action"] for x in g] == ["storage.objects.get"]
    base = "/v2/policies/cloudresourcemanager.googleapis.com/projects/p/denypolicies"
    for method, path, perm in (("POST", base + "?policyId=x", "create"), ("GET", base, "list"), ("GET", base + "/x", "get"),
                               ("DELETE", base + "/x", "delete")):
        r = map_gcp.required(method, path)
        assert [x["action"] for x in r] == ["iam.denypolicies." + perm], (method, path, r)
