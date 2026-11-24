import json

from cryptography.fernet import Fernet
from google.api_core import exceptions as gex
from google.cloud import kms

import gcp

client = gcp.rest(kms.KeyManagementServiceClient)
KEY = f"{gcp.PARENT}/keyRings/facilities/cryptoKeys/ledger-key"
CONTEXT = b"collection=approval-ledger"

record = json.dumps({"work_order": "WO-000102", "approved_by": "duty.manager@example.com"}).encode()
data_key = Fernet.generate_key()
sealed = Fernet(data_key).encrypt(record)
wrapped = client.encrypt(request={"name": KEY, "plaintext": data_key, "additional_authenticated_data": CONTEXT}).ciphertext
assert b"duty.manager" not in sealed and data_key not in wrapped
print("record sealed; the stored blob does not contain the approver")

back = client.decrypt(request={"name": KEY, "ciphertext": wrapped, "additional_authenticated_data": CONTEXT}).plaintext
print("round trip with the right context:", json.loads(Fernet(back).decrypt(sealed))["work_order"])
try:
    client.decrypt(request={"name": KEY, "ciphertext": wrapped, "additional_authenticated_data": b"collection=other"})
    print("wrong context: ACCEPTED (bad)")
except gex.GoogleAPICallError:
    print("wrong context refused")
