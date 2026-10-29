"""Unit tests for core/azure_dns_core.py (run: python3 tests/conformance/test_azure_dns_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_dns_core as dn  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, query=None, rg="rg1"):
    return dn.dispatch(st, method, "sub1", rg, chain, [], body or {}, query or {})


st = {}
r = cp(st, "PUT", ["dnsZones", "contoso.com"], {"location": "global", "tags": {"a": "b"}})
p = r["body"]["properties"]
check("create zone → 201, 4 name servers, SOA+NS seeded", r["status"] == 201 and len(p["nameServers"]) == 4 and p["numberOfRecordSets"] == 2
      and r["body"]["type"] == "Microsoft.Network/dnszones" and p["maxNumberOfRecordSets"] == 10000, r["body"])
check("update zone → 200", cp(st, "PUT", ["dnsZones", "contoso.com"], {"tags": {"c": "d"}})["status"] == 200)
check("zone names need 2+ labels", cp(st, "PUT", ["dnsZones", "contoso"], {})["status"] == 400)
check("get missing zone → 404", cp(st, "GET", ["dnsZones", "none.com"])["status"] == 404)

r = cp(st, "PUT", ["dnsZones", "contoso.com", "A", "www"], {"properties": {"TTL": 300, "ARecords": [{"ipv4Address": "1.2.3.4"}, {"ipv4Address": "1.2.3.4"}]}})
check("A record set → 201, duplicate records collapse, fqdn", r["status"] == 201 and r["body"]["properties"]["ARecords"] == [{"ipv4Address": "1.2.3.4"}]
      and r["body"]["properties"]["fqdn"] == "www.contoso.com.", r["body"])
check("record type must match the supplied records", cp(st, "PUT", ["dnsZones", "contoso.com", "A", "x"], {"properties": {"AAAARecords": [{"ipv6Address": "::1"}]}})["status"] == 400)
check("invalid IPv6 → 400", cp(st, "PUT", ["dnsZones", "contoso.com", "AAAA", "x"], {"properties": {"AAAARecords": [{"ipv6Address": "zz"}]}})["status"] == 400)
check("more than 20 records → 400", cp(st, "PUT", ["dnsZones", "contoso.com", "A", "many"],
      {"properties": {"ARecords": [{"ipv4Address": f"10.0.0.{i}"} for i in range(21)]}})["status"] == 400)
check("CNAME at the apex → 400", cp(st, "PUT", ["dnsZones", "contoso.com", "CNAME", "@"], {"properties": {"CNAMERecord": {"cname": "x.com"}}})["status"] == 400)
check("CNAME next to an A → 409", cp(st, "PUT", ["dnsZones", "contoso.com", "CNAME", "www"], {"properties": {"CNAMERecord": {"cname": "x.com"}}})["status"] == 409)
cp(st, "PUT", ["dnsZones", "contoso.com", "CNAME", "app"], {"properties": {"CNAMERecord": {"cname": "www.contoso.com"}}})
check("A next to a CNAME → 409", cp(st, "PUT", ["dnsZones", "contoso.com", "A", "app"], {"properties": {"ARecords": [{"ipv4Address": "1.1.1.1"}]}})["status"] == 409)
check("PUT without records → 400", cp(st, "PUT", ["dnsZones", "contoso.com", "A", "empty"], {"properties": {"TTL": 5}})["status"] == 400)
check("TXT string over 255 chars → 400", cp(st, "PUT", ["dnsZones", "contoso.com", "TXT", "t"], {"properties": {"TXTRecords": [{"value": ["x" * 256]}]}})["status"] == 400)
r = cp(st, "PATCH", ["dnsZones", "contoso.com", "A", "www"], {"properties": {"TTL": 60}})
check("PATCH changes TTL and keeps the records", r["status"] == 200 and r["body"]["properties"]["TTL"] == 60 and len(r["body"]["properties"]["ARecords"]) == 1)
check("PATCH missing record set → 404", cp(st, "PATCH", ["dnsZones", "contoso.com", "A", "zzz"], {"properties": {"TTL": 60}})["status"] == 404)
check("SOA cannot be deleted", cp(st, "DELETE", ["dnsZones", "contoso.com", "SOA", "@"])["status"] == 400)
check("apex NS cannot be deleted", cp(st, "DELETE", ["dnsZones", "contoso.com", "NS", "@"])["status"] == 400)
check("apex NS records cannot be changed", cp(st, "PUT", ["dnsZones", "contoso.com", "NS", "@"], {"properties": {"NSRecords": [{"nsdname": "ns.evil.com"}]}})["status"] == 400)
check("child delegation NS is allowed", cp(st, "PUT", ["dnsZones", "contoso.com", "NS", "sub"], {"properties": {"NSRecords": [{"nsdname": "ns1.sub.com"}]}})["status"] == 201)

r = cp(st, "GET", ["dnsZones", "contoso.com", "recordsets"], query={"$top": "2"})
check("list is paged with $top + nextLink", len(r["body"]["value"]) == 2 and "$skiptoken=2" in r["body"]["nextLink"], r["body"].get("nextLink"))
r = cp(st, "GET", ["dnsZones", "contoso.com", "all"], query={"$recordsetnamesuffix": "w"})
check("$recordsetnamesuffix filters by name", [x["name"] for x in r["body"]["value"]] == ["www"], r["body"])
check("list by type", len(cp(st, "GET", ["dnsZones", "contoso.com", "CNAME"])["body"]["value"]) == 1)
check("unknown record type → 404", cp(st, "GET", ["dnsZones", "contoso.com", "BOGUS", "x"])["status"] == 404)
check("zone listing by rg and sub", len(cp(st, "GET", ["dnsZones"])["body"]["value"]) == 1 and len(cp(st, "GET", ["dnsZones"], rg=None)["body"]["value"]) == 1)
check("other rg lists nothing", cp(st, "GET", ["dnsZones"], rg="other")["body"]["value"] == [])

q = dn.resolve(st, "app.contoso.com", "A")
check("resolve follows a CNAME", q["status"] == "NOERROR" and [a["type"] for a in q["answer"]] == ["CNAME", "A"] and q["answer"][1]["data"] == "1.2.3.4", q)
cp(st, "PUT", ["dnsZones", "contoso.com", "A", "*.wild"], {"properties": {"ARecords": [{"ipv4Address": "9.9.9.9"}]}})
check("wildcard matches", dn.resolve(st, "a.b.wild.contoso.com", "A")["answer"][0]["data"] == "9.9.9.9")
check("missing name → NXDOMAIN", dn.resolve(st, "no.contoso.com", "A")["status"] == "NXDOMAIN")
check("existing name, other type → NOERROR empty", dn.resolve(st, "www.contoso.com", "MX") == {"status": "NOERROR", "answer": [], "zone": "contoso.com"})
check("outside every zone → REFUSED", dn.resolve(st, "x.example.org", "A")["status"] == "REFUSED")
check("data plane answers JSON", dn.data_dispatch(st, "GET", {"name": "www.contoso.com", "type": "A"})["body"]["Answer"][0]["data"] == "1.2.3.4")

r = cp(st, "POST", ["getDnsResourceReference"], {"properties": {"targetResources": [{"id": "/subscriptions/s/x"}]}}, rg=None)
check("getDnsResourceReference → empty references", r["status"] == 200 and r["body"]["properties"]["dnsResourceReferences"][0]["dnsResources"] == [])
check("delete record set → 200, then 204", cp(st, "DELETE", ["dnsZones", "contoso.com", "A", "www"])["status"] == 200
      and cp(st, "DELETE", ["dnsZones", "contoso.com", "A", "www"])["status"] == 204)
r = cp(st, "DELETE", ["dnsZones", "contoso.com"])
check("delete zone → LRO", r["status"] == 200 and r["lro"] and cp(st, "GET", ["dnsZones", "contoso.com"])["status"] == 404)
check("delete missing zone → 204", cp(st, "DELETE", ["dnsZones", "contoso.com"])["status"] == 204)

# through the Nano ARM wire
arm = AzureArm()
P = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network"
r = arm.handle("PUT", P + "/dnsZones/nano.example.com", {}, {"location": "global"})
check("Nano ARM: zone create", r["status"] == 201 and r["body"]["name"] == "nano.example.com", r)
r = arm.handle("PUT", P + "/dnsZones/nano.example.com/A/w", {}, {"properties": {"ARecords": [{"ipv4Address": "1.1.1.1"}]}})
check("Nano ARM: record set create", r["status"] == 201, r)
check("Nano ARM: vnet (generic type) still works", arm.handle("PUT", P + "/virtualNetworks/v1", {}, {"location": "eastus"})["status"] in (200, 201))
r = arm.handle("DELETE", P + "/dnsZones/nano.example.com", {}, None)
check("Nano ARM: zone delete (LRO headers)", r["status"] == 200 and "Azure-AsyncOperation" in r["headers"], r)

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
