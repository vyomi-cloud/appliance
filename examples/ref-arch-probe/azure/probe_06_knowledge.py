"""Component 6 Knowledge: Azure AI Search index create, document upload, BM25 + vector + hybrid + semantic queries (azure-search-documents)."""
import requests
from _common import *

P = Probe(6, "knowledge", "Knowledge: AI Search BM25 + vector + hybrid + semantic")
B = endpoint(); ensure_rg(B)
S = {}
DOCS = [{"id": "1", "title": "Approval policy", "content": "approvals above 500 need a manager sign off", "vec": [1, 0, 0, 0]},
        {"id": "2", "title": "Leak runbook", "content": "report a water leak in the lobby to facilities", "vec": [0, 1, 0, 0]},
        {"id": "3", "title": "Badge policy", "content": "lost badge must be reported to security", "vec": [0, 0, 1, 0]}]


def service():
    from azure.mgmt.search import SearchManagementClient
    c = arm(SearchManagementClient, B)
    svc = c.services.begin_create_or_update(RG, "srch1", {"location": LOC, "sku": {"name": "basic"}}).result()
    S["key"] = c.admin_keys.get(RG, "srch1").primary_key
    S["arm_endpoint"] = svc.properties.endpoint if hasattr(svc, "properties") and svc.properties else getattr(svc, "endpoint", None)
    S["ep"] = f"{B}/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Search/searchServices/srch1"
    return {"advertised_endpoint": getattr(svc, "endpoint", None) or S["arm_endpoint"]}


def advertised_reachable():
    ep = getattr(__import__("azure.mgmt.search", fromlist=["x"]), "x", None)
    from azure.mgmt.search import SearchManagementClient
    svc = arm(SearchManagementClient, B).services.get(RG, "srch1")
    url = svc.endpoint if hasattr(svc, "endpoint") and svc.endpoint else f"https://srch1.search.windows.net/"
    assert B.split("//")[1].split(":")[0] in url, f"ARM advertises {url}, which is not served by the simulator (data plane lives under an ARM-extension path instead)"
    return url


def sdk_create_index():
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (HnswAlgorithmConfiguration, SearchField, SearchFieldDataType, SearchIndex, SearchableField, SemanticConfiguration,
                                                       SemanticField, SemanticPrioritizedFields, SemanticSearch, SimpleField, VectorSearch, VectorSearchProfile)
    from azure.core.credentials import AzureKeyCredential
    ic = SearchIndexClient(S["ep"], AzureKeyCredential(S["key"]))
    fields = [SimpleField(name="id", type=SearchFieldDataType.String, key=True), SearchableField(name="title", type=SearchFieldDataType.String), SearchableField(name="content", type=SearchFieldDataType.String),
              SearchField(name="vec", type=SearchFieldDataType.Collection(SearchFieldDataType.Single), searchable=True, vector_search_dimensions=4, vector_search_profile_name="vp")]
    idx = SearchIndex(name="kb", fields=fields, vector_search=VectorSearch(algorithms=[HnswAlgorithmConfiguration(name="h")], profiles=[VectorSearchProfile(name="vp", algorithm_configuration_name="h")]),
                      semantic_search=SemanticSearch(configurations=[SemanticConfiguration(name="sem", prioritized_fields=SemanticPrioritizedFields(title_field=SemanticField(field_name="title"), content_fields=[SemanticField(field_name="content")]))]))
    return ic.create_index(idx).name


def sdk_create_or_update_index():
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import SearchFieldDataType, SearchIndex, SimpleField
    from azure.core.credentials import AzureKeyCredential
    SearchIndexClient(S["ep"], AzureKeyCredential(S["key"])).create_or_update_index(SearchIndex(name="kb2", fields=[SimpleField(name="id", type=SearchFieldDataType.String, key=True)]))


def sdk_upload():
    from azure.search.documents import SearchClient
    from azure.core.credentials import AzureKeyCredential
    S["sc"] = SearchClient(S["ep"], "kb", AzureKeyCredential(S["key"]))
    res = S["sc"].upload_documents(DOCS)
    assert all(r.succeeded for r in res), res
    return len(res)


def sdk_bm25():
    r = list(S["sc"].search("manager approvals"))
    assert r and r[0]["id"] == "1", r


def sdk_vector():
    from azure.search.documents.models import VectorizedQuery
    r = list(S["sc"].search(search_text=None, vector_queries=[VectorizedQuery(vector=[0, 1, 0, 0], k_nearest_neighbors=2, fields="vec")]))
    assert r and r[0]["id"] == "2", r


def sdk_hybrid():
    from azure.search.documents.models import VectorizedQuery
    r = list(S["sc"].search("water leak", vector_queries=[VectorizedQuery(vector=[0, 1, 0, 0], k_nearest_neighbors=2, fields="vec")]))
    assert r and r[0]["id"] == "2", r


def sdk_semantic():
    r = list(S["sc"].search("who signs off approvals", query_type="semantic", semantic_configuration_name="sem"))
    assert r and r[0].get("@search.reranker_score") is not None, [(x["id"], x.get("@search.reranker_score")) for x in r]


# ── engine-level: raw REST against the ARM-extension path (the only path the simulator serves), to size the wire gap separately from the engine ──
def raw(body, op="search"):
    url = S["ep"] + "/indexes/kb2e/docs/" + op
    return requests.post(url, params={"api-version": "2024-07-01"}, headers={"api-key": S["key"], "Content-Type": "application/json"}, json=body, timeout=20)


def raw_setup():
    H = {"api-key": S["key"], "Content-Type": "application/json"}; Q = {"api-version": "2024-07-01"}
    ix = {"name": "kb2e", "fields": [{"name": "id", "type": "Edm.String", "key": True}, {"name": "title", "type": "Edm.String", "searchable": True}, {"name": "content", "type": "Edm.String", "searchable": True},
          {"name": "vec", "type": "Collection(Edm.Single)", "searchable": True, "dimensions": 4, "vectorSearchProfile": "vp"}],
          "vectorSearch": {"algorithms": [{"name": "h", "kind": "hnsw"}], "profiles": [{"name": "vp", "algorithm": "h"}]},
          "semantic": {"configurations": [{"name": "sem", "prioritizedFields": {"titleField": {"fieldName": "title"}, "prioritizedContentFields": [{"fieldName": "content"}]}}]}}
    r = requests.put(S["ep"] + "/indexes/kb2e", params=Q, headers=H, json=ix); assert r.status_code in (200, 201), (r.status_code, r.text[:150])
    r = raw({"value": [dict(d, **{"@search.action": "upload"}) for d in DOCS]}, "index"); assert r.status_code == 200, r.text[:150]
    return "index + 3 docs via /indexes/{name}/docs/index"


def raw_bm25():
    r = raw({"search": "manager approvals"}).json()["value"]; assert r[0]["id"] == "1", r; return [(x["id"], x["@search.score"]) for x in r]


def raw_vector():
    r = raw({"vectorQueries": [{"kind": "vector", "vector": [0, 1, 0, 0], "k": 2, "fields": "vec"}]}).json()["value"]; assert r[0]["id"] == "2", r; return [(x["id"], x["@search.score"]) for x in r]


def raw_hybrid():
    r = raw({"search": "water leak", "vectorQueries": [{"kind": "vector", "vector": [0, 1, 0, 0], "k": 2, "fields": "vec"}]}).json()["value"]; assert r[0]["id"] == "2", r; return [(x["id"], x["@search.score"]) for x in r]


def raw_semantic():
    r = raw({"search": "manager approvals", "queryType": "semantic", "semanticConfiguration": "sem"}).json()["value"]
    assert r and any("@search.rerankerScore" in x for x in r), f"no @search.rerankerScore in {[list(x) for x in r][:2]}"
    return [(x["id"], x.get("@search.rerankerScore")) for x in r]


P.step("AI Search service + admin key via ARM (azure-mgmt-search)", service)
P.step("endpoint advertised by ARM (https://<svc>.search.windows.net) is served by the simulator", advertised_reachable)
P.step("SearchIndexClient.create_index (vector + semantic config) at the ARM-extension endpoint", sdk_create_index)
P.step("SearchIndexClient.create_or_update_index (PUT indexes('name'))", sdk_create_or_update_index)
P.step("SearchClient.upload_documents", sdk_upload)
P.step("SearchClient.search BM25", sdk_bm25)
P.step("SearchClient.search vector (VectorizedQuery)", sdk_vector)
P.step("SearchClient.search hybrid (text + vector)", sdk_hybrid)
P.step("SearchClient.search semantic ranker (reranker score)", sdk_semantic)
if P.step("ENGINE-LEVEL raw REST (ARM-extension path): index + docs", raw_setup):
    P.step("engine BM25", raw_bm25)
    P.step("engine vector", raw_vector)
    P.step("engine hybrid (RRF)", raw_hybrid)
    P.step("engine semantic ranker (@search.rerankerScore)", raw_semantic)
P.finish()
