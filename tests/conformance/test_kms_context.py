"""KMS encryption-context binding, ReEncrypt, grants and CloudTrail audit, via the REAL boto3 client against the in-process simulator.

Run: PYTHONPATH=. python3 tests/conformance/test_kms_context.py   (needs boto3; the Facilities example's in-process server is reused)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "examples", "enterprise-facilities-agent"))
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
import boto3
from botocore.exceptions import ClientError
from facilities.server import start_in_process

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:300]}")


def code(fn):
    try:
        fn()
        return None
    except ClientError as e:
        return e.response["Error"]["Code"]


ep = start_in_process()
kms = boto3.client("kms", endpoint_url=ep)
ct = boto3.client("cloudtrail", endpoint_url=ep)
k = kms.create_key(Description="ctx test")["KeyMetadata"]["KeyId"]
ctx = {"table": "approval-ledger", "env": "prod"}
blob = kms.encrypt(KeyId=k, Plaintext=b"secret", EncryptionContext=ctx)["CiphertextBlob"]
check("decrypt with the same context", kms.decrypt(CiphertextBlob=blob, EncryptionContext=dict(reversed(list(ctx.items()))))["Plaintext"] == b"secret")
check("wrong context -> InvalidCiphertextException", code(lambda: kms.decrypt(CiphertextBlob=blob, EncryptionContext={"table": "x"})) == "InvalidCiphertextException")
check("missing context -> InvalidCiphertextException", code(lambda: kms.decrypt(CiphertextBlob=blob)) == "InvalidCiphertextException")
check("extra key -> InvalidCiphertextException", code(lambda: kms.decrypt(CiphertextBlob=blob, EncryptionContext={**ctx, "a": "b"})) == "InvalidCiphertextException")
nb = kms.encrypt(KeyId=k, Plaintext=b"plain")["CiphertextBlob"]
check("no-context round trip", kms.decrypt(CiphertextBlob=nb)["Plaintext"] == b"plain")
check("context supplied but none bound -> refused", code(lambda: kms.decrypt(CiphertextBlob=nb, EncryptionContext={"a": "b"})) == "InvalidCiphertextException")
check("tampered blob -> InvalidCiphertextException", code(lambda: kms.decrypt(CiphertextBlob=blob[:-1] + bytes([blob[-1] ^ 1]), EncryptionContext=ctx)) == "InvalidCiphertextException")
dk = kms.generate_data_key(KeyId=k, KeySpec="AES_256", EncryptionContext=ctx)
check("GenerateDataKey: context bound", kms.decrypt(CiphertextBlob=dk["CiphertextBlob"], EncryptionContext=ctx)["Plaintext"] == dk["Plaintext"]
      and code(lambda: kms.decrypt(CiphertextBlob=dk["CiphertextBlob"], EncryptionContext={"table": "no"})) == "InvalidCiphertextException")
dk2 = kms.generate_data_key_without_plaintext(KeyId=k, KeySpec="AES_128", EncryptionContext=ctx)
check("GenerateDataKeyWithoutPlaintext: context bound", "Plaintext" not in dk2 and len(kms.decrypt(CiphertextBlob=dk2["CiphertextBlob"], EncryptionContext=ctx)["Plaintext"]) == 16)

k2 = kms.create_key()["KeyMetadata"]["KeyId"]
re = kms.re_encrypt(CiphertextBlob=blob, SourceEncryptionContext=ctx, DestinationKeyId=k2, DestinationEncryptionContext={"to": "k2"})
check("ReEncrypt moves key + context", kms.decrypt(CiphertextBlob=re["CiphertextBlob"], EncryptionContext={"to": "k2"})["Plaintext"] == b"secret" and re["KeyId"].endswith(k2))
check("ReEncrypt with wrong source context refused", code(lambda: kms.re_encrypt(CiphertextBlob=blob, SourceEncryptionContext={"x": "y"}, DestinationKeyId=k2)) == "InvalidCiphertextException")

g = kms.create_grant(KeyId=k, GranteePrincipal="arn:aws:iam::000000000000:role/agent", Operations=["Decrypt", "Encrypt"], Name="g1")
check("CreateGrant/ListGrants", g["GrantId"] and kms.list_grants(KeyId=k)["Grants"][0]["Operations"] == ["Decrypt", "Encrypt"])
check("CreateGrant bad operation -> ValidationException", code(lambda: kms.create_grant(KeyId=k, GranteePrincipal="p", Operations=["Nope"])) == "ValidationException")
kms.revoke_grant(KeyId=k, GrantId=g["GrantId"])
check("RevokeGrant removes it", kms.list_grants(KeyId=k)["Grants"] == [])

ev = []
for _ in range(10):
    ev = [e for e in ct.lookup_events(LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": "Decrypt"}], MaxResults=50)["Events"]
          if json.loads(e["CloudTrailEvent"]).get("requestParameters", {}).get("encryptionContext") == ctx]
    if ev:
        break
    time.sleep(0.3)
check("CloudTrail records Decrypt with encryptionContext in requestParameters", bool(ev))
if ev:
    d = json.loads(ev[0]["CloudTrailEvent"])
    check("CloudTrail event has keyId and no payload bytes", "ciphertextBlob" not in d["requestParameters"] and "plaintext" not in d["requestParameters"], d)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
