from azure.keyvault.keys import KeyClient
from azlab import DevToken, ENDPOINT

client = KeyClient(vault_url=ENDPOINT, credential=DevToken(), verify_challenge_resource=False)
key = client.create_rsa_key("ledger-key", size=2048)
print("key", key.name, "type", key.key.kty, "| listed:", [k.name for k in client.list_properties_of_keys()])
