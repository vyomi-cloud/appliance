"""Provisioning helpers: Function App (azure-mgmt-web: plan + site with app settings) + zip deploy of the function sources, seed Table storage."""
import io, json, os, zipfile
from .runtime import NAMES, RG, LOC, STORAGE, ACCOUNT_KEY, fixture_dir

FUNCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "functions")


def main_py(module):
    """One self-contained __init__.py per function: the shared tool code (tools.py) is inlined ahead of the entry module, so a function never imports a sibling."""
    tools = open(os.path.join(FUNCS, "tools.py")).read()
    entry = "".join(l for l in open(os.path.join(FUNCS, module + ".py")) if not l.startswith("from tools import"))
    return tools + "\n\n" + entry


def zip_of(functions):
    """functions: {trigger_name: module}. Layout of the Python v1 model: <name>/__init__.py + function.json, host.json, requirements.txt."""
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("host.json", json.dumps({"version": "2.0"}))
        z.write(os.path.join(FUNCS, "requirements.txt"), "requirements.txt")
        for name, module in functions.items():
            z.writestr(f"{name}/__init__.py", main_py(module))
            z.writestr(f"{name}/function.json", json.dumps({"scriptFile": "__init__.py", "bindings": [
                {"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["get", "post"]},
                {"type": "http", "direction": "out", "name": "$return"}]}))
    return b.getvalue()


def app_settings(ctx, extra=None):
    """Application settings the functions read: the Table connection string (explicit TableEndpoint, plain-http address the sandbox can reach), the AI Search endpoint + key."""
    s = {"FUNCTIONS_WORKER_RUNTIME": "python",
         "TABLE_CONNECTION_STRING": f"DefaultEndpointsProtocol=http;AccountName={STORAGE};AccountKey={ACCOUNT_KEY};TableEndpoint={ctx.http}/{STORAGE};",
         "SEARCH_ENDPOINT": ctx.state.get("search_endpoint_http", ""), "SEARCH_KEY": ctx.state.get("search_key", ""), "SEARCH_INDEX": NAMES["index"],
         "ASSETS_TABLE": NAMES["assets"], "WORK_ORDERS_TABLE": NAMES["work_orders"], "LEDGER_TABLE": NAMES["ledger"], "INDEXER_NAME": "docs-indexer"}
    s.update(extra or {})
    return s


def create_function_app(ctx, name, functions, extra=None):
    """Create the Function App through ARM (azure-mgmt-web), then deploy the zip the way `az functionapp deployment source config-zip` does (Kudu zipdeploy)."""
    import requests
    from azure.mgmt.web import WebSiteManagementClient
    w = ctx.arm(WebSiteManagementClient)
    w.app_service_plans.begin_create_or_update(RG, name + "-plan", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
    w.web_apps.begin_create_or_update(RG, name, {"location": LOC, "kind": "functionapp,linux", "server_farm_id": ctx.rid("Microsoft.Web", "serverfarms", name + "-plan"),
        }).result()
    from azure.mgmt.web.models import StringDictionary
    w.web_apps.update_application_settings(RG, name, StringDictionary(properties=app_settings(ctx, extra)))   # `az functionapp config appsettings set`
    r = requests.post(f"{ctx.endpoint}/azure-data/functions/{name}/api/zipdeploy", data=zip_of(functions), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"zipdeploy {name} -> HTTP {r.status_code}: {r.text[:300]}")
    return name


def call_function(ctx, app, fn, payload, timeout=120):
    """HTTPS call to a function's HTTP trigger (x-functions-key when ARM gave us one)."""
    import requests
    h = {"x-functions-key": ctx.state["func_key"]} if ctx.state.get("func_key") else {}
    r = requests.post(ctx.func_url(app, fn), json=payload, headers=h, timeout=timeout)
    if r.status_code == 401 and h:
        from .runtime import Blocked, LANE
        raise Blocked(LANE["runtime"], f"the front door rejects the host key ARM list_host_keys returned (HTTP 401 for {app}/{fn}); the ARM key store and the serving key store differ")
    if r.status_code != 200:
        raise RuntimeError(f"function {app}/{fn} HTTP {r.status_code}: {r.text[-400:]}")
    return r.json()


def fixture(name):
    with open(os.path.join(fixture_dir(), name)) as f:
        return json.load(f)


def seed_table(ctx, table, rows, pk, key):
    t = ctx.table(table)
    for r in rows:
        t.upsert_entity(dict(r, PartitionKey=pk, RowKey=str(r[key])))


def agent_bundle():
    """base64 zip of the supervisor app for a Container App (`VYOMI_APP_SOURCE_B64`): app.py (the entrypoint) + the facilities package (agents, runtime, azure IO)."""
    import base64
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(root, "facilities", "azure", "agent_app.py"), "app.py")
        for base in ("facilities",):
            for d, dirs, files in os.walk(os.path.join(root, base)):
                dirs[:] = [x for x in dirs if x not in ("__pycache__", "gcp", "lambdas", "components", "functions")]
                for f in files:
                    if f.endswith(".py"):
                        full = os.path.join(d, f)
                        z.write(full, os.path.relpath(full, root))
    return base64.b64encode(buf.getvalue()).decode()
