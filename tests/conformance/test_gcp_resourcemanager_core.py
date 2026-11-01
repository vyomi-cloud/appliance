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
s, _ = call(st, "DELETE", f"/v3/tagKeys/{tkid}")
check("delete tag key 200", s == 200)
s, lst2 = call(st, "GET", "/v3/tagKeys", query={"parent": f"projects/{project}"})
check("deleted tag key dropped", lst2["tagKeys"] == [])

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

# organizations — every project has an implicit backing organization (depth: the
# former "requires an organization" excuse for Groups / Workforce Identity
# Federation / Principal Access Boundary / Identity & Organization is now real)
s, pmeta = call(st, "GET", f"/v3/projects/{project}")
check("project auto-gets a parent organization", s == 200 and pmeta.get("parent", {}).get("type") == "organization", pmeta)
org_id = pmeta["parent"]["id"]
s, org = call(st, "GET", f"/v3/organizations/{org_id}")
check("get organization 200", s == 200 and org["name"] == f"organizations/{org_id}", org)
check("organization has a directory customer id", bool(org.get("directoryCustomerId")))
s, search = call(st, "GET", "/v3/organizations")
check("organizations:search lists the same org", s == 200 and search["organizations"][0]["name"] == org["name"])
s, missing = call(st, "GET", "/v3/organizations/0")
check("unknown organization -> 404", s == 404)

# Cloud Identity groups + memberships
s, grp = call(st, "POST", "/v1/groups", {"groupKey": {"id": "eng@example.com"}, "displayName": "Engineering"})
check("create group 200", s == 200 and grp["groupKey"]["id"] == "eng@example.com", grp)
s, dup = call(st, "POST", "/v1/groups", {"groupKey": {"id": "eng@example.com"}})
check("duplicate group -> 409", s == 409)
s, lst = call(st, "GET", "/v1/groups")
check("list groups has eng@", s == 200 and "eng@example.com" in [g["groupKey"]["id"] for g in lst["groups"]])
gid = grp["name"].rsplit("/", 1)[-1]
s, got = call(st, "GET", f"/v1/groups/{gid}")
check("get group 200", s == 200 and got["name"] == grp["name"])
s, mem = call(st, "POST", f"/v1/{grp['name']}/memberships", {"preferredMemberKey": {"id": "user:alice@example.com"}})
check("add membership 200", s == 200 and mem["preferredMemberKey"]["id"] == "user:alice@example.com", mem)
s, dupmem = call(st, "POST", f"/v1/{grp['name']}/memberships", {"preferredMemberKey": {"id": "user:alice@example.com"}})
check("duplicate membership -> 409", s == 409)
s, memlst = call(st, "GET", f"/v1/{grp['name']}/memberships")
check("list memberships has alice", s == 200 and len(memlst["memberships"]) == 1)
s, _ = call(st, "DELETE", f"/v1/groups/{gid}")
check("delete group 200", s == 200)
s, memlst2 = call(st, "GET", f"/v1/{grp['name']}/memberships")
check("deleting a group drops its memberships too", memlst2["memberships"] == [])

# Workforce Identity Federation pools (org-scoped)
s, wp = call(st, "POST", "/v1/locations/global/workforcePools", {"displayName": "Contractors"}, query={"workforcePoolId": "contractors"})
check("create workforce pool 200", s == 200 and wp["name"] == "locations/global/workforcePools/contractors", wp)
check("workforce pool parented under the default organization", wp["parent"] == org["name"])
s, dup = call(st, "POST", "/v1/locations/global/workforcePools", {}, query={"workforcePoolId": "contractors"})
check("duplicate workforce pool -> 409", s == 409)
s, lst = call(st, "GET", "/v1/locations/global/workforcePools", query={"parent": org["name"]})
check("list workforce pools has contractors", s == 200 and "contractors" in [p["name"].rsplit("/", 1)[-1] for p in lst["workforcePools"]])
s, got = call(st, "GET", f"/v1/{wp['name']}")
check("get workforce pool 200", s == 200 and got["name"] == wp["name"])
s, _ = call(st, "DELETE", f"/v1/{wp['name']}")
check("delete workforce pool 200", s == 200)
s, after = call(st, "GET", f"/v1/{wp['name']}")
check("deleted workforce pool 404s", s == 404)

# Principal Access Boundary policies + bindings (enforcement itself is proven against
# core/gcp_iam_core.py's testIamPermissions in test_gcp_iam_core.py)
s, pab = call(st, "POST", f"/v3/{org['name']}/locations/global/principalAccessBoundaryPolicies",
             {"displayName": "Prod only", "details": {"rules": [{"resources": [f"projects/{project}"]}]}},
             query={"principalAccessBoundaryPolicyId": "prod-only"})
check("create PAB policy 200", s == 200 and pab["details"]["rules"][0]["resources"] == [f"projects/{project}"], pab)
s, lst = call(st, "GET", f"/v3/{org['name']}/locations/global/principalAccessBoundaryPolicies")
check("list PAB policies has prod-only", s == 200 and pab["name"] in [p["name"] for p in lst["principalAccessBoundaryPolicies"]])
s, bad_bind = call(st, "POST", f"/v3/{org['name']}/locations/global/policyBindings",
                   {"policy": "organizations/0/locations/global/principalAccessBoundaryPolicies/nope",
                    "target": {"principal": "user:x@example.com"}}, query={"policyBindingId": "b1"})
check("binding to an unknown policy -> 400", s == 400)
s, bind = call(st, "POST", f"/v3/{org['name']}/locations/global/policyBindings",
              {"policy": pab["name"], "target": {"principal": "user:x@example.com"}}, query={"policyBindingId": "b1"})
check("create PAB binding 200", s == 200 and bind["policy"] == pab["name"], bind)
s, lst = call(st, "GET", f"/v3/{org['name']}/locations/global/policyBindings")
check("list PAB bindings has b1", s == 200 and bind["name"] in [b["name"] for b in lst["policyBindings"]])
s, _ = call(st, "DELETE", f"/v3/{pab['name']}")
check("delete PAB policy 200", s == 200)
s, lst2 = call(st, "GET", f"/v3/{org['name']}/locations/global/policyBindings")
check("deleting a PAB policy drops its bindings too", lst2["policyBindings"] == [])

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
