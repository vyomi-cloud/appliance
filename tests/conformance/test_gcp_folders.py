"""GCP resource hierarchy: folders (create/list/search/patch/move/delete/undelete), project parent + move
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_folders.py)."""
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


s, orgs = call("GET", "/v3/organizations:search")
ORG = orgs["organizations"][0]["name"]
s, op = call("POST", "/v3/folders", {"parent": ORG, "displayName": "Engineering"})
eng = op.get("response", {})
check("create folder returns a done LRO with the Folder", s == 200 and op["done"] and eng["name"].startswith("folders/") and eng["parent"] == ORG and eng["state"] == "ACTIVE", op)
check("duplicate sibling name -> 409", call("POST", "/v3/folders", {"parent": ORG, "displayName": "engineering"})[0] == 409)
check("short / bad displayName -> 400", call("POST", "/v3/folders", {"parent": ORG, "displayName": "a"})[0] == 400 and call("POST", "/v3/folders", {"parent": ORG, "displayName": "bad!name"})[0] == 400)
check("missing parent folder -> 404", call("POST", "/v3/folders", {"parent": "folders/999", "displayName": "Nope"})[0] == 404)
check("malformed parent -> 400", call("POST", "/v3/folders", {"parent": "projects/x", "displayName": "Nope"})[0] == 400)
s, op = call("POST", "/v3/folders", {"parent": eng["name"], "displayName": "Payments"})
pay = op["response"]
s, lst = call("GET", "/v3/folders", query={"parent": ORG})
check("list folders under the org", s == 200 and [f["displayName"] for f in lst["folders"]] == ["Engineering"], lst)
check("list requires a parent", call("GET", "/v3/folders")[0] == 400)
s, sr = call("GET", "/v3/folders:search", query={"query": "displayName=pay"})
check("search by displayName", [f["displayName"] for f in sr["folders"]] == ["Payments"], sr)
s, g = call("GET", "/v3/" + pay["name"])
check("get folder", s == 200 and g["parent"] == eng["name"])
s, op = call("PATCH", "/v3/" + pay["name"], {"displayName": "Payments Team"}, {"updateMask": "displayName"})
check("rename folder", s == 200 and op["response"]["displayName"] == "Payments Team")

# projects: create under a folder, ancestry, move
check("project under a missing folder -> 404", call("POST", "/v3/projects", {"projectId": "hier-proj-0", "parent": "folders/12345"})[0] == 404)
s, p = call("POST", "/v3/projects", {"projectId": "hier-proj-1", "parent": pay["name"]})
check("create project under a folder", s == 200 and p["parent"] == {"type": "folder", "id": pay["name"].split("/")[1]}, p)
s, anc = call("POST", "/v3/projects/hier-proj-1:getAncestry")
check("getAncestry walks project > folder > folder > org", [a["resourceId"]["type"] for a in anc["ancestor"]] == ["project", "folder", "folder", "organization"], anc)
s, dele = call("DELETE", "/v3/" + pay["name"])
check("deleting a folder with a project -> 400 FAILED_PRECONDITION", s == 400 and dele["error"]["status"] == "FAILED_PRECONDITION", dele)
check("cannot move a folder into its own descendant", call("POST", "/v3/" + eng["name"] + ":move", {"destinationParent": pay["name"]})[0] == 400)
s, op = call("POST", "/v3/projects/hier-proj-1:move", {"destinationParent": ORG})
check("move project to the org", s == 200 and op["done"] and op["response"]["parent"]["type"] == "organization", op)
check("move to current parent -> 400", call("POST", "/v3/projects/hier-proj-1:move", {"destinationParent": ORG})[0] == 400)
s, op = call("POST", "/v3/folders", {"parent": ORG, "displayName": "Platform"})
plat = op["response"]
s, op = call("POST", "/v3/" + pay["name"] + ":move", {"destinationParent": plat["name"]})
check("move folder to another folder", s == 200 and op["response"]["parent"] == plat["name"], op)
check("name clash on move -> 409", (lambda: (call("POST", "/v3/folders", {"parent": ORG, "displayName": "Payments Team"}), call("POST", "/v3/" + pay["name"] + ":move", {"destinationParent": ORG})[0] == 409)[1])())
# depth
cur = plat["name"]
for i in range(10):
    s, op = call("POST", "/v3/folders", {"parent": cur, "displayName": "level %d" % i})
    if s != 200:
        break
    cur = op["response"]["name"]
check("nesting limited to 10 levels", s == 400 and "10" in json.dumps(op), op)
# delete / undelete
s, op = call("POST", "/v3/folders", {"parent": ORG, "displayName": "Scratch"})
sc = op["response"]
s, op = call("DELETE", "/v3/" + sc["name"])
check("delete empty folder -> DELETE_REQUESTED", s == 200 and op["response"]["state"] == "DELETE_REQUESTED" and "deleteTime" in op["response"], op)
check("deleted folder hidden from list, shown with showDeleted", all(f["name"] != sc["name"] for f in call("GET", "/v3/folders", query={"parent": ORG})[1]["folders"]) and any(f["name"] == sc["name"] for f in call("GET", "/v3/folders", query={"parent": ORG, "showDeleted": "true"})[1]["folders"]))
check("name reusable after delete", call("POST", "/v3/folders", {"parent": ORG, "displayName": "Scratch"})[0] == 200)
check("undelete clashes with the reused name -> 409", call("POST", "/v3/" + sc["name"] + ":undelete")[0] == 409)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
