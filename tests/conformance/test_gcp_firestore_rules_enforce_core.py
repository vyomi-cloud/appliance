"""Firestore security rules: full language evaluator + enforcement of client-SDK style requests on the
data plane + the Firebase Rules API (rulesets / releases / :test).
Run: PYTHONPATH=. python tests/conformance/test_gcp_firestore_rules_enforce_core.py"""
import base64
import json

try:
    from core import gcp_firestore_core as fs, firestore_rules_core as fr
except ImportError:  # pragma: no cover
    import gcp_firestore_core as fs  # type: ignore
    import firestore_rules_core as fr  # type: ignore

P = "demo"
BASE = f"/v1/projects/{P}/databases/(default)/documents"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def jwt(uid, **extra):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'none'})}.{b({'iss': 'https://securetoken.google.com/' + P, 'sub': uid, 'user_id': uid, **extra})}."


RULES = """rules_version = '2';
service cloud.firestore {
  function signedIn() { return request.auth != null; }
  function isOwner(uid) { return signedIn() && request.auth.uid == uid; }
  function validUser() {
    let d = request.resource.data;
    return d.keys().hasOnly(['name', 'age', 'role']) && d.name is string && d.name.size() > 1 && d.age is int && d.age >= 0;
  }
  match /databases/{database}/documents {
    match /users/{userId} {
      allow get: if isOwner(userId) || get(/databases/$(database)/documents/users/$(request.auth.uid)).data.role == 'admin';
      allow create: if isOwner(userId) && validUser() && request.resource.data.role == 'user';
      allow update: if isOwner(userId) && validUser() && !request.resource.data.diff(resource.data).affectedKeys().hasAny(['role']);
      allow delete: if isOwner(userId);
    }
    match /posts/{postId} {
      allow read: if resource.data.public == true;
      allow write: if signedIn() && request.resource.data.owner == request.auth.uid;
    }
    match /{path=**}/comments/{c} { allow read: if signedIn(); }
    match /open/{doc} { allow read; }
  }
}
"""


def H(uid=None, key=False):
    h = {}
    if uid:
        h["authorization"] = "Bearer " + jwt(uid)
    return h


def S(x):
    return {"stringValue": x}


def I(x):
    return {"integerValue": str(x)}


def call(st, method, path, body=None, headers=None, q=None):
    r = fs.dispatch(st, method, path, q or {}, headers or {}, json.dumps(body or {}).encode())
    try:
        return r.status, json.loads(r.body or b"{}")
    except Exception:
        return r.status, {}


def run() -> int:
    st = fs.FirestoreStore()
    # --- Firebase Rules API
    s, rs = call(st, "POST", f"/v1/projects/{P}/rulesets", {"source": {"files": [{"name": "firestore.rules", "content": "service cloud.firestore { match /x { allow read: if ; } }"}]}})
    _check("invalid ruleset rejected with position", s == 400 and "line 1" in rs["error"]["message"])
    s, rs = call(st, "POST", f"/v1/projects/{P}/rulesets", {"source": {"files": [{"name": "firestore.rules", "content": "service cloud.firestore { match /databases/{d}/documents { allow read: if nope(); } }"}]}})
    _check("undefined function rejected", s == 400 and "Unknown function" in rs["error"]["message"])
    s, rs = call(st, "POST", f"/v1/projects/{P}/rulesets", {"source": {"files": [{"name": "firestore.rules", "content": RULES}]}})
    _check("ruleset created", s == 200 and rs["name"].startswith(f"projects/{P}/rulesets/"))
    rname = rs["name"]
    # client request BEFORE a release is denied (default deny), admin bypasses
    call(st, "PATCH", f"{BASE}/users/u1", {"fields": {"name": S("Ann"), "age": I(3), "role": S("user")}})
    s, _ = call(st, "GET", f"{BASE}/users/u1", headers=H("u1"))
    _check("client denied before any release", s == 403)
    s, _ = call(st, "GET", f"{BASE}/users/u1", headers={"authorization": "Bearer owner"})
    _check("Bearer owner (admin) bypasses rules", s == 200)
    s, rel = call(st, "POST", f"/v1/projects/{P}/releases", {"name": f"projects/{P}/releases/cloud.firestore", "rulesetName": rname})
    _check("release created", s == 200 and rel["rulesetName"] == rname)
    s, _ = call(st, "POST", f"/v1/projects/{P}/releases", {"name": f"projects/{P}/releases/cloud.firestore", "rulesetName": rname})
    _check("duplicate release 409", s == 409)
    _check("ruleset in use cannot be deleted", call(st, "DELETE", f"/v1/projects/{P}/{rname.split(P + '/')[1]}")[0] == 400)
    _check("list rulesets", len(call(st, "GET", f"/v1/projects/{P}/rulesets")[1]["rulesets"]) == 1)
    _check("get release", call(st, "GET", f"/v1/projects/{P}/releases/cloud.firestore")[1]["rulesetName"] == rname)

    # --- enforcement
    s, _ = call(st, "GET", f"{BASE}/users/u1", headers=H("u1"))
    _check("owner get allowed", s == 200)
    s, e = call(st, "GET", f"{BASE}/users/u1", headers=H("u2"))
    _check("other user get denied with PERMISSION_DENIED", s == 403 and e["error"]["status"] == "PERMISSION_DENIED")
    s, _ = call(st, "GET", f"{BASE}/users/u1", headers={"x-goog-api-key": "k"})
    _check("api-key-only (unauthenticated client) denied", s == 403)
    s, _ = call(st, "GET", f"{BASE}/users/u1")
    _check("no credentials (admin/emulator style) bypasses", s == 200)
    call(st, "PATCH", f"{BASE}/users/root", {"fields": {"role": S("admin")}})
    s, _ = call(st, "GET", f"{BASE}/users/u1", headers=H("root"))
    _check("get() lookup grants admin read", s == 200)
    # create validation
    s, _ = call(st, "PATCH", f"{BASE}/users/u9", {"fields": {"name": S("Zed"), "age": I(5), "role": S("user")}}, H("u9"), {"currentDocument.exists": "false"})
    _check("valid create allowed", s == 200)
    s, _ = call(st, "PATCH", f"{BASE}/users/u8", {"fields": {"name": S("Zed"), "age": S("5"), "role": S("user")}}, H("u8"))
    _check("age as string rejected by validUser()", s == 403)
    s, _ = call(st, "PATCH", f"{BASE}/users/u7", {"fields": {"name": S("Zed"), "age": I(5), "role": S("admin")}}, H("u7"))
    _check("self-assigned admin role rejected", s == 403)
    # update must not touch role (diff().affectedKeys())
    s, _ = call(st, "PATCH", f"{BASE}/users/u9", {"fields": {"name": S("Zed2"), "age": I(6), "role": S("user")}}, H("u9"))
    _check("update leaving role unchanged allowed", s == 200)
    s, _ = call(st, "PATCH", f"{BASE}/users/u9", {"fields": {"name": S("Zed2"), "age": I(6), "role": S("admin")}}, H("u9"))
    _check("update changing role denied", s == 403)
    s, _ = call(st, "DELETE", f"{BASE}/users/u9", headers=H("u2"))
    _check("non-owner delete denied", s == 403)
    s, _ = call(st, "DELETE", f"{BASE}/users/u9", headers=H("u9"))
    _check("owner delete allowed", s == 200)
    # commit (batch) is evaluated per write
    w = {"writes": [{"update": {"name": f"projects/{P}/databases/(default)/documents/users/u5", "fields": {"name": S("Bob"), "age": I(1), "role": S("user")}}}]}
    _check("commit by other uid denied", call(st, "POST", f"{BASE}:commit", w, H("u6"))[0] == 403)
    _check("commit by owner allowed", call(st, "POST", f"{BASE}:commit", w, H("u5"))[0] == 200)
    # list: rule depends on resource.data -> the query must constrain it
    call(st, "PATCH", f"{BASE}/posts/p1", {"fields": {"public": {"booleanValue": True}, "owner": S("u1")}})
    call(st, "PATCH", f"{BASE}/posts/p2", {"fields": {"public": {"booleanValue": False}, "owner": S("u1")}})
    q_all = {"structuredQuery": {"from": [{"collectionId": "posts"}]}}
    q_pub = {"structuredQuery": {"from": [{"collectionId": "posts"}], "where": {"fieldFilter": {"field": {"fieldPath": "public"}, "op": "EQUAL", "value": {"booleanValue": True}}}}}
    _check("unconstrained list of posts denied", call(st, "POST", f"{BASE}:runQuery", q_all, H("u1"))[0] == 403)
    s, rows = call(st, "POST", f"{BASE}:runQuery", q_pub, H("u1"))
    _check("list constrained to public == true allowed", s == 200)
    _check("get on unpublished post denied", call(st, "GET", f"{BASE}/posts/p2", headers=H("u1"))[0] == 403)
    _check("get on public post allowed", call(st, "GET", f"{BASE}/posts/p1", headers=H("u1"))[0] == 200)
    _check("collection list GET denied (no resource)", call(st, "GET", f"{BASE}/posts", headers=H("u1"))[0] == 403)
    _check("`allow read;` without condition is open", call(st, "GET", f"{BASE}/open/x", headers={"x-goog-api-key": "k"})[0] in (200, 404))
    cg = {"structuredQuery": {"from": [{"collectionId": "comments", "allDescendants": True}]}}
    _check("collection-group rule `/{path=**}/comments/{c}` needs auth", call(st, "POST", f"{BASE}:runQuery", cg, {"x-goog-api-key": "k"})[0] == 403
           and call(st, "POST", f"{BASE}:runQuery", cg, H("u1"))[0] == 200)
    _check("listCollectionIds denied to clients", call(st, "POST", f"{BASE}:listCollectionIds", {}, H("u1"))[0] == 403)

    # --- :test API
    tc = [{"expectation": "ALLOW", "method": "GET", "path": "/databases/(default)/documents/users/u1", "request": {"auth": {"uid": "u1"}}},
          {"expectation": "DENY", "method": "GET", "path": "/databases/(default)/documents/users/u1", "request": {"auth": {"uid": "zz"}}},
          {"expectation": "ALLOW", "method": "GET", "path": "/databases/(default)/documents/users/u1", "request": {"auth": {"uid": "zz"}}}]
    s, t = call(st, "POST", f"/v1/projects/{P}:test", {"source": {"files": [{"name": "firestore.rules", "content": RULES}]}, "testSuite": {"testCases": tc}})
    _check("projects:test results", s == 200 and [r["state"] for r in t["testResults"]] == ["SUCCESS", "SUCCESS", "FAILURE"])
    s, t = call(st, "POST", f"/v1/projects/{P}:test", {"source": {"files": [{"name": "f", "content": "service cloud.firestore {"}]}})
    _check(":test with bad source returns issues", t.get("issues"))

    # --- console publish path (legacy endpoints) now validates and creates a ruleset+release
    s, _ = call(st, "POST", f"/v1/projects/{P}/databases/(default):updateSecurityRules", {"rules": "service cloud.firestore {"})
    _check("publishing broken rules is refused", s == 400)
    s, _ = call(st, "POST", f"/v1/projects/{P}/databases/(default):updateSecurityRules", {"rules": "service cloud.firestore { match /databases/{d}/documents { match /{x=**} { allow read: if true; } } }"})
    _check("publish ok", s == 200)
    _check("publish creates ruleset history", len(call(st, "GET", f"/v1/projects/{P}/rulesets")[1]["rulesets"]) == 2)
    _check("published rules take effect for clients", call(st, "GET", f"{BASE}/users/u1", headers=H("zz"))[0] == 200)
    print("firestore rules enforcement: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
