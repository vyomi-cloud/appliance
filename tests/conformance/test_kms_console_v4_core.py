"""KMS v4-console conformance — the AWS-managed-key liveness goal, tags, key
policy, aliases CRUD, rotation history, Sign/Verify, GenerateMac/VerifyMac, and
custom key store CRUD added to core/kms_core.py for the v4 KMS console.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_kms_console_v4_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64

try:
    from core.kms_keystore import InMemoryKeyStore
    from core import kms_core as kms
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import kms_core as kms  # type: ignore

T = "TrentService."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _b64(s: str) -> bytes:
    return base64.b64decode(s)


def _e(s: bytes) -> str:
    return base64.b64encode(s).decode()


def run() -> int:
    st = InMemoryKeyStore()

    # 1. AWS-managed key liveness: Encrypt against alias/aws/<service> auto-provisions it.
    nf = kms.dispatch(st, T + "DescribeKey", {"KeyId": "alias/aws/s3"})
    _check("aws-managed alias absent before first use", nf.body.get("__type") == "NotFoundException")
    enc = kms.dispatch(st, T + "Encrypt", {"KeyId": "alias/aws/s3", "Plaintext": _e(b"data")})
    _check("encrypt against unseen aws/ alias auto-provisions + succeeds", enc.status == 200)
    desc = kms.dispatch(st, T + "DescribeKey", {"KeyId": "alias/aws/s3"}).body["KeyMetadata"]
    _check("provisioned key is AWS-managed", desc["KeyManager"] == "AWS")
    _check("provisioned key is Enabled", desc["KeyState"] == "Enabled")
    enc2 = kms.dispatch(st, T + "Encrypt", {"KeyId": "alias/aws/s3", "Plaintext": _e(b"more")})
    desc2 = kms.dispatch(st, T + "DescribeKey", {"KeyId": "alias/aws/s3"}).body["KeyMetadata"]
    _check("second use reuses the SAME aws-managed key", desc2["KeyId"] == desc["KeyId"])
    gdk = kms.dispatch(st, T + "GenerateDataKey", {"KeyId": "alias/aws/ddb"})
    _check("GenerateDataKey also auto-provisions its own aws/ alias", gdk.status == 200)
    desc3 = kms.dispatch(st, T + "DescribeKey", {"KeyId": "alias/aws/ddb"}).body["KeyMetadata"]
    _check("a distinct service gets its OWN aws-managed key", desc3["KeyId"] != desc["KeyId"])

    # 2. Customer key: default policy, tags, Sign/Verify, GenerateMac/VerifyMac.
    kid = kms.dispatch(st, T + "CreateKey", {"Description": "v4 test key"}).body["KeyMetadata"]["KeyId"]
    md = kms.dispatch(st, T + "DescribeKey", {"KeyId": kid}).body["KeyMetadata"]
    _check("customer key KeyManager", md["KeyManager"] == "CUSTOMER")
    _check("customer key has a KeyMaterialId", bool(md.get("KeyMaterialId")))

    pol = kms.dispatch(st, T + "GetKeyPolicy", {"KeyId": kid}).body["Policy"]
    _check("GetKeyPolicy returns a default policy document", '"Version"' in pol and "kms:*" in pol)
    custom_policy = '{"Version": "2012-10-17", "Statement": []}'
    kms.dispatch(st, T + "PutKeyPolicy", {"KeyId": kid, "Policy": custom_policy})
    _check("PutKeyPolicy round-trips over GetKeyPolicy",
           kms.dispatch(st, T + "GetKeyPolicy", {"KeyId": kid}).body["Policy"] == custom_policy)
    bad_policy = kms.dispatch(st, T + "PutKeyPolicy", {"KeyId": kid, "Policy": "not json"})
    _check("PutKeyPolicy rejects invalid JSON", bad_policy.body["__type"] == "MalformedPolicyDocumentException")
    names = kms.dispatch(st, T + "ListKeyPolicies", {"KeyId": kid}).body["PolicyNames"]
    _check("ListKeyPolicies lists 'default'", names == ["default"])

    kms.dispatch(st, T + "TagResource", {"KeyId": kid, "Tags": [{"TagKey": "env", "TagValue": "prod"}]})
    tags = {t["TagKey"]: t["TagValue"] for t in kms.dispatch(st, T + "ListResourceTags", {"KeyId": kid}).body["Tags"]}
    _check("TagResource -> ListResourceTags", tags.get("env") == "prod")
    kms.dispatch(st, T + "UntagResource", {"KeyId": kid, "TagKeys": ["env"]})
    _check("UntagResource removes the tag",
           not kms.dispatch(st, T + "ListResourceTags", {"KeyId": kid}).body["Tags"])

    kms.dispatch(st, T + "CreateAlias", {"AliasName": "alias/v4test", "TargetKeyId": kid})
    kid2 = kms.dispatch(st, T + "CreateKey", {}).body["KeyMetadata"]["KeyId"]
    kms.dispatch(st, T + "UpdateAlias", {"AliasName": "alias/v4test", "TargetKeyId": kid2})
    _check("UpdateAlias repoints the alias",
           kms.dispatch(st, T + "DescribeKey", {"KeyId": "alias/v4test"}).body["KeyMetadata"]["KeyId"] == kid2)
    kms.dispatch(st, T + "DeleteAlias", {"AliasName": "alias/v4test"})
    _check("DeleteAlias removes it",
           kms.dispatch(st, T + "DescribeKey", {"KeyId": "alias/v4test"}).body["__type"] == "NotFoundException")

    # 3. Sign/Verify (asymmetric) + GenerateMac/VerifyMac (HMAC) — key-usage enforced.
    signing_key = kms.dispatch(st, T + "CreateKey", {"KeyUsage": "SIGN_VERIFY", "KeySpec": "RSA_2048"}).body["KeyMetadata"]["KeyId"]
    s = kms.dispatch(st, T + "Sign", {"KeyId": signing_key, "Message": _e(b"hello"), "SigningAlgorithm": "RSASSA_PKCS1_V1_5_SHA_256"})
    _check("Sign 200", s.status == 200)
    v = kms.dispatch(st, T + "Verify", {"KeyId": signing_key, "Message": _e(b"hello"), "Signature": s.body["Signature"],
                                        "SigningAlgorithm": "RSASSA_PKCS1_V1_5_SHA_256"})
    _check("Verify valid signature", v.body["SignatureValid"] is True)
    v2 = kms.dispatch(st, T + "Verify", {"KeyId": signing_key, "Message": _e(b"tampered"), "Signature": s.body["Signature"],
                                         "SigningAlgorithm": "RSASSA_PKCS1_V1_5_SHA_256"})
    _check("Verify rejects a tampered message", v2.body["SignatureValid"] is False)
    bad_usage = kms.dispatch(st, T + "Sign", {"KeyId": kid, "Message": _e(b"x"), "SigningAlgorithm": "RSASSA_PKCS1_V1_5_SHA_256"})
    _check("Sign on an ENCRYPT_DECRYPT key is InvalidKeyUsageException", bad_usage.body["__type"] == "InvalidKeyUsageException")

    mac_key = kms.dispatch(st, T + "CreateKey", {"KeyUsage": "GENERATE_VERIFY_MAC", "KeySpec": "HMAC_256"}).body["KeyMetadata"]["KeyId"]
    gm = kms.dispatch(st, T + "GenerateMac", {"KeyId": mac_key, "Message": _e(b"payload"), "MacAlgorithm": "HMAC_SHA_256"})
    _check("GenerateMac 200", gm.status == 200)
    vm = kms.dispatch(st, T + "VerifyMac", {"KeyId": mac_key, "Message": _e(b"payload"), "Mac": gm.body["Mac"], "MacAlgorithm": "HMAC_SHA_256"})
    _check("VerifyMac valid", vm.body["MacValid"] is True)

    # 4. Automatic rotation history + on-demand rotation keeps old ciphertext decryptable.
    rkey = kms.dispatch(st, T + "CreateKey", {}).body["KeyMetadata"]["KeyId"]
    ct1 = kms.dispatch(st, T + "Encrypt", {"KeyId": rkey, "Plaintext": _e(b"before rotation")}).body["CiphertextBlob"]
    mid1 = kms.dispatch(st, T + "DescribeKey", {"KeyId": rkey}).body["KeyMetadata"]["KeyMaterialId"]
    kms.dispatch(st, T + "RotateKeyOnDemand", {"KeyId": rkey})
    mid2 = kms.dispatch(st, T + "DescribeKey", {"KeyId": rkey}).body["KeyMetadata"]["KeyMaterialId"]
    _check("RotateKeyOnDemand changes the key material id", mid1 != mid2)
    dec1 = kms.dispatch(st, T + "Decrypt", {"CiphertextBlob": ct1})
    _check("ciphertext from BEFORE rotation still decrypts", _b64(dec1.body["Plaintext"]) == b"before rotation")
    ct2 = kms.dispatch(st, T + "Encrypt", {"KeyId": rkey, "Plaintext": _e(b"after rotation")}).body["CiphertextBlob"]
    dec2 = kms.dispatch(st, T + "Decrypt", {"CiphertextBlob": ct2})
    _check("ciphertext from AFTER rotation also decrypts", _b64(dec2.body["Plaintext"]) == b"after rotation")
    rotations = kms.dispatch(st, T + "ListKeyRotations", {"KeyId": rkey}).body["Rotations"]
    _check("ListKeyRotations records the on-demand rotation",
           len(rotations) == 1 and rotations[0]["RotationType"] == "CUSTOMER_INITIATED" and rotations[0]["KeyMaterialId"] == mid2)

    # 5. CancelKeyDeletion.
    dkey = kms.dispatch(st, T + "CreateKey", {}).body["KeyMetadata"]["KeyId"]
    kms.dispatch(st, T + "ScheduleKeyDeletion", {"KeyId": dkey, "PendingWindowInDays": 7})
    cancel = kms.dispatch(st, T + "CancelKeyDeletion", {"KeyId": dkey})
    _check("CancelKeyDeletion 200", cancel.status == 200)
    _check("CancelKeyDeletion leaves the key Disabled", cancel.body["KeyState"] == "Disabled")
    _check("DescribeKey reflects Disabled, not PendingDeletion",
           kms.dispatch(st, T + "DescribeKey", {"KeyId": dkey}).body["KeyMetadata"]["KeyState"] == "Disabled")

    # 6. Custom key stores: real metadata CRUD; Connect is an HONEST failure (no real
    #    CloudHSM cluster / external XKS proxy exists for Vyomi to reach).
    cks = kms.dispatch(st, T + "CreateCustomKeyStore", {"CustomKeyStoreName": "v4-hsm", "CloudHsmClusterId": "cluster-1"})
    _check("CreateCustomKeyStore 200", cks.status == 200)
    cks_id = cks.body["CustomKeyStoreId"]
    desc_cks = kms.dispatch(st, T + "DescribeCustomKeyStores", {}).body["CustomKeyStores"]
    _check("DescribeCustomKeyStores lists it DISCONNECTED", any(
        c["CustomKeyStoreId"] == cks_id and c["ConnectionState"] == "DISCONNECTED" for c in desc_cks))
    dup = kms.dispatch(st, T + "CreateCustomKeyStore", {"CustomKeyStoreName": "v4-hsm"})
    _check("duplicate custom key store name rejected", dup.body["__type"] == "CustomKeyStoreNameInUseException")
    conn = kms.dispatch(st, T + "ConnectCustomKeyStore", {"CustomKeyStoreId": cks_id})
    _check("ConnectCustomKeyStore 200 (connection attempt itself succeeds)", conn.status == 200)
    after_connect = kms.dispatch(st, T + "DescribeCustomKeyStores", {"CustomKeyStoreId": cks_id}).body["CustomKeyStores"][0]
    _check("connect HONESTLY fails: no real HSM/proxy to reach", after_connect["ConnectionState"] == "FAILED")
    blocked = kms.dispatch(st, T + "DeleteCustomKeyStore", {"CustomKeyStoreId": cks_id})
    _check("delete while FAILED is still deletable (not CONNECTED)", blocked.status == 200)
    missing = kms.dispatch(st, T + "DescribeCustomKeyStores", {"CustomKeyStoreId": cks_id})
    _check("deleted custom key store is gone", missing.body["__type"] == "CustomKeyStoreNotFoundException")

    print("\nRESULT: PASS — KMS v4-console additions conform (native wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
