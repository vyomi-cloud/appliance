"""Secrets Manager core conformance — the acceptance gate for the WASM extraction.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE AWS Secrets Manager wire semantics (secretsmanager.*
X-Amz-Target dispatch, ARN/VersionId shapes, SecretString/SecretBinary round-trip,
AWSCURRENT/AWSPREVIOUS version stages, GetSecretValue by VersionStage and by
VersionId, scheduled deletion blocking reads + restore, native {"__type",
"message"} errors) — proving the extracted core conforms regardless of substrate.
No network, no fastapi/boto3/hvac.

Run on host:    python3 tests/conformance/test_secrets_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""

# Allow running both as a repo script (host) and from a flat FS (Pyodide).
try:
    from core.kv_store import InMemoryKvStore
    from core import secrets_core as sm
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kv_store import InMemoryKvStore  # type: ignore
    import secrets_core as sm  # type: ignore

T = "secretsmanager."  # the native Secrets Manager X-Amz-Target prefix


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = InMemoryKvStore()

    # 1. CreateSecret -> ARN + VersionId
    r = sm.dispatch(st, T + "CreateSecret", {"Name": "db/password", "SecretString": "hunter2"})
    _check("create 200", r.status == 200)
    _check("create ARN", r.body["ARN"].endswith(":secret:db/password"))
    _check("create Name", r.body["Name"] == "db/password")
    v1 = r.body["VersionId"]
    _check("create VersionId is a uuid hex", len(v1) == 32)

    # 2. CreateSecret again -> ResourceExistsException
    dup = sm.dispatch(st, T + "CreateSecret", {"Name": "db/password", "SecretString": "x"})
    _check("duplicate ResourceExistsException", dup.body["__type"] == "ResourceExistsException")

    # 3. GetSecretValue (default AWSCURRENT) -> round-trips the value
    g = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "db/password"})
    _check("get 200", g.status == 200)
    _check("get SecretString round-trips", g.body["SecretString"] == "hunter2")
    _check("get VersionId = create version", g.body["VersionId"] == v1)
    _check("get stage AWSCURRENT", "AWSCURRENT" in g.body["VersionStages"])

    # 4. PutSecretValue -> new AWSCURRENT, old becomes AWSPREVIOUS
    p = sm.dispatch(st, T + "PutSecretValue", {"SecretId": "db/password", "SecretString": "hunter3"})
    v2 = p.body["VersionId"]
    _check("put new VersionId differs", v2 != v1)
    _check("put new version is AWSCURRENT", "AWSCURRENT" in p.body["VersionStages"])
    cur = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "db/password"})
    _check("current is the new value", cur.body["SecretString"] == "hunter3" and cur.body["VersionId"] == v2)
    prev = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "db/password", "VersionStage": "AWSPREVIOUS"})
    _check("AWSPREVIOUS is the old value", prev.body["SecretString"] == "hunter2" and prev.body["VersionId"] == v1)

    # 5. GetSecretValue by explicit VersionId
    byid = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "db/password", "VersionId": v1})
    _check("get by VersionId returns that version", byid.body["SecretString"] == "hunter2")

    # 6. Binary secret round-trips via SecretBinary (base64 string on the wire)
    sm.dispatch(st, T + "CreateSecret", {"Name": "blob", "SecretBinary": "AAECAwQ="})
    gb = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "blob"})
    _check("binary secret round-trips", gb.body.get("SecretBinary") == "AAECAwQ=")
    _check("binary secret has no SecretString", "SecretString" not in gb.body)

    # 7. DescribeSecret -> metadata + VersionIdsToStages (no secret value)
    d = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "db/password"})
    _check("describe has ARN", d.body["ARN"].endswith(":secret:db/password"))
    _check("describe VersionIdsToStages maps current+previous",
           d.body["VersionIdsToStages"].get(v2) == ["AWSCURRENT"] and "AWSPREVIOUS" in d.body["VersionIdsToStages"].get(v1, []))
    _check("describe leaks no value", "SecretString" not in d.body)

    # 8. ListSecretVersionIds -> both versions with stages
    lv = sm.dispatch(st, T + "ListSecretVersionIds", {"SecretId": "db/password"})
    ids = {v["VersionId"] for v in lv.body["Versions"]}
    _check("list-versions has both", ids == {v1, v2})

    # 9. ListSecrets -> both secrets (no values), excludes scheduled-deleted
    ls = sm.dispatch(st, T + "ListSecrets", {})
    names = {s["Name"] for s in ls.body["SecretList"]}
    _check("list-secrets has both", names == {"db/password", "blob"})

    # 10. UpdateSecret changes the value (new current version) + description
    up = sm.dispatch(st, T + "UpdateSecret", {"SecretId": "db/password", "SecretString": "hunter4", "Description": "rotated"})
    _check("update returns new version", up.body["VersionId"] not in (v1, v2))
    after = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "db/password"})
    _check("update applied", after.body["SecretString"] == "hunter4")
    _check("update description persisted",
           sm.dispatch(st, T + "DescribeSecret", {"SecretId": "db/password"}).body["Description"] == "rotated")

    # 11. DeleteSecret (scheduled) -> DeletionDate; GetSecretValue then blocked
    dl = sm.dispatch(st, T + "DeleteSecret", {"SecretId": "blob", "RecoveryWindowInDays": 7})
    _check("delete returns DeletionDate", "DeletionDate" in dl.body)
    blocked = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "blob"})
    _check("get on scheduled-deleted secret blocked", blocked.body["__type"] == "InvalidRequestException")
    _check("scheduled-deleted hidden from default ListSecrets",
           "blob" not in {s["Name"] for s in sm.dispatch(st, T + "ListSecrets", {}).body["SecretList"]})

    # 12. RestoreSecret -> readable again
    sm.dispatch(st, T + "RestoreSecret", {"SecretId": "blob"})
    restored = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "blob"})
    _check("restored secret readable", restored.body.get("SecretBinary") == "AAECAwQ=")

    # 13. ForceDeleteWithoutRecovery -> gone
    sm.dispatch(st, T + "DeleteSecret", {"SecretId": "blob", "ForceDeleteWithoutRecovery": True})
    gone = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "blob"})
    _check("force-deleted secret ResourceNotFound", gone.body["__type"] == "ResourceNotFoundException")

    # 14. SecretId may be the full ARN
    arn = after.body["ARN"]
    by_arn = sm.dispatch(st, T + "GetSecretValue", {"SecretId": arn})
    _check("get by ARN works", by_arn.body["SecretString"] == "hunter4")

    # 15. Unknown secret + missing target
    nf = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "nope"})
    _check("missing secret ResourceNotFoundException", nf.body["__type"] == "ResourceNotFoundException")
    noact = sm.dispatch(st, "", {})
    _check("missing target MissingAction", noact.body["__type"] == "MissingAction")

    # 16. Tags: set on create, then Tag/UntagResource
    sm.dispatch(st, T + "CreateSecret", {"Name": "tagged", "SecretString": "v", "Tags": [{"Key": "env", "Value": "prod"}],
                                          "KmsKeyId": "alias/custom"})
    dt = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "tagged"})
    _check("create Tags round-trip", dt.body["Tags"] == [{"Key": "env", "Value": "prod"}])
    _check("create KmsKeyId round-trips", dt.body["KmsKeyId"] == "alias/custom")
    sm.dispatch(st, T + "TagResource", {"SecretId": "tagged", "Tags": [{"Key": "team", "Value": "sec"}]})
    tagged = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "tagged"}).body["Tags"]
    _check("TagResource adds a tag", {"Key": "team", "Value": "sec"} in tagged and len(tagged) == 2)
    sm.dispatch(st, T + "UntagResource", {"SecretId": "tagged", "TagKeys": ["env"]})
    untagged = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "tagged"}).body["Tags"]
    _check("UntagResource removes a tag", untagged == [{"Key": "team", "Value": "sec"}])

    # 17. UpdateSecret with no value touches metadata only (no new version)
    before_v = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "tagged"}).body["VersionIdsToStages"]
    sm.dispatch(st, T + "UpdateSecret", {"SecretId": "tagged", "KmsKeyId": "alias/other"})
    after_v = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "tagged"})
    _check("metadata-only UpdateSecret creates no new version", after_v.body["VersionIdsToStages"] == before_v)
    _check("metadata-only UpdateSecret still updates KmsKeyId", after_v.body["KmsKeyId"] == "alias/other")

    # 18. RotateSecret flips rotation metadata + stages (same shape ListSecrets/DescribeSecret expose)
    rot = sm.dispatch(st, T + "RotateSecret", {"SecretId": "tagged", "RotationRules": {"AutomaticallyAfterDays": 30}})
    _check("rotate returns a VersionId", "VersionId" in rot.body)
    rdesc = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "tagged"}).body
    _check("rotation enabled reflected", rdesc["RotationEnabled"] is True)
    _check("rotation rules reflected", rdesc["RotationRules"] == {"AutomaticallyAfterDays": 30})
    _check("last rotated date set", "LastRotatedDate" in rdesc)

    # 19. GetSecretValue stamps LastAccessedDate (ListSecrets/DescribeSecret column)
    sm.dispatch(st, T + "GetSecretValue", {"SecretId": "tagged"})
    _check("last accessed date set", "LastAccessedDate" in sm.dispatch(st, T + "DescribeSecret", {"SecretId": "tagged"}).body)

    # 20. Resource policy: Get (none) -> Put -> Get (round-trips) -> Delete -> Get (gone)
    rp0 = sm.dispatch(st, T + "GetResourcePolicy", {"SecretId": "tagged"})
    _check("no resource policy initially", "ResourcePolicy" not in rp0.body)
    policy = '{"Version":"2012-10-17","Statement":[]}'
    sm.dispatch(st, T + "PutResourcePolicy", {"SecretId": "tagged", "ResourcePolicy": policy})
    rp1 = sm.dispatch(st, T + "GetResourcePolicy", {"SecretId": "tagged"})
    _check("resource policy round-trips", rp1.body["ResourcePolicy"] == policy)
    sm.dispatch(st, T + "DeleteResourcePolicy", {"SecretId": "tagged"})
    rp2 = sm.dispatch(st, T + "GetResourcePolicy", {"SecretId": "tagged"})
    _check("resource policy deleted", "ResourcePolicy" not in rp2.body)

    print("\nRESULT: PASS — Secrets Manager core conforms (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
