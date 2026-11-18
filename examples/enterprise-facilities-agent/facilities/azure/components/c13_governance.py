"""C13: governance and security: Key Vault key envelope encryption (wrap / unwrap a data key, encrypt the approved ledger record) and the Activity Log read-back of the run."""
import os, time
from ..runtime import NAMES, LANE, Blocked, RG, LOC


def run(ctx):
    S = {}

    def vault():
        from azure.mgmt.keyvault import KeyVaultManagementClient
        from azure.mgmt.keyvault.models import Sku, SkuFamily, SkuName, VaultCreateOrUpdateParameters, VaultProperties
        v = ctx.arm(KeyVaultManagementClient).vaults.begin_create_or_update(RG, NAMES["vault"], VaultCreateOrUpdateParameters(location=LOC, properties=VaultProperties(
            tenant_id="00000000-0000-0000-0000-000000000000", sku=Sku(family=SkuFamily.A, name=SkuName.STANDARD), access_policies=[]))).result()
        S["uri"] = v.properties.vault_uri
        return S["uri"]
    ctx.step("key vault: create facilities-kv through ARM (azure-mgmt-keyvault)", vault, lane=LANE["runtime"])
    if "uri" in S:
        uri = S["uri"]
        if ctx.tls:
            uri = ctx.endpoint      # host-only https URL: the SDK rebuilds the vault URL from a key id as scheme://host:port; the simulator infers the vault from the key name
            ctx.note("Key Vault: KeyClient uses the simulator's https host (not properties.vault_uri, which stays the console path form).")
        if not ctx.tls:
            ctx.step("key vault: the azure-keyvault-keys SDK needs an https vault URI", lambda: (_ for _ in ()).throw(Blocked("https endpoint", "azure-keyvault-keys refuses bearer auth over plain http; run against https://")))
        else:
            _keys(ctx, uri, S)
    _activity(ctx)


def _keys(ctx, uri, S):
    def key():
        from azure.keyvault.keys import KeyClient
        S["kc"] = KeyClient(vault_url=uri, credential=ctx.cred(), verify_challenge_resource=False)   # vendor option for vault hosts that are not *.vault.azure.net
        k = S["kc"].create_rsa_key(NAMES["key"], size=2048)
        assert k.name == NAMES["key"] and k.key.kty.startswith("RSA"), k.key
        return f"RSA-2048 key {k.name} created ({k.id})"
    ctx.step("key vault: KeyClient.create_rsa_key ledger-key (azure-keyvault-keys)", key, lane=LANE["runtime"])
    if "kc" not in S:
        return

    def crypto():
        from azure.keyvault.keys.crypto import CryptographyClient
        return CryptographyClient(S["kc"].get_key(NAMES["key"]).id, ctx.cred(), verify_challenge_resource=False)

    def envelope():
        from azure.keyvault.keys.crypto import KeyWrapAlgorithm
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        cc = crypto()
        dek = AESGCM.generate_key(bit_length=256)
        rid = ctx.state.get("work_order_id") or "no-work-order"
        record = f"ledger record: work order {rid} approved by duty.manager".encode()
        nonce = os.urandom(12)
        ct = AESGCM(dek).encrypt(nonce, record, b"approvalledger")
        w = cc.wrap_key(KeyWrapAlgorithm.rsa_oaep_256, dek)
        assert w.encrypted_key != dek
        u = cc.unwrap_key(KeyWrapAlgorithm.rsa_oaep_256, w.encrypted_key)
        assert u.key == dek, "unwrapped DEK differs"
        assert AESGCM(u.key).decrypt(nonce, ct, b"approvalledger") == record
        return "DEK wrapped by ledger-key, record AES-GCM encrypted; unwrap -> decrypt restores the ledger record (envelope encryption)"
    ctx.step("key vault: envelope encryption: wrap_key / unwrap_key a data key that protects a ledger record", envelope, lane=LANE["runtime"])

    def roundtrip():
        from azure.keyvault.keys.crypto import EncryptionAlgorithm
        cc = crypto()
        e = cc.encrypt(EncryptionAlgorithm.rsa_oaep_256, b"hello")
        assert cc.decrypt(EncryptionAlgorithm.rsa_oaep_256, e.ciphertext).plaintext == b"hello"
        return "direct encrypt/decrypt round trip with the vault key"
    ctx.step("key vault: encrypt / decrypt round trip with the vault key", roundtrip, lane=LANE["runtime"])


def _activity(ctx):
    since = time.strftime('%Y-%m-%dT00:00:00Z', time.gmtime(time.time() - 86400))

    def activity():
        from azure.mgmt.monitor import MonitorManagementClient
        evs = list(ctx.arm(MonitorManagementClient).activity_logs.list(filter=f"eventTimestamp ge '{since}'"))
        assert evs, "Activity Log is empty"
        names = {e.operation_name.value for e in evs if e.operation_name}
        for need in ("Microsoft.KeyVault/vaults/write", "Microsoft.Web/sites/write"):
            assert need in names, f"{need} not in the activity log: {sorted(names)[:8]}"
        return f"{len(evs)} control-plane events; includes the vault create and the function app create"
    ctx.step("activity log: the run's control-plane operations are readable (azure-mgmt-monitor)", activity, lane=LANE["runtime"])

    def activity_rg():
        from azure.mgmt.monitor import MonitorManagementClient
        evs = list(ctx.arm(MonitorManagementClient).activity_logs.list(filter=f"eventTimestamp ge '{since}' and resourceGroupName eq '{RG}'"))
        assert evs, "no events for the resource group"
        return f"{len(evs)} events for resource group {RG}"
    ctx.step("activity log: filtered by resource group", activity_rg, lane=LANE["runtime"])
