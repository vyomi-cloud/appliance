from azure.mgmt.search import SearchManagementClient
from azlab import arm, ensure_rg, RG, LOC
from azdata import SEARCH_SERVICE, search_endpoint

ensure_rg()
arm(SearchManagementClient).services.begin_create_or_update(RG, SEARCH_SERVICE, {"location": LOC, "sku": {"name": "basic"}}).result()
print("search service", SEARCH_SERVICE, "ready; data-plane address:", search_endpoint())
