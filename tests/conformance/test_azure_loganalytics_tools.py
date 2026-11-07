"""Log Analytics workspace tools: linkedStorageAccounts (real ARM, validated config) and Computer groups (classic) = saved searches whose
query returns Computer; members evaluated live; usable in KQL as `Computer in (Group)`.
Run: PYTHONPATH=. python tests/conformance/test_azure_loganalytics_tools.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

AzureArm.STRICT_SUBSCRIPTION = False
a = AzureArm()
RG = f"/subscriptions/{SUB}/resourceGroups/lt-rg"
req = lambda m, p, b=None, v="2022-10-01", q=None: a.handle(m, p, {"api-version": v, **(q or {})}, b)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


req("PUT", RG, {"location": "eastus"}, "2021-04-01")
WS = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/lt-law"
req("PUT", WS, {"location": "eastus"})
ST1 = f"{RG}/providers/Microsoft.Storage/storageAccounts/ltstore1"
ST2 = f"{RG}/providers/Microsoft.Storage/storageAccounts/ltstore2"
STW = f"{RG}/providers/Microsoft.Storage/storageAccounts/ltstorew"
for sid, loc in ((ST1, "eastus"), (ST2, "eastus"), (STW, "westus")):
    req("PUT", sid, {"location": loc, "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, "2023-01-01")

# linked storage accounts
LS = WS + "/linkedStorageAccounts"
ok("empty list", req("GET", LS)["body"]["value"] == [])
ok("bad data source type -> 400", req("PUT", LS + "/Nope", {"properties": {"storageAccountIds": [ST1]}})["status"] == 400)
ok("empty accounts -> 400", req("PUT", LS + "/CustomLogs", {"properties": {"storageAccountIds": []}})["status"] == 400)
ok("unknown account -> 400", req("PUT", LS + "/CustomLogs", {"properties": {"storageAccountIds": [ST1 + "zz"]}})["status"] == 400)
ok("other-region account -> 400", req("PUT", LS + "/CustomLogs", {"properties": {"storageAccountIds": [STW]}})["status"] == 400)
ok("dataSourceType mismatch -> 400", req("PUT", LS + "/CustomLogs", {"properties": {"dataSourceType": "Query", "storageAccountIds": [ST1]}})["status"] == 400)
ok("duplicates -> 400", req("PUT", LS + "/CustomLogs", {"properties": {"storageAccountIds": [ST1, ST1.upper()]}})["status"] == 400)
r = req("PUT", LS + "/CustomLogs", {"properties": {"storageAccountIds": [ST1, ST2]}})
ok("link created", r["status"] == 200 and r["body"]["name"] == "CustomLogs" and r["body"]["type"].endswith("/linkedStorageAccounts")
   and r["body"]["properties"]["storageAccountIds"] == [ST1, ST2], r)
ok("get (case-insensitive name)", req("GET", LS + "/customlogs")["body"]["properties"]["dataSourceType"] == "CustomLogs")
ok("list", [x["name"] for x in req("GET", LS)["body"]["value"]] == ["CustomLogs"])
ok("update replaces accounts", req("PUT", LS + "/CustomLogs", {"properties": {"storageAccountIds": [ST2]}})["body"]["properties"]["storageAccountIds"] == [ST2])
ok("delete", req("DELETE", LS + "/CustomLogs")["status"] == 200 and req("GET", LS + "/CustomLogs")["status"] == 404)

# computer groups
rows = [{"Computer": "web1", "OSType": "Linux"}, {"Computer": "web2", "OSType": "Linux"}, {"Computer": "win1", "OSType": "Windows"}, {"Computer": "web1", "OSType": "Linux"}]
for row in rows:
    req("POST", WS + "/api/logs", row, q={"logType": "Fleet"})
CG = WS + "/computerGroups"
ok("empty groups", req("GET", CG)["body"]["value"] == [])
ok("bad name -> 400", req("PUT", CG + "/bad-name", {"properties": {"query": "Fleet_CL | project Computer_s"}})["status"] == 400)
ok("query without Computer column -> 400", req("PUT", CG + "/g0", {"properties": {"query": "Fleet_CL | project OSType_s"}})["status"] == 400)
ok("invalid KQL -> 400", req("PUT", CG + "/g0", {"properties": {"query": "Fleet_CL | frobnicate"}})["status"] == 400)
r = req("PUT", CG + "/LinuxBoxes", {"properties": {"displayName": "Linux boxes", "query": "Fleet_CL | where OSType_s == 'Linux' | project Computer_s"}})
ok("group created with live members", r["status"] == 200 and r["body"]["properties"]["members"] == ["web1", "web2"] and r["body"]["properties"]["memberCount"] == 2, r)
ok("shows up as a real saved search (category Computer Groups, functionAlias)", (lambda s: s["properties"]["category"] == "Computer Groups" and s["properties"]["functionAlias"] == "LinuxBoxes")(
    req("GET", WS + "/savedSearches/LinuxBoxes")["body"]))
ok("members endpoint", [m["computer"] for m in req("GET", CG + "/LinuxBoxes/members")["body"]["value"]] == ["web1", "web2"])
q = lambda text: req("POST", WS + "/api/query", {"query": text})["body"]["tables"][0]["rows"]
ok("group used in KQL: Computer in (Group)", sorted(r[0] for r in q("Fleet_CL | where Computer_s in (LinuxBoxes) | distinct Computer_s")) == ["web1", "web2"])
req("POST", WS + "/api/logs", {"Computer": "web3", "OSType": "Linux"}, q={"logType": "Fleet"})
ok("membership follows new data", sorted(m["computer"] for m in req("GET", CG + "/LinuxBoxes/members")["body"]["value"]) == ["web1", "web2", "web3"])
ok("unrelated alias left alone", req("POST", WS + "/api/query", {"query": "Fleet_CL | where Computer_s in (Nope)"})["status"] == 400)
ok("group list", [g["name"] for g in req("GET", CG)["body"]["value"]] == ["LinuxBoxes"])
req("PUT", WS + "/savedSearches/plain", {"properties": {"category": "General", "displayName": "p", "query": "Heartbeat"}})
ok("plain saved searches are not groups", [g["name"] for g in req("GET", CG)["body"]["value"]] == ["LinuxBoxes"])
ok("name clash with a plain saved search -> 409", req("PUT", CG + "/plain", {"properties": {"query": "Fleet_CL | project Computer_s"}})["status"] == 409)
ok("delete group", req("DELETE", CG + "/LinuxBoxes")["status"] == 200 and req("GET", WS + "/savedSearches/LinuxBoxes")["status"] == 404)
print("PASS")
