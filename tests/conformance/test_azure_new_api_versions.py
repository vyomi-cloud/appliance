"""Upstream drift (#502 Cosmos 2026-07-15, #500 CognitiveServices 2026-09-15-preview,
#499 Web 2026-08-01, #520 KeyVault 2026-10-01-preview, #528 Sql 2026-08-01-preview, #534 Storage 2027-03-07, #340 Compute 2026-11-01-preview): Vyomi's ARM layer must accept
the newly published api-versions the same way it accepts older ones (create, get, delete)."""
import json, os, sys, time, urllib.request, urllib.error

B = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
SUB = "00000000-0000-0000-0000-cloudlearn01"
CASES = [
    ("Microsoft.DocumentDB/databaseAccounts", "vyomidrift502", "2026-07-15",
     {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard"}}),
    ("Microsoft.CognitiveServices/accounts", "vyomidrift500", "2026-09-15-preview",
     {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {}}),
    ("Microsoft.Web/serverfarms", "vyomidrift499", "2026-08-01",
     {"location": "eastus", "sku": {"name": "B1"}, "properties": {}}),
    ("Microsoft.KeyVault/vaults", "vyomidrift520", "2026-10-01-preview",
     {"location": "eastus", "properties": {"tenantId": "00000000-0000-0000-0000-000000000000",
                                          "sku": {"family": "A", "name": "standard"}}}),
    ("Microsoft.Sql/servers", "vyomidrift528", "2026-08-01-preview",
     {"location": "eastus", "properties": {"administratorLogin": "vyomiadmin", "administratorLoginPassword": "P@ssw0rd-Vyomi1"}}),
    ("Microsoft.Storage/storageAccounts", "vyomidrift534", "2027-03-07",
     {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}, "properties": {}}),
]
fails = 0

def call(method, url, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

RUN = str(int(time.time() * 1000) % 10000000)  # soft-deleted names (Cognitive Services) can't be reused
for rtype, name, ver, body in CASES:
    name += RUN
    url = f"{B}/subscriptions/{SUB}/resourceGroups/rg-drift/providers/{rtype}/{name}?api-version={ver}"
    s1, _ = call("PUT", url, body)
    s2, b2 = call("GET", url)
    ok = s1 in (200, 201, 202) and s2 == 200 and name.encode() in b2
    s3, _ = call("DELETE", url)
    ok = ok and s3 in (200, 202, 204)
    print(f"[{'PASS' if ok else 'FAIL'}] {rtype} accepts api-version {ver} (put={s1} get={s2} delete={s3})")
    fails += not ok

# #340 Compute 2026-11-01-preview: Vyomi's compute routes are api-version neutral, so the preview
# version must behave exactly like a known-good one (and never be rejected as an unknown version).
cu = f"{B}/subscriptions/{SUB}/resourceGroups/rg-drift/providers/Microsoft.Compute/restorePointCollections/vyomidrift340"
body = {"location": "eastus", "properties": {"source": {"id": "/x"}}}
sa, ba = call("PUT", cu + "?api-version=2024-07-01", body)
sb, bb = call("PUT", cu + "?api-version=2026-11-01-preview", body)
ok = sa == sb and b"InvalidApiVersion" not in bb and b"NoRegisteredProvider" not in bb
print(f"[{'PASS' if ok else 'FAIL'}] Microsoft.Compute accepts api-version 2026-11-01-preview like 2024-07-01 ({sa} vs {sb})")
fails += not ok

# #534 Storage data plane: a blob request pinned to x-ms-version 2027-03-07 must be served like an older one.
def blob_status(ver):
    req = urllib.request.Request(f"{B}/devstoreaccount1?comp=list", headers={"x-ms-version": ver})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
va, vb = blob_status("2023-11-03"), blob_status("2027-03-07")
ok = va == vb and vb < 500
print(f"[{'PASS' if ok else 'FAIL'}] Blob service accepts x-ms-version 2027-03-07 like 2023-11-03 ({va} vs {vb})")
fails += not ok
sys.exit(1 if fails else 0)
