"""Azure AI Search round 8: BM25 keyword scoring, semantic ranker approximation (captions/answers), vector query weights,
MergeSkill + sentence SplitSkill, Cosmos DB and Azure SQL indexers (incremental high-water mark, soft delete, fieldMappings).
Everything goes through the shared wire router (ARM + Cosmos data plane + Azure SQL data plane), the same path the console uses.

Run: PYTHONPATH=. python3 tests/conformance/test_azure_search_limvector.py
"""
import json
import sys

from core.aws_wire_router import AwsWireRouter
from core import llm_core as llm

AwsWireRouter.STRICT_GCP_PROJECT = False
llm.set_backend()
R = AwsWireRouter()
S = "00000000-0000-0000-0000-cloudlearn01"
fails = []


def ck(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name, "" if cond else str(extra)[:400])
    if not cond:
        fails.append(name)


def call(m, p, b=None, q=None, h=None):
    o = R.handle(m, p, q or {}, dict({"content-type": "application/json"}, **(h or {})), json.dumps(b).encode() if b is not None else b"")
    try:
        return o["status"], json.loads(o["body"] or b"{}")
    except Exception:
        return o["status"], o["body"]


AV = {"api-version": "2023-11-01"}
call("PUT", f"/subscriptions/{S}/resourcegroups/r", {"location": "eastus"}, {"api-version": "2021-04-01"})
B = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Search/searchServices"
s, o = call("PUT", f"{B}/limsvc", {"location": "eastus", "sku": {"name": "standard"}}, AV)
ck("service", s in (200, 201), o)
X = lambda m, p, b=None: call(m, f"{B}/limsvc/{p}", b, AV)

# ---- BM25 + semantic ranker
VS = {"algorithms": [{"name": "h", "kind": "hnsw"}], "profiles": [{"name": "p", "algorithm": "h"}]}
s, o = X("PUT", "indexes/kb", {"fields": [{"name": "id", "type": "Edm.String", "key": True}, {"name": "title", "type": "Edm.String", "searchable": True},
                                         {"name": "body", "type": "Edm.String", "searchable": True}],
                               "semantic": {"defaultConfiguration": "sc", "configurations": [{"name": "sc", "prioritizedFields": {"titleField": {"fieldName": "title"}, "prioritizedContentFields": [{"fieldName": "body"}]}}]}})
ck("semantic config accepted and stored", s == 201 and o["semantic"]["defaultConfiguration"] == "sc", o)
s, o = X("PUT", "indexes/badsem", {"fields": [{"name": "id", "type": "Edm.String", "key": True}], "semantic": {"configurations": [{"name": "x", "prioritizedFields": {"titleField": {"fieldName": "nope"}}}]}})
ck("semantic config references a real string field", s == 400, o)
docs = [("1", "Chiller plant maintenance", "The chiller plant on level 3 is serviced every quarter. Technicians check refrigerant pressure and the cooling tower."),
        ("2", "Boiler inspection", "Boiler inspection happens every October. The inspector signs the certificate and notes any leaks."),
        ("3", "Elevator contract", "The elevator maintenance contract renews in March and covers all lifts in the north tower."),
        ("4", "Cafeteria menu", "Lunch is served from noon. Vegetarian options include lentil soup and salad.")]
s, o = X("POST", "indexes/kb/docs/index", {"value": [{"@search.action": "upload", "id": i, "title": t, "body": b} for i, t, b in docs]})
ck("upload", s == 200, o)
s, o = X("POST", "indexes/kb/docs/search", {"search": "boiler inspection", "select": "id"})
ck("BM25 keyword ranks the boiler doc first", o["value"][0]["id"] == "2" and o["value"][0]["@search.score"] > 0, o)
s, o = X("POST", "indexes/kb/docs/search", {"search": "when does the lift contract renew", "queryType": "semantic", "captions": "extractive|highlight-true", "answers": "extractive|count-1", "select": "id,title"})
v = o["value"]
ck("semantic: reranker scores 0..4, descending", s == 200 and all(0 <= x["@search.rerankerScore"] <= 4 for x in v) and [x["@search.rerankerScore"] for x in v] == sorted((x["@search.rerankerScore"] for x in v), reverse=True), o)
ck("semantic: captions with highlights", "<em>" in v[0]["@search.captions"][0]["highlights"] and v[0]["@search.captions"][0]["text"], v[0])
ck("semantic: extractive answer", len(o.get("@search.answers", [])) == 1 and o["@search.answers"][0]["text"], o)
ck("semantic: the contract doc is first", v[0]["id"] == "3", [x["id"] for x in v])
s, o = X("POST", "indexes/kb/docs/search", {"search": "*", "queryType": "semantic"})
ck("semantic needs a text query", s == 400, o)
s, o = X("POST", "indexes/kb/docs/search", {"search": "x", "queryType": "semantic", "semanticConfiguration": "ghost"})
ck("unknown semantic configuration rejected", s == 400, o)
s, o = X("POST", "indexes/kb/docs/search", {"search": "x", "queryType": "bogus"})
ck("unknown queryType rejected", s == 400, o)

# ---- vector weights + MergeSkill / sentence SplitSkill through an indexer
s, o = X("PUT", "indexes/vw", {"fields": [{"name": "id", "type": "Edm.String", "key": True}, {"name": "t", "type": "Edm.String", "searchable": True},
                                         {"name": "v", "type": "Collection(Edm.Single)", "dimensions": 4, "vectorSearchProfile": "p"}], "vectorSearch": VS})
X("POST", "indexes/vw/docs/index", {"value": [{"@search.action": "upload", "id": "k", "t": "alpha", "v": [1, 0, 0, 0]}, {"@search.action": "upload", "id": "z", "t": "beta alpha", "v": [0, 1, 0, 0]}]})
lo = X("POST", "indexes/vw/docs/search", {"search": "beta", "vectorQueries": [{"kind": "vector", "vector": [1, 0, 0, 0], "fields": "v", "weight": 0.01}]})[1]["value"]
hi = X("POST", "indexes/vw/docs/search", {"search": "beta", "vectorQueries": [{"kind": "vector", "vector": [1, 0, 0, 0], "fields": "v", "weight": 100}]})[1]["value"]
ck("vector weight shifts the RRF balance", lo[0]["id"] == "z" and hi[0]["id"] == "k", (lo, hi))

# ---- Cosmos DB indexer
call("PUT", f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.DocumentDB/databaseAccounts/cs1", {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard"}}, {"api-version": "2024-05-15"})
ch = {"x-vyomi-account": "cs1"}
s, o = call("POST", "/dbs", {"id": "hotels"}, h=ch); ck("cosmos db", s in (200, 201), o)
s, o = call("POST", "/dbs/hotels/colls", {"id": "rooms", "partitionKey": {"paths": ["/city"], "kind": "Hash"}}, h=ch); ck("cosmos coll", s in (200, 201), o)
for i, (nm, city, deleted) in enumerate([("Lakeview", "Oslo", False), ("Harbor", "Bergen", False), ("Oldinn", "Oslo", False)]):
    call("POST", "/dbs/hotels/colls/rooms/docs", {"id": f"h{i}", "name": nm, "city": city, "rating": 4 + i, "isDeleted": deleted}, h=dict(ch, **{"x-ms-documentdb-partitionkey": json.dumps([city])}))
X("PUT", "indexes/hotels", {"fields": [{"name": "id", "type": "Edm.String", "key": True}, {"name": "name", "type": "Edm.String", "searchable": True},
                                      {"name": "city", "type": "Edm.String", "searchable": True, "filterable": True}, {"name": "rating", "type": "Edm.Int32", "filterable": True}]})
CS = "AccountEndpoint=https://cs1.documents.azure.com:443/;AccountKey=a2V5;Database=hotels;"
s, o = X("PUT", "datasources/cosmos-ds", {"type": "cosmosdb", "credentials": {"connectionString": CS}, "container": {"name": "rooms"},
                                         "dataChangeDetectionPolicy": {"@odata.type": "#Microsoft.Azure.Search.HighWaterMarkChangeDetectionPolicy", "highWaterMarkColumnName": "_ts"},
                                         "dataDeletionDetectionPolicy": {"@odata.type": "#Microsoft.Azure.Search.SoftDeleteColumnDeletionDetectionPolicy", "softDeleteColumnName": "isDeleted", "softDeleteMarkerValue": "true"}})
ck("cosmos data source stored", s in (200, 201), o)
s, o = X("PUT", "indexers/cosmos-ix", {"dataSourceName": "cosmos-ds", "targetIndexName": "hotels"})
s, o = X("POST", "indexers/cosmos-ix/run"); ck("run accepted", s == 202, o)
s, o = X("GET", "indexers/cosmos-ix/status")
ck("cosmos indexer succeeded with 3 items and a tracking state", o["lastResult"]["status"] == "success" and o["lastResult"]["itemsProcessed"] == 3 and o["lastResult"]["finalTrackingState"], o)
s, o = X("POST", "indexes/hotels/docs/search", {"search": "lakeview", "select": "id,name,city"})
ck("cosmos documents searchable", [d["id"] for d in o["value"]] == ["h0"], o)
call("PUT", "/dbs/hotels/colls/rooms/docs/h1", {"id": "h1", "name": "Harbor", "city": "Bergen", "rating": 5, "isDeleted": True}, h=dict(ch, **{"x-ms-documentdb-partitionkey": json.dumps(["Bergen"])}))
X("POST", "indexers/cosmos-ix/run")
s, o = X("GET", "indexers/cosmos-ix/status")
ck("soft-deleted Cosmos document removed from the index", X("GET", "indexes/hotels/docs/h1")[0] == 404, o["lastResult"])
ck("second run starts from the stored watermark", o["lastResult"]["itemsProcessed"] >= 1 and o["lastResult"]["initialTrackingState"], o["lastResult"])
s, o = X("PUT", "datasources/cosmos-bad", {"type": "cosmosdb", "credentials": {"connectionString": CS.replace("hotels", "nodb")}, "container": {"name": "rooms"}})
X("PUT", "indexers/cosmos-bad-ix", {"dataSourceName": "cosmos-bad", "targetIndexName": "hotels"}); X("POST", "indexers/cosmos-bad-ix/run")
o = X("GET", "indexers/cosmos-bad-ix/status")[1]
ck("missing Cosmos database -> modeled indexer failure", o["lastResult"]["status"] == "transientFailure" and "nodb" in o["lastResult"]["errorMessage"], o)

# ---- Azure SQL indexer
call("PUT", "/azure-sql/servers/sqlsrv")
call("PUT", "/azure-sql/servers/sqlsrv/databases/shop")
Q = lambda sql: call("POST", "/azure-sql/servers/sqlsrv/databases/shop/query", {"sql": sql})
Q("CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, descr TEXT, modified INTEGER, gone INTEGER DEFAULT 0)")
Q("INSERT INTO products VALUES ('p1','Desk lamp','LED lamp for the desk',1,0),('p2','Office chair','Ergonomic chair with lumbar support',2,0)")
X("PUT", "indexes/products", {"fields": [{"name": "sku", "type": "Edm.String", "key": True}, {"name": "title", "type": "Edm.String", "searchable": True}, {"name": "descr", "type": "Edm.String", "searchable": True}]})
SC = "Server=tcp:sqlsrv.database.windows.net,1433;Database=shop;User ID=u;Password=p;"
X("PUT", "datasources/sql-ds", {"type": "azuresql", "credentials": {"connectionString": SC}, "container": {"name": "dbo.products"},
                               "dataChangeDetectionPolicy": {"@odata.type": "#Microsoft.Azure.Search.HighWaterMarkChangeDetectionPolicy", "highWaterMarkColumnName": "modified"},
                               "dataDeletionDetectionPolicy": {"@odata.type": "#Microsoft.Azure.Search.SoftDeleteColumnDeletionDetectionPolicy", "softDeleteColumnName": "gone", "softDeleteMarkerValue": "1"}})
s, o = X("PUT", "indexers/sql-ix", {"dataSourceName": "sql-ds", "targetIndexName": "products", "fieldMappings": [{"sourceFieldName": "name", "targetFieldName": "title"}]})
ck("sql indexer with fieldMappings created", s in (200, 201), o)
X("POST", "indexers/sql-ix/run"); o = X("GET", "indexers/sql-ix/status")[1]
ck("sql indexer read 2 rows", o["lastResult"]["status"] == "success" and o["lastResult"]["itemsProcessed"] == 2, o)
o = X("POST", "indexes/products/docs/search", {"search": "ergonomic", "select": "sku,title"})[1]
ck("sql rows searchable through the mapped field", o["value"] and o["value"][0]["sku"] == "p2" and o["value"][0]["title"] == "Office chair", o)
Q("INSERT INTO products VALUES ('p3','Monitor arm','Adjustable arm',3,0)"); Q("UPDATE products SET gone=1, modified=4 WHERE sku='p1'")
X("POST", "indexers/sql-ix/run"); o = X("GET", "indexers/sql-ix/status")[1]
ck("incremental sql run: new row indexed, soft-deleted row removed", X("GET", "indexes/products/docs/p3")[0] == 200 and X("GET", "indexes/products/docs/p1")[0] == 404, o["lastResult"])
s, o = X("PUT", "datasources/sql-ct", {"type": "azuresql", "credentials": {"connectionString": SC}, "container": {"name": "products"}, "dataChangeDetectionPolicy": {"@odata.type": "#Microsoft.Azure.Search.SqlIntegratedChangeTrackingPolicy"}})
X("PUT", "indexers/sql-ct-ix", {"dataSourceName": "sql-ct", "targetIndexName": "products"}); X("POST", "indexers/sql-ct-ix/run")
o = X("GET", "indexers/sql-ct-ix/status")[1]
ck("SqlIntegratedChangeTracking is declared unsupported (not a silent full read)", o["lastResult"]["status"] == "transientFailure" and "SqlIntegratedChangeTracking" in o["lastResult"]["errorMessage"], o)
s, o = X("PUT", "indexers/badmap", {"dataSourceName": "sql-ds", "targetIndexName": "products", "fieldMappings": [{"sourceFieldName": "a", "mappingFunction": {"name": "nope"}}]})
ck("unknown mapping function rejected", s == 400, o)
Q("CREATE TABLE nokey (a TEXT)"); Q("INSERT INTO nokey VALUES ('x')")
X("PUT", "datasources/sql-nokey", {"type": "azuresql", "credentials": {"connectionString": SC}, "container": {"name": "nokey"}})
X("PUT", "indexers/nokey-ix", {"dataSourceName": "sql-nokey", "targetIndexName": "products"}); X("POST", "indexers/nokey-ix/run")
o = X("GET", "indexers/nokey-ix/status")[1]
ck("row without the index key fails per item with a clear message", o["lastResult"]["itemsFailed"] == 1 and "key" in o["lastResult"]["errors"][0]["errorMessage"], o)

# ---- MergeSkill + sentence split in a skillset (blob source)
call("PUT", f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/skstore", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, {"api-version": "2023-01-01"})
SKS = {"skills": [{"@odata.type": "#Microsoft.Skills.Text.MergeSkill", "name": "m", "context": "/document", "insertPreTag": "[", "insertPostTag": "]",
                   "inputs": [{"name": "text", "source": "/document/content"}, {"name": "itemsToInsert", "source": "/document/tags"}, {"name": "offsets", "source": "/document/offs"}],
                   "outputs": [{"name": "mergedText", "targetName": "merged"}]},
                  {"@odata.type": "#Microsoft.Skills.Text.SplitSkill", "name": "s", "textSplitMode": "sentences", "context": "/document",
                   "inputs": [{"name": "text", "source": "/document/merged"}], "outputs": [{"name": "textItems", "targetName": "sents"}]}]}
s, o = X("PUT", "skillsets/mk", SKS); ck("merge+sentence skillset accepted", s in (200, 201), o)
from core import azure_search_vector_core as V
tree, err = V.run_skillset(SKS, {"content": "Hello world. Second sentence here.", "tags": ["X"], "offs": [5]})
ck("MergeSkill inserts at offsets with tags", tree["document"]["merged"] == "Hello[X] world. Second sentence here." and err is None, tree)
ck("SplitSkill sentences mode", tree["document"]["sents"] == ["Hello[X] world.", "Second sentence here."], tree)
s, o = X("PUT", "skillsets/bad", {"skills": [{"@odata.type": "#Microsoft.Skills.Text.SplitSkill", "textSplitMode": "words", "inputs": [{"name": "text", "source": "/document/content"}], "outputs": [{"name": "textItems"}]}]})
ck("bad textSplitMode rejected", s == 400, o)
print("FAILS", len(fails))
sys.exit(1 if fails else 0)
