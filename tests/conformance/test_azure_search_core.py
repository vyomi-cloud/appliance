"""Azure AI Search: service ARM rules, keys, index schema, doc actions, ranked search + $filter/facets, blob indexer."""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
    from core.azure_blob_core import AzureBlobStore
    from core import azure_blob_core as blob
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore
    from azure_blob_core import AzureBlobStore  # type: ignore
    import azure_blob_core as blob  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    a.blob_store = store = AzureBlobStore()
    av = {"api-version": "2023-11-01"}
    h = lambda m, p, b=None, q=None: a.handle(m, p, dict(av, **(q or {})), b)
    h("PUT", f"/subscriptions/{S}/resourceGroups/r", {"location": "eastus"})
    base = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Search/searchServices"
    _check("bad name", h("PUT", f"{base}/Bad_Name", {"location": "eastus", "sku": {"name": "basic"}})["status"] == 400)
    _check("bad sku", h("PUT", f"{base}/svc1", {"location": "eastus", "sku": {"name": "huge"}})["status"] == 400)
    _check("basic partitions limited", h("PUT", f"{base}/svc1", {"location": "eastus", "sku": {"name": "basic"}, "properties": {"partitionCount": 2}})["status"] == 400)
    r = h("PUT", f"{base}/svc1", {"location": "eastus", "sku": {"name": "standard"}, "properties": {"replicaCount": 3, "partitionCount": 2}})
    _check("create standard", r["status"] == 201 and r["body"]["properties"]["endpoint"] == "https://svc1.search.windows.net/")
    _check("name globally unique", h("PUT", f"/subscriptions/{S}/resourceGroups/r2/providers/Microsoft.Search/searchServices/svc1", {"location": "eastus", "sku": {"name": "basic"}})["status"] == 409)
    _check("one free per sub", h("PUT", f"{base}/free1", {"location": "eastus", "sku": {"name": "free"}})["status"] == 201 and h("PUT", f"{base}/free2", {"location": "eastus", "sku": {"name": "free"}})["status"] == 403)
    _check("sku immutable", h("PUT", f"{base}/svc1", {"location": "eastus", "sku": {"name": "basic"}})["status"] == 400)
    _check("check name taken", h("POST", f"/subscriptions/{S}/providers/Microsoft.Search/checkNameAvailability", {"name": "svc1", "type": "searchServices"})["body"]["nameAvailable"] is False)
    k = h("POST", f"{base}/svc1/listAdminKeys")["body"]
    k2 = h("POST", f"{base}/svc1/regenerateAdminKey/primary")["body"]
    _check("admin key rotated", k2["primaryKey"] != k["primaryKey"] and k2["secondaryKey"] == k["secondaryKey"])
    qk = h("POST", f"{base}/svc1/createQueryKey/web")["body"]
    _check("query key listed + deleted", h("POST", f"{base}/svc1/listQueryKeys")["body"]["value"][0]["name"] == "web" and h("DELETE", f"{base}/svc1/deleteQueryKey/{qk['key']}")["status"] == 200)
    ix = f"{base}/svc1/indexes"
    fields = [{"name": "id", "type": "Edm.String", "key": True}, {"name": "title", "type": "Edm.String", "searchable": True},
              {"name": "cat", "type": "Edm.String", "filterable": True, "facetable": True}, {"name": "price", "type": "Edm.Double", "filterable": True, "sortable": True}]
    _check("two keys rejected", h("PUT", f"{ix}/bad", {"fields": fields + [{"name": "k2", "type": "Edm.String", "key": True}]})["status"] == 400)
    _check("non-string key rejected", h("PUT", f"{ix}/bad", {"fields": [{"name": "id", "type": "Edm.Int32", "key": True}]})["status"] == 400)
    _check("create index", h("PUT", f"{ix}/hotels", {"fields": fields})["status"] == 201)
    docs = [{"@search.action": "upload", "id": "1", "title": "Blue ocean hotel", "cat": "resort", "price": 120.0},
            {"@search.action": "upload", "id": "2", "title": "Ocean view budget inn", "cat": "budget", "price": 60.0},
            {"@search.action": "upload", "id": "3", "title": "City center hotel", "cat": "budget", "price": 80.5}]
    r = h("POST", f"{ix}/hotels/docs/index", {"value": docs})
    _check("docs uploaded", r["status"] == 200 and all(x["statusCode"] == 201 for x in r["body"]["value"]))
    r = h("POST", f"{ix}/hotels/docs/index", {"value": [{"@search.action": "upload", "id": "9", "price": "x"}, {"@search.action": "merge", "id": "77", "title": "t"}]})
    _check("type error 207 + merge-missing 404", r["status"] == 207 and r["body"]["value"][0]["statusCode"] == 400 and r["body"]["value"][1]["statusCode"] == 404)
    s = lambda body: h("POST", f"{ix}/hotels/docs/search", body)["body"]
    _check("ranked search", [d["id"] for d in s({"search": "ocean"})["value"]][:2] in (["1", "2"], ["2", "1"]) and len(s({"search": "ocean"})["value"]) == 2)
    _check("phrase", [d["id"] for d in s({"search": "\"city center\""})["value"]] == ["3"])
    _check("negation", [d["id"] for d in s({"search": "hotel -city"})["value"]] == ["1"])
    _check("filter + count", s({"search": "*", "$filter": "cat eq 'budget' and price lt 70", "$count": "true"})["@odata.count"] == 1)
    _check("filter parens/or", len(s({"search": "*", "$filter": "(cat eq 'resort') or price gt 70"})["value"]) == 2)
    _check("orderby desc", [d["id"] for d in s({"search": "*", "$orderby": "price desc"})["value"]] == ["1", "3", "2"])
    _check("facets", s({"search": "*", "facet": ["cat"]})["@search.facets"]["cat"][0] == {"count": 2, "value": "budget"})
    _check("select + top", list(s({"search": "*", "$select": "id", "$top": 1})["value"][0]) == ["@search.score", "id"])
    _check("bad filter 400", h("POST", f"{ix}/hotels/docs/search", {"$filter": "nope eq 1"})["status"] == 400)
    # blob indexer
    store.create_container("acct/docs")
    blob.dispatch(store, "PUT", "/docs/a.txt", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "text/plain"}, b"alpha beta gamma", account="acct")
    blob.dispatch(store, "PUT", "/docs/b.json", {}, {"x-ms-blob-type": "BlockBlob"}, b'{"id":"j1","title":"json doc about gamma","price":3.5}', account="acct")
    _check("blob index", h("PUT", f"{ix}/blobs", {"fields": [{"name": "id", "type": "Edm.String", "key": True}, {"name": "content", "type": "Edm.String", "searchable": True},
                                                          {"name": "title", "type": "Edm.String", "searchable": True}, {"name": "metadata_storage_name", "type": "Edm.String", "filterable": True}]})["status"] == 201)
    ds = f"{base}/svc1/datasources"
    _check("ds validation", h("PUT", f"{ds}/blobds", {"type": "azureblob", "credentials": {}, "container": {"name": "docs"}})["status"] == 400)
    _check("ds create", h("PUT", f"{ds}/blobds", {"type": "azureblob", "credentials": {"connectionString": "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=x"}, "container": {"name": "docs"}})["status"] == 201)
    _check("indexer needs real index", h("PUT", f"{base}/svc1/indexers/ix", {"dataSourceName": "blobds", "targetIndexName": "nope"})["status"] == 400)
    _check("indexer create", h("PUT", f"{base}/svc1/indexers/ix", {"dataSourceName": "blobds", "targetIndexName": "blobs"})["status"] == 201)
    _check("run accepted", h("POST", f"{base}/svc1/indexers/ix/run")["status"] == 202)
    st = h("GET", f"{base}/svc1/indexers/ix/status")["body"]["lastResult"]
    _check("indexer processed 2", st["status"] == "success" and st["itemsProcessed"] == 2)
    _check("indexed content searchable", len(h("POST", f"{ix}/blobs/docs/search", {"search": "gamma"})["body"]["value"]) == 2)
    _check("idempotent re-run", h("POST", f"{base}/svc1/indexers/ix/run") and h("GET", f"{ix}/blobs/docs/count")["body"] == 2)
    _check("cosmos ds not readable", h("PUT", f"{ds}/cos", {"type": "cosmosdb", "credentials": {"connectionString": "AccountEndpoint=x"}, "container": {"name": "c"}})["status"] == 201
           and h("PUT", f"{base}/svc1/indexers/ix2", {"dataSourceName": "cos", "targetIndexName": "blobs"})["status"] == 201
           and (h("POST", f"{base}/svc1/indexers/ix2/run"), h("GET", f"{base}/svc1/indexers/ix2/status")["body"]["lastResult"]["status"])[1] == "transientFailure")
    _check("index in use by indexer", h("DELETE", f"{ix}/blobs")["status"] == 409)
    print("PASS test_azure_search_core")


if __name__ == "__main__":
    run()
