"""boto3 (official SDK, endpoint changed only): KMS ML-KEM Encapsulate/Decapsulate
(upstream-drift #97/#98) and the EncapsulationAlgorithms member of a KEM key's
metadata (#99 — GetPublicKey now reports it)."""
import os
import sys

import boto3
from botocore.exceptions import ClientError

EP = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
kms = boto3.client("kms", endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
failed = False


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:200]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def code_of(fn):
    try:
        fn()
    except ClientError as e:
        return e.response["Error"]["Code"]
    return None


kem = kms.create_key(KeySpec="ML_KEM_768", KeyUsage="ENCAPSULATE_DECAPSULATE")["KeyMetadata"]
kid = kem["KeyId"]
check("KEM key metadata lists EncapsulationAlgorithms ML_KEM", lambda: kem.get("EncapsulationAlgorithms") == ["ML_KEM"] and kem["KeySpec"] == "ML_KEM_768")
enc = {}


def do_encaps():
    enc.update(kms.encapsulate(KeyId=kid, EncapsulationAlgorithm="ML_KEM"))
    return len(enc["SharedSecret"]) == 32 and enc["SharedSecretCiphertextBlob"] and enc["EncapsulationAlgorithm"] == "ML_KEM" and kid in enc["KeyId"]


check("Encapsulate returns a shared secret and ciphertext", do_encaps)
check("Decapsulate recovers the same shared secret",
      lambda: kms.decapsulate(KeyId=kid, SharedSecretCiphertextBlob=enc["SharedSecretCiphertextBlob"], EncapsulationAlgorithm="ML_KEM")["SharedSecret"] == enc["SharedSecret"])
sym = kms.create_key()["KeyMetadata"]["KeyId"]
check("Encapsulate on a symmetric key is InvalidKeyUsageException",
      lambda: code_of(lambda: kms.encapsulate(KeyId=sym, EncapsulationAlgorithm="ML_KEM")) == "InvalidKeyUsageException")
other = kms.create_key(KeySpec="ML_KEM_512", KeyUsage="ENCAPSULATE_DECAPSULATE")["KeyMetadata"]["KeyId"]
check("Decapsulate with the wrong key is IncorrectKeyException",
      lambda: code_of(lambda: kms.decapsulate(KeyId=other, SharedSecretCiphertextBlob=enc["SharedSecretCiphertextBlob"], EncapsulationAlgorithm="ML_KEM")) == "IncorrectKeyException")
kms.disable_key(KeyId=kid)
check("Encapsulate on a disabled key is DisabledException/KMSInvalidStateException",
      lambda: code_of(lambda: kms.encapsulate(KeyId=kid, EncapsulationAlgorithm="ML_KEM")) in ("DisabledException", "KMSInvalidStateException"))
sys.exit(1 if failed else 0)
