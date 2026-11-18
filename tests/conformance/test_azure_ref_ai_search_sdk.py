"""Azure ref-arch lane 2 (part 3): the REAL azure-search-documents clients (SearchIndexClient / SearchClient / SearchIndexerClient) speak the NATIVE
OData wire (`indexes('kb')`, `docs/search.post.search`, `search.index`, `search.run` ...) to the REAL appliance app (server.py, in-process), at both the
root endpoint and `/azure-data/search/<service>`; plus the `<service>.search.*` Host form. Semantic ranker uses the local embedding seam.
Run: PYTHONPATH=. <venv>/bin/python tests/conformance/test_azure_ref_ai_search_sdk.py   (skips cleanly without azure-search-documents)"""
import os, sys, warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "examples", "ref-arch-probe", "azure"))
warnings.filterwarnings("ignore")
try:
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
    from azure.mgmt.search import SearchManagementClient
except ImportError as e:
    print(f"SKIP: optional dependency missing ({e})")
    sys.exit(0)

PASS = FAIL = 0


def check(name, fn):
    global PASS, FAIL
    try:
        ev = fn()
        PASS += 1
        print(f"  [PASS] {name} {'' if ev is None else str(ev)[:140]}")
    except Exception as e:  # noqa: BLE001
        FAIL += 1
        print(f"  [FAIL] {name} {type(e).__name__}: {str(e)[:300]}")


def need(cond, what):
    if not cond:
        raise AssertionError(what)


DOCS = [{"id": "1", "title": "Approval policy", "content": "approvals above 500 dollars need a manager sign off", "vec": [1.0, 0, 0, 0]},
        {"id": "2", "title": "Leak runbook", "content": "report a water leak in the lobby to facilities", "vec": [0, 1.0, 0, 0]},
        {"id": "3", "title": "Badge policy", "content": "lost badge must be reported to security", "vec": [0, 0, 1.0, 0]}]


def main():
    from _common import endpoint, ensure_rg, arm, RG, LOC
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes.models import (HnswAlgorithmConfiguration, SearchField, SearchFieldDataType, SearchIndex, SearchableField, SemanticConfiguration,
        SemanticField, SemanticPrioritizedFields, SemanticSearch, SimpleField, VectorSearch, VectorSearchProfile, SearchSuggester, SynonymMap,
        SearchIndexerDataSourceConnection, SearchIndexerDataContainer, SearchIndexer, SearchIndexerSkillset, SearchAlias)
    from azure.search.documents.models import VectorizedQuery
    B = endpoint(); ensure_rg(B)
    mc = arm(SearchManagementClient, B)
    mc.services.begin_create_or_update(RG, "srch1", {"location": LOC, "sku": {"name": "basic"}}).result()
    key = mc.admin_keys.get(RG, "srch1").primary_key
    K = AzureKeyCredential(key)

    for label, ep in (("root endpoint", B), ("path-prefixed endpoint", B + "/azure-data/search/srch1")):
        first = label == "root endpoint"
        ic = SearchIndexClient(ep, K)
        iname = "kb" if first else "kbp"

        def mk():
            fields = [SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True, sortable=True),
                      SearchableField(name="title", type=SearchFieldDataType.String, filterable=True, sortable=True, facetable=True),
                      SearchableField(name="content", type=SearchFieldDataType.String),
                      SearchField(name="vec", type=SearchFieldDataType.Collection(SearchFieldDataType.Single), searchable=True, vector_search_dimensions=4, vector_search_profile_name="vp")]
            idx = SearchIndex(name=iname, fields=fields,
                              vector_search=VectorSearch(algorithms=[HnswAlgorithmConfiguration(name="h")], profiles=[VectorSearchProfile(name="vp", algorithm_configuration_name="h")]),
                              semantic_search=SemanticSearch(configurations=[SemanticConfiguration(name="sem", prioritized_fields=SemanticPrioritizedFields(
                                  title_field=SemanticField(field_name="title"), content_fields=[SemanticField(field_name="content")]))]),
                              suggesters=[SearchSuggester(name="sg", source_fields=["title", "content"])])
            need(ic.create_index(idx).name == iname, "create")
            need(ic.create_or_update_index(idx).name == iname, "create_or_update")
            need(ic.get_index(iname).name == iname and iname in [i.name for i in ic.list_indexes()] and iname in list(ic.list_index_names()), "get/list")
            return label
        check(f"[{label}] SearchIndexClient create_index / create_or_update_index / get / list", mk)
        sc = SearchClient(ep, iname, K)

        def upload():
            res = sc.upload_documents(DOCS)
            need(all(r.succeeded for r in res) and len(res) == 3, "upload")
            need(sc.merge_documents([{"id": "1", "title": "Approval policy v2"}])[0].succeeded, "merge")
            need(sc.merge_or_upload_documents([{"id": "4", "title": "Parking", "content": "park in the east lot", "vec": [0, 0, 0, 1.0]}])[0].succeeded, "mou")
            need(sc.delete_documents([{"id": "4"}])[0].succeeded, "delete")
            need(sc.get_document_count() == 3, "count")
            need(sc.get_document("1")["title"] == "Approval policy v2", "get_document")
        check(f"[{label}] SearchClient upload / merge / mergeOrUpload / delete / count / get_document", upload)

        def bm25():
            need([r["id"] for r in sc.search("manager approvals", select=["id", "title"])][0] == "1", "bm25")
            need(list(sc.search("*", filter="id eq '2'", select=["id"]))[0]["id"] == "2", "filter")
            need([r["id"] for r in sc.search("*", order_by=["id desc"], select=["id"])] == ["3", "2", "1"], "order_by")
            need(sc.search("*", include_total_count=True).get_count() == 3, "count")
            need(sc.search("*", facets=["title"]).get_facets(), "facets")
            need([r["id"] for r in sc.search("water", search_fields=["title"])] == [], "search_fields")
            need([r["id"] for r in sc.search("lobby facilities", search_mode="all")] == ["2"], "search_mode")
            return "ok"
        check(f"[{label}] search BM25 (select, filter, order_by, count, facets, search_fields, search_mode)", bm25)

        def vector():
            r = list(sc.search(search_text=None, vector_queries=[VectorizedQuery(vector=[0, 1.0, 0, 0], k_nearest_neighbors=2, fields="vec")]))
            need(r and r[0]["id"] == "2", r)
            h = list(sc.search("water leak", vector_queries=[VectorizedQuery(vector=[0, 1.0, 0, 0], k_nearest_neighbors=2, fields="vec")]))
            need(h and h[0]["id"] == "2", h)
            return "vector top=2, hybrid top=2"
        check(f"[{label}] search vector (VectorizedQuery) + hybrid", vector)

        def semantic():
            res = sc.search("who signs off approvals", query_type="semantic", semantic_configuration_name="sem", query_caption="extractive", query_answer="extractive", top=3)
            rows = list(res)
            need(rows and rows[0].get("@search.reranker_score") is not None, [(x["id"], x.get("@search.reranker_score")) for x in rows])
            return {"top": rows[0]["id"], "reranker": rows[0]["@search.reranker_score"], "captions": bool(rows[0].get("@search.captions")), "answers": bool(res.get_answers())}
        check(f"[{label}] SearchClient.search(query_type='semantic', captions + answers)", semantic)

        def sugg():
            need([x["id"] for x in sc.suggest("lea", "sg", select=["id"])] == ["2"], sc.suggest("lea", "sg"))
            need([x["text"] for x in sc.autocomplete("man", "sg")] == ["manager"], sc.autocomplete("man", "sg"))
            return "ok"
        check(f"[{label}] SearchClient.suggest / autocomplete", sugg)

        def misc():
            st = ic.get_index_statistics(iname)
            need((st.get("document_count") if hasattr(st, "get") and "document_count" in st else st.get("documentCount")) == 3, st)
            need(ic.get_service_statistics(), "svc stats")
            need(ic.create_or_update_synonym_map(SynonymMap(name="sy-" + iname, synonyms=["lavatory, restroom"])).name == "sy-" + iname, "syn")
            need("sy-" + iname in [m.name for m in ic.get_synonym_maps()], "syn list")
            ic.delete_synonym_map("sy-" + iname)
            need(ic.create_alias(SearchAlias(name="al-" + iname, indexes=[iname])).name == "al-" + iname, "alias")
            need("al-" + iname in [a.name for a in ic.list_aliases()], "alias list")
            ic.delete_alias("al-" + iname)
            return "ok"
        check(f"[{label}] index + service statistics, synonym maps, alias", misc)
        if first:
            def indexer():
                xc = SearchIndexerClient(ep, K)
                xc.create_or_update_data_source_connection(SearchIndexerDataSourceConnection(name="ds1", type="azureblob",
                    connection_string="DefaultEndpointsProtocol=https;AccountName=nope;AccountKey=a2V5;EndpointSuffix=core.windows.net", container=SearchIndexerDataContainer(name="docs")))
                ix = xc.create_or_update_indexer(SearchIndexer(name="ixr1", data_source_name="ds1", target_index_name=iname))
                xc.run_indexer("ixr1")
                st = xc.get_indexer_status("ixr1")
                need(ix.name == "ixr1" and st.status, st)
                need("ixr1" in [i.name for i in xc.get_indexers()] and "ds1" in [d.name for d in xc.get_data_source_connections()], "lists")
                xc.reset_indexer("ixr1")
                from azure.search.documents.indexes.models import SplitSkill, InputFieldMappingEntry, OutputFieldMappingEntry
                xc.create_or_update_skillset(SearchIndexerSkillset(name="ss1", description="d", skills=[SplitSkill(
                    inputs=[InputFieldMappingEntry(name="text", source="/document/content")], outputs=[OutputFieldMappingEntry(name="textItems", target_name="pages")],
                    text_split_mode="pages", maximum_page_length=500)]))
                need(xc.get_skillset("ss1").name == "ss1" and "ss1" in xc.get_skillset_names(), "skillset")
                xc.delete_skillset("ss1"); xc.delete_indexer("ixr1"); xc.delete_data_source_connection("ds1")
                return {"status": str(st.status), "last": getattr(st.last_result, "status", None)}
            check(f"[{label}] SearchIndexerClient datasource / indexer create, run, status, reset, list, skillset, delete", indexer)

        def drop():
            ic.delete_index(iname)
            need(iname not in [i.name for i in ic.list_indexes()], "still listed")
        check(f"[{label}] delete_index", drop)

    def host_form():
        import requests
        port = B.rsplit(":", 1)[1]
        ic = SearchIndexClient(B, K)
        ic.create_index(SearchIndex(name="hostidx", fields=[SimpleField(name="id", type=SearchFieldDataType.String, key=True)]))
        q = {"api-version": "2026-10-01"}
        r = requests.get(f"http://127.0.0.1:{port}/indexes('hostidx')", params=q, headers={"api-key": key, "Host": "srch1.search.localtest.me:" + port}, timeout=10)
        need(r.status_code == 200 and r.json()["name"] == "hostidx", r.text[:200])
        r = requests.get(f"http://127.0.0.1:{port}/indexes", params=q, headers={"api-key": "wrong"}, timeout=10)
        need(r.status_code == 403, r.status_code)
        r = requests.get(f"http://127.0.0.1:{port}/indexes", params=q, headers={"api-key": key, "Host": "other.search.localtest.me:" + port}, timeout=10)
        need(r.status_code == 404, r.status_code)
        qk = mc.query_keys.create(RG, "srch1", "ro").key
        r = requests.get(f"http://127.0.0.1:{port}/indexes('hostidx')/docs/$count", params=q, headers={"api-key": qk}, timeout=10)
        need(r.status_code == 200 and r.text.strip() == "0", (r.status_code, r.text))
        r = requests.delete(f"http://127.0.0.1:{port}/indexes('hostidx')", params=q, headers={"api-key": qk}, timeout=10)
        need(r.status_code == 403, "a query key must not delete an index")
        return "Host=<svc>.search.* resolves the service; bad key 403; unknown service 404; query key reads, cannot delete"
    check("Host form <service>.search.* + bad api-key 403 + unknown service 404 + query-key scope", host_form)
    print(f"{PASS} passed, {FAIL} failed")
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
