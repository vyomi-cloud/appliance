# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Amazon Bedrock Agents + Knowledge Bases + AgentCore (control plane, gateway MCP) — substrate-independent, Pyodide-loadable.

Built on the shared local-LLM seam (core/llm_core: chat + embed). No fastapi/boto3. State lives in the S3 ObjectStore's
persisted account bag: ``store.account["bedrock_agents"]``.

bedrock-agent (control, signing name ``bedrock``): CreateAgent/GetAgent/ListAgents/UpdateAgent/PrepareAgent/DeleteAgent,
agent aliases, AssociateAgentKnowledgeBase / ListAgentKnowledgeBases, action groups (stored), CreateKnowledgeBase /
GetKnowledgeBase / ListKnowledgeBases / DeleteKnowledgeBase, data sources (S3), ingestion jobs.
bedrock-agent-runtime (``bedrock``): Retrieve, RetrieveAndGenerate, InvokeAgent (vnd.amazon.eventstream chunks).
AgentCore (``bedrock-agentcore``): control plane runtimes (CreateAgentRuntime...), gateways and gateway targets, plus the
gateway's MCP endpoint (initialize / tools/list / tools/call -> Lambda targets are really invoked).

Real behaviour: ingestion reads the S3 objects of the data source, chunks them (fixed size / none), embeds every chunk with
``llm_core.embed`` and keeps the index in the account bag; Retrieve is exact cosine kNN with the S3 location + score; the
agent/RetrieveAndGenerate answer is the local model prompted with the retrieved passages and returns citations.

Honest limits: the model is a small local one (see llm_core.HONEST_LIMIT). Agent action groups are stored but the model does
not emit tool calls, so they are never invoked; only text (.txt/.md/.csv/.json/.html/.xml/.log) documents are ingested - other
types (PDF/Office) are counted as failed; vector storage is always the in-account index regardless of the storage type named;
AgentCore runtimes: InvokeAgentRuntime runs a Vyomi agent spec (core/agent_spec_core: JSON instructions + declarative tools in-process over
llm_core, Dev Simplified) carried in environmentVariables.VYOMI_AGENT_SPEC - container images are never run (without a spec the invoke
returns RuntimeClientError); runtime endpoints/versions/sessions are modelled; gateway targets of type openApiSchema/smithyModel/mcpServer are registered but their tools are not callable.
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import string
import time
import urllib.parse
from datetime import datetime, timezone

try:
    from core import llm_core as llm
    from core import knowledge_core as kc
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore
    import knowledge_core as kc  # type: ignore

_ACCT = "123456789012"
_REGION = "us-east-1"
_ALNUM = string.ascii_uppercase + string.digits
_TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml", ".log", ".tsv", ".yaml", ".yml", ".rst")
_STORAGE_TYPES = ("OPENSEARCH_SERVERLESS", "PINECONE", "REDIS_ENTERPRISE_CLOUD", "RDS", "MONGO_DB_ATLAS", "OPENSEARCH_MANAGED_CLUSTER",
                  "NEPTUNE_ANALYTICS", "S3_VECTORS")
_EMBED_MODELS = ("vyomi.nomic-embed-text",)      # + hidden aliases (amazon.titan-embed*, cohere.embed*) via ai_models_core._resolve_model
_GATEWAY_AUTH = ("CUSTOM_JWT", "AWS_IAM", "NONE")


class _Err(Exception):
    def __init__(self, code, message, status):
        self.code, self.message, self.status = code, message, status


def _bad(m):
    return _Err("ValidationException", m, 400)


def _nf(m):
    return _Err("ResourceNotFoundException", m, 404)


def _conflict(m):
    return _Err("ConflictException", m, 409)


def _j(status, doc, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    return {"status": status, "headers": h, "body": json.dumps(doc).encode() if doc is not None else b""}


def _err_resp(e):
    return {"status": e.status, "headers": {"content-type": "application/json", "x-amzn-errortype": e.code},
            "body": json.dumps({"message": e.message}).encode()}


def _iso(ts=None):
    return datetime.fromtimestamp(ts if ts is not None else time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _rid(n=10, alphabet=_ALNUM):
    return "".join(random.choice(alphabet) for _ in range(n))


def _state(store) -> dict:
    st = store.account.setdefault("bedrock_agents", {})
    for k in ("agents", "kbs", "runtimes", "gateways"):
        st.setdefault(k, {})
    return st


def _body(raw):
    if not raw:
        return {}
    try:
        p = json.loads(raw)
    except ValueError:
        raise _bad("Malformed request body")
    if not isinstance(p, dict):
        raise _bad("Malformed request body")
    return p


def _s3c():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m  # type: ignore
    return m


# ═══════════════════════════ knowledge bases ═══════════════════════════
_KB_NAME = re.compile(r"^([0-9a-zA-Z][_-]?){1,100}$")


def _kb_view(kb):
    return {k: v for k, v in kb.items() if k not in ("datasources", "chunks")}


def _find_kb(st, kid):
    kb = st["kbs"].get(kid)
    if not kb:
        raise _nf(f"Knowledge base with id {kid} does not exist")
    return kb


def _create_kb(st, p):
    name = p.get("name")
    if not name or not _KB_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: ^([0-9a-zA-Z][_-]?){1,100}$")
    if not p.get("roleArn"):
        raise _bad("1 validation error detected: Value null at 'roleArn' failed to satisfy constraint: Member must not be null")
    cfg = p.get("knowledgeBaseConfiguration") or {}
    if cfg.get("type") != "VECTOR":
        raise _bad("knowledgeBaseConfiguration.type must be VECTOR")
    emb = ((cfg.get("vectorKnowledgeBaseConfiguration") or {}).get("embeddingModelArn") or "")
    fmm = _resolve_fm(emb.rsplit("/", 1)[-1]) if emb else None
    try:
        from core import ai_model_catalog as _cat
    except ImportError:
        import ai_model_catalog as _cat  # type: ignore
    if not fmm or fmm[6] != _cat.DEFAULT_EMBED:       # nomic-embed-text on the appliance; all-minilm-l6-v2 (in-browser ONNX) on Nano
        raise _bad(f"The knowledge base embedding model {emb or '(none)'} is not supported; use vyomi.{_cat.DEFAULT_EMBED}")
    sto = p.get("storageConfiguration") or {}
    if sto.get("type") not in _STORAGE_TYPES:
        raise _bad(f"storageConfiguration.type must be one of {', '.join(_STORAGE_TYPES)}")
    if any(k["name"] == name for k in st["kbs"].values()):
        raise _conflict(f"Knowledge base with name {name} already exists")
    kid = _rid()
    now = _iso()
    kb = {"knowledgeBaseId": kid, "name": name, "knowledgeBaseArn": f"arn:aws:bedrock:{_REGION}:{_ACCT}:knowledge-base/{kid}",
          "description": p.get("description", ""), "roleArn": p["roleArn"], "knowledgeBaseConfiguration": cfg,
          "storageConfiguration": sto, "status": "ACTIVE", "createdAt": now, "updatedAt": now, "datasources": {}, "chunks": []}
    st["kbs"][kid] = kb
    return _j(202, {"knowledgeBase": _kb_view(kb)})


def _ds_view(ds):
    return {k: v for k, v in ds.items() if k != "jobs"}


def _create_ds(st, kb, p):
    name = p.get("name")
    if not name or not _KB_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: ^([0-9a-zA-Z][_-]?){1,100}$")
    conf = p.get("dataSourceConfiguration") or {}
    if conf.get("type") != "S3":
        raise _bad("dataSourceConfiguration.type must be S3 (the simulator ingests S3 data sources only)")
    s3c = conf.get("s3Configuration") or {}
    mt = re.match(r"^arn:aws[-a-z]*:s3:::([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])$", s3c.get("bucketArn") or "")
    if not mt:
        raise _bad("dataSourceConfiguration.s3Configuration.bucketArn must be a bucket ARN (arn:aws:s3:::bucket)")
    if any(d["name"] == name for d in kb["datasources"].values()):
        raise _conflict(f"Data source with name {name} already exists")
    did = _rid()
    now = _iso()
    ds = {"knowledgeBaseId": kb["knowledgeBaseId"], "dataSourceId": did, "name": name, "description": p.get("description", ""),
          "status": "AVAILABLE", "dataSourceConfiguration": conf, "dataDeletionPolicy": p.get("dataDeletionPolicy", "DELETE"),
          "vectorIngestionConfiguration": p.get("vectorIngestionConfiguration") or {}, "createdAt": now, "updatedAt": now, "jobs": {}}
    kb["datasources"][did] = ds
    return _j(202, {"dataSource": _ds_view(ds)})


def _chunk_cfg(ds):
    """-> (max_tokens|None, overlap_pct, strategy) from the standard chunkingConfiguration."""
    c = (ds.get("vectorIngestionConfiguration") or {}).get("chunkingConfiguration") or {}
    strat = c.get("chunkingStrategy", "FIXED_SIZE")
    if strat == "NONE":
        return None, 0, "NONE"
    if strat == "HIERARCHICAL":
        lv = (c.get("hierarchicalChunkingConfiguration") or {}).get("levelConfigurations") or [{"maxTokens": 300}]
        mx = int(lv[-1].get("maxTokens", 300))
        ov = int((c.get("hierarchicalChunkingConfiguration") or {}).get("overlapTokens", 60))
        return mx, min(90, int(100 * ov / max(mx, 1))), strat
    if strat == "SEMANTIC":
        return int((c.get("semanticChunkingConfiguration") or {}).get("maxTokens", 300)), 0, strat
    f = c.get("fixedSizeChunkingConfiguration") or {}
    return int(f.get("maxTokens", 300)), int(f.get("overlapPercentage", 20)), "FIXED_SIZE"


def _chunk_text(text, max_tokens, overlap_pct):
    words = text.split()
    if max_tokens is None or not words:
        return [text.strip()] if text.strip() else []
    step = max(1, max_tokens - int(max_tokens * overlap_pct / 100))
    out = []
    i = 0
    while i < len(words):
        out.append(" ".join(words[i:i + max_tokens]))
        if i + max_tokens >= len(words):
            break
        i += step
    return out


def _list_keys(s3, bucket, prefix):
    s3c = _s3c()
    keys, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        r = s3c.list_objects_v2(s3, bucket, q)
        if r.status != 200:
            raise _bad(f"Unable to list the data source bucket {bucket}")
        xml = r.body.decode()
        for blk in re.findall(r"<Contents>(.*?)</Contents>", xml, re.S):
            k = re.search(r"<Key>(.*?)</Key>", blk).group(1)
            keys.append(k.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
        nt = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", xml)
        if "<IsTruncated>true</IsTruncated>" in xml and nt:
            token = nt.group(1)
        else:
            return keys


def _pipeline_cfg(s3c, s3, bucket):
    """Optional Vyomi sidecar `.vyomi-pipeline.json` in the bucket root: {"guardrailIdentifier","guardrailVersion"} -> PII/guardrail scan per document."""
    r = s3c.get_object(s3, bucket, ".vyomi-pipeline.json", {}, {})
    try:
        return json.loads(r.body) if r.status == 200 else {}
    except ValueError:
        return {}


def _ingest(s3, kb, ds):
    conf = ds["dataSourceConfiguration"]["s3Configuration"]
    bucket = conf["bucketArn"].rsplit(":", 1)[-1]
    prefixes = conf.get("inclusionPrefixes") or [""]
    mx, ov, strat = _chunk_cfg(ds)
    s3c = _s3c()
    pipe = _pipeline_cfg(s3c, s3, bucket)
    gid, gver = pipe.get("guardrailIdentifier"), str(pipe.get("guardrailVersion", "DRAFT"))
    kb["chunks"] = [c for c in kb["chunks"] if c["ds"] != ds["dataSourceId"]]       # a re-sync replaces this data source's chunks
    scanned = failed = indexed = 0
    reasons, texts, metas = [], [], []
    seen = set()
    redacted = 0
    for pfx in prefixes:
        for key in _list_keys(s3, bucket, pfx):
            if key in seen or key.endswith("/") or key.endswith(".metadata.json") or key == ".vyomi-pipeline.json":
                continue
            seen.add(key)
            scanned += 1
            r = s3c.get_object(s3, bucket, key, {}, {})
            if r.status != 200:
                failed += 1
                reasons.append(f"s3://{bucket}/{key}: could not read object")
                continue
            try:
                txt = kc.parse_document(key, r.body)
            except kc.ParseError as e:
                failed += 1
                reasons.append(f"s3://{bucket}/{key}: {e}")
                continue
            txt, verdict = kc.guard(txt, gid, gver)
            if verdict == "blocked":
                failed += 1
                reasons.append(f"s3://{bucket}/{key}: blocked by guardrail {gid} (PII/sensitive content scan)")
                continue
            redacted += verdict == "redacted"
            meta = {}
            mr = s3c.get_object(s3, bucket, key + ".metadata.json", {}, {})
            if mr.status == 200:
                try:
                    meta = (json.loads(mr.body) or {}).get("metadataAttributes") or {}
                except ValueError:
                    meta = {}
            for ch, head in kc.split_text(txt, mx, ov, strat):
                texts.append(ch)
                metas.append((f"s3://{bucket}/{key}", meta, head, verdict))
            indexed += 1
    if texts:
        vecs = llm.embed(texts)["vectors"]
        for n, (t, (uri, meta, head, verdict), v) in enumerate(zip(texts, metas, vecs)):
            kb["chunks"].append({"id": f"{ds['dataSourceId']}-{n}", "ds": ds["dataSourceId"], "uri": uri, "text": t, "vec": v, "metadata": meta,
                                 "section": head, "tokens": len(t.split()), "pii": verdict})
    _mirror_opensearch(s3, kb, ds)
    return {"numberOfDocumentsScanned": scanned, "numberOfNewDocumentsIndexed": indexed, "numberOfModifiedDocumentsIndexed": 0,
            "numberOfMetadataDocumentsScanned": 0, "numberOfMetadataDocumentsModified": 0, "numberOfDocumentsDeleted": 0,
            "numberOfDocumentsFailed": failed}, reasons


def _mirror_opensearch(s3, kb, ds):
    """When the KB names an OpenSearch (Serverless/managed) index, also write the chunks there with the configured fieldMapping
    so opensearch-py _search on that index sees the same data (what a real KB does)."""
    sto = kb.get("storageConfiguration") or {}
    cfg = sto.get("opensearchServerlessConfiguration") or sto.get("opensearchManagedClusterConfiguration") or {}
    index = cfg.get("vectorIndexName")
    if not index:
        return
    fm = cfg.get("fieldMapping") or {}
    vf, tf, mf = fm.get("vectorField", "vector"), fm.get("textField", "text"), fm.get("metadataField", "metadata")
    try:
        from core import opensearch_core as osc
    except ImportError:
        import opensearch_core as osc  # type: ignore
    osc.drop_docs(s3, index, ds["dataSourceId"] + "-")
    dim = len(kb["chunks"][0]["vec"]) if kb["chunks"] else 0
    osc.index_docs(s3, index, [(c["id"], {vf: c["vec"], tf: c["text"], mf: {**c["metadata"], "source": c["uri"], "section": c.get("section", "")}})
                               for c in kb["chunks"] if c["ds"] == ds["dataSourceId"]],
                   {"properties": {vf: {"type": "knn_vector", "dimension": dim}, tf: {"type": "text"}, mf: {"type": "object"}}})


def _start_ingestion(s3, kb, ds, p):
    if s3 is None:
        raise _bad("S3 store unavailable")
    jid = _rid()
    now = _iso()
    stats, reasons = _ingest(s3, kb, ds)
    job = {"knowledgeBaseId": kb["knowledgeBaseId"], "dataSourceId": ds["dataSourceId"], "ingestionJobId": jid, "status": "COMPLETE",
           "description": p.get("description", ""), "statistics": stats, "startedAt": now, "updatedAt": _iso()}
    if reasons:
        job["failureReasons"] = reasons[:50]
    ds["jobs"][jid] = job
    return _j(202, {"ingestionJob": job})


def _paginate(items, query, key, size_default=100):
    n = int((query or {}).get("maxResults") or size_default)
    start = int((query or {}).get("nextToken") or 0)
    page = items[start:start + n]
    out = {key: page}
    if start + n < len(items):
        out["nextToken"] = str(start + n)
    return out


def _retrieve_trace(kb, text, k, flt=None, vs=None, hybrid_weight=None):
    """Retrieve with a per-candidate trace. ``vs`` = vectorSearchConfiguration (overrideSearchType, rerankingConfiguration).
    -> (results, trace) ; hybrid_weight (Vyomi extension) 0 = vector only, otherwise lexical+vector RRF."""
    import time as _t
    vs = vs or {}
    chunks = kb["chunks"]
    stages = {}
    if not chunks:
        return [], {"candidates": [], "latencyMs": {}}
    t0 = _t.time()
    qv = llm.embed(text)["vectors"][0]
    if any(len(c["vec"]) != len(qv) for c in chunks):   # index built by another embedder (e.g. hash fallback before the in-browser model loaded)
        for c, v in zip(chunks, llm.embed([c["text"] for c in chunks])["vectors"]):
            c["vec"] = v
        if any(len(c["vec"]) != len(qv) for c in chunks):
            qv = llm.embed(text, dimensions=len(chunks[0]["vec"]))["vectors"][0]
    stages["embed"] = (_t.time() - t0) * 1000
    t0 = _t.time()
    allowed, why = set(), {}
    for i, c in enumerate(chunks):
        if flt and not _match_filter(flt, c["metadata"]):
            why[i] = "metadata filter"
        else:
            allowed.add(i)
    stages["filter"] = (_t.time() - t0) * 1000
    mode = (vs.get("overrideSearchType") or "HYBRID").upper()
    lw = hybrid_weight if hybrid_weight is not None else (0.0 if mode == "SEMANTIC" else 0.5)
    t0 = _t.time()
    texts = [c["text"] for c in chunks]
    vsc = {i: llm.cosine(qv, c["vec"]) for i, c in enumerate(chunks)}
    lex_all = kc.bm25([texts[i] for i in sorted(allowed)], text) if lw else {}
    order = sorted(allowed)
    lex = {order[j]: sc for j, sc in lex_all.items()}
    stages["search"] = (_t.time() - t0) * 1000
    fused = kc.hybrid(texts, [c["vec"] for c in chunks], text, qv, allowed, max(len(chunks), 1), weight_lex=lw)
    rank = {i: (n + 1, sc) for n, (i, sc) in enumerate(fused)}
    rr = (vs.get("rerankingConfiguration") or {}).get("bedrockRerankingConfiguration") or {}
    top = fused[:max(k * 3, k)] if rr or vs.get("rerankingConfiguration") else fused[:k]
    rrs = {}
    t0 = _t.time()
    if vs.get("rerankingConfiguration"):
        n_out = int(rr.get("numberOfRerankedResults", k))
        for n, (j, sc) in enumerate(kc.rerank(text, [texts[i] for i, _ in top], n_out)):
            rrs[top[j][0]] = (n + 1, sc)
        final = [(i, rrs[i][1]) for i in sorted(rrs, key=lambda x: rrs[x][0])][:k]
        stages["rerank"] = (_t.time() - t0) * 1000
    else:
        final = top[:k]
    res = []
    for i, sc in final:
        c = chunks[i]
        r = {"content": {"type": "TEXT", "text": c["text"]}, "location": {"type": "S3", "s3Location": {"uri": c["uri"]}}, "score": round(max(min(sc, 1.0), 0.0), 6),
             "metadata": {**c["metadata"], "x-amz-bedrock-kb-source-uri": c["uri"], "x-amz-bedrock-kb-chunk-id": c.get("id", ""),
                          "x-amz-bedrock-kb-data-source-id": c["ds"]}}
        if c.get("section"):
            r["metadata"]["section"] = c["section"]
        res.append(r)
    cand = []
    for i, c in enumerate(chunks):
        cand.append({"chunkId": c.get("id", str(i)), "uri": c["uri"], "vector_score": round(vsc[i], 6), "bm25_score": round(lex.get(i, 0.0), 6),
                     "fused_rank": rank[i][0] if i in rank else None, "fused_score": round(rank[i][1], 6) if i in rank else None,
                     "rerank_score": rrs[i][1] if i in rrs else None, "rerank_rank": rrs[i][0] if i in rrs else None,
                     "returned": any(f[0] == i for f in final),
                     "filtered_out_reason": why.get(i) or (None if i in rank and any(f[0] == i for f in final) else
                                                           ("below top-k after fusion" if i in rank else "not ranked"))})
    return res, {"candidates": cand, "searchType": mode, "hybridWeight": lw, "reranked": bool(vs.get("rerankingConfiguration")),
                 "latencyMs": {k_: round(v, 3) for k_, v in stages.items()}}


def _retrieve(kb, text, k, flt=None, vs=None):
    return _retrieve_trace(kb, text, k, flt, vs)[0]


def _rerank_op(p):
    """bedrock-agent-runtime Rerank: queries[0].textQuery.text, sources[].inlineDocumentSource.textDocument.text."""
    qs = p.get("queries") or []
    srcs = p.get("sources") or []
    if not qs or not srcs:
        raise _bad("queries and sources are required")
    q = (qs[0].get("textQuery") or {}).get("text", "")
    docs = [((s.get("inlineDocumentSource") or {}).get("textDocument") or {}).get("text", "") for s in srcs]
    n = int(((p.get("rerankingConfiguration") or {}).get("bedrockRerankingConfiguration") or {}).get("numberOfResults", len(docs)))
    out = [{"index": i, "relevanceScore": sc} for i, sc in kc.rerank(q, docs, n)]
    return _j(200, {"results": out})


def inspect_dispatch(s3, method, path, query, body):
    """Vyomi extension (outside the AWS namespace) for the RAG Studio: GET /_vyomi/kb/{id}/chunks, POST /_vyomi/kb/{id}/retrieve-trace."""
    st = _state(s3)
    segs = [x for x in path.strip("/").split("/") if x]
    try:
        kb = _find_kb(st, segs[2]) if len(segs) >= 4 else None
        if kb is None:
            raise _nf("Unknown inspect route")
        if segs[3] == "chunks" and method == "GET":
            want_vec = (query or {}).get("vectors", "false") == "true"
            rows = [{"id": c.get("id"), "dataSourceId": c["ds"], "documentUri": c["uri"], "text": c["text"], "tokenCount": c.get("tokens", len(c["text"].split())),
                     "metadata": c["metadata"], "section": c.get("section", ""), "pii": c.get("pii", "ok"), "projection2d": None, "vector": c["vec"] if want_vec else None}
                    for c in kb["chunks"]]
            _project2d(rows, [c["vec"] for c in kb["chunks"]])
            return _j(200, {"knowledgeBaseId": kb["knowledgeBaseId"], "count": len(rows), "dimensions": len(kb["chunks"][0]["vec"]) if kb["chunks"] else 0, "chunks": rows})
        if segs[3] == "retrieve-trace" and method == "POST":
            p = _body(body)
            q = ((p.get("retrievalQuery") or {}).get("text") or "").strip()
            if not q:
                raise _bad("retrievalQuery.text is required")
            vs = (p.get("retrievalConfiguration") or {}).get("vectorSearchConfiguration") or {}
            res, trace = _retrieve_trace(kb, q, int(vs.get("numberOfResults", 5)), vs.get("filter"), vs, p.get("hybridWeight"))
            return _j(200, {"retrievalResults": res, "trace": trace})
    except _Err as e:
        return _err_resp(e)
    return _err_resp(_Err("UnknownOperationException", f"Unsupported inspect route: {method} {path}", 404))


def _project2d(rows, vecs):
    """2-D PCA projection (power iteration, pure Python) so the Studio can plot clusters without numpy."""
    n = len(vecs)
    if n < 2:
        for r in rows:
            r["projection2d"] = [0.0, 0.0]
        return
    d = len(vecs[0])
    mean = [sum(v[j] for v in vecs) / n for j in range(d)]
    X = [[v[j] - mean[j] for j in range(d)] for v in vecs]
    comps = []
    for c in range(2):
        w = [((j * 7919 + c * 104729) % 1000) / 1000.0 - 0.5 for j in range(d)]
        for _ in range(25):
            t = [sum(x[j] * w[j] for j in range(d)) for x in X]
            nw = [sum(X[i][j] * t[i] for i in range(n)) for j in range(d)]
            norm = sum(a * a for a in nw) ** 0.5 or 1.0
            w = [a / norm for a in nw]
        comps.append(w)
        X = [[x[j] - sum(x[m] * w[m] for m in range(d)) * w[j] for j in range(d)] for x in X]
    for i, r in enumerate(rows):
        c = [v - m for v, m in zip(vecs[i], mean)]
        r["projection2d"] = [round(sum(c[j] * comps[k][j] for j in range(d)), 6) for k in range(2)]


def _match_filter(f, meta):
    if "andAll" in f:
        return all(_match_filter(x, meta) for x in f["andAll"])
    if "orAll" in f:
        return any(_match_filter(x, meta) for x in f["orAll"])
    for op in ("equals", "notEquals", "greaterThan", "greaterThanOrEquals", "lessThan", "lessThanOrEquals", "in", "notIn",
               "startsWith", "stringContains", "listContains"):
        if op in f:
            key, val = f[op].get("key"), f[op].get("value")
            have = meta.get(key)
            try:
                if op == "equals":
                    return have == val
                if op == "notEquals":
                    return have != val
                if op == "greaterThan":
                    return have is not None and have > val
                if op == "greaterThanOrEquals":
                    return have is not None and have >= val
                if op == "lessThan":
                    return have is not None and have < val
                if op == "lessThanOrEquals":
                    return have is not None and have <= val
                if op == "in":
                    return have in (val or [])
                if op == "notIn":
                    return have not in (val or [])
                if op == "startsWith":
                    return isinstance(have, str) and have.startswith(val)
                if op == "stringContains":
                    return isinstance(have, str) and val in have or isinstance(have, list) and val in have
                if op == "listContains":
                    return isinstance(have, list) and val in have
            except TypeError:
                return False
    raise _bad("Unsupported retrieval filter")


def _rag_answer(st, results, question, model_hint=None):
    ctx = "\n\n".join(f"[{i + 1}] {r['content']['text']}" for i, r in enumerate(results))
    sysm = ("Answer the user's question using ONLY the numbered search results. If they do not contain the answer, say you "
            "could not find it. Cite results like [1].")
    r = llm.chat([{"role": "user", "content": f"Search results:\n{ctx}\n\nQuestion: {question}"}], system=sysm, max_tokens=300, temperature=0.2)
    return r["text"]


def _retrieve_op(st, kid, p):
    kb = _find_kb(st, kid)
    q = ((p.get("retrievalQuery") or {}).get("text") or "").strip()
    if not q:
        raise _bad("retrievalQuery.text is required")
    vs = (p.get("retrievalConfiguration") or {}).get("vectorSearchConfiguration") or {}
    k = int(vs.get("numberOfResults", 5))
    if not 1 <= k <= 100:
        raise _bad("numberOfResults must be between 1 and 100")
    return _j(200, {"retrievalResults": _retrieve(kb, q, k, vs.get("filter"), vs)})


def _rag_op(st, p):
    q = ((p.get("input") or {}).get("text") or "").strip()
    if not q:
        raise _bad("input.text is required")
    cfg = p.get("retrieveAndGenerateConfiguration") or {}
    if cfg.get("type") != "KNOWLEDGE_BASE":
        raise _bad("retrieveAndGenerateConfiguration.type must be KNOWLEDGE_BASE")
    kc = cfg.get("knowledgeBaseConfiguration") or {}
    kb = _find_kb(st, kc.get("knowledgeBaseId") or "")
    if not kc.get("modelArn"):
        raise _bad("knowledgeBaseConfiguration.modelArn is required")
    vs = (kc.get("retrievalConfiguration") or {}).get("vectorSearchConfiguration") or {}
    res = _retrieve(kb, q, int(vs.get("numberOfResults", 5)), vs.get("filter"), vs)
    sid = p.get("sessionId") or _rid(32, string.ascii_lowercase + string.digits)
    if not res:
        return _j(200, {"sessionId": sid, "output": {"text": "Sorry, I am unable to assist you with this request."}, "citations": []})
    try:
        text = _rag_answer(st, res, q)
    except llm.LlmUnavailable as e:
        return {"status": 424, "headers": {"content-type": "application/json", "x-amzn-errortype": "DependencyFailedException"},
                "body": json.dumps({"message": f"{e} (the local model has not been started)"}).encode()}
    return _j(200, {"sessionId": sid, "output": {"text": text},
                    "citations": [{"generatedResponsePart": {"textResponsePart": {"text": text, "span": {"start": 0, "end": len(text)}}},
                                   "retrievedReferences": [{k: v for k, v in r.items() if k != "score"} for r in res[:3]]}]})


# ═══════════════════════════ agents ═══════════════════════════
def _resolve_fm(arn_or_id):
    try:
        from core import ai_models_core as am
    except ImportError:
        import ai_models_core as am  # type: ignore
    return am._resolve_model(arn_or_id or "")


def _agent_view(a):
    return {k: v for k, v in a.items() if k not in ("aliases", "kbs", "actionGroups")}


def _find_agent(st, aid):
    a = st["agents"].get(aid)
    if not a:
        raise _nf(f"Could not find resource: Agent {aid}")
    return a


def _create_agent(st, p):
    name = p.get("agentName")
    if not name or not _KB_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'agentName' failed to satisfy constraint: Member must satisfy regular expression pattern: ^([0-9a-zA-Z][_-]?){1,100}$")
    fm = p.get("foundationModel")
    if fm and not _resolve_fm(fm):
        raise _bad(f"The provided foundation model {fm} is invalid or unsupported")
    if not p.get("agentResourceRoleArn"):
        raise _bad("1 validation error detected: Value null at 'agentResourceRoleArn' failed to satisfy constraint: Member must not be null")
    if p.get("instruction") is not None and not 40 <= len(p["instruction"]) <= 20000:
        raise _bad("1 validation error detected: Value at 'instruction' failed to satisfy constraint: Member must have length greater than or equal to 40")
    ttl = int(p.get("idleSessionTTLInSeconds", 600))
    if not 60 <= ttl <= 3600:
        raise _bad("idleSessionTTLInSeconds must be between 60 and 3600")
    if any(a["agentName"] == name for a in st["agents"].values()):
        raise _conflict(f"Agent with name {name} already exists")
    aid = _rid()
    now = _iso()
    a = {"agentId": aid, "agentName": name, "agentArn": f"arn:aws:bedrock:{_REGION}:{_ACCT}:agent/{aid}", "agentVersion": "DRAFT",
         "agentStatus": "NOT_PREPARED", "foundationModel": fm or "", "instruction": p.get("instruction", ""), "description": p.get("description", ""),
         "idleSessionTTLInSeconds": ttl, "agentResourceRoleArn": p["agentResourceRoleArn"], "createdAt": now, "updatedAt": now,
         "aliases": {}, "kbs": {}, "actionGroups": {}, "_version": 0}
    st["agents"][aid] = a
    return _j(202, {"agent": _agent_view(a)})


def _prepare(a):
    if not a["foundationModel"] or not a["instruction"]:
        raise _bad("The agent must have a foundationModel and an instruction before it can be prepared")
    a["agentStatus"] = "PREPARED"
    a["preparedAt"] = _iso()
    a["updatedAt"] = a["preparedAt"]
    return _j(202, {"agentId": a["agentId"], "agentStatus": "PREPARING", "agentVersion": "DRAFT", "preparedAt": a["preparedAt"]})


def _create_alias(a, p):
    name = p.get("agentAliasName")
    if not name or not _KB_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'agentAliasName' failed to satisfy constraint: Member must satisfy regular expression pattern: ^([0-9a-zA-Z][_-]?){1,100}$")
    if a["agentStatus"] != "PREPARED":
        raise _conflict("Create operation can't be performed on Agent when it is not in PREPARED state")
    if any(x["agentAliasName"] == name for x in a["aliases"].values()):
        raise _conflict(f"Agent alias with name {name} already exists")
    rc = p.get("routingConfiguration")
    if rc:
        ver = str(rc[0].get("agentVersion", ""))
        if not ver.isdigit() or not 1 <= int(ver) <= a["_version"]:
            raise _bad(f"agentVersion {ver} does not exist")
    else:
        a["_version"] += 1
        ver = str(a["_version"])
        a.setdefault("snapshots", {})[ver] = {"instruction": a["instruction"], "foundationModel": a["foundationModel"],
                                              "kbs": [dict(k) for k in a["kbs"].values()]}
        rc = [{"agentVersion": ver}]
    alid = _rid()
    now = _iso()
    al = {"agentId": a["agentId"], "agentAliasId": alid, "agentAliasName": name,
          "agentAliasArn": f"arn:aws:bedrock:{_REGION}:{_ACCT}:agent-alias/{a['agentId']}/{alid}", "description": p.get("description", ""),
          "routingConfiguration": rc, "agentAliasStatus": "PREPARED", "createdAt": now, "updatedAt": now}
    a["aliases"][alid] = al
    return _j(202, {"agentAlias": al})


def _invoke_agent(st, s3, aid, alias_id, sid, p):
    a = _find_agent(st, aid)
    text = (p.get("inputText") or "").strip()
    if not text:
        raise _bad("inputText is required")
    if alias_id == "TSTALIASID":     # the built-in test alias runs the DRAFT version
        snap = {"instruction": a["instruction"], "foundationModel": a["foundationModel"], "kbs": list(a["kbs"].values())}
        if a["agentStatus"] != "PREPARED":
            raise _conflict("The agent is not in PREPARED state; call PrepareAgent first")
    else:
        al = a["aliases"].get(alias_id)
        if not al:
            raise _nf(f"Could not find resource: Alias {alias_id} of agent {aid}")
        snap = (a.get("snapshots") or {}).get(str(al["routingConfiguration"][0]["agentVersion"]))
        if not snap:
            raise _nf("Agent version not found")
    refs, ctx = [], ""
    for k in snap["kbs"]:
        if k.get("knowledgeBaseState", "ENABLED") != "ENABLED" or k["knowledgeBaseId"] not in st["kbs"]:
            continue
        res = _retrieve(st["kbs"][k["knowledgeBaseId"]], text, 3)
        refs += res
        ctx += "\n".join(r["content"]["text"] for r in res) + "\n"
    sysm = snap["instruction"]
    if ctx.strip():
        sysm += "\n\nUse these knowledge base passages when relevant:\n" + ctx
    hist = (a.setdefault("sessions", {}).setdefault(sid, []))
    msgs = hist + [{"role": "user", "content": text}]
    try:
        r = llm.chat(msgs, system=sysm, max_tokens=400, temperature=0.4)
    except llm.LlmUnavailable as e:
        return {"status": 424, "headers": {"content-type": "application/json", "x-amzn-errortype": "DependencyFailedException"},
                "body": json.dumps({"message": f"{e} (the local model has not been started)"}).encode()}
    hist += [{"role": "user", "content": text}, {"role": "assistant", "content": r["text"]}]
    del hist[:-20]
    try:
        from core import ai_models_core as am
    except ImportError:
        import ai_models_core as am  # type: ignore
    part = {"bytes": base64.b64encode(r["text"].encode()).decode()}
    if refs:
        part["attribution"] = {"citations": [{"generatedResponsePart": {"textResponsePart": {"text": r["text"], "span": {"start": 0, "end": len(r["text"])}}},
                                              "retrievedReferences": [{k: v for k, v in x.items() if k != "score"} for x in refs[:3]]}]}
    body = am.eventstream_frame("chunk", part)
    return {"status": 200, "headers": {"content-type": "application/vnd.amazon.eventstream", "x-amz-bedrock-agent-session-id": sid,
                                        "x-amzn-bedrock-agent-content-type": "application/json"}, "body": body}


# ═══════════════════════════ dispatch: bedrock-agent / agent-runtime ═══════════════════════════
def handles(path: str) -> bool:
    p = path.lower()
    return bool(re.match(r"^/(agents|knowledgebases|retrieveandgenerate|rerank|_vyomi/kb)(/|$)", p))


def dispatch(s3, method, path, query, headers, body):
    method = method.upper()
    path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    segs = [urllib.parse.unquote(s) for s in path.strip("/").split("/")]
    low = [s.lower() for s in segs]
    try:
        st = _state(s3)
        p = _body(body) if method in ("PUT", "POST", "PATCH") else {}
        # ── runtime ──
        if low[0] == "_vyomi":
            return inspect_dispatch(s3, method, path, query, body)
        if low == ["rerank"] and method == "POST":
            return _rerank_op(p)
        if low == ["retrieveandgenerate"] and method == "POST":
            return _rag_op(st, p)
        if low[0] == "knowledgebases" and len(low) == 3 and low[2] == "retrieve" and method == "POST":
            return _retrieve_op(st, segs[1], p)
        if low[0] == "agents" and len(low) == 7 and low[2] == "agentaliases" and low[4] == "sessions" and low[6] == "text" and method == "POST":
            return _invoke_agent(st, s3, segs[1], segs[3], segs[5], p)
        # ── knowledge bases ──
        if low[0] == "knowledgebases":
            if len(low) == 1:
                if method == "PUT":
                    return _create_kb(st, p)
                if method == "POST":
                    return _j(200, _paginate([{"knowledgeBaseId": k["knowledgeBaseId"], "name": k["name"], "description": k["description"], "status": k["status"],
                                               "updatedAt": k["updatedAt"]} for k in st["kbs"].values()], query, "knowledgeBaseSummaries"))
            else:
                kb = _find_kb(st, segs[1])
                if len(low) == 2:
                    if method == "GET":
                        return _j(200, {"knowledgeBase": _kb_view(kb)})
                    if method == "PUT":
                        if p.get("name"):
                            kb["name"] = p["name"]
                        if "description" in p:
                            kb["description"] = p["description"]
                        kb["updatedAt"] = _iso()
                        return _j(202, {"knowledgeBase": _kb_view(kb)})
                    if method == "DELETE":
                        for a in st["agents"].values():
                            a["kbs"].pop(kb["knowledgeBaseId"], None)
                        del st["kbs"][kb["knowledgeBaseId"]]
                        return _j(202, {"knowledgeBaseId": kb["knowledgeBaseId"], "status": "DELETING"})
                elif low[2] == "datasources":
                    if len(low) == 3:
                        if method == "PUT":
                            return _create_ds(st, kb, p)
                        if method == "POST":
                            return _j(200, _paginate([{"knowledgeBaseId": kb["knowledgeBaseId"], "dataSourceId": d["dataSourceId"], "name": d["name"],
                                                       "status": d["status"], "updatedAt": d["updatedAt"]} for d in kb["datasources"].values()], query, "dataSourceSummaries"))
                    else:
                        ds = kb["datasources"].get(segs[3])
                        if not ds:
                            raise _nf(f"Data source with id {segs[3]} does not exist")
                        if len(low) == 4:
                            if method == "GET":
                                return _j(200, {"dataSource": _ds_view(ds)})
                            if method == "DELETE":
                                kb["chunks"] = [c for c in kb["chunks"] if c["ds"] != ds["dataSourceId"]]
                                del kb["datasources"][ds["dataSourceId"]]
                                return _j(202, {"knowledgeBaseId": kb["knowledgeBaseId"], "dataSourceId": ds["dataSourceId"], "status": "DELETING"})
                        elif low[4] == "ingestionjobs":
                            if len(low) == 5 and method == "PUT":
                                return _start_ingestion(s3, kb, ds, p)
                            if len(low) == 5 and method == "POST":
                                return _j(200, _paginate([{k: v for k, v in j.items() if k != "failureReasons"} for j in ds["jobs"].values()], query, "ingestionJobSummaries"))
                            if len(low) == 6 and method == "GET":
                                j = ds["jobs"].get(segs[5])
                                if not j:
                                    raise _nf(f"Ingestion job {segs[5]} does not exist")
                                return _j(200, {"ingestionJob": j})
        # ── agents ──
        elif low[0] == "agents":
            if len(low) == 1:
                if method == "PUT":
                    return _create_agent(st, p)
                if method == "GET":
                    return _j(200, _paginate([{"agentId": a["agentId"], "agentName": a["agentName"], "agentStatus": a["agentStatus"], "description": a["description"],
                                               "latestAgentVersion": "DRAFT", "updatedAt": a["updatedAt"]} for a in st["agents"].values()], query, "agentSummaries"))
            else:
                a = _find_agent(st, segs[1])
                if len(low) == 2:
                    if method == "GET":
                        return _j(200, {"agent": _agent_view(a)})
                    if method == "POST":
                        return _prepare(a)
                    if method == "PUT":
                        if not p.get("agentName") or not p.get("agentResourceRoleArn"):
                            raise _bad("agentName and agentResourceRoleArn are required")
                        if p.get("foundationModel") and not _resolve_fm(p["foundationModel"]):
                            raise _bad(f"The provided foundation model {p['foundationModel']} is invalid or unsupported")
                        a.update(agentName=p["agentName"], agentResourceRoleArn=p["agentResourceRoleArn"], updatedAt=_iso(), agentStatus="NOT_PREPARED")
                        for f in ("foundationModel", "instruction", "description", "idleSessionTTLInSeconds"):
                            if f in p:
                                a[f] = p[f]
                        return _j(202, {"agent": _agent_view(a)})
                    if method == "DELETE":
                        if a["aliases"] and (query or {}).get("skipResourceInUseCheck") != "true":
                            raise _conflict("Agent has aliases; delete them first or set skipResourceInUseCheck")
                        del st["agents"][a["agentId"]]
                        return _j(202, {"agentId": a["agentId"], "agentStatus": "DELETING"})
                elif low[2] == "agentaliases":
                    if len(low) == 3:
                        if method == "PUT":
                            return _create_alias(a, p)
                        if method == "POST":
                            return _j(200, _paginate([{k: v for k, v in al.items() if k in ("agentAliasId", "agentAliasName", "description", "routingConfiguration", "agentAliasStatus", "createdAt", "updatedAt")}
                                                      for al in a["aliases"].values()], query, "agentAliasSummaries"))
                    else:
                        al = a["aliases"].get(segs[3])
                        if not al:
                            raise _nf(f"Could not find resource: Alias {segs[3]}")
                        if len(low) == 4 and method == "GET":
                            return _j(200, {"agentAlias": al})
                        if len(low) == 4 and method == "DELETE":
                            del a["aliases"][segs[3]]
                            return _j(202, {"agentId": a["agentId"], "agentAliasId": segs[3], "agentAliasStatus": "DELETING"})
                elif low[2] == "agentversions" and len(low) >= 5 and low[3] == "draft":
                    if low[4] == "knowledgebases":
                        if len(low) == 5 and method == "PUT":
                            kid = p.get("knowledgeBaseId")
                            if kid not in st["kbs"]:
                                raise _nf(f"Knowledge base with id {kid} does not exist")
                            if not p.get("description"):
                                raise _bad("description is required")
                            now = _iso()
                            link = {"agentId": a["agentId"], "agentVersion": "DRAFT", "knowledgeBaseId": kid, "description": p["description"],
                                    "knowledgeBaseState": p.get("knowledgeBaseState", "ENABLED"), "createdAt": now, "updatedAt": now}
                            a["kbs"][kid] = link
                            a["agentStatus"] = "NOT_PREPARED"
                            return _j(200, {"agentKnowledgeBase": link})
                        if len(low) == 5 and method == "POST":
                            return _j(200, _paginate([{k: v for k, v in l.items() if k not in ("agentId", "agentVersion", "createdAt")} for l in a["kbs"].values()], query, "agentKnowledgeBaseSummaries"))
                        if len(low) == 6 and method == "DELETE":
                            if segs[5] not in a["kbs"]:
                                raise _nf("Knowledge base is not associated with the agent")
                            del a["kbs"][segs[5]]
                            a["agentStatus"] = "NOT_PREPARED"
                            return _j(204, None)
                    elif low[4] == "agentactiongroups":
                        if len(low) == 5 and method == "PUT":
                            nm = p.get("actionGroupName")
                            if not nm:
                                raise _bad("actionGroupName is required")
                            gid = _rid()
                            now = _iso()
                            g = {"agentId": a["agentId"], "agentVersion": "DRAFT", "actionGroupId": gid, "actionGroupName": nm, "description": p.get("description", ""),
                                 "actionGroupState": p.get("actionGroupState", "ENABLED"), "actionGroupExecutor": p.get("actionGroupExecutor"),
                                 "apiSchema": p.get("apiSchema"), "functionSchema": p.get("functionSchema"), "createdAt": now, "updatedAt": now}
                            a["actionGroups"][gid] = g
                            a["agentStatus"] = "NOT_PREPARED"
                            return _j(200, {"agentActionGroup": g})
                        if len(low) == 5 and method == "POST":
                            return _j(200, _paginate([{k: g[k] for k in ("actionGroupId", "actionGroupName", "actionGroupState", "description", "updatedAt")} for g in a["actionGroups"].values()], query, "actionGroupSummaries"))
    except _Err as e:
        return _err_resp(e)
    return _err_resp(_Err("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404))


# ═══════════════════════════ AgentCore ═══════════════════════════
_AC_NAME = re.compile(r"^([0-9a-zA-Z][-]?){1,100}$")
_RT_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$")
_LOWER = string.ascii_lowercase + string.digits


def _ac_ready(o):
    """Resources are CREATING for the first moments after Create, READY afterwards (real lifecycle is asynchronous)."""
    if o["status"] in ("CREATING", "UPDATING") and time.time() >= o["_readyAt"]:
        o["status"] = "READY"
        o["lastUpdatedAt"] = _iso()


def _pub(o):
    _ac_ready(o)
    return {k: v for k, v in o.items() if not k.startswith("_") and k != "targets"}


def _check_artifact(art):
    """agentRuntimeArtifact is a union: containerConfiguration (image) or codeConfiguration (zip in S3 + entryPoint)."""
    cc = art.get("codeConfiguration")
    if cc:
        s3 = (cc.get("code") or {}).get("s3") or {}
        if not s3.get("bucket") or not s3.get("prefix"):
            raise _bad("agentRuntimeArtifact.codeConfiguration.code.s3.bucket and prefix are required")
        if not cc.get("entryPoint"):
            raise _bad("agentRuntimeArtifact.codeConfiguration.entryPoint is required")
    elif not (art.get("containerConfiguration") or {}).get("containerUri"):
        raise _bad("agentRuntimeArtifact.containerConfiguration.containerUri is required")


def _snap(rt):
    """Per-version snapshot the host runs (artifact + env), so an endpoint pinned to version N keeps running version N's code."""
    rt.setdefault("_snap", {})[rt["agentRuntimeVersion"]] = {"version": rt["agentRuntimeVersion"], "agentRuntimeArtifact": rt["agentRuntimeArtifact"],
                                                              "environmentVariables": dict(rt.get("environmentVariables") or {})}


def _host():
    try:
        from core import agentcore_runtime_host as m
    except ImportError:
        import agentcore_runtime_host as m  # type: ignore
    return m


def _create_runtime(st, p):
    name = p.get("agentRuntimeName")
    if not name or not _RT_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'agentRuntimeName' failed to satisfy constraint: Member must satisfy regular expression pattern: [a-zA-Z][a-zA-Z0-9_]{0,47}")
    art = p.get("agentRuntimeArtifact") or {}
    _check_artifact(art)
    if not p.get("roleArn"):
        raise _bad("roleArn is required")
    net = (p.get("networkConfiguration") or {}).get("networkMode")
    if net not in ("PUBLIC", "VPC"):
        raise _bad("networkConfiguration.networkMode must be PUBLIC or VPC")
    if any(r["agentRuntimeName"] == name for r in st["runtimes"].values()):
        raise _conflict(f"An agent runtime named {name} already exists")
    rid = f"{name}-{_rid(10, string.ascii_letters + string.digits)}"
    now = _iso()
    rt = {"agentRuntimeId": rid, "agentRuntimeName": name, "agentRuntimeArn": f"arn:aws:bedrock-agentcore:{_REGION}:{_ACCT}:runtime/{rid}",
          "agentRuntimeVersion": "1", "description": p.get("description", ""), "agentRuntimeArtifact": art, "roleArn": p["roleArn"],
          "networkConfiguration": p["networkConfiguration"], "protocolConfiguration": p.get("protocolConfiguration") or {"serverProtocol": "HTTP"},
          "environmentVariables": p.get("environmentVariables") or {}, "status": "CREATING", "createdAt": now, "lastUpdatedAt": now,
          "workloadIdentityDetails": {"workloadIdentityArn": f"arn:aws:bedrock-agentcore:{_REGION}:{_ACCT}:workload-identity-directory/default/workload-identity/{name}-{_rid(10, _LOWER)}"},
          "_readyAt": time.time() + 1.0}
    st["runtimes"][rid] = rt
    return _j(202, {k: rt[k] for k in ("agentRuntimeArn", "agentRuntimeId", "agentRuntimeVersion", "createdAt", "workloadIdentityDetails", "status")})


def _create_gateway(st, p):
    name = p.get("name")
    if not name or not _AC_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: ([0-9a-zA-Z][-]?){1,100}")
    if not p.get("roleArn"):
        raise _bad("roleArn is required")
    if p.get("protocolType", "MCP") != "MCP":
        raise _bad("protocolType must be MCP")
    auth = p.get("authorizerType")
    if auth not in _GATEWAY_AUTH:
        raise _bad(f"authorizerType must be one of {', '.join(_GATEWAY_AUTH)}")
    if auth == "CUSTOM_JWT" and not (p.get("authorizerConfiguration") or {}).get("customJWTAuthorizer", {}).get("discoveryUrl"):
        raise _bad("authorizerConfiguration.customJWTAuthorizer.discoveryUrl is required for CUSTOM_JWT")
    if any(g["name"] == name for g in st["gateways"].values()):
        raise _conflict(f"A gateway named {name} already exists")
    gid = f"{name.lower()[:100]}-{_rid(10, _LOWER)}"
    now = _iso()
    gw = {"gatewayArn": f"arn:aws:bedrock-agentcore:{_REGION}:{_ACCT}:gateway/{gid}", "gatewayId": gid, "gatewayUrl": f"https://{gid}.gateway.bedrock-agentcore.{_REGION}.amazonaws.com/mcp",
          "createdAt": now, "updatedAt": now, "status": "CREATING", "name": name, "description": p.get("description", ""), "roleArn": p["roleArn"],
          "protocolType": "MCP", "protocolConfiguration": p.get("protocolConfiguration") or {"mcp": {"supportedVersions": ["2025-03-26"]}},
          "authorizerType": auth, "authorizerConfiguration": p.get("authorizerConfiguration"), "exceptionLevel": p.get("exceptionLevel"),
          "policyEngineConfiguration": p.get("policyEngineConfiguration"), "targets": {}, "_readyAt": time.time() + 1.0}
    st["gateways"][gid] = gw
    r = {k: v for k, v in gw.items() if not k.startswith("_") and k not in ("targets", "lastUpdatedAt")}
    return _j(202, r)


def _find_gw(st, gid):
    g = st["gateways"].get(gid)
    if not g:
        raise _nf(f"Gateway {gid} not found")
    return g


def _tool_schema(cfg):
    lam = (cfg.get("mcp") or {}).get("lambda") or {}
    ts = (lam.get("toolSchema") or {}).get("inlinePayload")
    if ts is None:
        raise _bad("targetConfiguration.mcp.lambda.toolSchema.inlinePayload is required")
    if not isinstance(ts, list) or not ts:
        raise _bad("toolSchema.inlinePayload must be a non-empty list of tool definitions")
    for t in ts:
        if not isinstance(t, dict) or not t.get("name") or not t.get("description") or not isinstance(t.get("inputSchema"), dict):
            raise _bad("each tool needs name, description and inputSchema")
        if not re.match(r"^[a-zA-Z0-9_-]+$", t["name"]):
            raise _bad(f"tool name {t['name']} is invalid")
    return ts


def _create_target(st, gw, p, s3=None):
    name = p.get("name")
    if not name or not _AC_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'name' failed to satisfy constraint: Member must satisfy regular expression pattern: ([0-9a-zA-Z][-]?){1,100}")
    cfg = p.get("targetConfiguration") or {}
    mcp = cfg.get("mcp") or {}
    kinds = [k for k in ("lambda", "openApiSchema", "smithyModel", "mcpServer") if k in mcp]
    if len(kinds) != 1:
        raise _bad("targetConfiguration.mcp must name exactly one of lambda, openApiSchema, smithyModel, mcpServer")
    if kinds[0] == "lambda":
        if not re.match(r"^arn:aws[-a-z]*:lambda:[-a-z0-9]+:\d{12}:function:[^:]+(:[^:]+)?$", (mcp["lambda"].get("lambdaArn") or "")):
            raise _bad("targetConfiguration.mcp.lambda.lambdaArn must be a Lambda function ARN")
        _tool_schema(cfg)
    else:
        if not p.get("credentialProviderConfigurations"):
            raise _bad(f"credentialProviderConfigurations is required for {kinds[0]} targets")
    gt = _gt()
    gt.check_target_providers(st, p)
    extra = {}
    if kinds[0] == "openApiSchema":
        spec = gt.validate_openapi(mcp, s3)
        extra = {"_base": spec["servers"][0]["url"], "_ops": gt.openapi_operations(spec)}
    elif kinds[0] == "mcpServer":
        if not str((mcp["mcpServer"] or {}).get("endpoint", "")).startswith(("http://", "https://")):
            raise _bad("targetConfiguration.mcp.mcpServer.endpoint must be an http(s) URL")
    if any(t["name"] == name for t in gw["targets"].values()):
        raise _conflict(f"A target named {name} already exists in this gateway")
    tid = _rid(10)
    now = _iso()
    t = {"gatewayArn": gw["gatewayArn"], "targetId": tid, "createdAt": now, "updatedAt": now, "status": "CREATING", "name": name,
         "description": p.get("description", ""), "targetConfiguration": cfg,
         "credentialProviderConfigurations": p.get("credentialProviderConfigurations") or [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
         "_readyAt": time.time() + 1.0, "_kind": kinds[0], **extra}
    gw["targets"][tid] = t
    gw["updatedAt"] = now
    return _j(202, {k: v for k, v in t.items() if not k.startswith("_")})


def _gt():
    try:
        from core import agentcore_gateway_targets as m
    except ImportError:
        import agentcore_gateway_targets as m  # type: ignore
    return m


def _mcp_tools(gw, st=None, headers=None):
    out = []
    for t in gw["targets"].values():
        if t["_kind"] == "lambda":
            for tool in _tool_schema(t["targetConfiguration"]):
                out.append((f"{t['name']}___{tool['name']}", t, tool))
        elif t["_kind"] == "openApiSchema":
            for o in t.get("_ops") or []:
                out.append((f"{t['name']}___{o['tool']}", t, {"name": o["tool"], "description": o["description"], "inputSchema": o["inputSchema"]}))
        elif t["_kind"] == "mcpServer" and st is not None:
            c = t.get("_up")
            if not c or c[0] < time.time():   # upstream catalog cached 30 s
                try:
                    c = (time.time() + 30, _gt().mcp_upstream(st, t, "tools/list", {}, headers).get("tools") or [])
                    t["_upErr"] = None
                except Exception as e:  # noqa: BLE001 - a dead upstream hides its tools, never fails the whole catalog
                    c = (time.time() + 5, [])
                    t["_upErr"] = f"{type(e).__name__}: {e}"
                t["_up"] = c
            for tool in c[1]:
                out.append((f"{t['name']}___{tool['name']}", t, {"name": tool["name"], "description": tool.get("description", ""), "inputSchema": tool.get("inputSchema") or {"type": "object"}}))
    return out


def _ext():
    try:
        from core import agentcore_ext_core as m
    except ImportError:
        import agentcore_ext_core as m  # type: ignore
    return m


def _mcp(st, lam, gid, p, headers):
    gw = _find_gw(st, gid)
    _ac_ready(gw)
    if gw["status"] != "READY":
        return _j(503, {"message": "Gateway is not READY"})
    if gw["authorizerType"] == "CUSTOM_JWT":
        _claims, deny = _gt().validate_inbound(gw, headers)
        if deny:
            return deny
    elif gw["authorizerType"] != "NONE":
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        if not (h.get("authorization") or "").strip():
            return _j(401, {"message": "Missing Authentication Token"})
    rid, method = p.get("id"), p.get("method")

    def ok(result):
        return _j(200, {"jsonrpc": "2.0", "id": rid, "result": result})

    def fail(code, msg):
        return _j(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}})
    if method == "initialize":
        return ok({"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": gw["name"], "version": "1.0.0"}})
    if method in ("notifications/initialized", "ping"):
        return ok({}) if method == "ping" else _j(202, None)
    ext = _ext()
    claims = ext.jwt_claims(headers)
    visible = [(n, t, tool) for n, t, tool in _mcp_tools(gw, st, headers) if ext.authorize(st, gw, claims, n, {}, probe=True)[0]]   # list is filtered by policy
    searchable = ((gw.get("protocolConfiguration") or {}).get("mcp") or {}).get("searchType") == "SEMANTIC"
    if method == "tools/list":
        tl = [{"name": n, "description": tool["description"], "inputSchema": tool["inputSchema"]} for n, _t, tool in visible]
        return ok({"tools": ([ext.search_tool_def()] if searchable else []) + tl})
    if method == "tools/call":
        prm = p.get("params") or {}
        if searchable and prm.get("name") == ext.SEARCH_TOOL:
            q = str((prm.get("arguments") or {}).get("query") or "")
            hits = ext.search_tools([(n, tool["description"], tool["inputSchema"]) for n, _t, tool in visible], q)
            return ok({"isError": False, "content": [{"type": "text", "text": json.dumps({"tools": hits})}], "structuredContent": {"tools": hits}})
        allowed, why = ext.authorize(st, gw, claims, prm.get("name") or "", prm.get("arguments") or {})
        if not allowed:
            return fail(-32002, f"Tool call not allowed due to policy enforcement [{why}]")
        hit = next(((t, tool) for n, t, tool in _mcp_tools(gw, st, headers) if n == prm.get("name")), None)
        if not hit:
            return fail(-32602, f"Unknown tool: {prm.get('name')}")
        t, tool = hit
        _ac_ready(t)
        if t["_kind"] in ("openApiSchema", "mcpServer"):
            gt = _gt()
            try:
                if t["_kind"] == "openApiSchema":
                    return ok(gt.call_openapi(st, t, t["_ops"], t["_base"], tool["name"], prm.get("arguments") or {}, headers))
                return ok(gt.mcp_upstream(st, t, "tools/call", {"name": tool["name"], "arguments": prm.get("arguments") or {}}, headers))
            except Exception as e:  # noqa: BLE001 - upstream / credential failure surfaces as a tool error
                return ok({"isError": True, "content": [{"type": "text", "text": f"Target call failed: {e}"}]})
        arn = t["targetConfiguration"]["mcp"]["lambda"]["lambdaArn"]
        fname = arn.split(":function:")[1].split(":")[0]
        if lam is None:
            return ok({"isError": True, "content": [{"type": "text", "text": "Lambda is unavailable on this substrate"}]})
        try:
            from core import lambda_core
        except ImportError:
            import lambda_core  # type: ignore
        r = lambda_core._invoke(lam, fname, json.dumps(prm.get("arguments") or {}).encode())
        txt = (r.body or b"").decode("utf-8", "replace")
        is_err = r.status >= 400 or "X-Amz-Function-Error" in (r.headers or {}) or "x-amz-function-error" in {k.lower() for k in (r.headers or {})}
        return ok({"isError": bool(is_err), "content": [{"type": "text", "text": txt}]})
    return fail(-32601, f"Method not found: {method}")


# ═══════════════ AgentCore runtimes: control plane + InvokeAgentRuntime over the Vyomi agent spec (Dev Simplified) ═══════════════
_RT_PATH = re.compile(r"^(?:arn:[^/]*:runtime/)?([A-Za-z][A-Za-z0-9_\-]*)(?:/(.*))?$")
_SESS_HDR = "x-amzn-bedrock-agentcore-runtime-session-id"
_SPEC_ENV = "VYOMI_AGENT_SPEC"


def _agent_core():
    try:
        from core import agent_spec_core as m
    except ImportError:
        import agent_spec_core as m  # type: ignore
    return m


def _rt_summary(rt):
    return {k: rt[k] for k in ("agentRuntimeArn", "agentRuntimeId", "agentRuntimeVersion", "agentRuntimeName", "description", "lastUpdatedAt", "status")}


def _ep_view(rt, ep):
    _ac_ready(ep)
    return {k: v for k, v in ep.items() if not k.startswith("_")}


def _mk_endpoint(rt, name, version, desc=""):
    now = _iso()
    return {"name": name, "id": f"{name}-{_rid(10, _LOWER)}", "agentRuntimeEndpointArn": f"{rt['agentRuntimeArn']}/runtime-endpoint/{name}", "agentRuntimeArn": rt["agentRuntimeArn"],
            "description": desc, "status": "CREATING", "liveVersion": version, "targetVersion": version, "createdAt": now, "lastUpdatedAt": now, "_readyAt": time.time() + 1.0}


def _page_q(pq, method, body):
    if method == "POST":
        pq.update({k: str(v) for k, v in _body(body).items() if k in ("maxResults", "nextToken")})
    return pq


def _runtimes(st, method, path, query, headers, body, lam=None, s3=None):
    rest = path[len("/runtimes"):].strip("/")
    pq = dict(query or {})
    if not rest:                                   # collection: create (PUT, or legacy POST with a name) / list (POST body or GET)
        p = _body(body) if method in ("PUT", "POST") else {}
        if method == "PUT" or (method == "POST" and "agentRuntimeName" in p):
            r = _create_runtime(st, p)
            rt = next(x for x in st["runtimes"].values() if x["agentRuntimeName"] == p["agentRuntimeName"])
            rt["_versions"] = {"1": _rt_summary(rt)}
            rt["_endpoints"] = {"DEFAULT": _mk_endpoint(rt, "DEFAULT", "1", "Default endpoint for the agent runtime")}
            rt["_sessions"] = {}
            _snap(rt)
            return r
        if method in ("GET", "POST"):
            pq.update({k: str(v) for k, v in p.items() if k in ("maxResults", "nextToken")})
            for r in st["runtimes"].values():
                _ac_ready(r)
            return _j(200, _paginate([_rt_summary(r) for r in st["runtimes"].values()], pq, "agentRuntimes"))
        raise _Err("UnknownOperationException", f"Unsupported AgentCore operation: {method} {path}", 404)
    m = _RT_PATH.match(urllib.parse.unquote(rest))
    if not m:
        raise _bad("Invalid agentRuntimeId / agentRuntimeArn")
    rid, tail = m.group(1), (m.group(2) or "").strip("/")
    rt = st["runtimes"].get(rid)
    if not rt:
        raise _nf(f"Runtime {rid} not found")
    rt.setdefault("_versions", {rt["agentRuntimeVersion"]: _rt_summary(rt)})
    rt.setdefault("_endpoints", {})
    rt.setdefault("_sessions", {})
    _ac_ready(rt)
    if tail == "invocations" and method == "POST":
        return _invoke_runtime(rt, query or {}, headers or {}, body, st, lam, s3)
    if tail == "stopruntimesession" and method == "POST":
        sid = _body(body).get("runtimeSessionId") or (headers or {}).get(_SESS_HDR)
        killed = _host().stop_session(rt["agentRuntimeId"], sid)
        if not sid or (sid not in rt["_sessions"] and not killed):
            raise _nf(f"Runtime session {sid} not found")
        rt["_sessions"].pop(sid, None)
        return _j(200, {"runtimeSessionId": sid, "statusCode": 200}, {_SESS_HDR: sid})
    if tail == "commands":
        raise _Err("ValidationException", "InvokeAgentRuntimeCommand needs a container; the Vyomi agent-spec runtime has none", 400)
    if tail == "":
        if method == "GET":
            v = pq.get("agentRuntimeVersion")
            if v and v not in rt["_versions"]:
                raise _nf(f"Runtime {rid} version {v} not found")
            return _j(200, _pub(rt))
        if method == "PUT":
            p = _body(body)
            art = p.get("agentRuntimeArtifact") or rt["agentRuntimeArtifact"]
            _check_artifact(art)
            rt["agentRuntimeArtifact"] = art
            rt["agentRuntimeVersion"] = str(int(rt["agentRuntimeVersion"]) + 1)
            for f in ("roleArn", "networkConfiguration", "description", "environmentVariables", "protocolConfiguration", "authorizerConfiguration"):
                if f in p:
                    rt[f] = p[f]
            rt["status"], rt["_readyAt"], rt["lastUpdatedAt"] = "UPDATING", time.time() + 1.0, _iso()
            rt["_versions"][rt["agentRuntimeVersion"]] = _rt_summary(rt)
            _snap(rt)
            if "DEFAULT" in rt["_endpoints"]:        # the DEFAULT endpoint always follows the latest version
                rt["_endpoints"]["DEFAULT"].update(liveVersion=rt["agentRuntimeVersion"], targetVersion=rt["agentRuntimeVersion"], lastUpdatedAt=_iso())
            return _j(202, {k: rt[k] for k in ("agentRuntimeArn", "agentRuntimeId", "agentRuntimeVersion", "createdAt", "lastUpdatedAt", "status", "workloadIdentityDetails")})
        if method == "DELETE":
            _host().stop_session(rid)
            del st["runtimes"][rid]
            return _j(202, {"status": "DELETING", "agentRuntimeId": rid, "agentRuntimeVersion": rt["agentRuntimeVersion"]})
    if tail == "versions" and method in ("POST", "GET"):
        return _j(200, _paginate([dict(v, status="READY") for v in rt["_versions"].values()], _page_q(pq, method, body), "agentRuntimes"))
    if tail.startswith("runtime-endpoints"):
        en = tail[len("runtime-endpoints"):].strip("/")
        if not en:
            if method == "PUT":
                p = _body(body)
                name = p.get("name")
                if not name or not re.match(r"^[a-zA-Z][a-zA-Z0-9_]{0,47}$", name):
                    raise _bad("name must match [a-zA-Z][a-zA-Z0-9_]{0,47}")
                if name in rt["_endpoints"]:
                    raise _conflict(f"Endpoint {name} already exists")
                ver = p.get("agentRuntimeVersion") or rt["agentRuntimeVersion"]
                if ver not in rt["_versions"]:
                    raise _nf(f"Runtime {rid} version {ver} not found")
                ep = rt["_endpoints"][name] = _mk_endpoint(rt, name, ver, p.get("description", ""))
                return _j(202, {"targetVersion": ver, "agentRuntimeEndpointArn": ep["agentRuntimeEndpointArn"], "agentRuntimeArn": rt["agentRuntimeArn"],
                                "agentRuntimeId": rid, "endpointName": name, "status": "CREATING", "createdAt": ep["createdAt"]})
            if method in ("POST", "GET"):
                return _j(200, _paginate([_ep_view(rt, e) for e in rt["_endpoints"].values()], _page_q(pq, method, body), "runtimeEndpoints"))
        else:
            ep = rt["_endpoints"].get(en)
            if not ep:
                raise _nf(f"Endpoint {en} not found")
            if method == "GET":
                return _j(200, _ep_view(rt, ep))
            if method == "PUT":
                p = _body(body)
                ver = p.get("agentRuntimeVersion") or ep["liveVersion"]
                if ver not in rt["_versions"]:
                    raise _nf(f"Runtime {rid} version {ver} not found")
                ep.update(targetVersion=ver, liveVersion=ver, status="UPDATING", lastUpdatedAt=_iso(), _readyAt=time.time() + 1.0)
                if "description" in p:
                    ep["description"] = p["description"]
                return _j(202, {k: ep[k] for k in ("liveVersion", "targetVersion", "agentRuntimeEndpointArn", "agentRuntimeArn", "status", "createdAt", "lastUpdatedAt")})
            if method == "DELETE":
                if en == "DEFAULT":
                    raise _bad("The DEFAULT endpoint cannot be deleted")
                del rt["_endpoints"][en]
                return _j(202, {"status": "DELETING", "agentRuntimeId": rid, "endpointName": en})
    raise _Err("UnknownOperationException", f"Unsupported AgentCore operation: {method} {path}", 404)


def _payload_text(raw):
    """Payload convention of AgentCore samples: JSON {"prompt": ...}; also message / input / inputText / question, or raw text."""
    if not raw:
        raise _bad("payload is required")
    txt = raw.decode("utf-8", "replace")
    try:
        d = json.loads(txt)
    except ValueError:
        return txt, False
    if isinstance(d, dict):
        for k in ("prompt", "message", "input", "inputText", "question", "query"):
            if isinstance(d.get(k), str) and d[k]:
                return d[k], bool(d.get("stream"))
        raise _bad('payload must carry a "prompt" (or message/input/inputText/question) string')
    return (d if isinstance(d, str) else txt), False


def _rt_client_err(msg):
    return {"status": 424, "headers": {"content-type": "application/json", "x-amzn-errortype": "RuntimeClientError"}, "body": json.dumps({"message": msg}).encode()}


def _invoke_hosted(rt, qual, h, body, s3):
    """Real hosting (core/agentcore_runtime_host): run the runtime's code/container through the AgentCore contract, one process per session."""
    host = _host()
    ver = rt["agentRuntimeVersion"]
    if qual and qual != "DEFAULT":
        ver = rt["_endpoints"][qual]["liveVersion"]
    elif qual == "DEFAULT" and "DEFAULT" in rt["_endpoints"]:
        ver = rt["_endpoints"]["DEFAULT"]["liveVersion"]
    snap = rt.get("_snap", {}).get(ver)
    if not snap:
        _snap(rt)
        snap = rt["_snap"][ver]
    sid = h.get(_SESS_HDR) or ("sess-" + _rid(32, string.ascii_lowercase + string.digits))
    if len(sid) < 33:
        raise _bad("1 validation error detected: Value at 'runtimeSessionId' failed to satisfy constraint: Member must have length greater than or equal to 33")
    endpoint = os.environ.get("VYOMI_SELF_ENDPOINT") or ("http://" + h["host"] if h.get("host") else "http://127.0.0.1:8099")
    try:
        status, rh, out = host.invoke(rt, snap, s3, endpoint, sid, body or b"", h)
    except host.HostError as e:
        return _rt_client_err(str(e))
    rt["_sessions"].setdefault(sid, {"history": [], "created": _iso()})
    ct = {k.lower(): v for k, v in rh.items()}.get("content-type", "application/json")
    hdrs = {_SESS_HDR: sid, "x-vyomi-runtime-backend": host.backend_for(snap["agentRuntimeArtifact"])}
    if status >= 400:
        raw = out if isinstance(out, bytes) else out.read()
        return _rt_client_err(f"Agent returned {status}: " + raw.decode("utf-8", "replace")[:500])
    if isinstance(out, bytes):
        return {"status": 200, "headers": {"content-type": ct, **hdrs}, "body": out}
    try:
        from core import ai_models_core as am
    except ImportError:
        import ai_models_core as am  # type: ignore
    return am._stream_out(200, hdrs, iter(lambda: out.read1(65536) if hasattr(out, "read1") else out.read(65536), b""), "text/event-stream")


def _invoke_runtime(rt, query, headers, body, st=None, lam=None, s3=None):
    """InvokeAgentRuntime: run the runtime's Vyomi agent spec (env VYOMI_AGENT_SPEC) in-process over llm_core."""
    q = {k.lower(): v for k, v in (query or {}).items()}
    h = {k.lower(): v for k, v in (headers or {}).items()}
    qual = q.get("qualifier")
    if qual and qual != "DEFAULT" and qual not in rt["_endpoints"]:
        raise _nf(f"Endpoint {qual} not found")
    if rt["status"] != "READY":
        return _rt_client_err(f"Runtime is {rt['status']}, not READY")
    raw_spec = (rt.get("environmentVariables") or {}).get(_SPEC_ENV)
    if not raw_spec and _host().hostable(rt["agentRuntimeArtifact"]):
        return _invoke_hosted(rt, qual, h, body, s3)
    if not raw_spec:
        return _rt_client_err("The simulator does not run AgentCore runtime containers. Give the runtime a Vyomi agent spec "
                              f"(environmentVariables[{_SPEC_ENV}] = JSON of instructions + tools) to make it invocable (Dev Simplified).")
    ag = _agent_core()
    try:
        spec = ag.parse_spec(raw_spec)
    except ag.SpecError as e:
        return _rt_client_err(f"Invalid Vyomi agent spec: {e}")
    proto = (rt.get("protocolConfiguration") or {}).get("serverProtocol")
    if proto in ("MCP", "A2A"):
        return _invoke_protocol(rt, proto, spec, ag, h, body, st, lam)
    sid = h.get(_SESS_HDR) or ("sess-" + _rid(32, string.ascii_lowercase + string.digits))
    if len(sid) < 33:
        raise _bad("1 validation error detected: Value at 'runtimeSessionId' failed to satisfy constraint: Member must have length greater than or equal to 33")
    text, want_stream = _payload_text(body)
    ext = _ext()
    raw_h = dict(h)
    claims = ext.jwt_claims(raw_h)
    jwt = ""
    for k in ("authorization", "x-amzn-bedrock-agentcore-runtime-custom-authorization"):
        if (raw_h.get(k) or "").lower().startswith("bearer "):
            jwt = raw_h[k][7:].strip()
            break
    actor = str(claims.get("sub") or h.get("x-amzn-bedrock-agentcore-runtime-user-id") or "anonymous")
    text, mem_after = ext.memory_hooks(ext._x(st), spec, actor, sid, text)
    sess = rt["_sessions"].setdefault(sid, {"history": [], "created": _iso()})
    accept = h.get("accept", "")
    hdrs = {_SESS_HDR: sid, "x-vyomi-local-model": llm.model_name()}
    try:
        if want_stream or "text/event-stream" in accept:
            evs = ext.run_context(st, lam, jwt, actor, lambda: list(ag.run_events(spec, text, sess["history"])))   # events buffered: the tool context is scoped to the call
            gen = iter(evs)
            first = next(gen)

            def sse():
                import itertools
                for ev in itertools.chain([first], gen):
                    if ev["type"] == "final":
                        sess["history"].extend(ev["messages"])
                        mem_after(ev["text"])
                        yield "data: " + json.dumps({"event": "final", "response": ev["text"], "usage": ev["usage"]}) + "\n\n"
                    elif ev["type"] == "model" and not ev["tool_calls"]:
                        yield "data: " + json.dumps({"event": "message", "text": ev["text"]}) + "\n\n"
                    elif ev["type"] == "model":
                        yield "data: " + json.dumps({"event": "tool_use", "tools": ev["tool_calls"]}) + "\n\n"
                    else:
                        yield "data: " + json.dumps({"event": "tool_result", "name": ev["name"], "result": ev["result"], "isError": ev["isError"]}) + "\n\n"
            try:
                from core import ai_models_core as am
            except ImportError:
                import ai_models_core as am  # type: ignore
            return am._stream_out(200, hdrs, sse(), "text/event-stream")
        r = ext.run_context(st, lam, jwt, actor, lambda: ag.run(spec, text, sess["history"]))
        mem_after(r["text"])
    except llm.LlmUnavailable as e:
        return {"status": 503, "headers": {"content-type": "application/json", "x-amzn-errortype": "ServiceUnavailableException"},
                "body": json.dumps({"message": f"{e}"}).encode()}
    except ValueError as e:
        raise _bad(str(e))
    sess["history"].extend(r["messages"])
    return _j(200, {"response": r["text"], "sessionId": sid,
                    "toolCalls": [{"name": s["name"], "arguments": s["arguments"], "result": s["result"], "isError": s["isError"]} for s in r["steps"] if s["type"] == "tool_result"],
                    "usage": r["usage"], "model": r["model"], "truncated": r["truncated"]}, hdrs)


def _invoke_protocol(rt, proto, spec, ag, h, body, st, lam):
    """serverProtocol MCP / A2A runtimes: the payload is a JSON-RPC 2.0 request (as the real service forwards it to the container)."""
    gt = _gt()
    try:
        req = json.loads((body or b"").decode("utf-8", "replace"))
        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0":
            raise ValueError("not a JSON-RPC 2.0 request")
    except ValueError as e:
        return _j(200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": f"Invalid request: {e}"}})
    hdrs = {_SESS_HDR: h.get(_SESS_HDR) or ("sess-" + _rid(32, string.ascii_lowercase + string.digits))}
    if proto == "MCP":
        r = gt.runtime_mcp(spec, req, ag, rt["agentRuntimeName"])
        return _j(202, None, hdrs) if r is None else _j(200, r, hdrs)
    ext = _ext()
    claims = ext.jwt_claims(h)
    jwt = next((h[k][7:].strip() for k in ("authorization", "x-amzn-bedrock-agentcore-runtime-custom-authorization") if (h.get(k) or "").lower().startswith("bearer ")), "")
    actor = str(claims.get("sub") or h.get("x-amzn-bedrock-agentcore-runtime-user-id") or "anonymous")

    def run_agent(text, ctx):
        text2, mem_after = ext.memory_hooks(ext._x(st), spec, actor, ctx, text)
        sess = rt["_sessions"].setdefault(ctx, {"history": [], "created": _iso()})
        r = ext.run_context(st, lam, jwt, actor, lambda: ag.run(spec, text2, sess["history"]))
        mem_after(r["text"])
        sess["history"].extend(r["messages"])
        return r["text"]
    try:
        out = gt.runtime_a2a(rt, spec, req, run_agent, rt.setdefault("_a2a_tasks", {}))
    except llm.LlmUnavailable as e:
        return {"status": 503, "headers": {"content-type": "application/json", "x-amzn-errortype": "ServiceUnavailableException"}, "body": json.dumps({"message": f"{e}"}).encode()}
    return _j(200, out, hdrs)


def agentcore_dispatch(s3, lam, method, path, query, headers, body):
    method = method.upper()
    path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    segs = [urllib.parse.unquote(s) for s in path.strip("/").split("/")]
    try:
        st = _state(s3)
        if segs[0] == "runtimes":
            return _runtimes(st, method, path, query, headers, body, lam, s3)
        if segs[0] == "identities":
            r = _gt().dispatch(st, method, segs, body)
            if r is not None:
                return r
        if segs[0] in ("memories", "policy-engines"):
            try:
                from core import agentcore_ext_core as ext
            except ImportError:
                import agentcore_ext_core as ext  # type: ignore
            r = ext.dispatch(st, lam, method, segs, query, headers, body)
            if r is not None:
                return r
        p = _body(body) if method in ("PUT", "POST", "PATCH") else {}
        if segs[0] == "gateways":
            if len(segs) == 1:
                if method == "POST":
                    return _create_gateway(st, p)
                if method == "GET":
                    return _j(200, _paginate([{k: _pub(g)[k] for k in ("gatewayId", "name", "status", "description", "createdAt", "updatedAt", "authorizerType", "protocolType")}
                                              for g in st["gateways"].values()], query, "items"))
            else:
                gw = _find_gw(st, segs[1])
                if len(segs) == 3 and segs[2] == "mcp" and method == "POST":
                    return _mcp(st, lam, segs[1], p, headers)
                if len(segs) == 2:
                    if method == "GET":
                        return _j(200, _pub(gw))
                    if method == "PUT":
                        if not p.get("name") or not p.get("roleArn") or p.get("authorizerType") not in _GATEWAY_AUTH:
                            raise _bad("name, roleArn and authorizerType are required")
                        gw.update(name=p["name"], roleArn=p["roleArn"], authorizerType=p["authorizerType"], updatedAt=_iso())
                        for f in ("description", "authorizerConfiguration", "exceptionLevel", "policyEngineConfiguration", "protocolConfiguration"):
                            if f in p:
                                gw[f] = p[f]
                        return _j(202, _pub(gw))
                    if method == "DELETE":
                        if gw["targets"]:
                            raise _Err("ValidationException", "Gateway has targets; delete the targets first", 400)
                        del st["gateways"][gw["gatewayId"]]
                        return _j(202, {"gatewayId": gw["gatewayId"], "status": "DELETING"})
                elif segs[2] == "targets":
                    if len(segs) == 3:
                        if method == "POST":
                            return _create_target(st, gw, p, s3)
                        if method == "GET":
                            for t in gw["targets"].values():
                                _ac_ready(t)
                            return _j(200, _paginate([{k: t[k] for k in ("targetId", "name", "status", "description", "createdAt", "updatedAt")} for t in gw["targets"].values()], query, "items"))
                    else:
                        t = gw["targets"].get(segs[3])
                        if not t:
                            raise _nf(f"Target {segs[3]} not found")
                        if len(segs) == 4:
                            if method == "GET":
                                _ac_ready(t)
                                return _j(200, {k: v for k, v in t.items() if not k.startswith("_")})
                            if method == "PUT":
                                if "targetConfiguration" in p:
                                    cfg = p["targetConfiguration"]
                                    if "lambda" in (cfg.get("mcp") or {}):
                                        _tool_schema(cfg)
                                    if "openApiSchema" in (cfg.get("mcp") or {}):
                                        _sp = _gt().validate_openapi(cfg["mcp"], s3)
                                        t["_base"], t["_ops"] = _sp["servers"][0]["url"], _gt().openapi_operations(_sp)
                                    t["targetConfiguration"] = cfg
                                for f in ("name", "description", "credentialProviderConfigurations"):
                                    if f in p:
                                        t[f] = p[f]
                                t["updatedAt"] = _iso()
                                return _j(202, {k: v for k, v in t.items() if not k.startswith("_")})
                            if method == "DELETE":
                                del gw["targets"][t["targetId"]]
                                return _j(202, {"gatewayArn": gw["gatewayArn"], "targetId": t["targetId"], "status": "DELETING"})
    except _Err as e:
        return _err_resp(e)
    return _err_resp(_Err("UnknownOperationException", f"Unsupported AgentCore operation: {method} {path}", 404))
