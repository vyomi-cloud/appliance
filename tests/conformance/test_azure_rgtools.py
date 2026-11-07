"""Resource group tools (core/azure_rgtools_core.py): forceDeletionTypes on group delete (validated; graceful deallocate vs direct force delete visible
in the Activity log) and the group's Insights computed from real records. Run: PYTHONPATH=. python tests/conformance/test_azure_rgtools.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

AzureArm.STRICT_SUBSCRIPTION = False
a = AzureArm()
req = lambda m, p, b=None, v="2023-07-01", q=None: a.handle(m, p, {"api-version": v, **(q or {})}, b)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def ops(rid):
    ev = [r for k, r in a.state.items() if "/__event__/" in k and str(r.get("resourceId", "")).lower() == rid.lower()]
    return [e["operationName"]["value"] + "|" + e["operationName"]["localizedValue"] for e in sorted(ev, key=lambda e: e["_seq"])]


def build(rg):
    G = f"/subscriptions/{SUB}/resourceGroups/{rg}"
    req("PUT", G, {"location": "eastus", "tags": {"env": "dev"}}, "2021-04-01")
    P = G + "/providers"
    req("PUT", P + "/Microsoft.Network/virtualNetworks/vn", {"location": "eastus", "tags": {"env": "dev", "team": "a"}, "properties": {"addressSpace": {"addressPrefixes": ["10.5.0.0/16"]}}}, "2023-11-01")
    req("PUT", P + "/Microsoft.Network/networkSecurityGroups/nsg", {"location": "westus", "properties": {}}, "2023-11-01")
    vms = []
    for n in ("vm1", "vm2"):
        vms.append(P + f"/Microsoft.Compute/virtualMachines/{n}")
        req("PUT", vms[-1], {"location": "eastus", "tags": {"env": "dev"}, "properties": {}}, "2023-09-01")
    return G, vms


# ── Insights ──
G, vms = build("ins-rg")
req("POST", vms[1] + "/deallocate", {}, "2023-09-01")
r = req("GET", G + "/providers/Microsoft.Vyomi/insights", None, "2024-01-01")
ok("insights 200", r["status"] == 200, r)
b = r["body"]
ok("inventory counts real resources", b["inventory"]["resourceCount"] == 4 and {x["type"]: x["count"] for x in b["inventory"]["byType"]}["Microsoft.Compute/virtualMachines"] == 2, b["inventory"])
ok("locations", {x["location"]: x["count"] for x in b["inventory"]["byLocation"]} == {"eastus": 3, "westus": 1}, b["inventory"])
ok("tag coverage: nsg is untagged", b["tags"]["untagged"] == 1 and b["tags"]["tagged"] == 3 and b["tags"]["coveragePercent"] == 75 and b["tags"]["untaggedResources"][0].endswith("/networkSecurityGroups/nsg"), b["tags"])
ok("tag keys", {k["key"]: k["count"] for k in b["tags"]["keys"]} == {"env": 3, "team": 1}, b["tags"])
ok("compute power states", b["compute"]["virtualMachines"] == 2 and sum(b["compute"]["powerStates"].values()) == 2, b["compute"])
ok("activity log summary counts the real writes", b["activity"]["last24h"] >= 4 and b["activity"]["failed"] == 0, b["activity"])
ok("unknown group -> 404", req("GET", f"/subscriptions/{SUB}/resourceGroups/nope-rg/providers/Microsoft.Vyomi/insights", None, "2024-01-01")["status"] == 404)

# ── force delete validation ──
ok("unsupported force type -> 400", req("DELETE", G, q={"forceDeletionTypes": "Microsoft.Storage/storageAccounts"})["status"] == 400)
ok("group still there after a rejected delete", req("GET", G, None, "2021-04-01")["status"] == 200)

# ── graceful (default) delete ──
G1, vms1 = build("del-graceful")
req("POST", vms1[1] + "/deallocate", {}, "2023-09-01")
ok("graceful delete 200", req("DELETE", G1, None, "2021-04-01")["status"] == 200)
o1 = ops(vms1[0])
ok("running VM was deallocated first, then deleted", [x.split("|")[0] for x in o1][-2:] == ["Microsoft.Compute/virtualMachines/deallocate/action", "Microsoft.Compute/virtualMachines/delete"], o1)
o2 = ops(vms1[1])
ok("already-deallocated VM goes straight to delete", [x.split("|")[0] for x in o2][-1] == "Microsoft.Compute/virtualMachines/delete" and not any("deallocate/action" in x for x in o2[-2:]), o2)
ok("group and resources gone", req("GET", G1, None, "2021-04-01")["status"] == 404 and vms1[0].lower() not in a.state)

# ── force delete ──
G2, vms2 = build("del-force")
ok("force delete 200", req("DELETE", G2, None, "2021-04-01", {"forceDeletionTypes": "Microsoft.Compute/virtualMachines,Microsoft.Compute/virtualMachineScaleSets"})["status"] == 200)
o3 = ops(vms2[0])
ok("forced VM: direct 'Force delete' row, no deallocate step", o3[-1] == "Microsoft.Compute/virtualMachines/delete|Force delete Virtual Machine" and not any("deallocate/action" in x for x in o3), o3)
ok("group gone", req("GET", G2, None, "2021-04-01")["status"] == 404)
print("PASS")
