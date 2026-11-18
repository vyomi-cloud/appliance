"""Component 7 Tools: Function App function create + invoke (HTTP trigger) and Cosmos DB reads/writes from the tool code."""
import io, json, zipfile, requests
from _common import *

P = Probe(7, "tools", "Tools: Function App function + Cosmos DB")
B = endpoint(); ensure_rg(B)
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
S = {}
COSMOS = B + "/azure-data/cosmos/cosmos1"


def cosmos_setup():
    from azure.mgmt.cosmosdb import CosmosDBManagementClient
    arm(CosmosDBManagementClient, B).database_accounts.begin_create_or_update(RG, "cosmos1", {"location": LOC, "kind": "GlobalDocumentDB", "locations": [{"location_name": LOC, "failover_priority": 0}],
        "database_account_offer_type": "Standard"}).result()
    from azure.cosmos import CosmosClient, PartitionKey
    c = CosmosClient(COSMOS, credential=KEY, connection_verify=False)
    S["ct"] = ct = c.create_database_if_not_exists("facilities").create_container_if_not_exists("assets", partition_key=PartitionKey(path="/site"))
    for i in range(3):
        ct.upsert_item({"id": f"a{i}", "site": "hq", "kind": "hvac", "floor": i})
    return "db + container (pk /site) + 3 items"


def cosmos_rw():
    ct = S["ct"]
    assert ct.read_item("a1", partition_key="hq")["floor"] == 1
    rows = list(ct.query_items("SELECT c.id FROM c WHERE c.site = 'hq' AND c.floor >= 1 ORDER BY c.floor", partition_key="hq"))
    assert [r["id"] for r in rows] == ["a1", "a2"], rows
    ct.delete_item("a0", partition_key="hq")
    assert len(list(ct.read_all_items())) == 2
    return "read_item, parameter-free SQL with ORDER BY, delete_item, read_all_items"


def cosmos_param_query():
    rows = list(S["ct"].query_items("SELECT * FROM c WHERE c.kind = @k", parameters=[{"name": "@k", "value": "hvac"}], enable_cross_partition_query=True))
    assert len(rows) == 2, rows


def cosmos_aggregate():
    rows = list(S["ct"].query_items("SELECT VALUE COUNT(1) FROM c", enable_cross_partition_query=True))
    assert rows == [2], rows


def func_create():
    from azure.mgmt.web import WebSiteManagementClient
    w = arm(WebSiteManagementClient, B)
    w.app_service_plans.begin_create_or_update(RG, "plan1", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
    app = w.web_apps.begin_create_or_update(RG, "tools-fn", {"location": LOC, "kind": "functionapp", "server_farm_id": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Web/serverfarms/plan1",
        "site_config": {"app_settings": [{"name": "FUNCTIONS_WORKER_RUNTIME", "value": "python"}]}}).result()
    # no Azure SDK import next to azure.functions: the shim shadows the azure namespace (see probe_05 fn_has_sdk)
    code = """import json
import azure.functions as func
def main(req: func.HttpRequest) -> func.HttpResponse:
    n = req.params.get("asset") or (req.get_json() or {}).get("asset")
    return func.HttpResponse(json.dumps({"asset": n, "floor": int(n[1:])}), mimetype="application/json")
"""
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("lookup_asset/__init__.py", code); zf.writestr("host.json", "{}")
    r = requests.post(B + "/azure-data/functions/tools-fn/api/zipdeploy", data=z.getvalue(), timeout=30)
    assert r.status_code == 200, r.text[:100]
    S["fn"] = w
    return "function app + zipdeploy"


def func_listed():
    names = [f.name for f in S["fn"].web_apps.list_functions(RG, "tools-fn")]
    assert "lookup_asset" in names, f"ARM list_functions after zipdeploy shows {names}"
    return names


def func_invoke_post():
    r = requests.post(B + "/azure-data/functions/tools-fn/api/lookup_asset", json={"asset": "a1"}, timeout=30)
    assert r.status_code == 200 and r.json()["floor"] == 1, (r.status_code, r.text[:300])
    return r.json()


def func_invoke_query():
    r = requests.get(B + "/azure-data/functions/tools-fn/api/lookup_asset?asset=a2", timeout=30)
    assert r.status_code == 200 and r.json()["floor"] == 2, (r.status_code, r.text[:300])


def func_native_host():
    """Real hostname form: https://<app>.azurewebsites.net/api/<fn> must reach the function (path form is a simulator extension)."""
    r = requests.get(B + "/api/lookup_asset?asset=a2", headers={"Host": "tools-fn.azurewebsites.net"}, timeout=30)
    assert r.status_code == 200, (r.status_code, r.text[:100])


def func_keys():
    from azure.mgmt.web import WebSiteManagementClient
    k = S["fn"].web_apps.list_function_keys(RG, "tools-fn", "lookup_asset")
    assert k is not None


P.step("Cosmos: account (ARM) + database + container + upsert items (azure-cosmos)", cosmos_setup)
P.step("Cosmos: read_item, SQL query with ORDER BY, delete, read_all", cosmos_rw)
P.step("Cosmos: parameterised SQL cross-partition query", cosmos_param_query)
P.step("Cosmos: SELECT VALUE COUNT(1) aggregate", cosmos_aggregate)
if P.step("Function App + HTTP function (azure.functions v1 model, calls Cosmos) deployed by zipdeploy", func_create):
    P.step("ARM list_functions shows the deployed function", func_listed)
    P.step("invoke function: POST JSON body", func_invoke_post)
    P.step("invoke function: GET with query string", func_invoke_query)
    P.step("invoke on the real hostname form <app>.azurewebsites.net/api/<fn>", func_native_host)
    P.step("ARM list_function_keys", func_keys)
P.finish()
