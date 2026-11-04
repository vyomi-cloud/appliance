"""Azure data-plane network rules (storage + SQL): a caller that declares its network identity (x-vyomi-source-ip /
-subnet / -private-endpoint / -trusted-service) is subject to publicNetworkAccess, IP rules, vnet rules and
private endpoints; an undeclared caller keeps the legacy behaviour.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_netaccess.py
"""
import json

from core import azure_blob_core as az
from core import azure_sql_core as sq

SUB = "/subscriptions/s1/resourceGroups/rg/providers"
ACCT = f"{SUB}/Microsoft.Storage/storageAccounts/stor1"
SRV = f"{SUB}/Microsoft.Sql/servers/srv1"
VNET = f"{SUB}/Microsoft.Network/virtualNetworks/vn1"
SUBNET = f"{VNET}/subnets/app"
PE = f"{SUB}/Microsoft.Network/privateEndpoints/pe1"


def ok(name, cond, extra=""):
    if not cond:
        raise AssertionError(f"{name} {extra}")
    print(f"  ok  {name}")


def main():
    state = {
        ACCT.lower(): {"id": ACCT, "_type": "microsoft.storage/storageaccounts", "properties": {
            "publicNetworkAccess": "Enabled",
            "networkAcls": {"defaultAction": "Deny", "bypass": "AzureServices",
                            "ipRules": [{"value": "203.0.113.0/24", "action": "Allow"}],
                            "virtualNetworkRules": [{"id": SUBNET, "action": "Allow"}]}}},
        VNET.lower(): {"id": VNET, "_type": "microsoft.network/virtualnetworks", "properties": {"subnets": [
            {"name": "app", "properties": {"addressPrefix": "10.0.1.0/24", "serviceEndpoints": [{"service": "Microsoft.Storage"}, {"service": "Microsoft.Sql"}]}},
            {"name": "bare", "properties": {"addressPrefix": "10.0.2.0/24"}}]}},
        PE.lower(): {"id": PE, "_type": "microsoft.network/privateendpoints", "properties": {"privateLinkServiceConnections": [
            {"name": "c", "properties": {"privateLinkServiceId": ACCT, "privateLinkServiceConnectionState": {"status": "Approved"}}}]}},
        SRV.lower(): {"id": SRV, "_type": "microsoft.sql/servers", "properties": {"publicNetworkAccess": "Enabled"}},
        (SRV + "/firewallRules/office").lower(): {"id": SRV + "/firewallRules/office", "_type": "microsoft.sql/servers/firewallrules",
                                                  "properties": {"startIpAddress": "198.51.100.10", "endIpAddress": "198.51.100.20"}},
    }
    st = az.AzureBlobStore()
    sk = {"authorization": "SharedKey stor1:sig"}
    az.dispatch(st, "PUT", "/stor1/c1", {"restype": "container"}, sk, b"", arm_state={})
    get = lambda **h: az.dispatch(st, "GET", "/stor1/c1", {"restype": "container", "comp": "list"}, {**sk, **h}, b"", arm_state=state)

    ok("undeclared caller keeps legacy behaviour (allow-list not applied)", get().status == 200)
    ok("allowed IP passes", get(**{"x-vyomi-source-ip": "203.0.113.9"}).status == 200)
    r = get(**{"x-vyomi-source-ip": "192.0.2.1"})
    ok("IP outside ipRules -> 403 AuthorizationFailure", r.status == 403 and r.headers.get("x-ms-error-code") == "AuthorizationFailure")
    ok("vnet rule + service endpoint passes", get(**{"x-vyomi-source-subnet": SUBNET}).status == 200)
    ok("subnet without a vnet rule is denied", get(**{"x-vyomi-source-subnet": f"{VNET}/subnets/bare"}).status == 403)
    ok("trusted Azure service honours bypass=AzureServices", get(**{"x-vyomi-trusted-service": "1", "x-vyomi-source-ip": "192.0.2.1"}).status == 200)
    ok("approved private endpoint passes the Deny default", get(**{"x-vyomi-private-endpoint": PE}).status == 200)
    ok("nonexistent private endpoint is denied", get(**{"x-vyomi-private-endpoint": PE + "x"}).status == 403)
    state[ACCT.lower()]["properties"]["publicNetworkAccess"] = "Disabled"
    ok("public access Disabled blocks an allowed IP", get(**{"x-vyomi-source-ip": "203.0.113.9"}).status == 403)
    ok("...but the private endpoint still works", get(**{"x-vyomi-private-endpoint": PE}).status == 200)
    state[PE.lower()]["properties"]["privateLinkServiceConnections"][0]["properties"]["privateLinkServiceConnectionState"]["status"] = "Rejected"
    ok("a Rejected private endpoint connection is denied", get(**{"x-vyomi-private-endpoint": PE}).status == 403)

    s = sq.SqlStore()
    sq.dispatch(s, "PUT", "/servers/srv1", {}, {}, b"", arm_state=None)
    sq.dispatch(s, "PUT", "/servers/srv1/databases/d", {}, {}, b"", arm_state=None)
    q = lambda **h: sq.dispatch(s, "POST", "/servers/srv1/databases/d/query", {}, h, json.dumps({"sql": "SELECT 1"}).encode(), arm_state=state)
    ok("SQL undeclared caller -> allowed", q().status == 200)
    ok("SQL IP inside a firewall rule", q(**{"x-vyomi-source-ip": "198.51.100.15"}).status == 200)
    r = q(**{"x-vyomi-source-ip": "198.51.100.99"})
    ok("SQL IP outside every rule -> 403 ClientIpNotAllowed", r.status == 403 and "ClientIpNotAllowed" in r.body.decode(), r.body)
    ok("SQL subnet without a vnet rule is denied", q(**{"x-vyomi-source-subnet": SUBNET}).status == 403)
    state[(SRV + "/virtualNetworkRules/v").lower()] = {"id": SRV + "/virtualNetworkRules/v", "_type": "microsoft.sql/servers/virtualnetworkrules",
                                                       "properties": {"virtualNetworkSubnetId": SUBNET}}
    ok("SQL vnet rule present -> allowed", q(**{"x-vyomi-source-subnet": SUBNET}).status == 200)
    state[SRV.lower()]["properties"]["publicNetworkAccess"] = "Disabled"
    ok("SQL public access Disabled blocks even a ruled IP", q(**{"x-vyomi-source-ip": "198.51.100.15"}).status == 403)
    print("azure netaccess: all checks passed")


if __name__ == "__main__":
    main()
