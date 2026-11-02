"""Sweep F (Azure) core conformance: Service Bus networking enforcement.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_sweepf_core.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB, servicebus_network_denied  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def p(rg, ns, typ, name):
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/{ns}/{typ}/{name}"


def run():
    arm = AzureArm()
    av = {"api-version": "2022-10-01-preview"}
    arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/sf", {"api-version": "2021-04-01"}, {"location": "eastus"})

    # ── Service Bus networking ──
    ns = p("sf", "Microsoft.ServiceBus", "namespaces", "sfns")
    arm.handle("PUT", ns, av, {"location": "eastus", "sku": {"name": "Premium", "tier": "Premium"}, "properties": {}})
    r = arm.handle("GET", ns + "/networkRuleSets/default", av)
    check("fresh namespace has an open default rule set", r["status"] == 200 and r["body"]["properties"]["defaultAction"] == "Allow")
    check("open namespace is not denied", not servicebus_network_denied(arm.state, "sfns"))
    r = arm.handle("PUT", ns + "/networkRuleSets/default", av, {"properties": {"defaultAction": "Deny", "ipRules": [{"ipMask": "10.0.0.0/24", "action": "Allow"}]}})
    check("rule set PUT stores", r["status"] in (200, 201))
    r = arm.handle("GET", ns + "/networkRuleSets/default", av)
    check("rule set round-trips", r["body"]["properties"]["ipRules"][0]["ipMask"] == "10.0.0.0/24")
    check("Deny default action blocks the data plane", servicebus_network_denied(arm.state, "sfns"))
    arm.handle("PUT", ns + "/networkRuleSets/default", av, {"properties": {"defaultAction": "Allow"}})
    check("Allow re-opens it", not servicebus_network_denied(arm.state, "sfns"))
    arm.handle("PATCH", ns, av, {"properties": {"publicNetworkAccess": "Disabled"}})
    check("publicNetworkAccess Disabled blocks the data plane", servicebus_network_denied(arm.state, "sfns"))
    check("unknown namespace is never blocked", not servicebus_network_denied(arm.state, "nope"))
    pec = ns + "/privateEndpointConnections/pe1"
    r = arm.handle("PUT", pec, av, {"properties": {"privateLinkServiceConnectionState": {"status": "Approved"}}})
    check("private endpoint connection stored", r["status"] in (200, 201))
    r = arm.handle("GET", ns + "/privateEndpointConnections", av)
    check("private endpoint connection listed", [x["name"] for x in r["body"]["value"]] == ["pe1"])


if __name__ == "__main__":
    run()
    print("\nRESULT: PASS — sweep F core conformance")
