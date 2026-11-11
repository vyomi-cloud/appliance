"""(1) An Event Grid system topic created with defaults shows a real Topic type + source (the Topics grid
column was '-'); an explicit topicType is kept. (2) Every taggable ARM service in the catalog has a Tags
tab (Event Grid namespaces/system topics/domains/partner types, Redis Cache, Data Explorer had none).
Run: PYTHONPATH=. python3 tests/conformance/test_azure_systemtopic_and_generic_tags_core.py"""
import sys
from core import azure_subblades as sb
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

AzureArm.STRICT_SUBSCRIPTION = False
ok = True
def check(name, cond, detail=""):
    global ok
    print(("  ok  " if cond else "  FAIL  ") + name + ("" if cond else f" :: {detail}")); ok &= bool(cond)

a = AzureArm()
G = f"/subscriptions/{SUB}/resourceGroups/rg"
a.handle("PUT", G, {"api-version": "2021-04-01"}, {"location": "eastus"})
P = G + "/providers/Microsoft.EventGrid/systemTopics/"
r = a.handle("PUT", P + "st1", {"api-version": "2022-06-15"}, {"location": "global", "properties": {}})["body"]["properties"]
check("default system topic has a topic type", r.get("topicType") == "Microsoft.Resources.ResourceGroups", r)
check("default system topic source is the resource group", (r.get("source") or "").lower() == G.lower(), r)
r = a.handle("PUT", P + "st2", {"api-version": "2022-06-15"}, {"location": "global", "properties": {"topicType": "Microsoft.Storage.StorageAccounts", "source": G + "/providers/Microsoft.Storage/storageAccounts/x"}})["body"]["properties"]
check("explicit topicType is kept", r.get("topicType") == "Microsoft.Storage.StorageAccounts", r)

def tabs(bl): return [i["label"] for g in bl for i in (g.get("items") or [g])]
for k in ("eventgrid_namespace", "eventgrid_systemtopic", "eventgrid_domain", "eventgrid_partnerconfiguration",
          "eventgrid_partnertopic", "eventgrid_partnerregistration", "eventgrid_partnernamespace", "rediscache", "dataexplorer"):
    check(f"{k} has a Tags tab", "Tags" in tabs(sb.SUB_BLADES.get(k, [])), k)
print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
