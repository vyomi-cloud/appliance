import boto3

kms = boto3.client("kms")
key = kms.describe_key(KeyId="alias/facilities-ledger")["KeyMetadata"]["KeyId"]
ctx = {"table": "approval-ledger"}
before = kms.encrypt(KeyId=key, Plaintext=b"approved before rotation", EncryptionContext=ctx)["CiphertextBlob"]
n = len(kms.list_key_rotations(KeyId=key)["Rotations"])
kms.rotate_key_on_demand(KeyId=key)
rotations = kms.list_key_rotations(KeyId=key)["Rotations"]
assert len(rotations) == n + 1, "the rotation was not recorded"
after = kms.encrypt(KeyId=key, Plaintext=b"approved after rotation", EncryptionContext=ctx)["CiphertextBlob"]
assert kms.decrypt(CiphertextBlob=before, EncryptionContext=ctx)["Plaintext"] == b"approved before rotation", "pre-rotation data became unreadable"
assert kms.decrypt(CiphertextBlob=after, EncryptionContext=ctx)["Plaintext"] == b"approved after rotation"
assert kms.get_key_rotation_status(KeyId=key)["KeyRotationEnabled"], "automatic rotation must stay on"
print("rotations recorded:", len(rotations), "| old ciphertext still opens | new ciphertext opens | automatic rotation on")
print("key rotation verified")
