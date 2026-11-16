"""The Service Bus endpoint an ARM namespace shows must be a route that answers on the runtime it
runs on: /azure-data/servicebus/<ns> on the appliance (/api/servicebus/topics is Nano's service
worker only and 404s on the appliance). Run: PYTHONPATH=. python3 tests/conformance/test_azure_shown_endpoints.py"""
import sys
from unittest import mock

from core import azure_arm_core as m
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

AzureArm.STRICT_SUBSCRIPTION = False


def shown(platform):
    a = AzureArm()
    a._public_base = "http://h:9000"
    G = f"/subscriptions/{SUB}/resourceGroups/rg"
    a.handle("PUT", G, {"api-version": "2021-04-01"}, {"location": "eastus"})
    with mock.patch.object(m.sys, "platform", platform):
        r = a.handle("PUT", G + "/providers/Microsoft.ServiceBus/namespaces/sb1", {"api-version": "2022-10-01-preview"}, {"location": "eastus"})
    return r["body"]["properties"]["serviceBusEndpoint"]


off = shown("linux")
nano = shown("emscripten")
assert off == "http://h:9000/azure-data/servicebus/sb1", off
assert nano == "http://h:9000/api/servicebus/topics", nano
print("ok servicebus endpoint: appliance", off, "| nano", nano)


def sql_shown(platform):
    a = AzureArm()
    a._public_base = "http://h:9000"
    G = f"/subscriptions/{SUB}/resourceGroups/rg"
    a.handle("PUT", G, {"api-version": "2021-04-01"}, {"location": "eastus"})
    with mock.patch.object(m.sys, "platform", platform):
        r = a.handle("PUT", G + "/providers/Microsoft.Sql/servers/s1", {"api-version": "2023-05-01-preview"},
                     {"location": "eastus", "properties": {"administratorLogin": "sqladmin", "administratorLoginPassword": "P@ssw0rd123!"}})
    return r["body"]["properties"]


p_off, p_nano = sql_shown("linux"), sql_shown("emscripten")
assert p_off["fullyQualifiedDomainName"] == "http://h:9000/api/console/azure-sql/databases", p_off["fullyQualifiedDomainName"]
assert "/api/console/azure-sql/execute" in p_off["vyomiAccess"]["query"], p_off["vyomiAccess"]
assert p_nano["fullyQualifiedDomainName"] == "http://h:9000/api/azuresql/servers", p_nano["fullyQualifiedDomainName"]
print("ok azure sql endpoint: appliance", p_off["fullyQualifiedDomainName"], "| nano", p_nano["fullyQualifiedDomainName"])
