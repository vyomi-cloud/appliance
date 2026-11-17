"""Component 13 Governance: Key Vault key envelope encrypt/decrypt (wrap/unwrap) and Activity Log read of the run."""
import os, time
from _common import *

P = Probe(13, "governance", "Governance: Key Vault envelope + Activity Log")
B = endpoint(); ensure_rg(B)
S = {}
VAULT = "kv-probe1"


def vault():
    from azure.mgmt.keyvault import KeyVaultManagementClient
    v = arm(KeyVaultManagementClient, B).vaults.begin_create_or_update(RG, VAULT, {"location": LOC, "properties": {"tenant_id": "00000000-0000-0000-0000-000000000000",
        "sku": {"family": "A", "name": "standard"}, "access_policies": []}}).result()
    S["uri"] = v.properties.vault_uri
    return S["uri"]


def kv_client():
    from azure.keyvault.keys import KeyClient
    # KeyClient insists on https and challenge auth; shim the transport to plain http and skip challenge validation.
    from urllib.parse import urlsplit
    hp = urlsplit(B).netloc
    uri = S["uri"]
    S["client"] = KeyClient(vault_url=uri.replace("http://", "https://"), credential=Cred(), transport=http_shim_transport(hp), verify_challenge_resource=False)
    k = S["client"].create_rsa_key("envelope-kek", size=2048)
    return k.key.kid if hasattr(k.key, "kid") else k.id


def wrap_unwrap():
    from azure.keyvault.keys.crypto import CryptographyClient, KeyWrapAlgorithm
    k = S["client"].get_key("envelope-kek")
    cc = CryptographyClient(k, Cred(), transport=http_shim_transport(__import__("urllib.parse", fromlist=["x"]).urlsplit(B).netloc), verify_challenge_resource=False)
    dek = os.urandom(32)
    w = cc.wrap_key(KeyWrapAlgorithm.rsa_oaep_256, dek)
    u = cc.unwrap_key(KeyWrapAlgorithm.rsa_oaep_256, w.encrypted_key)
    assert u.key == dek, "unwrapped DEK differs"
    return "wrap_key/unwrap_key round-trip (envelope encryption)"


def encrypt_decrypt():
    from azure.keyvault.keys.crypto import CryptographyClient, EncryptionAlgorithm
    k = S["client"].get_key("envelope-kek")
    cc = CryptographyClient(k, Cred(), transport=http_shim_transport(__import__("urllib.parse", fromlist=["x"]).urlsplit(B).netloc), verify_challenge_resource=False)
    e = cc.encrypt(EncryptionAlgorithm.rsa_oaep_256, b"hello")
    assert cc.decrypt(EncryptionAlgorithm.rsa_oaep_256, e.ciphertext).plaintext == b"hello"


def activity_log():
    from azure.mgmt.monitor import MonitorManagementClient
    m = arm(MonitorManagementClient, B)
    evs = list(m.activity_logs.list(filter="eventTimestamp ge '2026-11-01T00:00:00Z'"))
    assert evs, "Activity Log empty"
    names = {e.operation_name.value if e.operation_name else None for e in evs}
    assert any(n and "Microsoft.KeyVault/vaults/write" in n for n in names), f"vault create not in activity log: {sorted(x for x in names if x)[:6]}"
    return len(evs)


def activity_log_resource_group():
    from azure.mgmt.monitor import MonitorManagementClient
    evs = list(arm(MonitorManagementClient, B).activity_logs.list(filter=f"eventTimestamp ge '2026-11-01T00:00:00Z' and resourceGroupName eq '{RG}'"))
    assert evs


P.step("Key Vault via ARM (azure-mgmt-keyvault)", vault)
if P.step("KeyClient.create_rsa_key (azure-keyvault-keys, http shim)", kv_client):
    P.step("CryptographyClient wrap_key / unwrap_key RSA-OAEP-256 (envelope)", wrap_unwrap)
    P.step("CryptographyClient encrypt / decrypt", encrypt_decrypt)
P.step("Activity Log lists the run's control-plane operations (azure-mgmt-monitor activity_logs)", activity_log)
P.step("Activity Log filtered by resource group", activity_log_resource_group)
P.finish()
