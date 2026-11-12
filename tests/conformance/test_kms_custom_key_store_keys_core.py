"""KMS keys backed by a custom key store: the soft-HSM cluster (CloudHSM-style) and Vyomi's built-in XKS proxy.
Material lives in the key store partition, never in the KMS key table; a key is usable only while its store is CONNECTED.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_kms_custom_key_store_keys_core.py
"""
import base64

from core import kms_core as kms
from core.kms_keystore import InMemoryKeyStore

T = "TrentService."


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def main():
    st = InMemoryKeyStore()
    call = lambda op, **b: kms.dispatch(st, T + op, b)

    # --- CloudHSM-style store on the software HSM cluster
    cks = call("CreateCustomKeyStore", CustomKeyStoreName="soft", CloudHsmClusterId=kms.SOFT_HSM_CLUSTER,
               TrustAnchorCertificate="-----BEGIN CERTIFICATE-----", KeyStorePassword="pw").body["CustomKeyStoreId"]
    r = call("CreateKey", Origin="AWS_CLOUDHSM", CustomKeyStoreId=cks)
    _check("CreateKey in a DISCONNECTED store is refused", r.body.get("__type") == "CustomKeyStoreInvalidStateException", r.body)
    call("ConnectCustomKeyStore", CustomKeyStoreId=cks)
    d = call("DescribeCustomKeyStores", CustomKeyStoreId=cks).body["CustomKeyStores"][0]
    _check("soft-HSM store CONNECTED, private fields not leaked", d["ConnectionState"] == "CONNECTED" and not any(k.startswith("_") for k in d), d)
    md = call("CreateKey", Origin="AWS_CLOUDHSM", CustomKeyStoreId=cks).body["KeyMetadata"]
    kid = md["KeyId"]
    _check("key metadata carries store + cluster", md["CustomKeyStoreId"] == cks and md["CloudHsmClusterId"] == kms.SOFT_HSM_CLUSTER and md["Origin"] == "AWS_CLOUDHSM")
    _check("material is NOT in the KMS key table", kid not in st.material)
    ct = call("Encrypt", KeyId=kid, Plaintext=base64.b64encode(b"secret").decode()).body["CiphertextBlob"]
    pt = call("Decrypt", CiphertextBlob=ct).body["Plaintext"]
    _check("Encrypt/Decrypt round-trips through the partition", base64.b64decode(pt) == b"secret")
    call("DisconnectCustomKeyStore", CustomKeyStoreId=cks)
    r = call("Decrypt", CiphertextBlob=ct)
    _check("key unusable while its store is disconnected", r.body.get("__type") == "KMSInvalidStateException", r.body)
    r = call("DeleteCustomKeyStore", CustomKeyStoreId=cks)
    _check("store with keys cannot be deleted", r.body.get("__type") == "CustomKeyStoreHasCMKsException", r.body)
    call("ConnectCustomKeyStore", CustomKeyStoreId=cks)
    pt = call("Decrypt", CiphertextBlob=ct).body["Plaintext"]
    _check("reconnect restores the key (material persisted in the partition)", base64.b64decode(pt) == b"secret")
    _check("rotation is unsupported for these keys", call("RotateKeyOnDemand", KeyId=kid).body.get("__type") == "UnsupportedOperationException")

    # --- honest failures
    bad = call("CreateCustomKeyStore", CustomKeyStoreName="nocluster", CloudHsmClusterId="cluster-1", KeyStorePassword="pw").body["CustomKeyStoreId"]
    call("ConnectCustomKeyStore", CustomKeyStoreId=bad)
    d = call("DescribeCustomKeyStores", CustomKeyStoreId=bad).body["CustomKeyStores"][0]
    _check("unknown cluster -> FAILED CLUSTER_NOT_FOUND", d["ConnectionState"] == "FAILED" and d["ConnectionErrorCode"] == "CLUSTER_NOT_FOUND")
    nopw = call("CreateCustomKeyStore", CustomKeyStoreName="nopw", CloudHsmClusterId=kms.SOFT_HSM_CLUSTER).body["CustomKeyStoreId"]
    call("ConnectCustomKeyStore", CustomKeyStoreId=nopw)
    _check("no HSM password -> FAILED INVALID_CREDENTIALS", call("DescribeCustomKeyStores", CustomKeyStoreId=nopw).body["CustomKeyStores"][0]["ConnectionErrorCode"] == "INVALID_CREDENTIALS")

    # --- external key store via the built-in XKS proxy
    x = call("CreateCustomKeyStore", CustomKeyStoreName="xks", CustomKeyStoreType="EXTERNAL_KEY_STORE", XksProxyConnectivity="PUBLIC_ENDPOINT",
             XksProxyUriEndpoint="https://" + kms.XKS_BUILTIN_HOST, XksProxyUriPath="/kms/xks/v1").body["CustomKeyStoreId"]
    call("ConnectCustomKeyStore", CustomKeyStoreId=x)
    _check("built-in XKS proxy CONNECTED", call("DescribeCustomKeyStores", CustomKeyStoreId=x).body["CustomKeyStores"][0]["ConnectionState"] == "CONNECTED")
    _check("XKS key needs an XksKeyId", call("CreateKey", Origin="EXTERNAL_KEY_STORE", CustomKeyStoreId=x).body.get("__type") == "ValidationException")
    xk = call("CreateKey", Origin="EXTERNAL_KEY_STORE", CustomKeyStoreId=x, XksKeyId="ext-key-1").body["KeyMetadata"]
    _check("XKS key records its external key id", xk["XksKeyConfiguration"] == {"Id": "ext-key-1"})
    _check("same external key cannot back two KMS keys", call("CreateKey", Origin="EXTERNAL_KEY_STORE", CustomKeyStoreId=x, XksKeyId="ext-key-1").body.get("__type") == "XksKeyAlreadyInUseException")
    ct = call("Encrypt", KeyId=xk["KeyId"], Plaintext=base64.b64encode(b"x").decode()).body["CiphertextBlob"]
    _check("XKS key encrypts", call("Decrypt", CiphertextBlob=ct).status == 200)
    ext = call("CreateCustomKeyStore", CustomKeyStoreName="ext", CustomKeyStoreType="EXTERNAL_KEY_STORE", XksProxyUriEndpoint="http://127.0.0.1:9").body["CustomKeyStoreId"]
    call("ConnectCustomKeyStore", CustomKeyStoreId=ext)
    _check("unreachable external proxy -> FAILED XKS_PROXY_NOT_REACHABLE", call("DescribeCustomKeyStores", CustomKeyStoreId=ext).body["CustomKeyStores"][0]["ConnectionErrorCode"] == "XKS_PROXY_NOT_REACHABLE")


if __name__ == "__main__":
    main()
    print("RESULT: PASS")
