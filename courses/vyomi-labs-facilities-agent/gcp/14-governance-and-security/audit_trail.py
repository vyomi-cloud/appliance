import time

import gcp

client = gcp.logging_client()
flt = f'logName="projects/{gcp.PROJECT}/logs/cloudaudit.googleapis.com%2Factivity"'
methods = set()
for _ in range(20):
    entries = list(client.list_entries(filter_=flt, page_size=200))
    methods = {e.payload.get("methodName") for e in entries if isinstance(getattr(e, "payload", None), dict)} - {None}
    if any("CreateCryptoKey" in m for m in methods):
        break
    time.sleep(0.5)
short = sorted({m.rsplit(".", 1)[-1] for m in methods})
print("admin activity:", ", ".join(short))
for needed in ("CreateKeyRing", "CreateCryptoKey", "CreateTopic"):
    assert any(needed in m for m in methods), needed
print("the run is in the audit log")
