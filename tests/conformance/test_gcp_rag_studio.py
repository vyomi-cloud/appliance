"""GCP RAG Studio backend: the Vyomi inspect API (/_vyomi/gcp-rag/.../chunks + retrieve-trace), ragEmbeddingModelConfig on corpus create,
:retrieveContexts staying identical, and generateContent tools[].retrieval.vertexRagStore returning groundingMetadata citations.

Run: PYTHONPATH=. python3 tests/conformance/test_gcp_rag_studio.py
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
CONCEPTS = [("boiler", "furnace", "heater"), ("elevator", "lift"), ("cafeteria", "lunch", "soup"), ("chiller", "cooling", "refrigerant")]


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


llm.set_backend(lambda messages, system=None, max_tokens=256, temperature=0.7, stop=None: "The boiler is inspected every October.", embed_fn=emb)


def ck(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name, "" if cond else str(extra)[:600])
    if not cond:
        fails.append(name)


def call(m, p, b=None, q=None):
    o = R.handle(m, p, q or {}, {"content-type": "application/json"}, json.dumps(b).encode() if b is not None else b"")
    try:
        return o["status"], json.loads(o["body"] or b"{}")
    except Exception:
        return o["status"], o["body"]


P = "/v1/projects/demo/locations/us-central1"
# corpus-level embedding model config
s, o = call("POST", P + "/ragCorpora", {"displayName": "bad", "ragEmbeddingModelConfig": {"vertexPredictionEndpoint": {"model": "gemini-2.0-flash"}}})
ck("a chat model is rejected as the corpus embedding model", s == 400, o)
s, o = call("POST", P + "/ragCorpora", {"displayName": "bad2", "ragEmbeddingModelConfig": {}})
ck("an empty embedding config is ignored", s == 200, o)
s, o = call("POST", P + "/ragCorpora", {"displayName": "studio", "ragEmbeddingModelConfig": {"vertexPredictionEndpoint": {"model": "publishers/google/models/text-embedding-005"}}})
cn = o["response"]["name"]
ck("embedding config stored on the corpus", o["response"]["ragEmbeddingModelConfig"]["vertexPredictionEndpoint"]["model"].endswith("text-embedding-005"), o)
s, o = call("GET", "/v1/" + cn)
ck("embedding config returned on GET", "ragEmbeddingModelConfig" in o, o)
cid = cn.split("/")[-1]
docs = {"boiler.txt": "The furnace room houses the boiler. Boiler inspection happens every October. The burner is cleaned yearly. Contact boiler@plant.example for faults.",
        "lifts.txt": "The lift maintenance contract renews in March for the north tower. Elevator safety certificates are renewed in April.",
        "menu.txt": "The cafeteria serves soup at lunch. Friday lunch is fish."}
fids = {}
for n, t in docs.items():
    s, o = call("POST", "/upload/v1/" + cn + "/ragFiles:upload", {"ragFile": {"displayName": n}, "text": t, "uploadRagFileConfig": {"ragFileTransformationConfig": {"ragFileChunkingConfig": {"fixedLengthChunking": {"chunkSize": 80, "chunkOverlap": 10}}}}})
    fids[n] = o["ragFile"]["name"].split("/")[-1]
S = f"/_vyomi/gcp-rag/demo/us-central1/{cid}"

# routing + inspect chunks
s, o = call("GET", S + "/chunks", q={"vectors": "true"})
ck("inspect chunks 200 with count/dimensions", s == 200 and o["count"] >= 3 and o["dimensions"] == 8 and o["embeddingModel"].endswith("text-embedding-005"), o)
c0 = o["chunks"][0]
ck("chunk shape (id, documentUri, text, tokenCount, metadata, projection2d, vector)", all(k in c0 for k in ("id", "documentUri", "text", "tokenCount", "metadata", "section", "pii", "projection2d", "vector")) and len(c0["projection2d"]) == 2 and len(c0["vector"]) == 8, c0)
ck("PII flagged on the chunk with an email", any(c["pii"] == ["email"] for c in o["chunks"]), [c["pii"] for c in o["chunks"]])
s, o2 = call("GET", S + "/chunks")
ck("vectors omitted unless requested", s == 200 and o2["chunks"][0]["vector"] is None)
s, o2 = call("GET", f"/_vyomi/gcp-rag/demo/us-central1/999/chunks")
ck("unknown corpus 404", s == 404, o2)

# retrieve-trace + retrieveContexts parity
body = {"query": {"text": "when is the boiler inspected", "ragRetrievalConfig": {"topK": 2, "hybridSearch": {"alpha": 0.5}}}, "vertexRagStore": {"ragResources": [{"ragCorpus": cn}]}}
s, base = call("POST", P + ":retrieveContexts", body)
s2, tr = call("POST", S + "/retrieve-trace", body)
ck("retrieve-trace contexts identical to retrieveContexts", s == 200 and s2 == 200 and tr["contexts"] == base["contexts"], (base, tr["contexts"]))
t = tr["trace"]
cand = t["candidates"]
ck("trace covers every chunk with per-stage fields", len(cand) == call("GET", S + "/chunks")[1]["count"] and all(k in cand[0] for k in ("vector_score", "bm25_score", "fused_rank", "rerank_score", "filtered_out_reason", "returned")), cand[:1])
ck("trace marks exactly topK returned", sum(1 for c in cand if c["returned"]) == 2 and t["searchType"] == "HYBRID" and "total" in t["latencyMs"], t)
ck("dropped chunks carry a reason", all(c["filtered_out_reason"] for c in cand if not c["returned"]))
rr = {**body, "query": {**body["query"], "ragRetrievalConfig": {"topK": 2, "hybridSearch": {"alpha": 0.5}, "ranking": {"rankService": {"modelName": "semantic-ranker-512@latest"}}}}}
s, tr2 = call("POST", S + "/retrieve-trace", rr)
ck("rerank scores in the trace and vyomiRerankScore in the contexts", tr2["trace"]["reranked"] and any(c["rerank_score"] is not None for c in tr2["trace"]["candidates"]) and "vyomiRerankScore" in tr2["contexts"]["contexts"][0], tr2["trace"])
thr = {**body, "query": {**body["query"], "ragRetrievalConfig": {"topK": 5, "filter": {"vectorSimilarityThreshold": 0.9}}}}
s, tr3 = call("POST", S + "/retrieve-trace", thr)
ck("threshold drops are explained", any(c["filtered_out_reason"] == "below vectorSimilarityThreshold" for c in tr3["trace"]["candidates"]) and tr3["trace"]["searchType"] == "SEMANTIC", tr3["trace"]["candidates"][:3])
fl = {**body, "vertexRagStore": {"ragResources": [{"ragCorpus": cn, "ragFileIds": [fids["lifts.txt"]]}]}}
s, tr4 = call("POST", S + "/retrieve-trace", fl)
ck("ragFileIds filter: other files excluded with a reason", all(c["fileId"] == fids["lifts.txt"] for c in tr4["contexts"]["contexts"] and [c for c in tr4["trace"]["candidates"] if c["returned"]]) and any(c["filtered_out_reason"] == "excluded by ragFileIds filter" for c in tr4["trace"]["candidates"]), tr4["trace"]["candidates"][:2])
s, e = call("POST", S + "/retrieve-trace", {"query": {"text": ""}})
ck("empty query 400", s == 400, e)

# generateContent with the Vertex RAG retrieval tool -> groundingMetadata
gen = {"contents": [{"role": "user", "parts": [{"text": "When is the boiler inspected?"}]}],
       "tools": [{"retrieval": {"vertexRagStore": {"ragResources": [{"ragCorpus": cn}], "ragRetrievalConfig": {"topK": 2}}}}]}
s, g = call("POST", P + "/publishers/google/models/gemini-2.0-flash:generateContent", gen)
gm = (g.get("candidates") or [{}])[0].get("groundingMetadata") if s == 200 else None
ck("generateContent + vertexRagStore returns groundingMetadata", bool(gm) and gm.get("groundingChunks") and gm.get("groundingSupports") is not None, g)
ck("grounding chunk cites the RAG file", gm and "boiler" in json.dumps(gm["groundingChunks"]).lower(), gm)
print("FAILS", len(fails))
sys.exit(1 if fails else 0)
