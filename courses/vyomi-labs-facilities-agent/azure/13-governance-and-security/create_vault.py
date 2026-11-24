from azure.mgmt.keyvault import KeyVaultManagementClient
from azure.mgmt.keyvault.models import Sku, SkuFamily, SkuName, VaultCreateOrUpdateParameters, VaultProperties
from azlab import arm, ensure_rg, RG, LOC

ensure_rg()
v = arm(KeyVaultManagementClient).vaults.begin_create_or_update(RG, "facilities-kv", VaultCreateOrUpdateParameters(location=LOC, properties=VaultProperties(
    tenant_id="00000000-0000-0000-0000-000000000000", sku=Sku(family=SkuFamily.A, name=SkuName.STANDARD), access_policies=[]))).result()
print("vault", v.name, "created; uri advertised by ARM:", v.properties.vault_uri)
