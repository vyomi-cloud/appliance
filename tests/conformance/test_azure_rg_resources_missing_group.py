"""Listing the resources of a resource group that does not exist is 404 ResourceGroupNotFound (real ARM), not an empty 200.
An empty existing group, the implicit default group and a group created by PUT stay 200.
Run: PYTHONPATH=. python tests/conformance/test_azure_rg_resources_missing_group.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB, DEFAULT_RG
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    R = {"api-version": "2021-04-01"}
    lst = lambda g: a.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{g}/resources", R, None)
    r = lst("nope-zzz")
    _check("missing group -> 404", r["status"] == 404)
    _check("missing group -> ResourceGroupNotFound", (r["body"] or {}).get("error", {}).get("code") == "ResourceGroupNotFound")
    a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/emptygrp", R, {"location": "eastus"})
    e = lst("emptygrp")
    _check("created empty group -> 200 []", e["status"] == 200 and e["body"]["value"] == [])
    _check("case-insensitive existing group -> 200", lst("EMPTYGRP")["status"] == 200)
    _check("implicit default group -> 200", lst(DEFAULT_RG)["status"] == 200)


if __name__ == "__main__":
    run()
    print("PASS")
