"""Azure export -> Terraform -> import -> deploy round trip against a RUNNING appliance (docker) over the ARM wire.

    docker run -d --rm -p 9461:9000 vyomi/appliance:<tag>
    python3 tests/e2e/azure_tf_roundtrip_http.py http://127.0.0.1:9461
"""
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tests.azure_tf_seed import SUB, seed_items  # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9461").rstrip("/") + "/_wire"
fails = 0


def call(method, path, body=None, v="2021-04-01"):
    req = urllib.request.Request(f"{BASE}/subscriptions/{SUB}{path}{'&' if '?' in path else '?'}api-version={v}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def ok(c, m):
    global fails
    print(("PASS " if c else "FAIL ") + m)
    fails += 0 if c else 1


# unique global names + resource groups per run
sfx = str(os.getpid() % 10000)
A, B = f"tfha{sfx}", f"tfhb{sfx}"
items = seed_items(A)
rename = {}
for rel, _, _ in items:
    m = re.match(r"Microsoft\.(Storage/storageAccounts|KeyVault/vaults|Sql/servers|ServiceBus/namespaces|DocumentDB/databaseAccounts|Web/sites|ContainerRegistry/registries|OperationalInsights/workspaces)/([^/]+)$", rel)
    if m:
        rename[m.group(2)] = m.group(2) + sfx
# Cosmos DB and AKS are tier-gated on a Free appliance (403 tier_service_locked / FeatureNotAvailableForTier); run with a Pro/Max licence to include them
items = [(rel, v, b) for rel, v, b in items if not rel.startswith(("Microsoft.DocumentDB", "Microsoft.ContainerService")) or os.environ.get("TIER_UNLOCKED")]


def sub_names(s):
    for k, v in rename.items():
        s = s.replace(k, v)
    return s


call("PUT", f"/resourcegroups/{A}", {"location": "eastus"})
created = 0
for rel, v, body in items:
    st, b = call("PUT", f"/resourceGroups/{A}/providers/{sub_names(rel)}", json.loads(sub_names(json.dumps(body))), v)
    created += st < 300
    if st >= 300:
        print("  create failed", rel, st, str(b)[:150])
ok(created == len(items), f"{created}/{len(items)} resources created through the appliance ARM wire")
st, exp = call("POST", f"/resourceGroups/{A}/exportTemplate", {"resources": ["*"]})
ok(st == 200 and exp["terraform"].count('resource "azurerm_') >= 20 and "azapi_resource" not in exp["terraform"], "exportTemplate: azurerm resources, no azapi fallback")
ok("resourceId(" in json.dumps(exp["template"]) and '"dependsOn"' in json.dumps(exp["template"]), "ARM template has resourceId() + dependsOn")
tf = exp["terraform"]
st, imp = call("POST", f"/resourceGroups/{A}/importTerraform", {"terraform": tf})
ok(st == 200 and not imp["unsupported"] and len(imp["mapped"]) >= 20, f"importTerraform converted {len(imp.get('mapped', []))} blocks, unsupported={imp.get('unsupported')}")
# fresh group with renamed (globally unique) names
call("PUT", f"/resourcegroups/{B}", {"location": "eastus"})
tf_b = tf
for k, v in rename.items():
    tf_b = re.sub(rf'(\bname\s+=\s+)"{v}"', rf'\1"{v}b"', tf_b)
st, imp_b = call("POST", f"/resourceGroups/{B}/importTerraform", {"terraform": tf_b})
body = {"properties": {"mode": "Incremental", "template": imp_b["template"], "parameters": {"sqlvyomi01" + sfx + "_administrator_login_password": {"value": "Pw-12345!x"}}}}
st, wi = call("POST", f"/resourceGroups/{B}/providers/Microsoft.Resources/deployments/imp/whatIf", body)
if "properties" not in wi:
    print("whatIf error:", st, str(wi)[:600])
chg = [c["changeType"] for c in wi.get("properties", {}).get("changes", [])]
ok(st == 200 and chg and set(chg) == {"Create"}, f"whatIf: {len(chg)} Create, nothing else")
st, dep = call("PUT", f"/resourceGroups/{B}/providers/Microsoft.Resources/deployments/imp", body)
ok(dep["properties"]["provisioningState"] == "Succeeded", f"deployment {dep['properties']['provisioningState']} {dep['properties'].get('error', '')}")
st, wi2 = call("POST", f"/resourceGroups/{B}/providers/Microsoft.Resources/deployments/imp/whatIf", body)
ok(set(c["changeType"] for c in wi2["properties"]["changes"]) == {"NoChange"}, "whatIf after deploy: NoChange for every resource")
st, exp2 = call("POST", f"/resourceGroups/{B}/exportTemplate", {"resources": ["*"]})
back = exp2["terraform"]
for k, v in rename.items():
    back = back.replace(v + "b", v)
norm = lambda t, g: re.sub(r"_OsDisk_1_[0-9a-f]+", "_OsDisk", t.replace(g, "X"))
ok(norm(back, B) == norm(tf, A), "second export round-trips equal modulo names")
if norm(back, B) != norm(tf, A):
    import difflib
    print("\n".join(list(difflib.unified_diff(norm(tf, A).splitlines(), norm(back, B).splitlines(), lineterm="", n=0))[:30]))
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
