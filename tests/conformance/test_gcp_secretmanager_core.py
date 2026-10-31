"""GCP Secret Manager core conformance — the GCP analogue of the AWS
test_secrets_core.py, in the GCS test style.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Secret Manager REST API v1** wire semantics (secret /
version resource names, ?secretId= create, :addVersion / :access custom methods,
base64 payload round-trip, auto-incrementing integer versions, "latest" alias,
delete then 404 NOT_FOUND), proving google-cloud-secret-manager can drive the
core unchanged.

Run on host:    python3 tests/conformance/test_gcp_secretmanager_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import json

try:
    from core.kv_store import InMemoryKvStore
    from core import gcp_secretmanager_core as sm
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kv_store import InMemoryKvStore  # type: ignore
    import gcp_secretmanager_core as sm  # type: ignore

PROJECT = "demo-project"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def run() -> int:
    st = InMemoryKvStore()
    base = f"/v1/projects/{PROJECT}/secrets"

    # 1. create secret -> 200 secret resource with canonical name
    r = sm.dispatch(st, "POST", base, {"secretId": "db-password"},
                    {"content-type": "application/json"},
                    json.dumps({"replication": {"automatic": {}}}).encode())
    _check("create secret 200", r.status == 200)
    body = _jbody(r)
    _check("create secret name", body["name"] == f"projects/{PROJECT}/secrets/db-password")
    _check("create secret createTime present", "createTime" in body)
    _check("create secret replication echoed", body["replication"] == {"automatic": {}})

    # 1b. duplicate secret -> 409 ALREADY_EXISTS
    dup = sm.dispatch(st, "POST", base, {"secretId": "db-password"},
                      {"content-type": "application/json"},
                      json.dumps({"replication": {"automatic": {}}}).encode())
    _check("duplicate secret 409", dup.status == 409)
    _check("duplicate secret ALREADY_EXISTS", _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 2. addVersion -> versions/1, ENABLED
    secret1 = b"super-secret-value-1"
    av = sm.dispatch(st, "POST", f"{base}/db-password:addVersion", {},
                     {"content-type": "application/json"},
                     json.dumps({"payload": {"data": _b64(secret1)}}).encode())
    _check("addVersion 200", av.status == 200)
    avb = _jbody(av)
    _check("addVersion name versions/1", avb["name"] == f"projects/{PROJECT}/secrets/db-password/versions/1")
    _check("addVersion state ENABLED", avb["state"] == "ENABLED")

    # 3. access latest -> exact bytes round-trip via base64
    ac = sm.dispatch(st, "GET", f"{base}/db-password/versions/latest:access", {}, {}, b"")
    _check("access latest 200", ac.status == 200)
    acb = _jbody(ac)
    _check("access latest name versions/1", acb["name"].endswith("/versions/1"))
    _check("access latest bytes round-trip", base64.b64decode(acb["payload"]["data"]) == secret1)

    # 3b. access by explicit version number 1
    ac1 = sm.dispatch(st, "GET", f"{base}/db-password/versions/1:access", {}, {}, b"")
    _check("access v1 bytes round-trip", base64.b64decode(_jbody(ac1)["payload"]["data"]) == secret1)

    # 4. add second version -> versions/2 and latest reflects it
    secret2 = b"rotated-secret-value-2"
    av2 = sm.dispatch(st, "POST", f"{base}/db-password:addVersion", {},
                      {"content-type": "application/json"},
                      json.dumps({"payload": {"data": _b64(secret2)}}).encode())
    _check("addVersion 2 name versions/2", _jbody(av2)["name"].endswith("/versions/2"))
    ac2 = sm.dispatch(st, "GET", f"{base}/db-password/versions/latest:access", {}, {}, b"")
    acb2 = _jbody(ac2)
    _check("latest now versions/2", acb2["name"].endswith("/versions/2"))
    _check("latest bytes = second version", base64.b64decode(acb2["payload"]["data"]) == secret2)
    # v1 still independently accessible
    ac1b = sm.dispatch(st, "GET", f"{base}/db-password/versions/1:access", {}, {}, b"")
    _check("v1 still returns first bytes", base64.b64decode(_jbody(ac1b)["payload"]["data"]) == secret1)

    # 5. list secrets + list versions
    ls = sm.dispatch(st, "GET", base, {}, {}, b"")
    lsb = _jbody(ls)
    _check("list secrets totalSize 1", lsb["totalSize"] == 1)
    _check("list secrets has db-password",
           any(s["name"].endswith("/secrets/db-password") for s in lsb["secrets"]))
    lv = sm.dispatch(st, "GET", f"{base}/db-password/versions", {}, {}, b"")
    lvb = _jbody(lv)
    _check("list versions has both", lvb["totalSize"] == 2)

    # 6. delete secret -> 200, then access -> 404 NOT_FOUND
    dele = sm.dispatch(st, "DELETE", f"{base}/db-password", {}, {}, b"")
    _check("delete secret 200", dele.status == 200)
    miss = sm.dispatch(st, "GET", f"{base}/db-password/versions/latest:access", {}, {}, b"")
    _check("deleted secret access 404", miss.status == 404)
    _check("deleted secret NOT_FOUND", _jbody(miss)["error"]["status"] == "NOT_FOUND")

    # 7. create with labels, annotations, rotation, ttl, topics, versionAliases -> all echoed
    create2 = sm.dispatch(st, "POST", base, {"secretId": "api-key"}, {}, json.dumps({
        "replication": {"automatic": {}},
        "labels": {"env": "prod"},
        "annotations": {"owner": "team-x"},
        "rotation": {"rotationPeriod": "2592000s"},
        "ttl": "86400s",
        "topics": [{"name": "projects/demo-project/topics/notify"}],
        "versionAliases": {"stable": 1},
    }).encode())
    _check("create2 200", create2.status == 200)
    c2b = _jbody(create2)
    _check("create2 labels echoed", c2b["labels"] == {"env": "prod"})
    _check("create2 annotations echoed", c2b["annotations"] == {"owner": "team-x"})
    _check("create2 rotation echoed", c2b["rotation"] == {"rotationPeriod": "2592000s"})
    _check("create2 ttl converted to expireTime", "expireTime" in c2b)
    _check("create2 topics echoed", c2b["topics"][0]["name"].endswith("/topics/notify"))
    _check("create2 versionAliases echoed", c2b["versionAliases"] == {"stable": 1})

    # 8. patch secret (updateMask=labels) -> only labels change
    patch = sm.dispatch(st, "PATCH", f"{base}/api-key", {"updateMask": "labels"}, {},
                        json.dumps({"labels": {"env": "staging"}, "annotations": {"owner": "team-y"}}).encode())
    _check("patch secret 200", patch.status == 200)
    pb = _jbody(patch)
    _check("patch updates labels", pb["labels"] == {"env": "staging"})
    _check("patch respects updateMask (annotations untouched)", pb["annotations"] == {"owner": "team-x"})

    # 8b. patch secret with no updateMask -> every field present in the body applies
    patch2 = sm.dispatch(st, "PATCH", f"{base}/api-key", {}, {},
                         json.dumps({"annotations": {"owner": "team-z"}}).encode())
    _check("patch2 updates annotations with no updateMask", _jbody(patch2)["annotations"] == {"owner": "team-z"})

    # 8c. patch unknown secret -> 404
    pmiss = sm.dispatch(st, "PATCH", f"{base}/does-not-exist", {}, {}, json.dumps({"labels": {}}).encode())
    _check("patch unknown secret 404", pmiss.status == 404)

    # 9. replication: structural validation + immutability (v4 DEPTH)
    both = sm.dispatch(st, "POST", base, {"secretId": "rep-both"}, {},
                       json.dumps({"replication": {"automatic": {}, "userManaged": {"replicas": [{"location": "us-east1"}]}}}).encode())
    _check("replication both -> 400", both.status == 400)
    empty_um = sm.dispatch(st, "POST", base, {"secretId": "rep-empty"}, {},
                           json.dumps({"replication": {"userManaged": {"replicas": []}}}).encode())
    _check("replication empty userManaged -> 400", empty_um.status == 400)
    dup_loc = sm.dispatch(st, "POST", base, {"secretId": "rep-dup"}, {}, json.dumps({
        "replication": {"userManaged": {"replicas": [{"location": "us-east1"}, {"location": "us-east1"}]}},
    }).encode())
    _check("replication duplicate location -> 400", dup_loc.status == 400)
    bad_cmek = sm.dispatch(st, "POST", base, {"secretId": "rep-badcmek"}, {},
                           json.dumps({"replication": {"automatic": {"customerManagedEncryption": {"kmsKeyName": "not-a-key"}}}}).encode())
    _check("replication bad CMEK name -> 400", bad_cmek.status == 400)
    mismatched_cmek = sm.dispatch(st, "POST", base, {"secretId": "rep-mismatch"}, {}, json.dumps({
        "replication": {"userManaged": {"replicas": [{
            "location": "us-east1",
            "customerManagedEncryption": {"kmsKeyName": "projects/demo-project/locations/us-west1/keyRings/r/cryptoKeys/k"},
        }]}},
    }).encode())
    _check("replication CMEK location mismatch -> 400", mismatched_cmek.status == 400)
    good_rep = sm.dispatch(st, "POST", base, {"secretId": "rep-good"}, {}, json.dumps({
        "replication": {"userManaged": {"replicas": [{
            "location": "us-east1",
            "customerManagedEncryption": {"kmsKeyName": "projects/demo-project/locations/us-east1/keyRings/r/cryptoKeys/k"},
        }]}},
    }).encode())
    _check("replication valid userManaged+CMEK -> 200", good_rep.status == 200)
    immut = sm.dispatch(st, "PATCH", f"{base}/rep-good", {}, {}, json.dumps({"replication": {"automatic": {}}}).encode())
    _check("replication immutable on patch -> 400", immut.status == 400)

    # 10. rotation: real pre-conditions (v4 DEPTH)
    rot_no_topic = sm.dispatch(st, "POST", base, {"secretId": "rot-no-topic"}, {},
                               json.dumps({"rotation": {"rotationPeriod": "604800s"}}).encode())
    _check("rotation without topic -> 400", rot_no_topic.status == 400)
    rot_short = sm.dispatch(st, "POST", base, {"secretId": "rot-short"}, {}, json.dumps({
        "rotation": {"rotationPeriod": "60s"}, "topics": [{"name": "projects/demo-project/topics/t"}],
    }).encode())
    _check("rotation period < 1h -> 400", rot_short.status == 400)
    rot_past = sm.dispatch(st, "POST", base, {"secretId": "rot-past"}, {}, json.dumps({
        "rotation": {"nextRotationTime": "2000-01-01T00:00:00Z"}, "topics": [{"name": "projects/demo-project/topics/t"}],
    }).encode())
    _check("rotation nextRotationTime in the past -> 400", rot_past.status == 400)
    rot_ok = sm.dispatch(st, "POST", base, {"secretId": "rot-ok"}, {}, json.dumps({
        "rotation": {"rotationPeriod": "604800s"}, "topics": [{"name": "projects/demo-project/topics/t"}],
    }).encode())
    _check("rotation with topic + valid period -> 200", rot_ok.status == 200)
    rot_drop_topic = sm.dispatch(st, "PATCH", f"{base}/rot-ok", {"updateMask": "topics"}, {},
                                 json.dumps({"topics": []}).encode())
    _check("dropping the last topic while rotation active -> 400", rot_drop_topic.status == 400)

    # 11. expiration: a secret past expireTime is actually deleted on next read (v4 DEPTH)
    sm.dispatch(st, "POST", base, {"secretId": "exp-secret"}, {}, json.dumps({"expireTime": "2000-01-01T00:00:00.000000Z"}).encode())
    exp_get = sm.dispatch(st, "GET", f"{base}/exp-secret", {}, {}, b"")
    _check("expired secret get -> 404 (auto-deleted)", exp_get.status == 404)
    exp_list = sm.dispatch(st, "GET", base, {}, {}, b"")
    _check("expired secret absent from list", not any(s["name"].endswith("/exp-secret") for s in _jbody(exp_list)["secrets"]))
    recreate = sm.dispatch(st, "POST", base, {"secretId": "exp-secret"}, {}, json.dumps({}).encode())
    _check("expired secret id can be recreated", recreate.status == 200)

    # 12. version aliases resolve wherever a version number/"latest" is accepted (v4 DEPTH)
    bad_alias = sm.dispatch(st, "POST", base, {"secretId": "alias-bad"}, {},
                            json.dumps({"versionAliases": {"latest": 1}}).encode())
    _check("alias named 'latest' -> 400", bad_alias.status == 400)
    sm.dispatch(st, "POST", base, {"secretId": "aliased"}, {}, json.dumps({}).encode())
    sm.dispatch(st, "POST", f"{base}/aliased:addVersion", {}, {}, json.dumps({"payload": {"data": _b64(b"v1")}}).encode())
    sm.dispatch(st, "PATCH", f"{base}/aliased", {"updateMask": "versionAliases"}, {},
               json.dumps({"versionAliases": {"stable": 1}}).encode())
    via_alias = sm.dispatch(st, "GET", f"{base}/aliased/versions/stable:access", {}, {}, b"")
    _check("access by alias", via_alias.status == 200 and base64.b64decode(_jbody(via_alias)["payload"]["data"]) == b"v1")
    disable_alias = sm.dispatch(st, "POST", f"{base}/aliased/versions/stable:disable", {}, {}, b"")
    _check("disable by alias", disable_alias.status == 200 and _jbody(disable_alias)["state"] == "DISABLED")
    unknown_alias = sm.dispatch(st, "GET", f"{base}/aliased/versions/nope:access", {}, {}, b"")
    _check("unknown alias -> 404", unknown_alias.status == 404)

    # 13. permissions: a real, enforced per-secret IAM policy (v4 DEPTH) — unlike GCP KMS/
    # Pub/Sub's store-only policy, this one actually denies.
    sm.dispatch(st, "POST", base, {"secretId": "locked"}, {}, json.dumps({}).encode())
    sm.dispatch(st, "POST", f"{base}/locked:addVersion", {}, {}, json.dumps({"payload": {"data": _b64(b"locked-v1")}}).encode())
    default_pol = sm.dispatch(st, "GET", f"{base}/locked:getIamPolicy", {}, {}, b"")
    _check("getIamPolicy default empty", default_pol.status == 200 and _jbody(default_pol)["bindings"] == [])
    set_pol = sm.dispatch(st, "POST", f"{base}/locked:setIamPolicy", {}, {}, json.dumps({
        "policy": {"bindings": [{"role": "roles/secretmanager.secretAccessor", "members": ["user:alice@example.com"]}]},
    }).encode())
    _check("setIamPolicy 200", set_pol.status == 200)
    bad_pol = sm.dispatch(st, "POST", f"{base}/locked:setIamPolicy", {}, {},
                          json.dumps({"policy": {"bindings": [{"role": "roles/x", "members": []}]}}).encode())
    _check("setIamPolicy rejects empty members -> 400", bad_pol.status == 400)
    denied = sm.dispatch(st, "GET", f"{base}/locked/versions/latest:access", {},
                         {"X-Cloudlearn-Principal": "bob@example.com"}, b"")
    _check("access denied for ungranted principal -> 403", denied.status == 403)
    allowed = sm.dispatch(st, "GET", f"{base}/locked/versions/latest:access", {},
                          {"X-Cloudlearn-Principal": "alice@example.com"}, b"")
    _check("access allowed for granted principal", allowed.status == 200)
    owner_bypass = sm.dispatch(st, "GET", f"{base}/locked/versions/latest:access", {}, {}, b"")
    _check("access allowed with no principal header (owner bypass)", owner_bypass.status == 200)
    test_perms = sm.dispatch(st, "POST", f"{base}/locked:testIamPermissions", {},
                             {"X-Cloudlearn-Principal": "bob@example.com"},
                             json.dumps({"permissions": ["secretmanager.versions.access", "secretmanager.secrets.delete"]}).encode())
    _check("testIamPermissions narrows to granted set", _jbody(test_perms).get("permissions", []) == [])
    test_perms_alice = sm.dispatch(st, "POST", f"{base}/locked:testIamPermissions", {},
                                   {"X-Cloudlearn-Principal": "alice@example.com"},
                                   json.dumps({"permissions": ["secretmanager.versions.access", "secretmanager.secrets.delete"]}).encode())
    _check("testIamPermissions grants what alice holds", _jbody(test_perms_alice)["permissions"] == ["secretmanager.versions.access"])

    # 14. notifier (Pub/Sub) + logger (Cloud Logging) callbacks — wired by core/aws_wire_router.py
    # in production; the conformance test drives them directly with plain collectors.
    notified, logged = [], []
    notifier = lambda topic, event, name: notified.append((topic, event, name))
    logger = lambda name, event, message: logged.append((name, event, message))
    sm.dispatch(st, "POST", base, {"secretId": "notify-secret"}, {}, json.dumps({
        "topics": [{"name": "projects/demo-project/topics/notify-me"}],
    }).encode(), notifier=notifier, logger=logger)
    sm.dispatch(st, "POST", f"{base}/notify-secret:addVersion", {}, {},
               json.dumps({"payload": {"data": _b64(b"n1")}}).encode(), notifier=notifier, logger=logger)
    sm.dispatch(st, "POST", f"{base}/notify-secret/versions/1:disable", {}, {}, b"", notifier=notifier, logger=logger)
    _check("notifier fired on addVersion", ("projects/demo-project/topics/notify-me", "SECRET_VERSION_ADD", "projects/demo-project/secrets/notify-secret") in notified)
    _check("notifier fired on disable", any(e == "SECRET_VERSION_DISABLE" for _, e, _ in notified))
    _check("logger fired on create", any(e == "SECRET_CREATE" for _, e, _ in logged))
    _check("logger fired on addVersion", any(e == "SECRET_VERSION_ADD" for _, e, _ in logged))
    exp_logged = []
    sm.dispatch(st, "POST", base, {"secretId": "exp-logged"}, {}, json.dumps({"expireTime": "2000-01-01T00:00:00.000000Z"}).encode())
    sm.dispatch(st, "GET", f"{base}/exp-logged", {}, {}, b"", logger=lambda n, e, m: exp_logged.append(e))
    _check("logger fired on auto-expire", "SECRET_EXPIRE" in exp_logged)

    # 15. REGIONAL secrets (v4 DEPTH): projects/{p}/locations/{l}/secrets — a distinct
    # resource from the global one above, with no replication policy (it IS the one
    # location) but the same version lifecycle, labels, rotation, IAM and logging.
    rbase = f"/v1/projects/{PROJECT}/locations/us-east1/secrets"
    rcreate = sm.dispatch(st, "POST", rbase, {"secretId": "db-password"}, {}, json.dumps({}).encode())
    _check("regional create 200", rcreate.status == 200)
    rcb = _jbody(rcreate)
    _check("regional create name includes location",
           rcb["name"] == f"projects/{PROJECT}/locations/us-east1/secrets/db-password")
    _check("regional create has no replication field", "replication" not in rcb)
    # Same secretId as the global secret deleted earlier (step 6) — distinct resource space.
    gcreate = sm.dispatch(st, "GET", base, {}, {}, b"")
    _check("regional secret absent from the GLOBAL list",
           not any(s["name"].endswith("/locations/us-east1/secrets/db-password") for s in _jbody(gcreate)["secrets"]))
    rlist = sm.dispatch(st, "GET", rbase, {}, {}, b"")
    _check("regional list totalSize 1", _jbody(rlist)["totalSize"] == 1)

    rav = sm.dispatch(st, "POST", f"{rbase}/db-password:addVersion", {}, {},
                      json.dumps({"payload": {"data": _b64(b"regional-v1")}}).encode())
    _check("regional addVersion name has location", _jbody(rav)["name"] ==
           f"projects/{PROJECT}/locations/us-east1/secrets/db-password/versions/1")
    rac = sm.dispatch(st, "GET", f"{rbase}/db-password/versions/latest:access", {}, {}, b"")
    _check("regional access round-trip", base64.b64decode(_jbody(rac)["payload"]["data"]) == b"regional-v1")

    # Bad / mismatched CMEK rejected the same way global's replication validation is.
    rbad = sm.dispatch(st, "POST", rbase, {"secretId": "bad-cmek"}, {},
                       json.dumps({"customerManagedEncryption": {"kmsKeyName": "not-a-key"}}).encode())
    _check("regional bad CMEK name -> 400", rbad.status == 400)
    rmismatch = sm.dispatch(st, "POST", rbase, {"secretId": "mismatch-cmek"}, {}, json.dumps({
        "customerManagedEncryption": {"kmsKeyName": f"projects/{PROJECT}/locations/us-west1/keyRings/r/cryptoKeys/k"},
    }).encode())
    _check("regional CMEK location mismatch -> 400", rmismatch.status == 400)
    rgood = sm.dispatch(st, "POST", rbase, {"secretId": "good-cmek"}, {}, json.dumps({
        "customerManagedEncryption": {"kmsKeyName": f"projects/{PROJECT}/locations/us-east1/keyRings/r/cryptoKeys/k"},
    }).encode())
    _check("regional valid CMEK -> 200", rgood.status == 200)
    _check("regional CMEK echoed", "customerManagedEncryption" in _jbody(rgood))
    rimmut = sm.dispatch(st, "PATCH", f"{rbase}/good-cmek", {}, {},
                        json.dumps({"customerManagedEncryption": {"kmsKeyName": "x"}}).encode())
    _check("regional CMEK immutable on patch -> 400", rimmut.status == 400)

    # Permissions + delete, scoped to the regional resource.
    rdenied = sm.dispatch(st, "GET", f"{rbase}/db-password/versions/latest:access", {},
                          {"X-Cloudlearn-Principal": "bob@example.com"}, b"")
    rpol = sm.dispatch(st, "POST", f"{rbase}/db-password:setIamPolicy", {}, {}, json.dumps({
        "policy": {"bindings": [{"role": "roles/secretmanager.secretAccessor", "members": ["user:bob@example.com"]}]},
    }).encode())
    _check("regional setIamPolicy 200", rpol.status == 200)
    rallowed = sm.dispatch(st, "GET", f"{rbase}/db-password/versions/latest:access", {},
                           {"X-Cloudlearn-Principal": "bob@example.com"}, b"")
    _check("regional access allowed after grant", rallowed.status == 200)

    rdel = sm.dispatch(st, "DELETE", f"{rbase}/db-password", {}, {}, b"")
    _check("regional delete 200", rdel.status == 200)
    rmiss = sm.dispatch(st, "GET", f"{rbase}/db-password", {}, {}, b"")
    _check("regional deleted secret get -> 404", rmiss.status == 404)
    # The global secret namespace is untouched by the regional delete.
    gstill = sm.dispatch(st, "GET", base, {}, {}, b"")
    _check("global list unaffected by regional delete", _jbody(gstill)["totalSize"] >= 1)

    print("\nGCP Secret Manager core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
