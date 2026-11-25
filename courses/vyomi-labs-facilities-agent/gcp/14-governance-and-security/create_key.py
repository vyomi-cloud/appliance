import time

from google.api_core import exceptions as gex
from google.cloud import kms

import gcp

client = gcp.rest(kms.KeyManagementServiceClient)
ring = f"{gcp.PARENT}/keyRings/facilities"
try:
    client.create_key_ring(request={"parent": gcp.PARENT, "key_ring_id": "facilities", "key_ring": {}})
except gex.Conflict:
    pass
try:
    key = client.create_crypto_key(request={"parent": ring, "crypto_key_id": "ledger-key", "crypto_key": {
        "purpose": kms.CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT, "rotation_period": {"seconds": 7776000},
        "next_rotation_time": {"seconds": int(time.time()) + 7776000}}}).name
except gex.Conflict:
    key = f"{ring}/cryptoKeys/ledger-key"
print("key:", key.split("/keyRings/", 1)[1], "with 90-day rotation")
