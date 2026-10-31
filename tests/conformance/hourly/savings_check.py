#!/usr/bin/env python3
"""Cost-savings conformance: every resource created, and every use of it, must
show up in the space's savings metrics, on every cloud.

For AWS, GCP and Azure in turn: switch to that cloud's space, create a storage
resource through the cloud's native API, check the space's resource_count and
that cloud's savings went up, then USE the resource (upload objects) and check
the savings went up again — real clouds bill storage and requests, so a
simulator that saves you that bill must count it.

    ENDPOINT=http://localhost:9000 python3 tests/conformance/hourly/savings_check.py

Prints one PASS/FAIL line per check; exits 1 on any FAIL.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid

BASE = os.environ.get("ENDPOINT", "http://localhost:9000").rstrip("/")
fails = 0


def check(ok: bool, what: str, detail: str = "") -> bool:
    global fails
    print(f"{'PASS' if ok else 'FAIL'}: {what}" + (f" :: {detail}" if detail and not ok else ""))
    fails += 0 if ok else 1
    return ok


def http(method: str, url: str, body=None, headers=None, raw: bytes | None = None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode(errors="replace")
        return r.status, (json.loads(txt) if txt.strip().startswith(("{", "[")) else txt)


def savings() -> dict:
    _, d = http("GET", f"{BASE}/api/spaces")
    sp = d.get("active_space") or {}
    cs = sp.get("cost_savings") or {}
    return {"count": cs.get("resource_count", 0) or 0, "usd": cs.get("savings_usd", 0.0) or 0.0,
            "by_provider": cs.get("by_provider") or {}}


def wait_for(pred, before: dict, timeout=12.0) -> dict:
    """Savings recompute on the space tick after a write; poll briefly."""
    end = time.time() + timeout
    cur = savings()
    while time.time() < end and not pred(before, cur):
        time.sleep(1.0)
        cur = savings()
    return cur


def switch_to(cloud: str) -> bool:
    _, d = http("GET", f"{BASE}/api/spaces")
    sid = next((s.get("space_id") or s.get("id") for s in d.get("spaces", []) if s.get("provider") == cloud), None)
    if not sid:
        return check(False, f"{cloud}: a {cloud} space exists to switch to")
    http("POST", f"{BASE}/api/spaces/{sid}/switch")
    return True


def create_aws(name: str):
    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", endpoint_url=BASE, region_name="us-east-1", aws_access_key_id="test",
                      aws_secret_access_key="test", config=Config(s3={"addressing_style": "path"}))
    s3.create_bucket(Bucket=name)
    return lambda i, blob: s3.put_object(Bucket=name, Key=f"obj-{i}.bin", Body=blob)


def create_gcp(name: str):
    # Every GCP space is one project; the legacy "gcp-dev" id is refused like any unknown project.
    _, projs = http("GET", f"{BASE}/v1/projects")
    project = projs["projects"][0]["projectId"]
    http("POST", f"{BASE}/storage/v1/b?project={project}", {"name": name})
    return lambda i, blob: http("POST", f"{BASE}/upload/storage/v1/b/{name}/o?uploadType=media&name=obj-{i}.bin",
                                raw=blob, headers={"Content-Type": "application/octet-stream"})


def create_azure(name: str):
    sub, rg = "00000000-0000-0000-0000-cloudlearn01", "rg-savings-check"
    arm = f"{BASE}/subscriptions/{sub}/resourceGroups/{rg}"
    http("PUT", f"{arm}?api-version=2021-04-01", {"location": "eastus"})
    http("PUT", f"{arm}/providers/Microsoft.Storage/storageAccounts/{name}?api-version=2023-01-01",
         {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"})
    # Blob data plane is Azurite (native wire); the well-known dev account is what
    # the appliance wires the Azure blob service to.
    from azure.storage.blob import BlobServiceClient
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or (
        "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
        "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
        f"BlobEndpoint=http://{BASE.split('://', 1)[-1].split(':')[0]}:10000/devstoreaccount1;")
    container = BlobServiceClient.from_connection_string(conn).create_container(name)
    return lambda i, blob: container.upload_blob(name=f"obj-{i}.bin", data=blob, overwrite=True)


CLOUDS = {
    "aws": ("S3 bucket", create_aws, lambda: f"sav-{uuid.uuid4().hex[:10]}"),
    "gcp": ("Cloud Storage bucket", create_gcp, lambda: f"sav-{uuid.uuid4().hex[:10]}"),
    "azure": ("Storage account", create_azure, lambda: f"sav{uuid.uuid4().hex[:12]}"),
}


def check_azure_vm() -> None:
    """An Azure VM is billed per hour by size: Standard_B1s is $0.0104/h list price,
    so one VM must add about $7.59 (730 h) to Azure savings, not $0."""
    print("\n== azure: Virtual machine (Standard_B1s) ==")
    try:
        if not switch_to("azure"):
            return
        sub, rg, name = "00000000-0000-0000-0000-cloudlearn01", "rg-savings-check", f"vm-sav-{uuid.uuid4().hex[:8]}"
        before = savings()
        http("PUT", f"{BASE}/subscriptions/{sub}/resourceGroups/{rg}?api-version=2021-04-01", {"location": "eastus"})
        http("PUT", f"{BASE}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}?api-version=2023-09-01",
             {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}}})
        after = wait_for(lambda b, c: c["by_provider"].get("azure", 0) > b["by_provider"].get("azure", 0) + 1, before)
        added = round(after["by_provider"].get("azure", 0) - before["by_provider"].get("azure", 0), 2)
        check(after["count"] > before["count"], "azure: creating a VM raises the space resource_count",
              f"{before['count']} → {after['count']}")
        check(abs(added - 7.59) < 0.05, "azure: a Standard_B1s VM adds its 730 h list price ($7.59) to Azure savings",
              f"added ${added}")
    except Exception as e:  # noqa: BLE001
        check(False, "azure: VM savings check ran", repr(e)[:300])


def main() -> int:
    for cloud, (label, create, mkname) in CLOUDS.items():
        print(f"\n== {cloud}: {label} ==")
        try:
            if not switch_to(cloud):
                continue
            before = savings()
            use = create(mkname())
            after = wait_for(lambda b, c: c["count"] > b["count"] and c["by_provider"].get(cloud, 0) > b["by_provider"].get(cloud, 0), before)
            check(after["count"] > before["count"], f"{cloud}: creating a {label} raises the space resource_count",
                  f"{before['count']} → {after['count']}")
            check(after["by_provider"].get(cloud, 0) > before["by_provider"].get(cloud, 0),
                  f"{cloud}: creating a {label} raises {cloud} savings",
                  f"${before['by_provider'].get(cloud, 0)} → ${after['by_provider'].get(cloud, 0)}")

            blob = os.urandom(2 * 1024 * 1024)
            for i in range(5):
                use(i, blob)
            used = wait_for(lambda b, c: c["usd"] > b["usd"], after)
            check(used["usd"] > after["usd"], f"{cloud}: using the {label} (5 × 2 MB uploads) raises savings",
                  f"${after['usd']} → ${used['usd']} (real {cloud} bills storage + requests)")
        except Exception as e:  # noqa: BLE001
            check(False, f"{cloud}: savings check ran", repr(e)[:300])
    check_azure_vm()
    print(f"\nRESULT fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
