"""GCP RAG Engine + Vertex AI Search round 8: dense / hybrid retrieval over the local embedder, GCS import from the SIMULATED Cloud Storage,
multipart upload (related + form-data), reranking, thresholds, live corpus counts, and a cited generated summary via the local chat model.

Run: PYTHONPATH=. python3 tests/conformance/test_gcp_rag_limvector.py
"""
import json
import math
import re
import sys

from core.aws_wire_router import AwsWireRouter
from core import llm_core as llm

AwsWireRouter.STRICT_GCP_PROJECT = False
R = AwsWireRouter()
fails = []

# a stand-in embedder with CONCEPT dimensions so "furnace" lands near "boiler" with zero shared words (what a real model does)
CONCEPTS = [("boiler", "furnace", "heater", "heating", "burner"), ("elevator", "lift", "escalator"), ("cafeteria", "lunch", "canteen", "soup", "menu"), ("chiller", "cooling", "refrigerant")]


def emb(texts):
    out = []
    for t in texts:
        toks = re.findall(r"[a-z0-9]+", t.lower())
        v = [sum(1.0 for w in toks if w in grp) for grp in CONCEPTS] + [0.0] * 4
        for w in toks:
            v[4 + (sum(map(ord, w)) % 4)] += 0.05
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def chat_stub(messages, system=None, max_tokens=256, temperature=0.7, stop=None):
    ctx = messages[-1]["content"]
    return "The boiler is inspected every October [1]. Elevators renew in March [2]." if "Search results" in ctx else "ok"


llm.set_backend(chat_stub, embed_fn=emb)


def ck(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name, "" if cond else str(extra)[:500])
    if not cond:
        fails.append(name)


def call(m, p, b=None, q=None, headers=None, raw=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    body = raw if raw is not None else (json.dumps(b).encode() if b is not None else b"")
    o = R.handle(m, p, q or {}, h, body)
    try:
        return o["status"], json.loads(o["body"] or b"{}")
    except Exception:
        return o["status"], o["body"]


P = "/v1/projects/demo/locations/us-central1"
s, o = call("POST", P + "/ragCorpora", {"displayName": "facilities"})
cn = o["response"]["name"]
s, o = call("POST", "/upload/v1/" + cn + "/ragFiles:upload", {"ragFile": {"displayName": "boiler.txt"}, "text": "The furnace room houses the boiler. Boiler inspection happens every October. The burner is cleaned yearly."})
ck("json upload embeds chunks", s == 200 and o["ragFile"]["vyomiChunks"] >= 1, o)
s, o = call("GET", "/v1/" + cn)
ck("corpus counts are live right after upload", o["vyomiStats"]["files"] == 1 and o["vyomiStats"]["chunks"] >= 1 and o["vyomiStats"]["embedded"] == o["vyomiStats"]["chunks"], o)

# multipart/related (JSON metadata then bytes), as the RAG Engine upload endpoint takes it
B = "vyomiboundary"
rel = (f"--{B}\r\nContent-Type: application/json\r\n\r\n" + json.dumps({"ragFile": {"displayName": "lifts.md", "description": "elevators"}}) +
       f"\r\n--{B}\r\nContent-Type: text/markdown\r\n\r\n# Elevators\nThe lift maintenance contract renews in March for the north tower.\r\n--{B}--\r\n").encode()
s, o = call("POST", "/upload/v1/" + cn + "/ragFiles:upload", headers={"content-type": f"multipart/related; boundary={B}"}, raw=rel)
ck("multipart/related upload", s == 200 and o["ragFile"]["displayName"] == "lifts.md" and o["ragFile"]["description"] == "elevators", o)
form = (f"--{B}\r\nContent-Disposition: form-data; name=\"metadata\"\r\nContent-Type: application/json\r\n\r\n" + json.dumps({"ragFile": {"displayName": "menu.txt"}}) +
        f"\r\n--{B}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"menu.txt\"\r\nContent-Type: text/plain\r\n\r\nLunch in the canteen: soup and salad.\r\n--{B}--\r\n").encode()
s, o = call("POST", "/upload/v1/" + cn + "/ragFiles:upload", headers={"content-type": f"multipart/form-data; boundary={B}"}, raw=form)
ck("multipart/form-data upload", s == 200 and o["ragFile"]["displayName"] == "menu.txt", o)
s, o = call("POST", "/upload/v1/" + cn + "/ragFiles:upload", headers={"content-type": f"multipart/related; boundary={B}"}, raw=f"--{B}\r\nContent-Type: application/json\r\n\r\n{{}}\r\n--{B}--\r\n".encode())
ck("multipart without a file part is INVALID_ARGUMENT", s == 400, o)

def ret(text, **cfg):
    return call("POST", P + ":retrieveContexts", {"query": {"text": text, "ragRetrievalConfig": dict({"topK": 3}, **cfg)}, "vertexRagStore": {"ragResources": [{"ragCorpus": cn}]}})
s, o = ret("when do we check the heating plant")
c = o["contexts"]["contexts"]
ck("dense retrieval finds the boiler doc with no shared words", s == 200 and "boiler" in c[0]["text"].lower() and c[0]["score"] > 0.3 and c[0]["distance"] < 0.7, o)
s, o = ret("lift contract")
ck("dense: elevator file first", "lift" in o["contexts"]["contexts"][0]["text"].lower(), o)
s, o = ret("heater", hybridSearch={"alpha": 0.0})
ck("hybrid alpha=0 is lexical only (no shared word -> nothing)", s == 200 and o["contexts"]["contexts"] == [], o)
s, o = ret("furnace", hybridSearch={"alpha": 0.0})
ck("hybrid alpha=0 finds the exact word", "furnace" in o["contexts"]["contexts"][0]["text"], o)
s, o = ret("boiler inspection October", hybridSearch={"alpha": 0.5})
ck("hybrid fuses dense + BM25", "October" in o["contexts"]["contexts"][0]["text"] and "sparseDistance" in o["contexts"]["contexts"][0], o)
s, o = ret("boiler inspection October", hybridSearch={"alpha": 2})
ck("alpha out of range is INVALID_ARGUMENT", s == 400, o)
s, o = ret("heating", filter={"vectorDistanceThreshold": 0.0001})
ck("vectorDistanceThreshold drops far contexts", o["contexts"]["contexts"] == [], o)
s, o = ret("heating", filter={"vectorSimilarityThreshold": 0.2})
ck("vectorSimilarityThreshold keeps near contexts", len(o["contexts"]["contexts"]) >= 1, o)
s, o = ret("boiler October", ranking={"rankService": {"modelName": "semantic-ranker-512@latest"}})
ck("reranking adds a rerank score", "vyomiRerankScore" in o["contexts"]["contexts"][0], o)
s, o = ret("x", topK=0) if False else call("POST", P + ":retrieveContexts", {"query": {"text": "x", "ragRetrievalConfig": {"topK": 5000}}, "vertexRagStore": {"ragResources": [{"ragCorpus": cn}]}})
ck("topK out of range is INVALID_ARGUMENT", s == 400, o)

# ---- import from the simulated Cloud Storage
call("POST", "/storage/v1/b", {"name": "kb-bucket"}, {"project": "demo"})
def put(name, data, ct="text/plain"):
    return call("POST", "/upload/storage/v1/b/kb-bucket/o", q={"uploadType": "media", "name": name}, headers={"content-type": ct}, raw=data)
put("docs/hvac.txt", b"The chiller plant needs refrigerant checks each quarter. Cooling towers are cleaned in May.")
put("docs/fire.md", b"# Fire safety\nExtinguishers are inspected every June by the safety officer.", "text/markdown")
put("docs/legacy.doc", b"\xd0\xcf\x11\xe0 legacy binary", "application/msword")
put("other/skip.txt", b"not in the import prefix")
s, o = call("POST", "/v1/" + cn + "/ragFiles:import", {"importRagFilesConfig": {"gcsSource": {"uris": ["gs://kb-bucket/docs/"]}}})
r = o.get("response", {})
ck("GCS import: 2 imported, the legacy .doc fails by name", s == 200 and r.get("importedRagFilesCount") == "2" and r.get("failedRagFilesCount") == "1" and "legacy.doc" in json.dumps(o["metadata"].get("vyomiFailures")), o)
s, o = call("GET", "/v1/" + cn + "/ragFiles")
names = sorted(f["displayName"] for f in o["ragFiles"])
ck("imported files list with their gcs source", "hvac.txt" in names and "fire.md" in names and "skip.txt" not in names and any(f.get("gcsSource", {}).get("uris") == ["gs://kb-bucket/docs/hvac.txt"] for f in o["ragFiles"]), o)
s, o = call("GET", "/v1/" + cn)
ck("corpus counts updated after import", o["vyomiStats"]["files"] == 5, o)
s, o = ret("cooling refrigerant")
ck("imported GCS content is retrievable", "chiller" in o["contexts"]["contexts"][0]["text"], o)
s, o = call("POST", "/v1/" + cn + "/ragFiles:import", {"importRagFilesConfig": {"gcsSource": {"uris": ["gs://kb-bucket/docs/hvac.txt"]}}})
ck("re-import of an unchanged object is skipped", o["response"]["skippedRagFilesCount"] == "1" and o["response"]["importedRagFilesCount"] == "0", o)
put("docs/hvac.txt", b"The chiller plant is serviced monthly now.")
s, o = call("POST", "/v1/" + cn + "/ragFiles:import", {"importRagFilesConfig": {"gcsSource": {"uris": ["gs://kb-bucket/docs/hvac.txt"]}}})
ck("a changed object is re-imported in place", o["response"]["importedRagFilesCount"] == "1" and len(call("GET", "/v1/" + cn + "/ragFiles")[1]["ragFiles"]) == 5, o)
s, o = call("POST", "/v1/" + cn + "/ragFiles:import", {"importRagFilesConfig": {"googleDriveSource": {"resourceIds": [{"resourceId": "x", "resourceType": "RESOURCE_TYPE_FILE"}]}}})
ck("Drive source is declared unsupported (400)", s == 400 and "google_drive" in o["error"]["message"].lower() or "googleDriveSource" in json.dumps(o), o)
s, o = call("POST", "/v1/" + cn + "/ragFiles:import", {"importRagFilesConfig": {"gcsSource": {"uris": ["gs://nope-bucket/x"]}}})
ck("missing bucket -> NOT_FOUND", s == 404, o)
s, o = call("POST", "/v1/" + cn + "/ragFiles:import", {"importRagFilesConfig": {"gcsSource": {"uris": ["notauri"]}}})
ck("bad uri -> INVALID_ARGUMENT", s == 400, o)

# ---- Vertex AI Search: GCS import, hybrid search, generated summary
D = "/v1/projects/demo/locations/global/collections/default_collection"
call("POST", D + "/dataStores", {"displayName": "docs", "industryVertical": "GENERIC", "contentConfig": "CONTENT_REQUIRED"}, {"dataStoreId": "docs"})
put("search/boiler.txt", b"Boiler inspection happens every October. The inspector signs the certificate.")
put("search/lifts.txt", b"The elevator maintenance contract renews in March for all lifts.")
put("search/menu.txt", b"Lunch menu: lentil soup and salad in the canteen.")
s, o = call("POST", D + "/dataStores/docs/branches/default_branch/documents:import", {"gcsSource": {"inputUris": ["gs://kb-bucket/search/"], "dataSchema": "content"}})
ck("discoveryengine GCS content import", s == 200 and o["metadata"]["successCount"] == "3" and o["metadata"]["failureCount"] == "0", o)
put("search/records.jsonl", b'{"id":"r1","title":"Heating loop","body":"The furnace heats the loop."}\n{"id":"r2","title":"Canteen","body":"Soup of the day"}\n', "application/json")
s, o = call("POST", D + "/dataStores/docs/branches/default_branch/documents:import", {"gcsSource": {"inputUris": ["gs://kb-bucket/search/records.jsonl"], "dataSchema": "custom"}})
ck("discoveryengine custom jsonl import", s == 200 and o["metadata"]["successCount"] == "2", o)
s, o = call("POST", D + "/dataStores/docs/branches/default_branch/documents:import", {"bigquerySource": {"projectId": "p", "datasetId": "d", "tableId": "t"}})
ck("BigQuery import is declared unsupported", s == 400, o)
s, o = call("GET", D + "/dataStores/docs")
ck("data store document count is live", o["vyomiStats"]["documents"] == 5, o)
S = D + "/dataStores/docs/servingConfigs/default_search:search"
s, o = call("POST", S, {"query": "heating furnace"})
ck("hybrid search: semantic hit with no shared token", s == 200 and any(r["id"] == "r1" for r in o["results"]) and all("vyomiRank" in r for r in o["results"]), o)
s, o = call("POST", S, {"query": "elevator lifts contract", "pageSize": 3, "contentSearchSpec": {"summarySpec": {"summaryResultCount": 2, "includeCitations": True}}})
sm = o["summary"]
ck("summary with citations from the local model", "October" in sm["summaryText"] and sm["summaryWithMetadata"]["citationMetadata"]["citations"] and sm["summaryWithMetadata"]["references"], o)
s, o = call("POST", S, {"query": "elevator", "contentSearchSpec": {"summarySpec": {"summaryResultCount": 1}}})
ck("summary without citations has no markers", "[1]" not in o["summary"]["summaryText"] and "summaryWithMetadata" not in o["summary"], o)
s, o = call("POST", S, {"query": "elevator"})
ck("no summarySpec -> empty summary", o["summary"] == {}, o)
def no_chat(*a, **k):
    raise llm.LlmUnavailable("no model")
llm.set_backend(no_chat, embed_fn=emb)
s, o = call("POST", S, {"query": "elevator", "contentSearchSpec": {"summarySpec": {}}})
ck("no local model -> summarySkippedReasons, search still succeeds", s == 200 and o["summary"]["summarySkippedReasons"] and o["results"], o)
print("FAILS", len(fails))
sys.exit(1 if fails else 0)
