import os
from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, EncryptionAlgorithm, KeyWrapAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from azlab import DevToken, ENDPOINT
from approval import ledger_row

row = ledger_row("req-demo0001")
record = f"ledger record: work order {row['work_order_id']} approved by {row['approver']}".encode()

kc = KeyClient(vault_url=ENDPOINT, credential=DevToken(), verify_challenge_resource=False)
crypto = CryptographyClient(kc.get_key("ledger-key").id, DevToken(), verify_challenge_resource=False)

dek = AESGCM.generate_key(bit_length=256)
nonce = os.urandom(12)
ciphertext = AESGCM(dek).encrypt(nonce, record, b"approvalledger")
wrapped = crypto.wrap_key(KeyWrapAlgorithm.rsa_oaep_256, dek).encrypted_key
print("the data key is wrapped by ledger-key; wrapped differs from the key:", wrapped != dek)

unwrapped = crypto.unwrap_key(KeyWrapAlgorithm.rsa_oaep_256, wrapped).key
print("unwrap + decrypt restores the record:", AESGCM(unwrapped).decrypt(nonce, ciphertext, b"approvalledger") == record)

sealed = crypto.encrypt(EncryptionAlgorithm.rsa_oaep_256, b"hello")
print("direct encrypt/decrypt round trip:", crypto.decrypt(EncryptionAlgorithm.rsa_oaep_256, sealed.ciphertext).plaintext == b"hello")
