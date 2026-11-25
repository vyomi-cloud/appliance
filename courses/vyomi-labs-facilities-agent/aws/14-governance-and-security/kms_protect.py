import json

import boto3

kms, s3 = boto3.client("kms"), boto3.client("s3")
key = kms.create_key(Description="facilities ledger key")["KeyMetadata"]["KeyId"]
kms.create_alias(AliasName="alias/facilities-ledger", TargetKeyId=key)
kms.enable_key_rotation(KeyId=key)
print("key", key, "with alias and rotation:", kms.get_key_rotation_status(KeyId=key)["KeyRotationEnabled"])

record = {"work_order": "WO-000104", "approved_by": "duty.manager@example.com"}
blob = kms.encrypt(KeyId=key, Plaintext=json.dumps(record).encode(), EncryptionContext={"table": "approval-ledger"})["CiphertextBlob"]
print("ciphertext hides the approver:", b"duty.manager" not in blob)
back = json.loads(kms.decrypt(CiphertextBlob=blob, EncryptionContext={"table": "approval-ledger"})["Plaintext"])
print("decrypt with the right context:", back["work_order"])
try:
    kms.decrypt(CiphertextBlob=blob, EncryptionContext={"table": "wrong"})
    print("wrong context was accepted: this is a bug")
except kms.exceptions.InvalidCiphertextException:
    print("wrong context refused")

s3.put_object(Bucket="facilities-docs", Key="audit/approval-record.json", Body=json.dumps(record).encode(), ServerSideEncryption="aws:kms", SSEKMSKeyId=key)
print("SSE-KMS object written")
