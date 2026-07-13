"""GCP Cloud IAM core conformance — the GCP analogue of test_iam_core.py.

Same file runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **GCP IAM REST** wire semantics: service-account
create/get/list/delete (email + uniqueId), resource IAM policy
setIamPolicy↔getIamPolicy binding round-trip, and — the star — testIamPermissions
that EVALUATES the binding model (returns only the permissions actually granted by
the caller's bound roles, not the requested set echoed back). Proving
google-cloud-iam / google-cloud-resource-manager can drive the core unchanged.

Run on host:    python3 tests/conformance/test_gcp_iam_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.iam_store import InMemoryIamStore
    from core import gcp_iam_core as giam
except ImportError:  # pragma: no cover - Pyodide flat layout
    from iam_store import InMemoryIamStore  # type: ignore
    import gcp_iam_core as giam  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def _post(st, path, obj=None):
    return giam.dispatch(st, "POST", path, {}, {},
                         json.dumps(obj or {}).encode() if obj is not None else b"")


def run() -> int:
    st = InMemoryIamStore()
    project = "demo-proj"

    # 1. create service account -> 200 with name/email/uniqueId
    cr = _post(st, f"/v1/projects/{project}/serviceAccounts",
               {"accountId": "svc-a", "serviceAccount": {"displayName": "Service A"}})
    _check("create SA 200", cr.status == 200)
    sa = _jbody(cr)
    _check("create SA email", sa["email"] == f"svc-a@{project}.iam.gserviceaccount.com")
    _check("create SA name", sa["name"] == f"projects/{project}/serviceAccounts/{sa['email']}")
    _check("create SA uniqueId 21 digits", sa["uniqueId"].isdigit() and len(sa["uniqueId"]) == 21)
    _check("create SA displayName", sa["displayName"] == "Service A")

    # 1b. duplicate accountId -> 409 ALREADY_EXISTS
    dup = _post(st, f"/v1/projects/{project}/serviceAccounts",
                {"accountId": "svc-a", "serviceAccount": {}})
    _check("duplicate SA 409", dup.status == 409 and _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 2. get service account (by email) -> matches
    g = giam.dispatch(st, "GET",
                      f"/v1/projects/{project}/serviceAccounts/{sa['email']}", {}, {}, b"")
    _check("get SA 200", g.status == 200 and _jbody(g)["email"] == sa["email"])

    # 3. list service accounts -> contains svc-a
    _post(st, f"/v1/projects/{project}/serviceAccounts",
          {"accountId": "svc-b", "serviceAccount": {"displayName": "Service B"}})
    ls = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts", {}, {}, b"")
    emails = [a["email"] for a in _jbody(ls)["accounts"]]
    _check("list SA has both", sa["email"] in emails and
           f"svc-b@{project}.iam.gserviceaccount.com" in emails)

    # 4. setIamPolicy then getIamPolicy round-trips bindings
    resource = f"projects/_/buckets/demo-bucket"
    bindings = [
        {"role": "roles/storage.objectViewer",
         "members": ["user:alice@example.com", f"serviceAccount:{sa['email']}"]},
        {"role": "roles/storage.admin", "members": ["user:admin@example.com"]},
    ]
    sp = _post(st, f"/v1/{resource}:setIamPolicy", {"policy": {"bindings": bindings}})
    _check("setIamPolicy 200", sp.status == 200)
    gp = _post(st, f"/v1/{resource}:getIamPolicy", {})
    _check("getIamPolicy 200", gp.status == 200)
    got = _jbody(gp)
    _check("policy has etag", bool(got.get("etag")))
    got_bindings = {b["role"]: sorted(b["members"]) for b in got["bindings"]}
    _check("binding roundtrip objectViewer",
           got_bindings.get("roles/storage.objectViewer") ==
           sorted(["user:alice@example.com", f"serviceAccount:{sa['email']}"]))
    _check("binding roundtrip storage.admin",
           got_bindings.get("roles/storage.admin") == ["user:admin@example.com"])

    # 5. getIamPolicy on a never-set resource -> empty bindings, version 1
    empty = _post(st, "/v1/projects/_/buckets/never-set:getIamPolicy", {})
    _check("empty policy version 1", _jbody(empty)["version"] == 1)
    _check("empty policy no bindings", _jbody(empty)["bindings"] == [])

    # 6. testIamPermissions EVALUATES bindings (returns ONLY granted perms) --------
    # alice is bound as objectViewer -> may get/list objects, NOT create/delete.
    tp = _post(st, f"/v1/{resource}:testIamPermissions",
               {"member": "user:alice@example.com",
                "permissions": ["storage.objects.get", "storage.objects.list",
                                "storage.objects.create", "storage.objects.delete",
                                "storage.buckets.delete"]})
    granted = _jbody(tp)["permissions"]
    _check("viewer granted get", "storage.objects.get" in granted)
    _check("viewer granted list", "storage.objects.list" in granted)
    _check("viewer NOT granted create", "storage.objects.create" not in granted)
    _check("viewer NOT granted delete", "storage.objects.delete" not in granted)
    _check("viewer NOT granted bucket delete", "storage.buckets.delete" not in granted)
    _check("testIamPermissions did NOT echo (subset only)", set(granted) < {
        "storage.objects.get", "storage.objects.list", "storage.objects.create",
        "storage.objects.delete", "storage.buckets.delete"})

    # admin has roles/storage.admin -> gets the elevated perms alice can't.
    tpa = _post(st, f"/v1/{resource}:testIamPermissions",
                {"member": "user:admin@example.com",
                 "permissions": ["storage.objects.create", "storage.buckets.delete",
                                 "storage.objects.get"]})
    ga = _jbody(tpa)["permissions"]
    _check("admin granted create", "storage.objects.create" in ga)
    _check("admin granted bucket delete", "storage.buckets.delete" in ga)

    # a member bound to NO role gets NOTHING.
    tpn = _post(st, f"/v1/{resource}:testIamPermissions",
                {"member": "user:nobody@example.com",
                 "permissions": ["storage.objects.get", "storage.objects.list"]})
    _check("unbound member granted nothing", _jbody(tpn)["permissions"] == [])

    # the SA (bound objectViewer) is evaluated by its member string too.
    tps = _post(st, f"/v1/{resource}:testIamPermissions",
                {"member": f"serviceAccount:{sa['email']}",
                 "permissions": ["storage.objects.get", "storage.objects.create"]})
    gs = _jbody(tps)["permissions"]
    _check("SA member granted get", gs == ["storage.objects.get"])

    # 7. delete SA -> 200, then get -> 404 NOT_FOUND
    d = giam.dispatch(st, "DELETE",
                      f"/v1/projects/{project}/serviceAccounts/{sa['email']}", {}, {}, b"")
    _check("delete SA 200", d.status == 200)
    miss = giam.dispatch(st, "GET",
                         f"/v1/projects/{project}/serviceAccounts/{sa['email']}", {}, {}, b"")
    _check("deleted SA 404", miss.status == 404 and _jbody(miss)["error"]["status"] == "NOT_FOUND")

    # 8. is_permission_granted convenience helper agrees with the wire.
    st2 = InMemoryIamStore()
    _post(st2, "/v1/projects/_/buckets/b2:setIamPolicy",
          {"policy": {"bindings": [{"role": "roles/owner",
                                    "members": ["user:root@example.com"]}]}})
    _check("owner grants anything (helper)",
           giam.is_permission_granted(st2, "projects/_/buckets/b2",
                                      "user:root@example.com", "storage.buckets.delete"))
    _check("owner still denies unbound member (helper)",
           not giam.is_permission_granted(st2, "projects/_/buckets/b2",
                                          "user:x@example.com", "storage.objects.get"))

    print("\nGCP IAM-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
