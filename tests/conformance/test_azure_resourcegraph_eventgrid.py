"""Event Grid Topics list "Open query": a real Azure Resource Graph query (Microsoft.ResourceGraph/resources) over the ARM
resource store returns the topics created through ARM — filter, project, order, limit, count; an unsupported operator is a
400, not a silent success. Run: PYTHONPATH=. python tests/conformance/test_azure_resourcegraph_eventgrid.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

AzureArm.STRICT_SUBSCRIPTION = False
a = AzureArm()
RG = f"/subscriptions/{SUB}/resourceGroups/rgq"
RGQ = "/providers/Microsoft.ResourceGraph/resources"


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
for n, loc in (("zeta-topic", "eastus"), ("alpha-topic", "westus2")):
    r = a.handle("PUT", f"{RG}/providers/Microsoft.EventGrid/topics/{n}", {"api-version": "2022-06-15"}, {"location": loc})
    ok(f"create {n}", r["status"] in (200, 201, 202), r)
a.handle("PUT", f"{RG}/providers/Microsoft.Network/virtualNetworks/notatopic", {"api-version": "2023-04-01"},
         {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}})

q = lambda kql: a.handle("POST", RGQ, {"api-version": "2021-03-01"}, {"subscriptions": [SUB], "query": kql})
r = q("Resources | where type =~ 'microsoft.eventgrid/topics' | project name, location, resourceGroup | order by name asc")
ok("200", r["status"] == 200, r)
rows = r["body"]["data"]["rows"]
ok("only the topics, ordered by name", [x[0] for x in rows] == ["alpha-topic", "zeta-topic"], rows)
ok("projected columns", [c["name"] for c in r["body"]["data"]["columns"]] == ["name", "location", "resourcegroup"], r["body"]["data"]["columns"])
ok("location filter", q("Resources | where type =~ 'microsoft.eventgrid/topics' and location == 'westus2' | project name")["body"]["data"]["rows"] == [["alpha-topic"]])
ok("limit", len(q("Resources | where type =~ 'microsoft.eventgrid/topics' | limit 1")["body"]["data"]["rows"]) == 1)
ok("count", q("Resources | where type =~ 'microsoft.eventgrid/topics' | count")["body"]["data"] == [{"Count": 2}])
ok("resource group in ResourceContainers", q("ResourceContainers | where name =~ 'rgq' | project name")["body"]["data"]["rows"] == [["rgq"]])
ok("unsupported operator -> 400", q("Resources | join kind=inner (Resources) on id")["status"] == 400)
ok("unknown table -> 400", q("Nope | count")["status"] == 400)
print("PASS")
