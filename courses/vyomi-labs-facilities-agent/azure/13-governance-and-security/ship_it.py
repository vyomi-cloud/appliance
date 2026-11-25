from azure.mgmt.resource.resources import ResourceManagementClient
from azlab import arm, RG

rc = arm(ResourceManagementClient)
res = rc.resource_groups.begin_export_template(RG, {"resources": ["*"], "options": "IncludeParameterDefaultValue"}).result()
t = res.template
assert "$schema" in t and t.get("contentVersion"), "an ARM template needs a schema and contentVersion"
types = sorted({r["type"] for r in t["resources"]})
print("resources exported:", len(t["resources"]), "| types:", len(types))
for must in ("Microsoft.KeyVault/vaults", "Microsoft.Web/sites"):
    assert must in types, must + " must be in the template"
errors = getattr(res, "error", None)
print("export warnings:", [getattr(d, "code", None) for d in (getattr(errors, "details", None) or [])] or "none returned")
params = t.get("parameters", {})
assert params, "names should be parameterised so the template can be deployed elsewhere"
print("parameters:", sorted(params)[:4], "...")
print("ship it verified: template exported with", len(t["resources"]), "resources; review it, then az deployment group create")
