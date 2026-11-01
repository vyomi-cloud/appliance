"""SSM core conformance — host + Pyodide. Parameter Store lifecycle/history/labels/paths,
documents, Run Command, associations, maintenance windows, patch baselines, tags, errors."""
try:
    from core.kms_keystore import InMemoryKeyStore
    from core import kms_core as kms
    from core import ssm_core as ssm
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import kms_core as kms  # type: ignore
    import ssm_core as ssm  # type: ignore

T = "AmazonSSM."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or ssm.SsmStore()

    def call(op, body=None):
        r = ssm.dispatch(s, T + op, body or {})
        return r.status, r.body

    def err(op, body, code):
        st, b = call(op, body)
        return st == 400 and b.get("__type") == code

    st, b = call("PutParameter", {"Name": "/app/db/host", "Value": "db.local", "Type": "String", "Description": "d", "Tags": [{"Key": "env", "Value": "dev"}]})
    _check("PutParameter → Version 1 Tier Standard", st == 200 and b == {"Version": 1, "Tier": "Standard"})
    _check("PutParameter existing without Overwrite → ParameterAlreadyExists", err("PutParameter", {"Name": "/app/db/host", "Value": "x", "Type": "String"}, "ParameterAlreadyExists"))
    _check("PutParameter without Type on create → ValidationException", err("PutParameter", {"Name": "/n/t", "Value": "x"}, "ValidationException"))
    _check("PutParameter reserved prefix → ValidationException", err("PutParameter", {"Name": "/ssm/x", "Value": "x", "Type": "String"}, "ValidationException"))
    _check("Overwrite + Tags → InvalidParameters", err("PutParameter", {"Name": "/app/db/host", "Value": "x", "Overwrite": True, "Tags": [{"Key": "a", "Value": "b"}]}, "InvalidParameters"))
    st, b = call("PutParameter", {"Name": "/app/db/host", "Value": "db2.local", "Overwrite": True})
    _check("Overwrite → Version 2", b["Version"] == 2)
    st, b = call("GetParameter", {"Name": "/app/db/host"})
    p = b["Parameter"]
    _check("GetParameter shape", p["Value"] == "db2.local" and p["Version"] == 2 and p["Type"] == "String" and p["ARN"] == "arn:aws:ssm:us-east-1:000000000000:parameter/app/db/host" and isinstance(p["LastModifiedDate"], float))
    _check("GetParameter by version selector", call("GetParameter", {"Name": "/app/db/host:1"})[1]["Parameter"]["Value"] == "db.local")
    _check("GetParameter unknown version → ParameterVersionNotFound", err("GetParameter", {"Name": "/app/db/host:9"}, "ParameterVersionNotFound"))
    _check("GetParameter missing → ParameterNotFound", err("GetParameter", {"Name": "/nope"}, "ParameterNotFound"))
    st, b = call("LabelParameterVersion", {"Name": "/app/db/host", "ParameterVersion": 1, "Labels": ["123", "ok-1"]})
    _check("LabelParameterVersion reports invalid labels", b["InvalidLabels"] == ["123"])
    call("LabelParameterVersion", {"Name": "/app/db/host", "ParameterVersion": 1, "Labels": ["prod"]})
    _check("GetParameter by label", call("GetParameter", {"Name": "/app/db/host:prod"})[1]["Parameter"]["Version"] == 1)
    st, b = call("GetParameterHistory", {"Name": "/app/db/host"})
    _check("GetParameterHistory lists both versions with labels", [h["Version"] for h in b["Parameters"]] == [1, 2] and "prod" in b["Parameters"][0]["Labels"])
    st, b = call("PutParameter", {"Name": "/app/secret", "Value": "s3cr3t", "Type": "SecureString"})
    _check("SecureString stored", st == 200)
    _check("SecureString hidden without WithDecryption", call("GetParameter", {"Name": "/app/secret"})[1]["Parameter"]["Value"] != "s3cr3t")
    _check("SecureString decrypted with WithDecryption", call("GetParameter", {"Name": "/app/secret", "WithDecryption": True})[1]["Parameter"]["Value"] == "s3cr3t")
    call("PutParameter", {"Name": "/app/nested/deep/x", "Value": "1", "Type": "String"})
    call("PutParameter", {"Name": "/other/y", "Value": "1", "Type": "StringList"})
    st, b = call("GetParametersByPath", {"Path": "/app"})
    _check("GetParametersByPath non-recursive", sorted(x["Name"] for x in b["Parameters"]) == ["/app/secret"])
    st, b = call("GetParametersByPath", {"Path": "/app", "Recursive": True})
    _check("GetParametersByPath recursive", len(b["Parameters"]) == 3)
    _check("GetParametersByPath bad path → ValidationException", err("GetParametersByPath", {"Path": "app"}, "ValidationException"))
    st, b = call("GetParameters", {"Names": ["/app/db/host", "/missing"]})
    _check("GetParameters splits InvalidParameters", len(b["Parameters"]) == 1 and b["InvalidParameters"] == ["/missing"])
    st, b = call("DescribeParameters", {"MaxResults": 2})
    _check("DescribeParameters paginates", len(b["Parameters"]) == 2 and "NextToken" in b)
    st, b2 = call("DescribeParameters", {"MaxResults": 10, "NextToken": b["NextToken"]})
    _check("DescribeParameters NextToken continues", len(b2["Parameters"]) == 2)
    st, b = call("DescribeParameters", {"ParameterFilters": [{"Key": "Type", "Values": ["SecureString"]}]})
    _check("DescribeParameters Type filter + KeyId", len(b["Parameters"]) == 1 and b["Parameters"][0]["KeyId"] == "alias/aws/ssm")
    st, b = call("DescribeParameters", {"ParameterFilters": [{"Key": "Name", "Option": "BeginsWith", "Values": ["/other"]}]})
    _check("DescribeParameters Name BeginsWith", [x["Name"] for x in b["Parameters"]] == ["/other/y"])
    _check("AllowedPattern mismatch", (call("PutParameter", {"Name": "/pat", "Value": "abc", "Type": "String", "AllowedPattern": "^[0-9]+$"})[1]["__type"] == "ParameterPatternMismatchException"))
    _check("Standard tier size limit", err("PutParameter", {"Name": "/big", "Value": "x" * 5000, "Type": "String"}, "ValidationException"))
    _check("Advanced tier takes 5000 chars", call("PutParameter", {"Name": "/big", "Value": "x" * 5000, "Type": "String", "Tier": "Advanced"})[1]["Tier"] == "Advanced")

    call("AddTagsToResource", {"ResourceType": "Parameter", "ResourceId": "/app/db/host", "Tags": [{"Key": "team", "Value": "a"}]})
    _check("ListTagsForResource", {t["Key"] for t in call("ListTagsForResource", {"ResourceType": "Parameter", "ResourceId": "/app/db/host"})[1]["TagList"]} == {"env", "team"})
    call("RemoveTagsFromResource", {"ResourceType": "Parameter", "ResourceId": "/app/db/host", "TagKeys": ["env"]})
    _check("RemoveTagsFromResource", [t["Key"] for t in call("ListTagsForResource", {"ResourceType": "Parameter", "ResourceId": "/app/db/host"})[1]["TagList"]] == ["team"])
    _check("Tags on unknown resource → InvalidResourceId", err("ListTagsForResource", {"ResourceType": "Parameter", "ResourceId": "/zzz"}, "InvalidResourceId"))

    _check("DeleteParameter", call("DeleteParameter", {"Name": "/other/y"})[0] == 200)
    _check("DeleteParameter again → ParameterNotFound", err("DeleteParameter", {"Name": "/other/y"}, "ParameterNotFound"))
    st, b = call("DeleteParameters", {"Names": ["/big", "/gone"]})
    _check("DeleteParameters", b == {"DeletedParameters": ["/big"], "InvalidParameters": ["/gone"]})

    # documents
    content = '{"schemaVersion":"2.2","description":"hello","mainSteps":[]}'
    st, b = call("CreateDocument", {"Name": "my-doc", "Content": content, "DocumentType": "Command", "DocumentFormat": "JSON"})
    _check("CreateDocument", st == 200 and b["DocumentDescription"]["Status"] == "Active" and b["DocumentDescription"]["DocumentVersion"] == "1")
    _check("CreateDocument duplicate → DocumentAlreadyExists", err("CreateDocument", {"Name": "my-doc", "Content": content}, "DocumentAlreadyExists"))
    _check("CreateDocument bad content → InvalidDocumentContent", err("CreateDocument", {"Name": "bad-doc", "Content": "nope"}, "InvalidDocumentContent"))
    _check("GetDocument", call("GetDocument", {"Name": "my-doc"})[1]["Content"] == content)
    st, b = call("UpdateDocument", {"Name": "my-doc", "Content": content.replace("hello", "v2"), "DocumentVersion": "$LATEST"})
    _check("UpdateDocument → version 2", b["DocumentDescription"]["DocumentVersion"] == "2")
    call("UpdateDocumentDefaultVersion", {"Name": "my-doc", "DocumentVersion": "2"})
    _check("DescribeDocument default version", call("DescribeDocument", {"Name": "my-doc"})[1]["Document"]["DefaultVersion"] == "2")
    _check("ListDocumentVersions", len(call("ListDocumentVersions", {"Name": "my-doc"})[1]["DocumentVersions"]) == 2)
    st, b = call("ListDocuments", {"Filters": [{"Key": "Owner", "Values": ["Self"]}]})
    _check("ListDocuments Owner=Self", [d["Name"] for d in b["DocumentIdentifiers"]] == ["my-doc"])
    _check("Amazon documents seeded", any(d["Name"] == "AWS-RunShellScript" for d in call("ListDocuments", {"Filters": [{"Key": "Owner", "Values": ["Amazon"]}], "MaxResults": 50})[1]["DocumentIdentifiers"]))

    # Run Command
    st, b = call("SendCommand", {"DocumentName": "AWS-RunShellScript", "InstanceIds": ["i-0123456789abcdef0"], "Parameters": {"commands": ["echo hi"]}})
    cid = b["Command"]["CommandId"]
    _check("SendCommand → Success", st == 200 and b["Command"]["Status"] == "Success" and b["Command"]["TargetCount"] == 1)
    _check("GetCommandInvocation", call("GetCommandInvocation", {"CommandId": cid, "InstanceId": "i-0123456789abcdef0"})[1]["Status"] == "Success")
    _check("ListCommands", [c["CommandId"] for c in call("ListCommands", {})[1]["Commands"]] == [cid])
    _check("ListCommandInvocations", len(call("ListCommandInvocations", {"CommandId": cid, "Details": True})[1]["CommandInvocations"]) == 1)
    _check("SendCommand unknown document → InvalidDocument", err("SendCommand", {"DocumentName": "nope", "InstanceIds": ["i-0123456789abcdef0"]}, "InvalidDocument"))
    _check("GetCommandInvocation unknown → InvalidCommandId", err("GetCommandInvocation", {"CommandId": "x", "InstanceId": "i-0123456789abcdef0"}, "InvalidCommandId"))

    # associations
    st, b = call("CreateAssociation", {"Name": "AWS-UpdateSSMAgent", "AssociationName": "agent-update", "Targets": [{"Key": "InstanceIds", "Values": ["i-0123456789abcdef0"]}], "ScheduleExpression": "rate(14 days)"})
    aid = b["AssociationDescription"]["AssociationId"]
    _check("CreateAssociation", st == 200 and aid)
    _check("ListAssociations", [a["AssociationId"] for a in call("ListAssociations", {})[1]["Associations"]] == [aid])
    _check("DeleteAssociation", call("DeleteAssociation", {"AssociationId": aid})[0] == 200)
    _check("DescribeAssociation gone → AssociationDoesNotExist", err("DescribeAssociation", {"AssociationId": aid}, "AssociationDoesNotExist"))

    # maintenance windows
    st, b = call("CreateMaintenanceWindow", {"Name": "nightly", "Schedule": "cron(0 2 * * ? *)", "Duration": 4, "Cutoff": 1, "AllowUnassociatedTargets": False})
    wid = b["WindowId"]
    _check("CreateMaintenanceWindow", st == 200 and wid.startswith("mw-"))
    _check("GetMaintenanceWindow", call("GetMaintenanceWindow", {"WindowId": wid})[1]["Name"] == "nightly")
    call("UpdateMaintenanceWindow", {"WindowId": wid, "Enabled": False})
    _check("DescribeMaintenanceWindows Enabled filter", call("DescribeMaintenanceWindows", {"Filters": [{"Key": "Enabled", "Values": ["false"]}]})[1]["WindowIdentities"][0]["WindowId"] == wid)
    tid = call("RegisterTargetWithMaintenanceWindow", {"WindowId": wid, "ResourceType": "INSTANCE", "Targets": [{"Key": "InstanceIds", "Values": ["i-0123456789abcdef0"]}]})[1]["WindowTargetId"]
    _check("DescribeMaintenanceWindowTargets", len(call("DescribeMaintenanceWindowTargets", {"WindowId": wid})[1]["Targets"]) == 1)
    _check("DeregisterTargetFromMaintenanceWindow", call("DeregisterTargetFromMaintenanceWindow", {"WindowId": wid, "WindowTargetId": tid})[0] == 200)
    _check("Cutoff >= Duration rejected", err("CreateMaintenanceWindow", {"Name": "bad-win", "Schedule": "rate(1 day)", "Duration": 2, "Cutoff": 2, "AllowUnassociatedTargets": True}, "ValidationException"))
    _check("DeleteMaintenanceWindow", call("DeleteMaintenanceWindow", {"WindowId": wid})[1] == {"WindowId": wid})
    _check("GetMaintenanceWindow gone → DoesNotExistException", err("GetMaintenanceWindow", {"WindowId": wid}, "DoesNotExistException"))

    # patch baselines
    bid = call("CreatePatchBaseline", {"Name": "pb-linux", "OperatingSystem": "AMAZON_LINUX_2"})[1]["BaselineId"]
    _check("DescribePatchBaselines", [x["BaselineId"] for x in call("DescribePatchBaselines", {})[1]["BaselineIdentities"]] == [bid])
    _check("GetPatchBaseline", call("GetPatchBaseline", {"BaselineId": bid})[1]["OperatingSystem"] == "AMAZON_LINUX_2")
    _check("DeletePatchBaseline", call("DeletePatchBaseline", {"BaselineId": bid})[0] == 200)

    st, b = call("Bogus")
    _check("unknown action → UnknownOperationException", b["__type"] == "UnknownOperationException")
    _check("operations list", len(ssm.OPERATIONS) >= 40)

    # v4 depth: a SecureString is genuinely encrypted/decrypted through the KMS core when a
    # kms_store is passed (every check above ran WITHOUT one and kept the pre-v4-depth
    # simulation — proof this is additive, not a behaviour change for existing callers).
    ks = InMemoryKeyStore()
    cmk = kms.dispatch(ks, "TrentService.CreateKey", {}).body["KeyMetadata"]["KeyId"]

    def kcall(op, body=None):
        r = ssm.dispatch(s, T + op, body or {}, kms_store=ks)
        return r.status, r.body

    st, b = kcall("PutParameter", {"Name": "/app/kms-secret", "Value": "s3cr3t", "Type": "SecureString"})
    _check("KMS-backed PutParameter → Version 1", st == 200 and b["Version"] == 1)
    plain = kcall("GetParameter", {"Name": "/app/kms-secret", "WithDecryption": True})[1]["Parameter"]["Value"]
    _check("KMS-backed SecureString round-trips plaintext", plain == "s3cr3t")
    masked = kcall("GetParameter", {"Name": "/app/kms-secret"})[1]["Parameter"]["Value"]
    _check("KMS-backed SecureString hidden without WithDecryption", masked != "s3cr3t")
    _check("the masked value is the real KMS CiphertextBlob (base64, not the kms:<key>: wrapper)",
           not masked.startswith("kms:"))
    # Default key auto-provisions exactly like every other AWS-managed key.
    aliases = kms.dispatch(ks, "TrentService.ListAliases", {}).body["Aliases"]
    _check("alias/aws/ssm auto-provisioned on first SecureString write",
           any(a["AliasName"] == "alias/aws/ssm" for a in aliases))

    st, b = kcall("PutParameter", {"Name": "/app/kms-cmk", "Value": "v1", "Type": "SecureString", "KeyId": cmk})
    _check("customer CMK accepted", st == 200)
    # Disabling the customer key really blocks decryption — proof the value is actually
    # encrypted under it, not just stored next to a KeyId label.
    kms.dispatch(ks, "TrentService.DisableKey", {"KeyId": cmk})
    blocked = kcall("GetParameter", {"Name": "/app/kms-cmk", "WithDecryption": True})
    _check("disabled customer key blocks GetParameter(WithDecryption)", blocked[0] >= 400)
    kms.dispatch(ks, "TrentService.EnableKey", {"KeyId": cmk})
    unblocked = kcall("GetParameter", {"Name": "/app/kms-cmk", "WithDecryption": True})[1]["Parameter"]["Value"]
    _check("re-enabling the key unblocks decryption", unblocked == "v1")

    hist = kcall("GetParameterHistory", {"Name": "/app/kms-secret", "WithDecryption": True})[1]["Parameters"]
    _check("GetParameterHistory also decrypts through the KMS core", hist[0]["Value"] == "s3cr3t")

    # Without a kms_store, SecureString keeps the pre-v4-depth simulation on the SAME store/key.
    legacy = call("GetParameter", {"Name": "/app/kms-secret"})[1]["Parameter"]["Value"]
    _check("omitting kms_store degrades to the opaque ciphertext blob (no crash)", legacy == masked)
    return True


if __name__ == "__main__":
    run()
    print("[PASS] ssm core")
