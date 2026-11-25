from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, KeyWrapAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from azlab import DevToken, ENDPOINT

kc = KeyClient(vault_url=ENDPOINT, credential=DevToken(), verify_challenge_resource=False)
v1 = kc.get_key("ledger-key")
dek = AESGCM.generate_key(bit_length=256)
alg = KeyWrapAlgorithm.rsa_oaep_256
wrapped_v1 = CryptographyClient(v1.id, DevToken(), verify_challenge_resource=False).wrap_key(alg, dek).encrypted_key

v2 = kc.rotate_key("ledger-key")
versions = list(kc.list_properties_of_key_versions("ledger-key"))
assert len(versions) >= 2 and v2.properties.version != v1.properties.version, "rotation must create a new version"
print("versions:", len(versions), "| current changed:", v2.properties.version != v1.properties.version)

assert CryptographyClient(v1.id, DevToken(), verify_challenge_resource=False).unwrap_key(alg, wrapped_v1).key == dek
print("data wrapped by the old version still unwraps")
wrapped_v2 = CryptographyClient(v2.id, DevToken(), verify_challenge_resource=False).wrap_key(alg, dek).encrypted_key
assert wrapped_v2 != wrapped_v1
print("key rotation verified")
