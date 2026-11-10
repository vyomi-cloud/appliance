"""One Azure subscription per space (core/azure_arm_core.py — Nano and, through
the shared helpers, the offline handler).

The az CLI and the console used to work on different subscriptions: any id was
accepted and got its own store, and GET /subscriptions (what `az login` reads)
wasn't served. Now the space's subscription is discoverable, any other id is
SubscriptionNotFound, resources stored under other ids earlier are adopted,
and resource groups persist even when empty.

    python3 -m pytest -q tests/conformance/test_azure_one_subscription.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core import azure_arm_core as arm  # noqa: E402

SUB = arm.DEFAULT_SUBSCRIPTION
API = "?api-version=2023-01-01"
STG = {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}


def call(a, method, path, body=None):
    return a.handle(method, path, {}, body)


def test_subscription_is_discoverable():
    a = arm.AzureArm()
    r = call(a, "GET", "/subscriptions?api-version=2022-12-01")
    assert r["status"] == 200
    assert [s["subscriptionId"] for s in r["body"]["value"]] == [SUB]
    assert r["body"]["value"][0]["state"] == "Enabled"
    assert call(a, "GET", f"/subscriptions/{SUB}")["body"]["subscriptionId"] == SUB
    t = call(a, "GET", "/tenants?api-version=2022-12-01")["body"]["value"]
    assert t[0]["tenantId"] == arm.TENANT_ID


def test_other_subscription_is_not_found():
    a = arm.AzureArm()
    for path in ("/subscriptions/sub-001", "/subscriptions/sub-001/resourcegroups",
                 f"/subscriptions/sub-001/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/x{API}"):
        r = call(a, "PUT" if path.endswith(API) else "GET", path, STG)
        assert r["status"] == 404 and r["body"]["error"]["code"] == "SubscriptionNotFound", path


def test_subscription_id_is_case_insensitive():
    a = arm.AzureArm()
    r = call(a, "PUT", f"/subscriptions/{SUB.upper()}/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/s1{API}", STG)
    assert r["status"] in (200, 201)
    lst = call(a, "GET", f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts{API}")
    assert [x["name"] for x in lst["body"]["value"]] == ["s1"]


def test_resources_under_other_subscriptions_are_adopted():
    a = arm.AzureArm()
    old = "/subscriptions/sub-001/resourceGroups/rg-smoke/providers/Microsoft.Storage/storageAccounts/legacy1"
    a.state[old.lower()] = {"id": old, "name": "legacy1", "type": "Microsoft.Storage/storageAccounts",
                            "_type": "Microsoft.Storage/storageAccounts", "location": "eastus", "properties": {"ref": old + "/blobServices/default"},
                            "_sub": "sub-001", "_rg": "rg-smoke"}
    lst = call(a, "GET", f"/subscriptions/{SUB}/resourceGroups/rg-smoke/providers/Microsoft.Storage/storageAccounts{API}")
    rec = {x["name"]: x for x in lst["body"]["value"]}["legacy1"]
    assert rec["id"].startswith(f"/subscriptions/{SUB}/")
    assert rec["properties"]["ref"].startswith(f"/subscriptions/{SUB}/")
    assert not any(k.startswith("/subscriptions/sub-001/") for k in a.state)
    assert "rg-smoke" in [g["name"] for g in call(a, "GET", f"/subscriptions/{SUB}/resourcegroups")["body"]["value"]]


def test_adoption_keeps_the_space_copy_on_collision():
    st = {f"/subscriptions/{SUB}/resourcegroups/rg/providers/x/y/n".lower(): {"id": "space", "_sub": SUB},
          "/subscriptions/other/resourcegroups/rg/providers/x/y/n": {"id": "foreign", "_sub": "other"}}
    assert arm.adopt_foreign_subscriptions(st) == 0
    assert [r["id"] for r in st.values()] == ["space"]


def test_resource_groups_persist_and_delete_cascades():
    a = arm.AzureArm()
    rg = f"/subscriptions/{SUB}/resourceGroups/empty-rg"
    assert call(a, "GET", rg)["status"] == 404
    assert call(a, "PUT", rg, {"location": "westus", "tags": {"env": "dev"}})["status"] == 201
    assert call(a, "PUT", rg, {"location": "westus"})["status"] == 200
    got = call(a, "GET", rg)["body"]
    assert got["location"] == "westus" and got["tags"] == {"env": "dev"}
    assert "empty-rg" in [g["name"] for g in call(a, "GET", f"/subscriptions/{SUB}/resourcegroups")["body"]["value"]]
    call(a, "PUT", f"{rg}/providers/Microsoft.Storage/storageAccounts/inrg{API}", STG)
    assert call(a, "DELETE", rg)["status"] == 200
    assert call(a, "GET", rg)["status"] == 404
    assert call(a, "GET", f"{rg}/providers/Microsoft.Storage/storageAccounts{API}")["body"]["value"] == []
