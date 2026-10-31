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
    from core.kms_keystore import InMemoryKeyStore
    from core.kv_store import InMemoryKvStore
    from core import kms_core as kms
    from core import secrets_core as sm
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    from kv_store import InMemoryKvStore  # type: ignore
    import kms_core as kms  # type: ignore
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
    policy = ('{"Version":"2012-10-17","Statement":[{"Effect":"Allow",'
              '"Principal":{"AWS":"arn:aws:iam::123456789012:root"},'
              '"Action":"secretsmanager:GetSecretValue","Resource":"*"}]}')
    sm.dispatch(st, T + "PutResourcePolicy", {"SecretId": "tagged", "ResourcePolicy": policy})
    rp1 = sm.dispatch(st, T + "GetResourcePolicy", {"SecretId": "tagged"})
    _check("resource policy round-trips", rp1.body["ResourcePolicy"] == policy)
    sm.dispatch(st, T + "DeleteResourcePolicy", {"SecretId": "tagged"})
    rp2 = sm.dispatch(st, T + "GetResourcePolicy", {"SecretId": "tagged"})
    _check("resource policy deleted", "ResourcePolicy" not in rp2.body)

    # 21. PutResourcePolicy validates shape (v4 depth pass)
    bad_json = sm.dispatch(st, T + "PutResourcePolicy", {"SecretId": "tagged", "ResourcePolicy": "not json"})
    _check("malformed JSON rejected", bad_json.body["__type"] == "MalformedPolicyDocumentException")
    no_statement = sm.dispatch(st, T + "PutResourcePolicy",
                               {"SecretId": "tagged", "ResourcePolicy": '{"Version":"2012-10-17","Statement":[]}'})
    _check("empty Statement rejected", no_statement.body["__type"] == "MalformedPolicyDocumentException")

    # 22. PutResourcePolicy blocks a public policy by default, allows it with BlockPublicPolicy=false
    public_policy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*","Action":"secretsmanager:GetSecretValue","Resource":"*"}]}'
    blocked = sm.dispatch(st, T + "PutResourcePolicy", {"SecretId": "tagged", "ResourcePolicy": public_policy})
    _check("public policy blocked by default", blocked.body["__type"] == "PublicPolicyException")
    allowed = sm.dispatch(st, T + "PutResourcePolicy",
                          {"SecretId": "tagged", "ResourcePolicy": public_policy, "BlockPublicPolicy": False})
    _check("public policy allowed with BlockPublicPolicy=false", allowed.status == 200)
    sm.dispatch(st, T + "DeleteResourcePolicy", {"SecretId": "tagged"})

    # 23. Automatic rotation really fires on its own schedule (lazy, on access — no Lambda,
    # so the "new" version carries the same value forward, same as RotateImmediately).
    sm.dispatch(st, T + "CreateSecret", {"Name": "not-due-yet", "SecretString": "v1"})
    nv1 = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "not-due-yet"}).body["VersionId"]
    sm.dispatch(st, T + "RotateSecret", {"SecretId": "not-due-yet",
               "RotationRules": {"AutomaticallyAfterDays": 30}, "RotateImmediately": False})
    still_v1 = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "not-due-yet"}).body["VersionId"]
    _check("a 30-day schedule does not fire immediately", still_v1 == nv1)

    sm.dispatch(st, T + "CreateSecret", {"Name": "auto-rotated", "SecretString": "v1"})
    v1 = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "auto-rotated"}).body["VersionId"]
    sm.dispatch(st, T + "RotateSecret", {"SecretId": "auto-rotated",
               "RotationRules": {"AutomaticallyAfterDays": 0}, "RotateImmediately": False})
    before = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "auto-rotated"}).body
    _check("rotation scheduled with a NextRotationDate", "NextRotationDate" in before)
    v2 = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "auto-rotated"}).body["VersionId"]  # AutomaticallyAfterDays=0 → already due
    _check("GetSecretValue lazily auto-rotates when due", v2 != v1)
    after = sm.dispatch(st, T + "DescribeSecret", {"SecretId": "auto-rotated"}).body
    _check("auto-rotation reschedules NextRotationDate forward", after["NextRotationDate"] > before["NextRotationDate"])

    # 24. A customer KmsKeyId is genuinely encrypted/decrypted through the KMS core
    # (v4 depth wave 5) when a kms_store is passed — every check above ran WITHOUT
    # one and must keep behaving exactly as before (plaintext stored as-is).
    ks = InMemoryKeyStore()
    key1 = kms.dispatch(ks, "TrentService.CreateKey", {}).body["KeyMetadata"]["KeyId"]
    key2 = kms.dispatch(ks, "TrentService.CreateKey", {}).body["KeyMetadata"]["KeyId"]
    sm.dispatch(st, T + "CreateSecret", {"Name": "cmk", "SecretString": "s3cr3t", "KmsKeyId": key1}, kms_store=ks)
    cmk_v1 = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "cmk"}, kms_store=ks).body
    _check("KMS-encrypted secret still round-trips plaintext", cmk_v1["SecretString"] == "s3cr3t")
    _check("KmsKeyId round-trips on DescribeSecret",
           sm.dispatch(st, T + "DescribeSecret", {"SecretId": "cmk"}, kms_store=ks).body["KmsKeyId"] == key1)

    # Disabling the key really blocks access — proof the value is actually
    # encrypted under it, not just stored next to a KmsKeyId label.
    kms.dispatch(ks, "TrentService.DisableKey", {"KeyId": key1})
    blocked_get = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "cmk"}, kms_store=ks)
    _check("GetSecretValue fails when the CMK is disabled", blocked_get.body.get("__type") == "InvalidRequestException")
    blocked_put = sm.dispatch(st, T + "PutSecretValue", {"SecretId": "cmk", "SecretString": "new"}, kms_store=ks)
    _check("PutSecretValue fails when the CMK is disabled", blocked_put.body.get("__type") == "InvalidRequestException")
    kms.dispatch(ks, "TrentService.EnableKey", {"KeyId": key1})
    _check("re-enabling the CMK restores access",
           sm.dispatch(st, T + "GetSecretValue", {"SecretId": "cmk"}, kms_store=ks).body["SecretString"] == "s3cr3t")

    # PutSecretValue (no explicit KmsKeyId) re-encrypts the new version under the
    # secret's existing key, and ClientRequestToken idempotency compares plaintext
    # (decrypting both sides) rather than raw ciphertext.
    put1 = sm.dispatch(st, T + "PutSecretValue",
                       {"SecretId": "cmk", "SecretString": "s3cr3t-2", "ClientRequestToken": "tok-1"}, kms_store=ks)
    _check("PutSecretValue under a CMK succeeds", put1.status == 200)
    retry = sm.dispatch(st, T + "PutSecretValue",
                        {"SecretId": "cmk", "SecretString": "s3cr3t-2", "ClientRequestToken": "tok-1"}, kms_store=ks)
    _check("idempotent retry (same value) returns the same version", retry.body["VersionId"] == put1.body["VersionId"])
    conflict = sm.dispatch(st, T + "PutSecretValue",
                           {"SecretId": "cmk", "SecretString": "different", "ClientRequestToken": "tok-1"}, kms_store=ks)
    _check("idempotent retry (different value) is ResourceExistsException",
           conflict.body.get("__type") == "ResourceExistsException")

    # UpdateSecret to a new KmsKeyId re-encrypts every existing version under it —
    # disabling the OLD key afterwards must NOT block access, proving the value
    # really moved to the new key (KMS embeds the key id in the ciphertext).
    sm.dispatch(st, T + "UpdateSecret", {"SecretId": "cmk", "KmsKeyId": key2}, kms_store=ks)
    _check("KmsKeyId updated", sm.dispatch(st, T + "DescribeSecret", {"SecretId": "cmk"}, kms_store=ks).body["KmsKeyId"] == key2)
    kms.dispatch(ks, "TrentService.DisableKey", {"KeyId": key1})
    still_ok = sm.dispatch(st, T + "GetSecretValue", {"SecretId": "cmk"}, kms_store=ks)
    _check("re-wrapped secret still readable after the OLD key is disabled",
           still_ok.status == 200 and still_ok.body["SecretString"] == "s3cr3t-2")
    kms.dispatch(ks, "TrentService.DisableKey", {"KeyId": key2})
    _check("re-wrapped secret now blocked once the NEW (current) key is disabled",
           sm.dispatch(st, T + "GetSecretValue", {"SecretId": "cmk"}, kms_store=ks).body.get("__type") == "InvalidRequestException")
    kms.dispatch(ks, "TrentService.EnableKey", {"KeyId": key2})

    # RotateSecret (immediate + lazy auto-rotation) carries the current, decrypted
    # value forward and re-encrypts it, under a kms_store.
    rotated = sm.dispatch(st, T + "RotateSecret", {"SecretId": "cmk"}, kms_store=ks)
    _check("RotateSecret works under a kms_store", rotated.status == 200)
    _check("rotated value still decrypts correctly",
           sm.dispatch(st, T + "GetSecretValue", {"SecretId": "cmk"}, kms_store=ks).body["SecretString"] == "s3cr3t-2")

    # A secret with no KmsKeyId is unaffected by kms_store being present — it
    # stays on the implicit default (no real encryption modeled for that path).
    sm.dispatch(st, T + "CreateSecret", {"Name": "no-cmk", "SecretString": "plain"}, kms_store=ks)
    _check("no-CMK secret has no KmsKeyId",
           "KmsKeyId" not in sm.dispatch(st, T + "DescribeSecret", {"SecretId": "no-cmk"}, kms_store=ks).body)
    _check("no-CMK secret still round-trips",
           sm.dispatch(st, T + "GetSecretValue", {"SecretId": "no-cmk"}, kms_store=ks).body["SecretString"] == "plain")

    print("\nRESULT: PASS — Secrets Manager core conforms (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
