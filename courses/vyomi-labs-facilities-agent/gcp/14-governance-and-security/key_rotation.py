from google.cloud import kms

import gcp

client = gcp.rest(kms.KeyManagementServiceClient)
KEY = f"{gcp.PARENT}/keyRings/facilities/cryptoKeys/ledger-key"
CTX = b"collection=approval-ledger"
dek = b"0123456789abcdef0123456789abcdef"

before = client.get_crypto_key(request={"name": KEY}).primary.name
old = client.encrypt(request={"name": KEY, "plaintext": dek, "additional_authenticated_data": CTX}).ciphertext

new_version = client.create_crypto_key_version(request={"parent": KEY, "crypto_key_version": {}}).name
client.update_crypto_key_primary_version(request={"name": KEY, "crypto_key_version_id": new_version.rsplit("/", 1)[-1]})
after = client.get_crypto_key(request={"name": KEY}).primary.name
assert after != before and after == new_version, "the new version must be primary"
print("primary:", before.rsplit("/", 1)[-1], "->", after.rsplit("/", 1)[-1])

assert client.decrypt(request={"name": KEY, "ciphertext": old, "additional_authenticated_data": CTX}).plaintext == dek
print("ciphertext from the old version still decrypts")
fresh = client.encrypt(request={"name": KEY, "plaintext": dek, "additional_authenticated_data": CTX}).ciphertext
assert fresh != old
print("key rotation verified")
