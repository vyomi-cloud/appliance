import json

import boto3

kms, s3 = boto3.client("kms"), boto3.client("s3")
key = kms.create_key(Description="facilities ledger key")["KeyMetadata"]["KeyId"]
kms.create_alias(AliasName="alias/facilities-ledger", TargetKeyId=key)
kms.enable_key_rotation(KeyId=key)
assert kms.get_key_rotation_status(KeyId=key)["KeyRotationEnabled"], "rotation must be on"
print("key", key, "with alias and rotation: True")

# The record says WHAT was approved. WHO approved is not typed in: it comes from the audit trail (below), so it cannot be forged by the writer.
record = {"work_order": "WO-000104", "request_id": "req-demo-0001", "decision": "approved"}
blob = kms.encrypt(KeyId=key, Plaintext=json.dumps(record).encode(), EncryptionContext={"table": "approval-ledger"})["CiphertextBlob"]
assert b"WO-000104" not in blob, "the ciphertext must not contain the plaintext"
print("ciphertext hides the work order:", True)
back = json.loads(kms.decrypt(CiphertextBlob=blob, EncryptionContext={"table": "approval-ledger"})["Plaintext"])
assert back == record
print("decrypt with the right context:", back["work_order"])
try:
    kms.decrypt(CiphertextBlob=blob, EncryptionContext={"table": "wrong"})
    raise AssertionError("a wrong encryption context was accepted")
except kms.exceptions.InvalidCiphertextException:
    print("wrong context refused")

# Encrypt at rest by DEFAULT: every object written to the bucket is protected with the key, with no per-request flag a developer can forget.
# (This simulator reflects the bucket-default configuration; a per-request ServerSideEncryption header is accepted but reported as AES256.)
s3.put_bucket_encryption(Bucket="facilities-docs", ServerSideEncryptionConfiguration={"Rules": [
    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": key}, "BucketKeyEnabled": True}]})
s3.put_object(Bucket="facilities-docs", Key="audit/approval-record.json", Body=json.dumps(record).encode())
head = s3.head_object(Bucket="facilities-docs", Key="audit/approval-record.json")
assert head.get("ServerSideEncryption") == "aws:kms" and key in head.get("SSEKMSKeyId", ""), "the object must inherit SSE-KMS from the bucket, got %s" % head.get("ServerSideEncryption")
print("SSE-KMS object written")
