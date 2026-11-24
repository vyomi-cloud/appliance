import requests
from urllib.parse import urlparse
from azure.data.tables import TableServiceClient
from azlab import arm, ENDPOINT, HTTP_ENDPOINT, STORAGE, ACCOUNT_KEY, RG, HOST

SEARCH_SERVICE = "facilities-search"
INDEX = "facilities-kb"
FUNCTION_APP = "facilities-tools"


def storage_cs(service, endpoint=ENDPOINT, proto="https"):
    return f"DefaultEndpointsProtocol={proto};AccountName={STORAGE};AccountKey={ACCOUNT_KEY};{service}Endpoint={endpoint}/{STORAGE};"


def tables():
    return TableServiceClient.from_connection_string(storage_cs("Table"))


def table(name):
    return tables().create_table_if_not_exists(name)


def search_endpoint():
    """The data-plane address of the AI Search service. A real service advertises https://<name>.search.windows.net; the simulator serves the same wire under its own path."""
    from azure.mgmt.search import SearchManagementClient
    advertised = arm(SearchManagementClient).services.get(RG, SEARCH_SERVICE).endpoint or ""
    if advertised and (urlparse(advertised).hostname or "") in (HOST, "localhost", "127.0.0.1"):
        return advertised.rstrip("/")
    return f"{ENDPOINT}/azure-data/search/{SEARCH_SERVICE}"


def search_key():
    from azure.mgmt.search import SearchManagementClient
    return arm(SearchManagementClient).admin_keys.get(RG, SEARCH_SERVICE).primary_key


def function_key(app=FUNCTION_APP):
    from azure.mgmt.web import WebSiteManagementClient
    keys = arm(WebSiteManagementClient).web_apps.list_host_keys(RG, app)
    return (keys.function_keys or {}).get("default") or keys.master_key


def call_function(app, name, payload, timeout=120):
    r = requests.post(f"{ENDPOINT}/azure-data/functions/{app}/api/{name}", json=payload, headers={"x-functions-key": function_key(app)}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"function {app}/{name} HTTP {r.status_code}: {r.text[-300:]}")
    return r.json()
