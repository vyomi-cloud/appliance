"""Azure reference architecture lane 3 (AI Search indexer): running an indexer over a Blob data source populates the index.
Blob bytes are uploaded with azure-storage-blob, the search service + admin key come from azure-mgmt-search, and the data-plane calls go to the
ARM-extension path (the native SearchIndexerClient / SearchClient wire is lane az-ref-ai's job; this test covers the indexer ENGINE and the
Blob account/connection-string resolution). Also Cosmos DB (SQL) as a source when azure-cosmos is available is covered by core tests.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_ref_search_indexer.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _az_ref_harness as H  # noqa: E402

KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


def main():
    try:
        import azure.mgmt.search, azure.mgmt.storage, azure.storage.blob, requests  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] needs the Azure SDKs ({e})")
        return 0
    base, _ = H.start()
    H.ensure_rg(base)
    import requests
    from azure.mgmt.search import SearchManagementClient
    from azure.mgmt.storage import StorageManagementClient
    from azure.storage.blob import BlobServiceClient

    ACCT = "facilitiesdocs"
    H.arm(StorageManagementClient, base).storage_accounts.begin_create(H.RG, ACCT, {"location": H.LOC, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).result()
    bs = BlobServiceClient.from_connection_string(f"DefaultEndpointsProtocol=http;AccountName={ACCT};AccountKey={KEY};BlobEndpoint={base}/{ACCT};")
    bs.create_container("docs")
    bs.get_blob_client("docs", "policy.txt").upload_blob(b"approvals above 500 need a manager sign off")
    bs.get_blob_client("docs", "leak.txt").upload_blob(b"water leak in the lobby needs facilities")
    sm = H.arm(SearchManagementClient, base)
    sm.services.begin_create_or_update(H.RG, "facilities-search", {"location": H.LOC, "sku": {"name": "basic"}}).result()
    key = sm.admin_keys.get(H.RG, "facilities-search").primary_key
    svc = f"{base}/subscriptions/{H.SUB}/resourceGroups/{H.RG}/providers/Microsoft.Search/searchServices/facilities-search"
    HD = {"api-key": key, "Content-Type": "application/json"}
    Q = {"api-version": "2024-07-01"}
    CS = f"DefaultEndpointsProtocol=https;AccountName={ACCT};AccountKey={KEY};EndpointSuffix=core.windows.net"

    def put(path, body):
        r = requests.put(f"{svc}/{path}", params=Q, headers=HD, json=body)
        assert r.status_code in (200, 201, 204), (path, r.status_code, r.text[:200])

    def t_indexer_fills_index():
        put("indexes/facilities-kb", {"name": "facilities-kb", "fields": [
            {"name": "id", "type": "Edm.String", "key": True}, {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "metadata_storage_name", "type": "Edm.String", "filterable": True}]})
        put("datasources/docs-ds", {"name": "docs-ds", "type": "azureblob", "credentials": {"connectionString": CS}, "container": {"name": "docs"}})
        put("indexers/docs-ix", {"name": "docs-ix", "dataSourceName": "docs-ds", "targetIndexName": "facilities-kb",
                                 "fieldMappings": [{"sourceFieldName": "metadata_storage_path", "targetFieldName": "id",
                                                    "mappingFunction": {"name": "base64Encode"}}]})
        r = requests.post(f"{svc}/indexers/docs-ix/run", params=Q, headers=HD)
        assert r.status_code in (200, 202), (r.status_code, r.text[:200])
        t0 = time.time()
        st = {}
        while time.time() - t0 < 15:
            st = requests.get(f"{svc}/indexers/docs-ix/status", params=Q, headers=HD).json()
            if (st.get("lastResult") or {}).get("status") in ("success", "transientFailure"):
                break
            time.sleep(0.5)
        lr = st.get("lastResult") or {}
        assert lr.get("status") == "success" and lr.get("itemsProcessed") == 2, lr
        r = requests.post(f"{svc}/indexes/facilities-kb/docs/search", params=Q, headers=HD, json={"search": "manager"}).json()
        assert [d["metadata_storage_name"] for d in r["value"]] == ["policy.txt"], r
        r = requests.post(f"{svc}/indexes/facilities-kb/docs/search", params=Q, headers=HD, json={"search": "lobby"}).json()
        assert [d["metadata_storage_name"] for d in r["value"]] == ["leak.txt"], r

    def t_rerun_picks_up_new_blob():
        bs.get_blob_client("docs", "extra.txt").upload_blob(b"elevator inspection overdue")
        requests.post(f"{svc}/indexers/docs-ix/run", params=Q, headers=HD)
        time.sleep(1)
        r = requests.post(f"{svc}/indexes/facilities-kb/docs/search", params=Q, headers=HD, json={"search": "elevator"}).json()
        assert [d["metadata_storage_name"] for d in r["value"]] == ["extra.txt"], r

    def t_devstorage_connection_string():
        put("datasources/dev-ds", {"name": "dev-ds", "type": "azureblob", "credentials": {"connectionString": "UseDevelopmentStorage=true"}, "container": {"name": "docs"}})
        put("indexers/dev-ix", {"name": "dev-ix", "dataSourceName": "dev-ds", "targetIndexName": "facilities-kb",
                                "fieldMappings": [{"sourceFieldName": "metadata_storage_path", "targetFieldName": "id", "mappingFunction": {"name": "base64Encode"}}]})
        requests.post(f"{svc}/indexers/dev-ix/run", params=Q, headers=HD)
        time.sleep(1)
        lr = requests.get(f"{svc}/indexers/dev-ix/status", params=Q, headers=HD).json().get("lastResult") or {}
        assert lr.get("status") == "success", lr

    H.run_cases([
        ("indexer over a Blob data source (account connection string) fills the index; BM25 finds the content", t_indexer_fills_index),
        ("re-running the indexer indexes a blob uploaded afterwards", t_rerun_picks_up_new_blob),
        ("UseDevelopmentStorage=true connection string resolves to the account holding the container", t_devstorage_connection_string),
    ])


if __name__ == "__main__":
    sys.exit(main())
