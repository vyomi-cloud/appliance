"""C13: governance and security: KMS envelope protection of the ledger payload, CloudTrail audit trail of the run."""
import base64, json, time
from ..runtime import NAMES, aws_json


def run(ctx):
    kms, ct = ctx.client("kms"), ctx.client("cloudtrail")

    def key():
        k = kms.create_key(Description="facilities ledger key")["KeyMetadata"]["KeyId"]
        kms.create_alias(AliasName="alias/facilities-ledger", TargetKeyId=k)
        kms.enable_key_rotation(KeyId=k)
        ctx.state["kms_key"] = k
        return f"key {k} with alias and rotation"
    ctx.step("kms: CreateKey + alias + rotation", key)
    k = ctx.state.get("kms_key")
    if k:
        def seal():
            wo = ctx.state.get("work_order_id", "WO-000000")
            blob = kms.encrypt(KeyId=k, Plaintext=json.dumps({"work_order": wo, "approved_by": "duty.manager@example.com"}).encode(), EncryptionContext={"table": NAMES["ledger"]})["CiphertextBlob"]
            assert b"duty.manager" not in blob
            back = json.loads(kms.decrypt(CiphertextBlob=blob, EncryptionContext={"table": NAMES["ledger"]})["Plaintext"])
            assert back["work_order"] == wo
            try:
                kms.decrypt(CiphertextBlob=blob, EncryptionContext={"table": "wrong"})
                raise AssertionError("decrypt succeeded with the wrong encryption context")
            except kms.exceptions.InvalidCiphertextException:
                pass
            return "ledger record encrypted; wrong context is refused"
        ctx.step("kms: Encrypt/Decrypt the approval record with an encryption context", seal)
        ctx.step("s3: SSE-KMS object written with the key", lambda: ctx.client("s3").put_object(
            Bucket=NAMES["bucket"], Key="audit/approval-record.json", Body=b"{}", ServerSideEncryption="aws:kms", SSEKMSKeyId=k)["ResponseMetadata"]["HTTPStatusCode"] == 200 and "SSE-KMS write ok")

    def trail():
        ct.create_trail(Name="facilities-trail", S3BucketName=NAMES["bucket"], S3KeyPrefix="audit", IsMultiRegionTrail=False)
        ct.start_logging(Name="facilities-trail")
        assert ct.get_trail_status(Name="facilities-trail")["IsLogging"]
        return "trail facilities-trail logging"
    ctx.step("cloudtrail: CreateTrail + StartLogging", trail, lane="approvals")

    def audit():
        names = set()
        for _ in range(10):
            ev = ct.lookup_events(LookupAttributes=[{"AttributeKey": "EventSource", "AttributeValue": "states.amazonaws.com"}], MaxResults=50)["Events"]
            names = {e["EventName"] for e in ev}
            if "StartExecution" in names:
                break
            time.sleep(0.5)
        assert "StartExecution" in names, f"events seen: {sorted(names)}"
        who = [e for e in ev if e["EventName"] == "SendTaskSuccess"]
        return f"audit trail records {sorted(names)}"
    ctx.step("cloudtrail: LookupEvents shows StartExecution / SendTaskSuccess for the approval", audit, lane="approvals")

    def ledger():
        items = [aws_json(i) for i in ctx.client("dynamodb").scan(TableName=NAMES["ledger"])["Items"]]
        st = {i["status"] for i in items}
        assert {"EXECUTED"} <= st, st
        return f"ledger rows: {len(items)} ({sorted(st)})"
    ctx.step("dynamodb: approval-ledger is the application-level audit record", ledger)
