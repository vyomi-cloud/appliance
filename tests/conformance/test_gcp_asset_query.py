"""Cloud Asset Inventory search query language over searchAllResources
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_asset_query.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

R = AwsWireRouter()
PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


P = "aq-proj-1"
call("POST", "/v3/projects", {"projectId": P, "displayName": "Asset Q"})
call("PATCH", f"/v3/projects/{P}", {"labels": {"env": "prod", "team": "core"}})
for n in ("web-app", "web-worker", "batch-job"):
    call("POST", f"/v1/projects/{P}/serviceAccounts", {"accountId": n, "serviceAccount": {"displayName": n.title()}})
call("POST", f"/v1/projects/{P}/roles", {"roleId": "webAdmin", "role": {"title": "Web Admin", "includedPermissions": ["storage.objects.get"]}})
call("POST", "/v3/folders", {"parent": call("GET", "/v3/organizations:search")[1]["organizations"][0]["name"], "displayName": "Team Folder"})


def q(query="", **kw):
    s, r = call("GET", f"/v1/projects/{P}:searchAllResources", query={"query": query, **kw})
    return s, r


def names(r):
    return sorted(x["displayName"] for x in r["results"])


s, r = q("")
check("no query lists everything", s == 200 and r["totalResults"] >= 6, r)
s, r = q("web")
check("bare term is a free-text search", len(r["results"]) >= 3, names(r))
s, r = q("displayName:web-*")
check("wildcard substring on a field", {x["displayName"] for x in r["results"]} >= {"Web-App", "Web-Worker"} and not any("batch" in x["displayName"].lower() for x in r["results"]), names(r))
s, r = q("assetType:ServiceAccount AND displayName:web")
check("explicit AND", len(r["results"]) == 2, names(r))
s, r = q("assetType:ServiceAccount displayName:batch")
check("implicit AND", names(r) == ["Batch-Job"], names(r))
s, r = q("displayName:batch OR displayName:Web-App")
check("OR", names(r) == ["Batch-Job", "Web-App"], names(r))
s, r = q("assetType:ServiceAccount -displayName:web")
check("negation with '-'", names(r) == ["Batch-Job"], names(r))
s, r = q("assetType:ServiceAccount AND NOT displayName:web")
check("NOT keyword", names(r) == ["Batch-Job"], names(r))
s, r = q("assetType:ServiceAccount AND (displayName:batch OR displayName:worker)")
check("parentheses", names(r) == ["Batch-Job", "Web-Worker"], names(r))
s, r = q("labels.env=prod")
check("labels.<key>=value", [x["assetType"] for x in r["results"]] == ["cloudresourcemanager.googleapis.com/Project"], r)
s, r = q("labels:team")
check("labels presence", len(r["results"]) == 1)
s, r = q('displayName="Web Admin"')
check("quoted value", names(r) == ["Web Admin"], names(r))
s, r = q("state=ACTIVE assetType:Folder")
check("folders are indexed", names(r) == ["Team Folder"], r)
s, r = q("", assetTypes="iam.googleapis.com/ServiceAccount")
check("assetTypes filter", s == 200 and len(r["results"]) == 3)
s, r = q("", assetTypes="iam.googleapis.com/*")
check("assetTypes wildcard", all(x["assetType"].startswith("iam.googleapis.com/") for x in r["results"]) and len(r["results"]) >= 4)
s, r = q("assetType:ServiceAccount", orderBy="displayName desc")
check("orderBy desc", [x["displayName"] for x in r["results"]] == ["Web-Worker", "Web-App", "Batch-Job"], r)
s, r = q("assetType:ServiceAccount", orderBy="displayName", pageSize="2")
check("pagination: first page + token", len(r["results"]) == 2 and r.get("nextPageToken") == "2" and r["totalResults"] == 3, r)
s, r2 = q("assetType:ServiceAccount", orderBy="displayName", pageSize="2", pageToken=r["nextPageToken"])
check("pagination: last page has no token", len(r2["results"]) == 1 and "nextPageToken" not in r2)
check("unknown field -> 400", q("bogus:1")[0] == 400)
check("unbalanced parens -> 400", q("(displayName:a")[0] == 400)
check("bad pageSize -> 400", q("", pageSize="0")[0] == 400)
check("unknown orderBy field -> 400", q("", orderBy="zzz")[0] == 400)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
