"""Unit tests for core/azure_eventhub_core.py (run: python3 tests/conformance/test_azure_eventhub_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_eventhub_core as eh  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, rg="rg1", query=None):
    return eh.dispatch(st, method, "sub1", rg, chain, [], body or {}, query or {})


st = {}
NS = {"location": "eastus", "sku": {"name": "Standard", "capacity": 2}}
r = cp(st, "PUT", ["namespaces", "ehns-one"], NS)
p = r["body"]["properties"]
check("namespace create → 201 + LRO, endpoint, Succeeded, Kafka on",
      r["status"] == 201 and r["lro"] and p["serviceBusEndpoint"] == "https://ehns-one.servicebus.windows.net:443/"
      and p["provisioningState"] == "Succeeded" and p["kafkaEnabled"] is True and r["body"]["sku"]["capacity"] == 2, r["body"])
check("name too short", cp(st, "PUT", ["namespaces", "ab"], NS)["status"] == 400)
check("name conflict across RGs", cp(st, "PUT", ["namespaces", "ehns-one"], NS, rg="rg2")["status"] == 409)
check("location required", cp(st, "PUT", ["namespaces", "ehns-two"], {})["status"] == 400)
check("bad sku", cp(st, "PUT", ["namespaces", "ehns-two"], {"location": "eastus", "sku": {"name": "Gold"}})["status"] == 400)
r = cp(st, "PATCH", ["namespaces", "ehns-one"], {"tags": {"a": "b"}, "properties": {"isAutoInflateEnabled": True, "maximumThroughputUnits": 10}})
check("PATCH tags + auto-inflate", r["body"]["tags"] == {"a": "b"} and r["body"]["properties"]["maximumThroughputUnits"] == 10, r["body"])
check("auto-inflate needs max TUs", cp(st, "PATCH", ["namespaces", "ehns-one"], {"properties": {"isAutoInflateEnabled": True, "maximumThroughputUnits": 0}})["status"] == 400)
check("checkNameAvailability taken / free",
      cp(st, "POST", ["checkNameAvailability"], {"name": "ehns-one"}, rg=None)["body"]["nameAvailable"] is False
      and cp(st, "POST", ["checkNameAvailability"], {"name": "fresh-ns"}, rg=None)["body"]["nameAvailable"] is True)

rules = cp(st, "GET", ["namespaces", "ehns-one", "authorizationRules"])["body"]["value"]
check("RootManageSharedAccessKey exists with all rights", [x["name"] for x in rules] == ["RootManageSharedAccessKey"]
      and sorted(rules[0]["properties"]["rights"]) == ["Listen", "Manage", "Send"])
k = cp(st, "POST", ["namespaces", "ehns-one", "authorizationRules", "RootManageSharedAccessKey", "listKeys"])["body"]
check("listKeys connection strings", k["primaryConnectionString"].startswith("Endpoint=sb://ehns-one.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey="), k)
k2 = cp(st, "POST", ["namespaces", "ehns-one", "authorizationRules", "RootManageSharedAccessKey", "regenerateKeys"], {"keyType": "PrimaryKey"})["body"]
check("regenerateKeys rotates only the named key", k2["primaryKey"] != k["primaryKey"] and k2["secondaryKey"] == k["secondaryKey"])
check("Manage requires Listen+Send", cp(st, "PUT", ["namespaces", "ehns-one", "authorizationRules", "bad"], {"properties": {"rights": ["Manage"]}})["status"] == 400)
check("root rule can't be deleted", cp(st, "DELETE", ["namespaces", "ehns-one", "authorizationRules", "RootManageSharedAccessKey"])["status"] == 400)

H = ["namespaces", "ehns-one", "eventhubs"]
r = cp(st, "PUT", H + ["orders"], {"properties": {"partitionCount": 4, "messageRetentionInDays": 3}})
hp = r["body"]["properties"]
check("event hub create", r["status"] == 201 and hp["partitionIds"] == ["0", "1", "2", "3"] and hp["messageRetentionInDays"] == 3
      and hp["status"] == "Active", r["body"])
check("partitionCount bounds", cp(st, "PUT", H + ["x"], {"properties": {"partitionCount": 99}})["status"] == 400)
check("retention bounds (Standard ≤ 7)", cp(st, "PUT", H + ["x"], {"properties": {"messageRetentionInDays": 30}})["status"] == 400)
check("partition count immutable on Standard", cp(st, "PUT", H + ["orders"], {"properties": {"partitionCount": 8}})["status"] == 400)
cgs = cp(st, "GET", H + ["orders", "consumergroups"])["body"]["value"]
check("$Default consumer group auto-created", [c["name"] for c in cgs] == ["$Default"])
check("create + delete consumer group", cp(st, "PUT", H + ["orders", "consumergroups", "cg1"], {"properties": {"userMetadata": "m"}})["body"]["properties"]["userMetadata"] == "m"
      and cp(st, "DELETE", H + ["orders", "consumergroups", "cg1"])["status"] == 200)
check("$Default can't be deleted", cp(st, "DELETE", H + ["orders", "consumergroups", "$Default"])["status"] == 400)
check("hub-scoped rule connection string has EntityPath",
      cp(st, "PUT", H + ["orders", "authorizationRules", "send"], {"properties": {"rights": ["Send"]}})["status"] == 200
      and cp(st, "POST", H + ["orders", "authorizationRules", "send", "listKeys"])["body"]["primaryConnectionString"].endswith(";EntityPath=orders"))
check("missing hub → 404", cp(st, "GET", H + ["nope"])["status"] == 404)

r = cp(st, "POST", H + ["orders", "events"], {"events": [{"body": "a", "partitionKey": "k1"}, {"body": "b", "partitionKey": "k1"}, {"body": "c"}]})
check("send events", r["status"] == 201 and r["body"]["sent"] == 3, r["body"])
same = {e["partitionId"] for e in r["body"]["value"][:2]}
check("same partition key → same partition, ordered sequence", len(same) == 1
      and r["body"]["value"][1]["sequenceNumber"] == r["body"]["value"][0]["sequenceNumber"] + 1)
got = cp(st, "GET", H + ["orders", "events"], query={"maxCount": "10"})["body"]
check("read events back", got["count"] == 3 and {e["body"] for e in got["value"]} == {"a", "b", "c"})
check("read one partition", all(e["partitionId"] == list(same)[0] for e in cp(st, "GET", H + ["orders", "events"], query={"partitionId": list(same)[0]})["body"]["value"]))
check("bad partition id", cp(st, "POST", H + ["orders", "events"], {"events": [{"body": "z"}], "partitionId": "9"})["status"] == 400)
parts = cp(st, "GET", H + ["orders", "events", "partitions"])["body"]["value"]
check("partition properties", len(parts) == 4 and sum(1 for p_ in parts if not p_["isEmpty"]) >= 1)
cp(st, "PUT", H + ["off"], {"properties": {"status": "SendDisabled"}})
check("sending to a disabled hub → 403", cp(st, "POST", H + ["off", "events"], {"events": [{"body": "x"}]})["status"] == 403)

d = eh.data_dispatch(st, "ehns-one", "POST", "/orders/messages", {}, {"content-type": "application/atom+xml;type=entry", "BrokerProperties": json.dumps({"PartitionKey": "pk"})}, b"hello")
check("REST send single event → 201", d["status"] == 201, d)
d = eh.data_dispatch(st, "ehns-one", "POST", "/orders/messages", {}, {"content-type": eh.BATCH_MEDIA}, json.dumps([{"Body": "x"}, {"Body": "y", "BrokerProperties": {"PartitionKey": "z"}}]).encode())
check("REST send batch → 201", d["status"] == 201, d)
d = eh.data_dispatch(st, "ehns-one", "POST", "/orders/partitions/2/messages", {}, {}, b"to-p2")
check("REST send to partition 2", d["status"] == 201 and any(e["partitionId"] == "2" and e["body"] == "to-p2" for e in cp(st, "GET", H + ["orders", "events"], query={"partitionId": "2"})["body"]["value"]))
check("REST unknown hub → 404", eh.data_dispatch(st, "ehns-one", "POST", "/nope/messages", {}, {}, b"x")["status"] == 404)
check("REST partition properties", eh.data_dispatch(st, "ehns-one", "GET", "/orders/partitions/2")["body"]["partitionId"] == "2")

check("basic tier: one consumer group only", cp(st, "PUT", ["namespaces", "ehbasic"], {"location": "eastus", "sku": {"name": "Basic"}})["body"]["properties"]["kafkaEnabled"] is False
      and cp(st, "PUT", ["namespaces", "ehbasic", "eventhubs", "h"], {})["status"] == 201
      and cp(st, "PUT", ["namespaces", "ehbasic", "eventhubs", "h", "consumergroups", "c"], {})["status"] == 400)
check("basic tier: retention capped at 1 day", cp(st, "PUT", ["namespaces", "ehbasic", "eventhubs", "h2"], {"properties": {"messageRetentionInDays": 2}})["status"] == 400)
check("network rule set default", cp(st, "PUT", ["namespaces", "ehns-one", "networkRuleSets", "default"], {"properties": {"defaultAction": "Deny", "ipRules": [{"ipMask": "1.2.3.4", "action": "Allow"}]}})["body"]["properties"]["defaultAction"] == "Deny")
partner = next(k_ for k_ in st if k_.endswith("/ehbasic"))
dr = cp(st, "PUT", ["namespaces", "ehns-one", "disasterRecoveryConfigs", "alias1"], {"properties": {"partnerNamespace": partner}})
check("geo-recovery pairing", dr["status"] == 200 and dr["body"]["properties"]["role"] == "Primary", dr["body"])
check("list in RG / subscription", len(cp(st, "GET", ["namespaces"])["body"]["value"]) == 2 and len(cp(st, "GET", ["namespaces"], rg=None)["body"]["value"]) == 2)
check("internal state never serialised", "_hubs" not in json.dumps(cp(st, "GET", ["namespaces", "ehns-one"])["body"]))
check("delete hub", cp(st, "DELETE", H + ["orders"])["status"] == 200 and cp(st, "GET", H + ["orders"])["status"] == 404)
r = cp(st, "DELETE", ["namespaces", "ehns-one"])
check("delete namespace (LRO) then 404", r["status"] == 200 and r["lro"] and cp(st, "GET", ["namespaces", "ehns-one"])["status"] == 404)

# through the Nano ARM class (the same engine behind native /subscriptions/* paths)
arm = AzureArm()
base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg/providers/Microsoft.EventHub"
resp = arm.handle("PUT", f"{base}/namespaces/armns-one", {"api-version": "2024-01-01"}, NS)
check("AzureArm routes Microsoft.EventHub to the engine (+ LRO headers)", resp["status"] == 200 and "Azure-AsyncOperation" in resp["headers"], resp)
resp = arm.handle("PUT", f"{base}/namespaces/armns-one/eventhubs/h1", {"api-version": "2024-01-01"}, {"properties": {"partitionCount": 2}})
check("AzureArm routes event hub children", resp["status"] == 201 and resp["body"]["properties"]["partitionCount"] == 2, resp)
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
