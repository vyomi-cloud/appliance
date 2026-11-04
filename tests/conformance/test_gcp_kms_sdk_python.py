"""Cloud KMS importJobs + destroy-scheduled versions through the official google-cloud-kms
Python SDK (REST transport, endpoint changed only). Exercises CreateImportJob / GetImportJob /
ListImportJobs and DestroyCryptoKeyVersion (scheduled-destroy purge path)."""
import os
import sys
import time
import uuid

from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import kms

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)}")
    failed = failed or not ok


c = kms.KeyManagementServiceClient(credentials=AnonymousCredentials(), transport="rest",
                                   client_options=ClientOptions(api_endpoint=BASE))
c._transport._host = BASE  # keep http scheme for the local endpoint
proj, loc, tag = "vyomi-project", "us-central1", uuid.uuid4().hex[:6]
parent = f"projects/{proj}/locations/{loc}"
try:
    ring = c.create_key_ring(request={"parent": parent, "key_ring_id": f"sdk-{tag}", "key_ring": {}})
    check("CreateKeyRing", ring.name.endswith(f"/keyRings/sdk-{tag}"), ring.name)
    ij = c.create_import_job(request={"parent": ring.name, "import_job_id": "job1", "import_job": {
        "import_method": kms.ImportJob.ImportMethod.RSA_OAEP_3072_SHA1_AES_256,
        "protection_level": kms.ProtectionLevel.SOFTWARE}})
    check("CreateImportJob", ij.name.endswith("/importJobs/job1"), ij.name)
    got = None
    for _ in range(20):
        got = c.get_import_job(request={"name": ij.name})
        if got.state == kms.ImportJob.ImportJobState.ACTIVE:
            break
        time.sleep(0.5)
    check("GetImportJob becomes ACTIVE with public key", got.state == kms.ImportJob.ImportJobState.ACTIVE and bool(got.public_key.pem), got.state)
    check("ListImportJobs", [j.name for j in c.list_import_jobs(request={"parent": ring.name})] == [ij.name])
    key = c.create_crypto_key(request={"parent": ring.name, "crypto_key_id": "k1", "crypto_key": {
        "purpose": kms.CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT}})
    v = c.create_crypto_key_version(request={"parent": key.name, "crypto_key_version": {}})
    d = c.destroy_crypto_key_version(request={"name": v.name})
    check("DestroyCryptoKeyVersion -> DESTROY_SCHEDULED", d.state == kms.CryptoKeyVersion.CryptoKeyVersionState.DESTROY_SCHEDULED, d.state)
except Exception as e:  # noqa: BLE001
    check("SDK flow", False, repr(e)[:300])
sys.exit(1 if failed else 0)
