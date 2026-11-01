"""Unit tests for core/gcp_resourcemanager_core.py
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_resourcemanager_core.py).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_resourcemanager_core as rm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, path, body=None, query=None):
    r = rm.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, (json.loads(r.body or b"{}"))


st = rm.ResourceManagerStore()
project = "demo-proj"

# project get/patch
s, p = call(st, "GET", f"/v3/projects/{project}")
check("get project 200, auto-created", s == 200 and p["projectId"] == project and p["displayName"] == project, p)
s, p = call(st, "PATCH", f"/v3/projects/{project}", {"displayName": "Demo Project", "labels": {"env": "test"}})
check("patch project updates displayName + labels", s == 200 and p["displayName"] == "Demo Project" and p["labels"] == {"env": "test"}, p)
s, p2 = call(st, "GET", f"/v3/projects/{project}")
check("get project reflects patch", p2["displayName"] == "Demo Project")

# projects.create / projects.search / projects.delete (Manage resources page)
s, created = call(st, "POST", "/v3/projects", {"projectId": "uic-new-proj", "displayName": "UIC New Project"})
check("create project 200", s == 200 and created["projectId"] == "uic-new-proj" and created["displayName"] == "UIC New Project", created)
s, bad_id = call(st, "POST", "/v3/projects", {"projectId": "N0T-VALID!"})
check("create project with invalid id -> 400", s == 400)
s, dupe = call(st, "POST", "/v3/projects", {"projectId": "uic-new-proj"})
check("create duplicate project -> 409", s == 409)
s, found = call(st, "GET", "/v3/projects:search", query={"query": "uic-new"})
check("search projects finds the new one", s == 200 and "uic-new-proj" in [x["projectId"] for x in found["projects"]], found)
s, all_ = call(st, "GET", "/v3/projects:search")
check("search with no query returns every known project", s == 200 and {project, "uic-new-proj"} <= {x["projectId"] for x in all_["projects"]})
s, _ = call(st, "DELETE", "/v3/projects/uic-new-proj")
check("delete project 200", s == 200)
s, after = call(st, "GET", "/v3/projects:search", query={"query": "uic-new"})
check("deleted project dropped from search", after["projects"] == [])
s, _ = call(st, "DELETE", "/v3/projects/no-such-project")
check("delete unknown project -> 404", s == 404)

# tag keys
s, tk = call(st, "POST", "/v3/tagKeys", {"parent": f"projects/{project}", "shortName": "env", "description": "environment"})
check("create tag key 200", s == 200 and tk["shortName"] == "env", tk)
dupe_s, _ = call(st, "POST", "/v3/tagKeys", {"parent": f"projects/{project}", "shortName": "env"})
check("duplicate tag key 409", dupe_s == 409)
s, lst = call(st, "GET", "/v3/tagKeys", query={"parent": f"projects/{project}"})
check("list tag keys has env", s == 200 and "env" in [t["shortName"] for t in lst["tagKeys"]])
tkid = tk["name"].rsplit("/", 1)[-1]
s, got = call(st, "GET", f"/v3/tagKeys/{tkid}")
check("get tag key 200", s == 200 and got["name"] == tk["name"])

# tag values (nested under the tag key) + tag bindings (attach a value to any resource,
# e.g. a GCS bucket — see gcp.storage.tags)
s, tv = call(st, "POST", "/v3/tagValues", {"parent": tk["name"], "shortName": "prod"})
check("create tag value 200", s == 200 and tv["shortName"] == "prod" and tv["namespacedName"] == f"{project}/env/prod", tv)
s, dupe_tv = call(st, "POST", "/v3/tagValues", {"parent": tk["name"], "shortName": "prod"})
check("duplicate tag value 409", s == 409)
s, no_key = call(st, "POST", "/v3/tagValues", {"parent": "tagKeys/999999999", "shortName": "x"})
check("tag value under unknown key 404", s == 404)
s, lstv = call(st, "GET", "/v3/tagValues", query={"parent": tk["name"]})
check("list tag values has prod", s == 200 and "prod" in [v["shortName"] for v in lstv["tagValues"]])

bucket_resource = "//storage.googleapis.com/projects/_/buckets/uic-bucket"
s, tb = call(st, "POST", "/v3/tagBindings", {"parent": bucket_resource, "tagValue": tv["name"]})
check("create tag binding on a GCS bucket 200", s == 200 and tb["parent"] == bucket_resource and tb["tagValue"] == tv["name"], tb)
s, dupe_tb = call(st, "POST", "/v3/tagBindings", {"parent": bucket_resource, "tagValue": tv["name"]})
check("duplicate binding of the same tag KEY to the same resource -> 409", s == 409)
s, lstb = call(st, "GET", "/v3/tagBindings", query={"parent": bucket_resource})
check("list tag bindings for the bucket shows it", s == 200 and len(lstb["tagBindings"]) == 1)
bid = tb["name"].rsplit("/", 1)[-1]
s, _ = call(st, "DELETE", f"/v3/tagBindings/{bid}")
check("delete tag binding 200", s == 200)
s, lstb2 = call(st, "GET", "/v3/tagBindings", query={"parent": bucket_resource})
check("deleted tag binding dropped", lstb2["tagBindings"] == [])

s, _ = call(st, "DELETE", f"/v3/tagKeys/{tkid}")
check("delete tag key 200", s == 200)
s, lst2 = call(st, "GET", "/v3/tagKeys", query={"parent": f"projects/{project}"})
check("deleted tag key dropped", lst2["tagKeys"] == [])
s, lstv2 = call(st, "GET", "/v3/tagValues", query={"parent": tk["name"]})
check("deleting a tag key cascades to its tag values", s == 200 and lstv2["tagValues"] == [])

# essential contacts
s, c = call(st, "POST", f"/v1/projects/{project}/contacts", {"email": "ops@example.com", "notificationCategorySubscriptions": ["ALL"]})
check("create contact 200", s == 200 and c["email"] == "ops@example.com", c)
s, bad = call(st, "POST", f"/v1/projects/{project}/contacts", {"email": "not-an-email"})
check("invalid email -> 400", s == 400)
s, lst = call(st, "GET", f"/v1/projects/{project}/contacts")
check("list contacts has ops@", s == 200 and "ops@example.com" in [x["email"] for x in lst["contacts"]])
cid = c["name"].rsplit("/", 1)[-1]
s, _ = call(st, "DELETE", f"/v1/projects/{project}/contacts/{cid}")
check("delete contact 200", s == 200)
s, lst2 = call(st, "GET", f"/v1/projects/{project}/contacts")
check("deleted contact dropped", lst2["contacts"] == [])

# org policies
s, pol = call(st, "POST", f"/v2/projects/{project}/policies", {"spec": {"rules": [{"enforce": True}]}}, query={"policyId": "custom.noExternalIps"})
check("create org policy 200", s == 200 and pol["name"].endswith("/policies/custom.noExternalIps"), pol)
s, dup = call(st, "POST", f"/v2/projects/{project}/policies", {}, query={"policyId": "custom.noExternalIps"})
check("duplicate org policy 409", s == 409)
s, lst = call(st, "GET", f"/v2/projects/{project}/policies")
check("list org policies has it", s == 200 and pol["name"] in [x["name"] for x in lst["policies"]])
s, got = call(st, "GET", f"/v2/{pol['name']}")
check("get org policy 200", s == 200 and got["name"] == pol["name"])
s, _ = call(st, "DELETE", f"/v2/{pol['name']}")
check("delete org policy 200", s == 200)
s, lst2 = call(st, "GET", f"/v2/projects/{project}/policies")
check("deleted org policy dropped", lst2["policies"] == [])

# predefined constraints are named "constraints/x" — a policyId with a slash in it; get/delete
# must address the WHOLE suffix, not just the first segment after "policies/" (core/gcp_iam_core's
# org_policy_enforced() looks up this exact name for the two constraints it evaluates).
s, pol2 = call(st, "POST", f"/v2/projects/{project}/policies", {"spec": {"rules": [{"enforce": True}]}},
              query={"policyId": "constraints/iam.disableServiceAccountCreation"})
check("create predefined constraint 200", s == 200
      and pol2["name"] == f"projects/{project}/policies/constraints/iam.disableServiceAccountCreation", pol2)
s, got2 = call(st, "GET", f"/v2/{pol2['name']}")
check("get predefined constraint by its full (slash-containing) name", s == 200 and got2["name"] == pol2["name"])
s, _ = call(st, "DELETE", f"/v2/{pol2['name']}")
check("delete predefined constraint by its full (slash-containing) name", s == 200)
s, got3 = call(st, "GET", f"/v2/{pol2['name']}")
check("deleted predefined constraint is gone", s == 404)

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
