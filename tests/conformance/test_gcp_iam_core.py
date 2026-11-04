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
    from core import gcp_resourcemanager_core as grm
    from core import gcp_iamcredentials_core as giamc
except ImportError:  # pragma: no cover - Pyodide flat layout
    from iam_store import InMemoryIamStore  # type: ignore
    import gcp_iam_core as giam  # type: ignore
    import gcp_resourcemanager_core as grm  # type: ignore
    import gcp_iamcredentials_core as giamc  # type: ignore


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

    # 9. predefined roles catalog -------------------------------------------
    pr = giam.dispatch(st, "GET", "/v1/roles", {}, {}, b"")
    _check("predefined roles 200", pr.status == 200)
    pr_names = [r["name"] for r in _jbody(pr)["roles"]]
    _check("predefined roles has owner/editor/viewer", {"roles/owner", "roles/editor", "roles/viewer"} <= set(pr_names))

    # 10. custom roles CRUD ---------------------------------------------------
    cr_role = _post(st, f"projects/{project}/roles",
                    {"roleId": "myCustomRole",
                     "role": {"title": "My Custom Role", "description": "d", "includedPermissions": ["storage.objects.get"]}})
    _check("create role 200", cr_role.status == 200)
    role = _jbody(cr_role)
    _check("create role name", role["name"] == f"projects/{project}/roles/myCustomRole")
    _check("create role title", role["title"] == "My Custom Role")
    dup_role = _post(st, f"projects/{project}/roles", {"roleId": "myCustomRole", "role": {}})
    _check("duplicate role 409", dup_role.status == 409)
    gr = giam.dispatch(st, "GET", f"/v1/{role['name']}", {}, {}, b"")
    _check("get role 200", gr.status == 200 and _jbody(gr)["title"] == "My Custom Role")
    lr = giam.dispatch(st, "GET", f"/v1/projects/{project}/roles", {}, {}, b"")
    _check("list roles has myCustomRole", "myCustomRole" in [r["name"].rsplit("/", 1)[-1] for r in _jbody(lr)["roles"]])
    pr2 = giam.dispatch(st, "PATCH", f"/v1/{role['name']}", {}, {}, json.dumps({"title": "Renamed"}).encode())
    _check("patch role 200", pr2.status == 200 and _jbody(pr2)["title"] == "Renamed")
    dr = giam.dispatch(st, "DELETE", f"/v1/{role['name']}", {}, {}, b"")
    _check("delete role 200", dr.status == 200 and _jbody(dr)["deleted"] is True)
    lr2 = giam.dispatch(st, "GET", f"/v1/projects/{project}/roles", {}, {}, b"")
    _check("deleted role dropped from list", "myCustomRole" not in [r["name"].rsplit("/", 1)[-1] for r in _jbody(lr2)["roles"]])

    # 11. service account keys -----------------------------------------------
    sa2 = _jbody(_post(st, f"/v1/projects/{project}/serviceAccounts",
                       {"accountId": "svc-keys", "serviceAccount": {}}))
    ck = _post(st, f"/v1/projects/{project}/serviceAccounts/{sa2['email']}/keys",
               {"privateKeyType": "TYPE_GOOGLE_CREDENTIALS_FILE"})
    _check("create key 200", ck.status == 200)
    key = _jbody(ck)
    _check("create key has privateKeyData", bool(key.get("privateKeyData")))
    kid = key["name"].rsplit("/", 1)[-1]
    lk = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa2['email']}/keys", {}, {}, b"")
    _check("list keys has new key", kid in [k["name"].rsplit("/", 1)[-1] for k in _jbody(lk)["keys"]])
    _check("list keys omits private key material", all("privateKeyData" not in k for k in _jbody(lk)["keys"]))
    gk = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa2['email']}/keys/{kid}", {}, {}, b"")
    _check("get key 200", gk.status == 200 and _jbody(gk)["name"] == key["name"])
    dk = giam.dispatch(st, "DELETE", f"/v1/projects/{project}/serviceAccounts/{sa2['email']}/keys/{kid}", {}, {}, b"")
    _check("delete key 200", dk.status == 200)
    lk2 = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa2['email']}/keys", {}, {}, b"")
    _check("deleted key dropped", kid not in [k["name"].rsplit("/", 1)[-1] for k in _jbody(lk2)["keys"]])

    # 12. auditConfigs round-trip on setIamPolicy/getIamPolicy ---------------
    aud_resource = f"projects/{project}"
    _post(st, f"/v1/{aud_resource}:setIamPolicy", {"policy": {"bindings": [], "auditConfigs": [
        {"service": "storage.googleapis.com", "auditLogConfigs": [
            {"logType": "DATA_WRITE", "exemptedMembers": ["user:exempt@example.com"]}]}]}})
    aud_get = _post(st, f"/v1/{aud_resource}:getIamPolicy", {})
    acfgs = _jbody(aud_get).get("auditConfigs") or []
    _check("auditConfigs round-trip", acfgs and acfgs[0]["service"] == "storage.googleapis.com"
           and acfgs[0]["auditLogConfigs"][0]["exemptedMembers"] == ["user:exempt@example.com"])

    # 13. deny policies CRUD ---------------------------------------------------
    attach = f"cloudresourcemanager.googleapis.com%2Fprojects%2F{project}"
    cdp = giam.dispatch(st, "POST", f"/v2/policies/{attach}/denypolicies", {"policyId": "myDenyPolicy"}, {},
                        json.dumps({"displayName": "My deny", "rules": [{"denyRule": {
                            "deniedPrincipals": ["user:bad@example.com"], "deniedPermissions": ["storage.objects.delete"]}}]}).encode())
    _check("create deny policy 200", cdp.status == 200)
    dp = _jbody(cdp)
    _check("deny policy name", dp["name"].endswith("/denypolicies/myDenyPolicy"))
    ldp = giam.dispatch(st, "GET", f"/v2/policies/{attach}/denypolicies", {}, {}, b"")
    _check("list deny policies has it", "myDenyPolicy" in [p["name"].rsplit("/", 1)[-1] for p in _jbody(ldp)["policies"]])
    gdp = giam.dispatch(st, "GET", f"/v2/policies/{attach}/denypolicies/myDenyPolicy", {}, {}, b"")
    _check("get deny policy 200", gdp.status == 200)
    ddp = giam.dispatch(st, "DELETE", f"/v2/policies/{attach}/denypolicies/myDenyPolicy", {}, {}, b"")
    _check("delete deny policy 200", ddp.status == 200)
    ldp2 = giam.dispatch(st, "GET", f"/v2/policies/{attach}/denypolicies", {}, {}, b"")
    _check("deleted deny policy dropped", _jbody(ldp2)["policies"] == [])

    # 14. workload identity pools ---------------------------------------------
    cwp = giam.dispatch(st, "POST", f"/v1/projects/{project}/locations/global/workloadIdentityPools",
                        {"workloadIdentityPoolId": "my-pool"}, {},
                        json.dumps({"displayName": "My pool"}).encode())
    _check("create pool 200", cwp.status == 200 and _jbody(cwp)["state"] == "ACTIVE")
    lwp = giam.dispatch(st, "GET", f"/v1/projects/{project}/locations/global/workloadIdentityPools", {}, {}, b"")
    _check("list pools has my-pool", "my-pool" in [p["name"].rsplit("/", 1)[-1] for p in _jbody(lwp)["workloadIdentityPools"]])
    gwp = giam.dispatch(st, "GET", f"/v1/projects/{project}/locations/global/workloadIdentityPools/my-pool", {}, {}, b"")
    _check("get pool 200", gwp.status == 200)
    dwp = giam.dispatch(st, "DELETE", f"/v1/projects/{project}/locations/global/workloadIdentityPools/my-pool", {}, {}, b"")
    _check("delete pool -> state DELETED", dwp.status == 200 and _jbody(dwp)["state"] == "DELETED")

    # 14b. service account patch + disable/enable -----------------------------
    sa3 = _jbody(_post(st, f"/v1/projects/{project}/serviceAccounts", {"accountId": "svc-patch", "serviceAccount": {}}))
    pch = giam.dispatch(st, "PATCH", f"/v1/projects/{project}/serviceAccounts/{sa3['email']}", {}, {},
                        json.dumps({"serviceAccount": {"displayName": "Patched", "description": "d2"}}).encode())
    _check("patch SA 200", pch.status == 200 and _jbody(pch)["displayName"] == "Patched" and _jbody(pch)["description"] == "d2")
    dis = _post(st, f"projects/{project}/serviceAccounts/{sa3['email']}:disable", {})
    _check("disable SA 200", dis.status == 200)
    got_dis = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa3['email']}", {}, {}, b"")
    _check("SA shows disabled", _jbody(got_dis)["disabled"] is True)
    en = _post(st, f"projects/{project}/serviceAccounts/{sa3['email']}:enable", {})
    _check("enable SA 200", en.status == 200)
    got_en = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa3['email']}", {}, {}, b"")
    _check("SA shows enabled", _jbody(got_en)["disabled"] is False)

    # 15. policy-change activity log (recommendations-history backing) -------
    act_project = f"{project}-activity"
    act_resource = f"projects/{act_project}"
    _post(st, f"/v1/{act_resource}:setIamPolicy",
          {"policy": {"bindings": [{"role": "roles/viewer", "members": ["user:a@example.com"]}]}})
    _post(st, f"/v1/{act_resource}:setIamPolicy", {"policy": {"bindings": []}})
    act = giam.dispatch(st, "GET", f"/v1/projects/{act_project}/policyActivity", {}, {}, b"")
    log = _jbody(act)["activity"]
    _check("activity has GRANT then REVOKE, most recent first",
           len(log) == 2 and log[0]["action"] == "REVOKE" and log[1]["action"] == "GRANT")
    _check("activity entry has role/member/time", bool(log[0]["role"]) and bool(log[0]["member"]) and bool(log[0]["time"]))

    # 16. per-service-account activity log (console SA detail 'Logs' tab) ----
    # Key create/delete, disable/enable and a Principals-with-access grant on the SA's
    # OWN resource all land in the same per-resource log, filtered by the SA's name.
    sa4 = _jbody(_post(st, f"/v1/projects/{project}/serviceAccounts", {"accountId": "svc-logs", "serviceAccount": {}}))
    sa4_resource = sa4["name"]
    ck4 = _post(st, f"/v1/projects/{project}/serviceAccounts/{sa4['email']}/keys", {})
    kid4 = _jbody(ck4)["name"].rsplit("/", 1)[-1]
    giam.dispatch(st, "DELETE", f"/v1/projects/{project}/serviceAccounts/{sa4['email']}/keys/{kid4}", {}, {}, b"")
    _post(st, f"projects/{project}/serviceAccounts/{sa4['email']}:disable", {})
    _post(st, f"projects/{project}/serviceAccounts/{sa4['email']}:enable", {})
    _post(st, f"/v1/{sa4_resource}:setIamPolicy",
          {"policy": {"bindings": [{"role": "roles/iam.serviceAccountUser", "members": ["user:dev@example.com"]}]}})
    sa_act = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa4['email']}/policyActivity", {}, {}, b"")
    _check("SA activity 200", sa_act.status == 200)
    sa_log = _jbody(sa_act)["activity"]
    actions = [e["action"] for e in sa_log]
    _check("SA log has CREATE_KEY, DELETE_KEY, DISABLE, ENABLE, GRANT",
           {"CREATE_KEY", "DELETE_KEY", "DISABLE", "ENABLE", "GRANT"} <= set(actions))
    _check("SA log most-recent-first", sa_log[0]["action"] == "GRANT")
    _check("SA log scoped to this SA only (project-level activity untouched)",
           all(e["resource"] == sa4_resource for e in sa_log))

    # 17. org policy enforcement (depth: config_only -> limited) -------------
    rm_st = grm.ResourceManagerStore()
    proj17 = f"{project}-orgpol"
    free = _jbody(giam.dispatch(st, "POST", f"/v1/projects/{proj17}/serviceAccounts", {}, {},
                                json.dumps({"accountId": "svc-free"}).encode(), rm_store=rm_st))
    _check("SA creation allowed with no org policy", free["email"].startswith("svc-free@"))
    grm.dispatch(rm_st, "POST", f"/v3/projects/{proj17}/policies",
                {"policyId": "constraints/iam.disableServiceAccountCreation"}, {},
                json.dumps({"spec": {"rules": [{"enforce": True}]}}).encode())
    blocked = giam.dispatch(st, "POST", f"/v1/projects/{proj17}/serviceAccounts", {}, {},
                            json.dumps({"accountId": "svc-blocked"}).encode(), rm_store=rm_st)
    _check("SA creation blocked by enforced org policy -> 412 FAILED_PRECONDITION",
           blocked.status == 412 and _jbody(blocked)["error"]["status"] == "FAILED_PRECONDITION")
    grm.dispatch(rm_st, "POST", f"/v3/projects/{proj17}/policies",
                {"policyId": "constraints/iam.disableServiceAccountKeyCreation"}, {},
                json.dumps({"spec": {"rules": [{"enforce": True}]}}).encode())
    key_blocked = giam.dispatch(st, "POST", f"/v1/projects/{proj17}/serviceAccounts/{free['email']}/keys",
                                {}, {}, b"{}", rm_store=rm_st)
    _check("key creation blocked by enforced org policy", key_blocked.status == 412)
    unaffected = giam.dispatch(st, "GET", f"/v1/projects/{proj17}/serviceAccounts/{free['email']}/keys",
                               {}, {}, b"", rm_store=rm_st)
    _check("reads (list keys) unaffected by the creation-only constraint", unaffected.status == 200)

    # 18. Data Access audit log config taking effect (depth: config_only -> limited) ---
    logged = []

    def _logger(proj, log_type, message):
        logged.append((proj, log_type, message))

    proj18 = f"{project}-audit"
    giam.dispatch(st, "GET", f"/v1/projects/{proj18}/serviceAccounts", {}, {}, b"", logger=_logger)
    _check("no entry when ADMIN_READ is not configured", logged == [])
    giam.dispatch(st, "POST", f"/v1/projects/{proj18}:setIamPolicy", {}, {},
                 json.dumps({"policy": {"auditConfigs": [
                     {"service": "iam.googleapis.com", "auditLogConfigs": [{"logType": "ADMIN_READ"}]}]}}).encode())
    giam.dispatch(st, "GET", f"/v1/projects/{proj18}/serviceAccounts", {}, {}, b"", logger=_logger)
    _check("ADMIN_READ enabled -> one entry logged", len(logged) == 1 and logged[0][0] == proj18
           and logged[0][1] == "ADMIN_READ")
    giam.dispatch(st, "POST", f"/v1/projects/{proj18}:setIamPolicy", {}, {},
                 json.dumps({"policy": {"auditConfigs": [
                     {"service": "iam.googleapis.com", "auditLogConfigs": [{"logType": "DATA_WRITE"}]}]}}).encode())
    giam.dispatch(st, "GET", f"/v1/projects/{proj18}/serviceAccounts", {}, {}, b"", logger=_logger)
    _check("DATA_WRITE toggle does not log a read", len(logged) == 1)

    # 19. service account Metrics tab — derived from real iamcredentials issuance ---
    iamc_st = giamc.shared_store()
    sa19 = _jbody(_post(st, f"/v1/projects/{project}/serviceAccounts", {"accountId": "svc-metrics"}))
    empty_metrics = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa19['email']}:metrics",
                                  {}, {}, b"", iamc_store=iamc_st)
    _check("metrics 200 with zero requests before any credential issuance",
           empty_metrics.status == 200 and _jbody(empty_metrics)["totalRequests"] == 0)
    giamc.generate_access_token(iamc_st, sa19["email"], {"scope": ["https://www.googleapis.com/auth/cloud-platform"]})
    giamc.sign_blob(iamc_st, sa19["email"], {"payload": "aGVsbG8="})
    m19 = giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa19['email']}:metrics",
                        {}, {}, b"", iamc_store=iamc_st)
    mbody = _jbody(m19)
    _check("metrics counts real issued credentials, not another SA's", mbody["totalRequests"] == 2)
    _check("metrics breaks down by method", {d["method"] for d in mbody["byMethod"]} == {"generateAccessToken", "signBlob"})
    _check("metrics unaffected by an unrelated SA's activity",
           _jbody(giam.dispatch(st, "GET", f"/v1/projects/{project}/serviceAccounts/{sa4['email']}:metrics",
                                {}, {}, b"", iamc_store=iamc_st))["totalRequests"] == 0)

    # 20. Managed Workload Identities — nested under a workload identity pool, real
    #     synthetic-cert lifecycle (create, rotate, delete) ------------------------
    pool20 = _jbody(giam.dispatch(st, "POST", f"/v1/projects/{project}/locations/global/workloadIdentityPools",
                                  {"workloadIdentityPoolId": "mwi-pool"}, {}, json.dumps({"displayName": "MWI pool"}).encode()))
    mi_create = giam.dispatch(st, "POST", f"/v1/{pool20['name']}/managedIdentities",
                              {"workloadIdentityPoolManagedIdentityId": "svc1"}, {}, b"{}")
    _check("create managed identity 200", mi_create.status == 200)
    mi20 = _jbody(mi_create)
    _check("managed identity has a SPIFFE id", mi20["spiffeId"].startswith("spiffe://"))
    _check("managed identity issued one certificate", len(mi20["certificates"]) == 1)
    rotated = _jbody(giam.dispatch(st, "POST", f"/v1/{mi20['name']}:rotateCertificate", {}, {}, b"{}"))
    _check("rotate issues a NEW certificate (different serial)",
           len(rotated["certificates"]) == 2 and rotated["certificates"][0]["serialNumber"] != rotated["certificates"][1]["serialNumber"])
    listed20 = _jbody(giam.dispatch(st, "GET", f"/v1/{pool20['name']}/managedIdentities", {}, {}, b""))
    _check("list managed identities has svc1", any(x["name"] == mi20["name"] for x in listed20["managedIdentities"]))
    del20 = giam.dispatch(st, "DELETE", f"/v1/{mi20['name']}", {}, {}, b"")
    _check("delete managed identity 200", del20.status == 200)
    _check("deleted managed identity 404s", giam.dispatch(st, "GET", f"/v1/{mi20['name']}", {}, {}, b"").status == 404)

    # 21. Asset Inventory — searchAllResources over real IAM + Resource Manager state --
    rm21 = grm.ResourceManagerStore()
    grm.dispatch(rm21, "GET", f"/v3/projects/{project}")  # auto-creates the project record
    assets = _jbody(giam.dispatch(st, "GET", f"/v1/projects/{project}:searchAllResources", {}, {}, b"", rm_store=rm21))
    types = {a["assetType"] for a in assets["results"]}
    _check("asset inventory indexes service accounts", "iam.googleapis.com/ServiceAccount" in types)
    _check("asset inventory indexes the project itself", "cloudresourcemanager.googleapis.com/Project" in types)
    filtered = _jbody(giam.dispatch(st, "GET", f"/v1/projects/{project}:searchAllResources",
                                    {"query": "svc-metrics"}, {}, b"", rm_store=rm21))
    _check("asset inventory query filters results", all("svc-metrics" in a["displayName"] for a in filtered["results"]) and filtered["results"])

    # 22. Security Insights — real lint over live policy/key/credential state --------
    sa22 = _jbody(_post(st, f"/v1/projects/{project}/serviceAccounts", {"accountId": "svc-insight"}))
    giam.dispatch(st, "POST", f"/v1/projects/{project}/serviceAccounts/{sa22['email']}/keys", {}, {}, b"{}")
    _post(st, f"/v1/projects/{project}:setIamPolicy",
          {"policy": {"bindings": [{"role": "roles/owner", "members": [f"serviceAccount:{sa22['email']}"]}]}})
    insights = _jbody(giam.dispatch(st, "GET", f"/v1/projects/{project}/locations/global/insights", {}, {}, b"", iamc_store=iamc_st))
    _check("insights flag the primitive-role grant",
           any("basic role roles/owner" in i["description"] for i in insights["insights"]))
    _check("insights flag the service account with user-managed keys",
           any(sa22["email"] in i["description"] and "user-managed key" in i["description"] for i in insights["insights"]))
    _check("insights flag the unused SA (no keys, never issued a credential)",
           any(sa4["email"] in i["description"] and "never issued a credential" in i["description"] for i in insights["insights"]))

    # 23. Identity-Aware Proxy — real per-resource toggle + the Allow decision it gates -
    iap_res = _jbody(giam.dispatch(st, "POST", f"/v1/projects/{project}/iap_web",
                                   {"resourceId": "app1"}, {}, json.dumps({"displayName": "App 1"}).encode()))
    denied = _jbody(giam.dispatch(st, "POST", f"/v1/{iap_res['name']}:checkAccess", {}, {},
                                  json.dumps({"member": "user:nobody@example.com"}).encode()))
    _check("checkAccess denies a member with no IAP role", denied["allowed"] is False)
    _post(st, f"/v1/{iap_res['name']}:setIamPolicy",
          {"policy": {"bindings": [{"role": "roles/iap.httpsResourceAccessor", "members": ["user:ok@example.com"]}]}})
    allowed = _jbody(giam.dispatch(st, "POST", f"/v1/{iap_res['name']}:checkAccess", {}, {},
                                   json.dumps({"member": "user:ok@example.com"}).encode()))
    _check("checkAccess allows a member holding iap.httpsResourceAccessor", allowed["allowed"] is True)
    giam.dispatch(st, "PATCH", f"/v1/{iap_res['name']}", {}, {}, json.dumps({"enabled": False}).encode())
    off = _jbody(giam.dispatch(st, "POST", f"/v1/{iap_res['name']}:checkAccess", {}, {},
                               json.dumps({"member": "user:ok@example.com"}).encode()))
    _check("checkAccess denies everyone once IAP is turned off", off["allowed"] is False and "turned off" in off["reason"])

    # 24. Principal Access Boundary — org-scoped policy + binding REALLY narrows access --
    rm24 = grm.ResourceManagerStore()
    org24 = grm.get_or_create_default_org(rm24)
    proj_in, proj_out = f"{project}-pab-in", f"{project}-pab-out"
    _post(st, f"/v1/projects/{proj_in}:setIamPolicy", {"policy": {"bindings": [{"role": "roles/owner", "members": ["user:bound@example.com"]}]}})
    _post(st, f"/v1/projects/{proj_out}:setIamPolicy", {"policy": {"bindings": [{"role": "roles/owner", "members": ["user:bound@example.com"]}]}})
    pol24 = _jbody(grm.dispatch(rm24, "POST", f"/v3/{org24['name']}/locations/global/principalAccessBoundaryPolicies",
                               {"principalAccessBoundaryPolicyId": "p1"}, {},
                               json.dumps({"details": {"rules": [{"resources": [f"projects/{proj_in}"]}]}}).encode()))
    grm.dispatch(rm24, "POST", f"/v3/{org24['name']}/locations/global/policyBindings",
                {"policyBindingId": "b1"}, {},
                json.dumps({"policy": pol24["name"], "target": {"principal": "user:bound@example.com"}}).encode())
    in_perm = _jbody(giam.dispatch(st, "POST", f"/v1/projects/{proj_in}:testIamPermissions", {}, {},
                                   json.dumps({"permissions": ["resourcemanager.projects.get"], "member": "user:bound@example.com"}).encode(),
                                   rm_store=rm24))
    out_perm = _jbody(giam.dispatch(st, "POST", f"/v1/projects/{proj_out}:testIamPermissions", {}, {},
                                    json.dumps({"permissions": ["resourcemanager.projects.get"], "member": "user:bound@example.com"}).encode(),
                                    rm_store=rm24))
    _check("PAB allows the in-boundary resource despite an owner binding existing elsewhere too",
           in_perm["permissions"] == ["resourcemanager.projects.get"])
    _check("PAB DENIES the same member+role on an out-of-boundary resource",
           out_perm["permissions"] == [])
    _post(st, f"/v1/projects/{proj_out}:setIamPolicy", {"policy": {"bindings": [{"role": "roles/owner", "members": ["user:free@example.com"]}]}})
    unbound = _jbody(giam.dispatch(st, "POST", f"/v1/projects/{proj_out}:testIamPermissions", {}, {},
                                   json.dumps({"permissions": ["resourcemanager.projects.get"], "member": "user:free@example.com"}).encode(),
                                   rm_store=rm24))
    _check("a member with no PAB binding at all keeps its normal grant on the same resource PAB blocks the bound member on",
           unbound["permissions"] == ["resourcemanager.projects.get"])

    print("\nGCP IAM-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
