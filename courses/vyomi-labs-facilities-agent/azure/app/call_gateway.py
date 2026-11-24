import requests
from gw import url, headers

ok = requests.post(url("tools/asset-status"), json={"asset_id": "B-12"}, headers=headers(), timeout=60)
print("with the subscription key:", ok.status_code, "| B-12 status:", ok.json()["asset"]["status"])
no = requests.post(url("tools/asset-status"), json={"asset_id": "B-12"}, headers={"Content-Type": "application/json"}, timeout=30)
print("without a key:", no.status_code)
