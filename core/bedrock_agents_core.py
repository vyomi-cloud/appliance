"""Amazon Bedrock Agents + Knowledge Bases + AgentCore (control plane, gateway MCP) — substrate-independent, Pyodide-loadable.

Built on the shared local-LLM seam (core/llm_core: chat + embed). No fastapi/boto3. State lives in the S3 ObjectStore's
persisted account bag: ``store.account["bedrock_agents"]``.

bedrock-agent (control, signing name ``bedrock``): CreateAgent/GetAgent/ListAgents/UpdateAgent/PrepareAgent/DeleteAgent,
agent aliases, AssociateAgentKnowledgeBase / ListAgentKnowledgeBases, action groups (stored), CreateKnowledgeBase /
GetKnowledgeBase / ListKnowledgeBases / DeleteKnowledgeBase, data sources (S3), ingestion jobs.
bedrock-agent-runtime (``bedrock``): Retrieve, RetrieveAndGenerate, InvokeAgent (vnd.amazon.eventstream chunks).
AgentCore (``bedrock-agentcore``): control plane runtimes (CreateAgentRuntime...), gateways and gateway targets, plus the
gateway's MCP endpoint (initialize / tools/list / tools/call -> Lambda targets are really invoked).

Real behaviour: ingestion reads the S3 objects of the data source, chunks them (fixed size / hierarchical / semantic / none), embeds every chunk with
``llm_core.embed`` and keeps the index in the account bag; Retrieve is exact cosine kNN with the S3 location + score; the
agent/RetrieveAndGenerate answer is the local model prompted with the retrieved passages and returns citations.

Honest limits: the model is a small local one (see llm_core.HONEST_LIMIT). Agent action groups are stored but the model does
not emit tool calls, so they are never invoked; text/CSV/HTML/Markdown, PDF (pypdf), DOCX, XLSX and PPTX are ingested - other
types (legacy .doc/.xls, scanned PDFs) are counted as failed with a per-file reason; vector storage is always the in-account index regardless of the storage type named;
AgentCore runtimes: InvokeAgentRuntime runs a Vyomi agent spec (core/agent_spec_core: JSON instructions + declarative tools in-process over
llm_core, Dev Simplified) carried in environmentVariables.VYOMI_AGENT_SPEC - container images are never run (without a spec the invoke
returns RuntimeClientError); runtime endpoints/versions/sessions are modelled; gateway targets of type openApiSchema/smithyModel/mcpServer are registered but their tools are not callable.
"""
from __future__ import annotations

import base64
import hashlib
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
    try:
        kc.chunk_config(p.get("vectorIngestionConfiguration") or {})
        kc.parsing_config(p.get("vectorIngestionConfiguration") or {})
    except ValueError as e:
        raise _bad(str(e))
    did = _rid()
    now = _iso()
    ds = {"knowledgeBaseId": kb["knowledgeBaseId"], "dataSourceId": did, "name": name, "description": p.get("description", ""),
          "status": "AVAILABLE", "dataSourceConfiguration": conf, "dataDeletionPolicy": p.get("dataDeletionPolicy", "DELETE"),
          "vectorIngestionConfiguration": p.get("vectorIngestionConfiguration") or {}, "createdAt": now, "updatedAt": now, "jobs": {}}
    kb["datasources"][did] = ds
    return _j(202, {"dataSource": _ds_view(ds)})


def _read_metadata(raw):
    """A `<object>.metadata.json` -> (attributes, embed_keys). Accepts {"metadataAttributes": {k: v}} where v is a string, number, bool or
    list of strings, or the typed form {"value": {"type": STRING|NUMBER|BOOLEAN|STRING_LIST, ...}, "includeForEmbedding": bool}.
    Raises ValueError on a malformed file (the data document is then counted as failed, as Bedrock does)."""
    if len(raw) > 10 * 1024:
        raise ValueError("metadata file is over the 10 KB limit")
    try:
        doc = json.loads(raw)
    except ValueError:
        raise ValueError("metadata file is not valid JSON")
    attrs = doc.get("metadataAttributes") if isinstance(doc, dict) else None
    if not isinstance(attrs, dict):
        raise ValueError("metadata file must be an object with a metadataAttributes object")
    out, emb = {}, []
    for k, v in attrs.items():
        inc = False
        if isinstance(v, dict) and "value" in v:
            inc = bool(v.get("includeForEmbedding"))
            tv = v["value"]
            if isinstance(tv, dict):
                key = {"STRING": "stringValue", "NUMBER": "numberValue", "BOOLEAN": "booleanValue", "STRING_LIST": "stringListValue"}.get(tv.get("type"))
                if not key or key not in tv:
                    raise ValueError(f"metadata attribute {k}: typed value needs type and the matching *Value field")
                v = tv[key]
            else:
                v = tv
        ok = isinstance(v, (str, bool, int, float)) or (isinstance(v, list) and all(isinstance(x, str) for x in v))
        if not ok:
            raise ValueError(f"metadata attribute {k}: value must be a string, number, boolean or list of strings")
        out[k] = v
        if inc:
            emb.append(k)
    if len(out) > 10:
        raise ValueError("a document can have at most 10 metadata attributes")
    return out, emb


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
    vic = ds.get("vectorIngestionConfiguration") or {}
    cfg, pcfg = kc.chunk_config(vic), kc.parsing_config(vic)
    s3c = _s3c()
    pipe = _pipeline_cfg(s3c, s3, bucket)
    gid, gver = pipe.get("guardrailIdentifier"), str(pipe.get("guardrailVersion", "DRAFT"))
    kb["chunks"] = [c for c in kb["chunks"] if c["ds"] != ds["dataSourceId"]]       # a re-sync replaces this data source's chunks
    scanned = failed = indexed = meta_scanned = 0
    reasons, items = [], []
    seen = set()
    for pfx in prefixes:
        for key in _list_keys(s3, bucket, pfx):
            if key in seen or key.endswith("/") or key.endswith(".metadata.json") or key == ".vyomi-pipeline.json":
                continue
            seen.add(key)
            scanned += 1
            uri = f"s3://{bucket}/{key}"
            r = s3c.get_object(s3, bucket, key, {}, {})
            if r.status != 200:
                failed += 1
                reasons.append(f"{uri}: could not read object")
                continue
            try:
                txt = kc.parse_document(key, r.body, pcfg["markdown_tables"])
            except kc.ParseError as e:
                failed += 1
                reasons.append(f"{uri}: {e}")
                continue
            meta, emb_keys = {}, []
            mr = s3c.get_object(s3, bucket, key + ".metadata.json", {}, {})
            if mr.status == 200:
                meta_scanned += 1
                try:
                    meta, emb_keys = _read_metadata(mr.body)
                except ValueError as e:
                    failed += 1
                    reasons.append(f"{uri}: invalid {key.rsplit('/', 1)[-1]}.metadata.json: {e}")
                    continue
            txt, verdict = kc.guard(txt, gid, gver)
            if verdict == "blocked":
                failed += 1
                reasons.append(f"{uri}: blocked by guardrail {gid} (PII/sensitive content scan)")
                continue
            try:
                parts = kc.chunk_document(txt, cfg)
            except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
                failed += 1
                reasons.append(f"{uri}: semantic chunking needs the embedding model: {e}")
                continue
            if not parts:
                failed += 1
                reasons.append(f"{uri}: no text left after chunking")
                continue
            for pt in parts:
                items.append((pt, uri, meta, emb_keys, verdict))
            indexed += 1
    if items:
        etexts = [pt["text"] + ("".join(f"\n{k}: {m[k]}" for k in ek if k in m)) for pt, _, m, ek, _ in items]
        vecs = llm.embed(etexts)["vectors"]
        for n, ((pt, uri, meta, _ek, verdict), v) in enumerate(zip(items, vecs)):
            c = {"id": f"{ds['dataSourceId']}-{n}", "ds": ds["dataSourceId"], "uri": uri, "text": pt["text"], "vec": v, "metadata": meta,
                 "section": pt["section"], "tokens": len(pt["text"].split()), "pii": verdict}
            if pt.get("parent"):
                c["parent"] = pt["parent"]
            kb["chunks"].append(c)
    _mirror_opensearch(s3, kb, ds)
    return {"numberOfDocumentsScanned": scanned, "numberOfNewDocumentsIndexed": indexed, "numberOfModifiedDocumentsIndexed": 0,
            "numberOfMetadataDocumentsScanned": meta_scanned, "numberOfMetadataDocumentsModified": 0, "numberOfDocumentsDeleted": 0,
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
    mode_in = vs.get("overrideSearchType")
    if mode_in is not None and str(mode_in).upper() not in ("HYBRID", "SEMANTIC"):
        raise _bad(f"overrideSearchType must be HYBRID or SEMANTIC (got {mode_in})")
    _validate_filter(flt)
    rr_cfg = _validate_rerank_cfg(vs.get("rerankingConfiguration"), "numberOfRerankedResults")
    if vs.get("implicitFilterConfiguration") is not None:
        flt = _implicit_filter(vs["implicitFilterConfiguration"], text, flt)
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
    top = fused[:max(k * 3, k)] if rr_cfg else fused[:k]
    rrs = {}
    t0 = _t.time()
    if rr_cfg:
        n_out = int(rr_cfg.get("numberOfRerankedResults", k))
        for n, (j, sc) in enumerate(kc.rerank(text, [_rerank_text(chunks[i]["text"], chunks[i]["metadata"], rr_cfg.get("metadataConfiguration")) for i, _ in top], n_out)):
            rrs[top[j][0]] = (n + 1, sc)
        final = [(i, rrs[i][1]) for i in sorted(rrs, key=lambda x: rrs[x][0])][:k]
        stages["rerank"] = (_t.time() - t0) * 1000
    elif mode == "SEMANTIC":
        final = [(i, max(vsc[i], 0.0)) for i, _ in fused[:k]]       # pure vector search: the score is the cosine similarity
    else:
        final = top[:k]
    res, seen_parent = [], set()
    for i, sc in final:
        c = chunks[i]
        if c.get("parent"):                      # hierarchical: the child matched, the parent chunk is returned (once)
            if (c["uri"], c["parent"]) in seen_parent:
                continue
            seen_parent.add((c["uri"], c["parent"]))
        r = {"content": {"type": "TEXT", "text": c.get("parent") or c["text"]}, "location": {"type": "S3", "s3Location": {"uri": c["uri"]}}, "score": round(max(min(sc, 1.0), 0.0), 6),
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
    return res, {"candidates": cand, "searchType": mode, "hybridWeight": lw, "reranked": bool(rr_cfg), "rerankBackend": kc.rerank_backend() if rr_cfg else None,
                 "latencyMs": {k_: round(v, 3) for k_, v in stages.items()}}


def _retrieve(kb, text, k, flt=None, vs=None):
    return _retrieve_trace(kb, text, k, flt, vs)[0]


def _rerank_op(p):
    """bedrock-agent-runtime Rerank: queries[0].textQuery.text, sources[].inlineDocumentSource.textDocument.text -> relevance scored results."""
    qs = p.get("queries") or []
    srcs = p.get("sources") or []
    if not isinstance(qs, list) or len(qs) != 1:
        raise _bad("queries must contain exactly one query.")
    if qs[0].get("type") != "TEXT" or not (qs[0].get("textQuery") or {}).get("text"):
        raise _bad("queries[0] must be of type TEXT with textQuery.text.")
    if not isinstance(srcs, list) or not 1 <= len(srcs) <= 1000:
        raise _bad("sources must contain between 1 and 1000 documents.")
    docs = []
    for i, sr in enumerate(srcs):
        if sr.get("type") != "INLINE":
            raise _bad(f"sources[{i}].type must be INLINE.")
        src = sr.get("inlineDocumentSource") or {}
        if src.get("type") != "TEXT" or not isinstance((src.get("textDocument") or {}).get("text"), str):
            raise _bad(f"sources[{i}].inlineDocumentSource must be a TEXT document with textDocument.text (JSON documents are not supported).")
        docs.append(src["textDocument"]["text"])
    b = _validate_rerank_cfg(p.get("rerankingConfiguration"), "numberOfResults")
    if b is None:
        raise _bad("rerankingConfiguration is required.")
    n = min(int(b.get("numberOfResults", len(docs))), len(docs))
    q = qs[0]["textQuery"]["text"]
    out = [{"index": i, "relevanceScore": sc, "document": {"type": "TEXT", "textDocument": {"text": docs[i]}}} for i, sc in kc.rerank(q, docs, n)]
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


_FILTER_OPS = ("equals", "notEquals", "greaterThan", "greaterThanOrEquals", "lessThan", "lessThanOrEquals", "in", "notIn",
               "startsWith", "stringContains", "listContains")
_RERANK_MODELS = ("amazon.rerank-v1:0", "cohere.rerank-v3-5:0")


def _validate_filter(f, depth=0):
    """RetrievalFilter union rules: exactly one member; andAll/orAll hold 2..5 filters; typed values per operator."""
    if f is None:
        return
    if not isinstance(f, dict) or len(f) != 1:
        raise _bad("A retrieval filter must contain exactly one operator (equals, notEquals, greaterThan, greaterThanOrEquals, lessThan, "
                   "lessThanOrEquals, in, notIn, startsWith, stringContains, listContains, andAll or orAll).")
    (op, arg), = f.items()
    if op in ("andAll", "orAll"):
        if depth >= 2:
            raise _bad("Filters can be nested at most two levels deep.")
        if not isinstance(arg, list) or not 2 <= len(arg) <= 5:
            raise _bad(f"{op} needs between 2 and 5 filters.")
        for x in arg:
            _validate_filter(x, depth + 1)
        return
    if op not in _FILTER_OPS:
        raise _bad(f"Unknown retrieval filter operator '{op}'.")
    if not isinstance(arg, dict) or not isinstance(arg.get("key"), str) or not 1 <= len(arg["key"]) <= 200 or "value" not in arg:
        raise _bad(f"{op} needs a 'key' (1-200 characters) and a 'value'.")
    v = arg["value"]
    if op in ("in", "notIn"):
        if not isinstance(v, list) or not v or any(isinstance(x, (dict, list)) for x in v):
            raise _bad(f"{op} needs a non-empty list of strings or numbers.")
    elif op in ("startsWith", "stringContains", "listContains"):
        if not isinstance(v, str):
            raise _bad(f"{op} needs a string value.")
    elif op in ("greaterThan", "greaterThanOrEquals", "lessThan", "lessThanOrEquals"):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise _bad(f"{op} needs a numeric value.")
    elif isinstance(v, (dict,)) or (isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v)):
        raise _bad(f"{op} needs a string, number, boolean or list of strings.")


def _same_kind(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return True
    return type(a) is type(b)


def _match_filter(f, meta):
    if "andAll" in f:
        return all(_match_filter(x, meta) for x in f["andAll"])
    if "orAll" in f:
        return any(_match_filter(x, meta) for x in f["orAll"])
    for op in _FILTER_OPS:
        if op in f:
            key, val = f[op].get("key"), f[op].get("value")
            have = meta.get(key)
            if op == "notEquals":
                return have is None or not (_same_kind(have, val) and have == val)
            if op == "notIn":
                return have is None or not any(_same_kind(have, x) and have == x for x in val)
            if have is None:
                return False
            if op == "equals":
                return _same_kind(have, val) and have == val if not isinstance(have, list) else have == val
            if op == "in":
                return any(_same_kind(have, x) and have == x for x in val)
            if op in ("greaterThan", "greaterThanOrEquals", "lessThan", "lessThanOrEquals"):
                if isinstance(have, bool) or not isinstance(have, (int, float)):
                    return False
                return {"greaterThan": have > val, "greaterThanOrEquals": have >= val, "lessThan": have < val, "lessThanOrEquals": have <= val}[op]
            if op == "startsWith":
                return isinstance(have, str) and have.startswith(val)
            if op == "stringContains":      # a string containing the value, or a list of strings with a member containing it
                return (isinstance(have, str) and val in have) or (isinstance(have, list) and any(isinstance(x, str) and val in x for x in have))
            if op == "listContains":
                return isinstance(have, list) and val in have
    raise _bad("Unsupported retrieval filter")


def _implicit_filter(cfg, query, explicit):
    """implicitFilterConfiguration: the local chat model derives a metadata filter from the query (Bedrock uses a foundation model)."""
    attrs = (cfg or {}).get("metadataAttributes")
    if not isinstance(attrs, list) or not attrs or not (cfg or {}).get("modelArn"):
        raise _bad("implicitFilterConfiguration needs metadataAttributes and modelArn.")
    for a in attrs:
        if not a.get("key") or a.get("type") not in ("STRING", "NUMBER", "BOOLEAN", "STRING_LIST"):
            raise _bad("Each metadataAttribute needs a key and a type of STRING, NUMBER, BOOLEAN or STRING_LIST.")
    desc = "\n".join(f"- {a['key']} ({a['type']}): {a.get('description', '')}" for a in attrs)
    sysm = ("Derive a metadata filter from the user question. Reply with ONLY JSON: either {} when no attribute is implied, or one filter object like "
            '{"equals":{"key":"dept","value":"hvac"}}, or {"andAll":[f1,f2]} / {"orAll":[f1,f2]} (2 to 5 members). Operators: equals, notEquals, '
            "greaterThan, greaterThanOrEquals, lessThan, lessThanOrEquals, in, notIn, startsWith, stringContains, listContains. Allowed attributes:\n" + desc)
    r = llm.chat([{"role": "user", "content": query}], system=sysm, max_tokens=200, temperature=0.0)
    try:
        f, _parsed = llm.extract_json(r["text"])
    except Exception:  # noqa: BLE001
        f = None
    keys = {a["key"] for a in attrs}

    def ok(x):
        if not isinstance(x, dict) or len(x) != 1:
            return False
        (op, arg), = x.items()
        return all(ok(y) for y in arg) if op in ("andAll", "orAll") and isinstance(arg, list) else (op in _FILTER_OPS and isinstance(arg, dict) and arg.get("key") in keys)
    if not f or not ok(f):
        return explicit
    try:
        _validate_filter(f)
    except _Err:
        return explicit
    return {"andAll": [explicit, f]} if explicit else f


def _validate_rerank_cfg(rc, count_key):
    """rerankingConfiguration (Retrieve) / Rerank API config -> the bedrockRerankingConfiguration dict (+ type/model checks), or None."""
    if not rc:
        return None
    if rc.get("type") != "BEDROCK_RERANKING_MODEL":
        raise _bad("rerankingConfiguration.type must be BEDROCK_RERANKING_MODEL.")
    b = rc.get("bedrockRerankingConfiguration") or {}
    arn = (b.get("modelConfiguration") or {}).get("modelArn") or ""
    if not re.match(r"^arn:aws(?:-[a-z-]+)?:bedrock:[a-z0-9-]+::foundation-model/(%s)$" % "|".join(re.escape(m) for m in _RERANK_MODELS), arn):
        raise _bad("modelConfiguration.modelArn must be the ARN of a reranking model (%s)." % ", ".join(_RERANK_MODELS))
    n = b.get(count_key)
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 1000):
        raise _bad(f"{count_key} must be an integer between 1 and 1000.")
    mc = b.get("metadataConfiguration")
    if mc is not None and mc.get("selectionMode") not in ("SELECTIVE", "ALL"):
        raise _bad("metadataConfiguration.selectionMode must be SELECTIVE or ALL.")
    return b


def _rerank_text(text, meta, mc):
    """Document text handed to the reranker: the chunk, plus the metadata attributes selected by metadataConfiguration."""
    if not mc or not meta:
        return text
    if mc.get("selectionMode") == "ALL":
        keys = [k for k in meta if not k.startswith("x-amz-")]
    else:
        sel = mc.get("selectiveModeConfiguration") or {}
        inc = [x.get("fieldName") for x in sel.get("fieldsToInclude") or []]
        exc = {x.get("fieldName") for x in sel.get("fieldsToExclude") or []}
        keys = [k for k in meta if k in inc] if inc else [k for k in meta if k not in exc and not k.startswith("x-amz-")]
    return text + "".join(f"\n{k}: {meta[k]}" for k in keys)


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
    return {k: v for k, v in a.items() if k not in ("aliases", "kbs", "actionGroups", "sessions", "memories", "snapshots")}


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
    _check_agent_cfg(p)
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
    for f in ("guardrailConfiguration", "memoryConfiguration"):
        if p.get(f):
            a[f] = p[f]
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
                                              "kbs": [dict(k) for k in a["kbs"].values()],
                                              "actionGroups": json.loads(json.dumps(list(a["actionGroups"].values()))),
                                              "guardrailConfiguration": a.get("guardrailConfiguration"), "memoryConfiguration": a.get("memoryConfiguration")}
        rc = [{"agentVersion": ver}]
    alid = _rid()
    now = _iso()
    al = {"agentId": a["agentId"], "agentAliasId": alid, "agentAliasName": name,
          "agentAliasArn": f"arn:aws:bedrock:{_REGION}:{_ACCT}:agent-alias/{a['agentId']}/{alid}", "description": p.get("description", ""),
          "routingConfiguration": rc, "agentAliasStatus": "PREPARED", "createdAt": now, "updatedAt": now}
    a["aliases"][alid] = al
    return _j(202, {"agentAlias": al})


# ── action groups -> model tools ──
_MAX_STEPS = 6
_REPLAY: dict = {}      # Lambda results of the request in flight: Nano replays the whole handler per awaited model call (llm.arun)
_TYPES = {"string": "string", "number": "number", "integer": "integer", "boolean": "boolean", "array": "array"}


def _gr():
    try:
        from core import bedrock_guardrails_core as m
    except ImportError:
        import bedrock_guardrails_core as m  # type: ignore
    return m


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)[:60]


def _load_openapi(g):
    sch = g.get("apiSchema") or {}
    txt = sch.get("payload")
    if txt is None:
        raise _bad("apiSchema.s3 is not supported: pass the OpenAPI document inline as apiSchema.payload")
    try:
        doc = json.loads(txt)
    except (TypeError, ValueError):
        try:
            import yaml  # type: ignore
            doc = yaml.safe_load(txt)
        except ImportError:
            raise _bad("apiSchema.payload is not JSON and PyYAML is not available on this substrate; send the OpenAPI document as JSON")
        except Exception as e:  # noqa: BLE001
            raise _bad(f"apiSchema.payload is not valid OpenAPI JSON/YAML: {e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict) or not str(doc.get("openapi", "")).startswith("3"):
        raise _bad("apiSchema.payload must be an OpenAPI 3 document with a paths object")
    return doc


def _deref(doc, node):
    if isinstance(node, dict) and "$ref" in node and str(node["$ref"]).startswith("#/"):
        cur = doc
        for part in node["$ref"][2:].split("/"):
            cur = (cur or {}).get(part, {})
        return cur or {}
    return node or {}


def _jschema(spec, desc=""):
    spec = spec or {}
    t = _TYPES.get(spec.get("type", "string"), "string")
    out = {"type": t}
    d = spec.get("description") or desc
    if d:
        out["description"] = d
    if t == "array":
        out["items"] = {}
    return out


def _group_tools(g):
    """-> list of {name, description, parameters (JSON schema), kind, group, meta, executor} for one ENABLED action group."""
    if g.get("actionGroupState", "ENABLED") != "ENABLED":
        return []
    ex = g.get("actionGroupExecutor") or {}
    out = []
    gname = g["actionGroupName"]
    for fn in ((g.get("functionSchema") or {}).get("functions") or []):
        props, req = {}, []
        for pn, ps in (fn.get("parameters") or {}).items():
            props[pn] = _jschema(ps)
            if ps.get("required"):
                req.append(pn)
        out.append({"name": f"{_safe(gname)}__{_safe(fn['name'])}", "description": fn.get("description") or fn["name"],
                    "parameters": {"type": "object", "properties": props, "required": req}, "kind": "function", "group": gname,
                    "meta": {"function": fn["name"]}, "executor": ex})
    if g.get("apiSchema"):
        doc = _load_openapi(g)
        for path, item in doc["paths"].items():
            for verb, op in (item or {}).items():
                if verb.lower() not in ("get", "post", "put", "delete", "patch") or not isinstance(op, dict):
                    continue
                props, req, inbody = {}, [], []
                for prm in op.get("parameters") or []:
                    prm = _deref(doc, prm)
                    props[prm["name"]] = _jschema(_deref(doc, prm.get("schema")), prm.get("description", ""))
                    if prm.get("required"):
                        req.append(prm["name"])
                rb = _deref(doc, (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema"))
                for pn, ps in (rb.get("properties") or {}).items():
                    props[pn] = _jschema(_deref(doc, ps))
                    inbody.append(pn)
                    if pn in (rb.get("required") or []):
                        req.append(pn)
                oid = op.get("operationId") or f"{verb}_{path}"
                out.append({"name": f"{_safe(gname)}__{_safe(oid)}", "description": op.get("description") or op.get("summary") or oid,
                            "parameters": {"type": "object", "properties": props, "required": req}, "kind": "api", "group": gname,
                            "meta": {"apiPath": path, "httpMethod": verb.upper(), "inbody": inbody}, "executor": ex})
    return out


def _arg_text(v):
    return v if isinstance(v, str) else json.dumps(v)


def _arg_params(t, args):
    """Arguments -> Bedrock Parameter lists [{name,type,value}] (values are strings, as the real agent sends them): (plain, in request body)."""
    props = t["parameters"]["properties"]
    inb = set(t["meta"].get("inbody") or [])
    plain = [{"name": k, "type": props.get(k, {}).get("type", "string"), "value": _arg_text(v)} for k, v in args.items() if k not in inb]
    body = [{"name": k, "type": props.get(k, {}).get("type", "string"), "value": _arg_text(v)} for k, v in args.items() if k in inb]
    return plain, body


def _lambda_name(arn):
    return arn.split(":function:")[1].split(":")[0] if ":function:" in arn else arn


def _run_lambda(lam, t, args, ctx):
    """Invoke the action-group Lambda with the Bedrock Agents event; -> (result text, sessionAttributes|None, is_error)."""
    plain, body = _arg_params(t, args)
    ev = {"messageVersion": "1.0", "agent": {"name": ctx["agent"]["agentName"], "id": ctx["agent"]["agentId"], "alias": ctx["alias"], "version": ctx["version"]},
          "inputText": ctx["text"], "sessionId": ctx["sid"], "actionGroup": t["group"], "parameters": plain,
          "sessionAttributes": ctx["sess"].get("attrs") or {}, "promptSessionAttributes": ctx["prompt_attrs"]}
    if t["kind"] == "function":
        ev["function"] = t["meta"]["function"]
    else:
        ev["apiPath"], ev["httpMethod"] = t["meta"]["apiPath"], t["meta"]["httpMethod"]
        ev["requestBody"] = {"content": {"application/json": {"properties": body}}}
    key = json.dumps([ctx["sid"], ctx["req"], t["name"], args], sort_keys=True, default=str)
    if key in _REPLAY:
        return _REPLAY[key]
    if lam is None:
        res = ("Lambda is unavailable on this substrate", None, True)
    else:
        try:
            from core import lambda_core
        except ImportError:
            import lambda_core  # type: ignore
        r = lambda_core._invoke(lam, _lambda_name(t["executor"]["lambda"]), json.dumps(ev).encode())
        raw = (r.body or b"").decode("utf-8", "replace")
        hdrs = {str(k).lower() for k in (r.headers or {})}
        if r.status >= 400 or "x-amz-function-error" in hdrs:
            res = (raw[:2000], None, True)
        else:
            try:
                doc = json.loads(raw)
            except ValueError:
                doc = None
            resp = doc.get("response") if isinstance(doc, dict) else None
            if not isinstance(resp, dict):
                res = (raw[:4000], None, False)       # not the agent response contract: hand the model what the function returned
            else:
                rb = (resp.get("functionResponse") or {}).get("responseBody") if t["kind"] == "function" else resp.get("responseBody")
                txt = next((v.get("body", "") for v in (rb or {}).values() if isinstance(v, dict)), "")
                bad = t["kind"] == "api" and int(resp.get("httpStatusCode", 200)) >= 400
                res = (txt if isinstance(txt, str) else json.dumps(txt), doc.get("sessionAttributes"), bad)
    _REPLAY[key] = res
    return res


def _rc_inputs(t, args):
    plain, body = _arg_params(t, args)
    if t["kind"] == "function":
        return {"functionInvocationInput": {"actionGroup": t["group"], "actionInvocationType": "RESULT", "function": t["meta"]["function"], "parameters": plain}}
    d = {"actionGroup": t["group"], "actionInvocationType": "RESULT", "apiPath": t["meta"]["apiPath"], "httpMethod": t["meta"]["httpMethod"], "parameters": plain}
    if body:
        d["requestBody"] = {"content": {"application/json": body}}
    return {"apiInvocationInput": d}


def _rc_match(t, res):
    if t["kind"] == "function":
        f = res.get("functionResult")
        return bool(f) and f.get("actionGroup") == t["group"] and f.get("function") == t["meta"]["function"]
    x = res.get("apiResult")
    return bool(x) and x.get("actionGroup") == t["group"] and x.get("apiPath") == t["meta"]["apiPath"] and str(x.get("httpMethod", "")).upper() == t["meta"]["httpMethod"]


def _rc_text(res):
    body = (res.get("functionResult") or res.get("apiResult") or {}).get("responseBody") or {}
    return next((v.get("body", "") for v in body.values() if isinstance(v, dict)), "")


# ── session memory (SESSION_SUMMARY) ──
def _mem_cfg(snap):
    mc = snap.get("memoryConfiguration") or {}
    return mc if "SESSION_SUMMARY" in (mc.get("enabledMemoryTypes") or []) else None


def _memories(a, alias_id, mid):
    return a.setdefault("memories", {}).setdefault(alias_id, {}).setdefault(mid, [])


def _live_memories(a, alias_id, mid):
    now = time.time()
    return [m for m in (a.get("memories") or {}).get(alias_id, {}).get(mid, []) if m["_expires"] > now]


def _summarise(transcript):
    r = llm.chat([{"role": "user", "content": "Summarise this conversation in two or three sentences, keeping names, preferences and open requests:\n\n" + transcript}],
                 system="You write short factual conversation summaries.", max_tokens=200, temperature=0.2)
    return r["text"].strip()


def _memory_op(a, alias_id, method, query):
    if alias_id != "TSTALIASID" and alias_id not in a["aliases"]:
        raise _nf(f"Could not find resource: Alias {alias_id} of agent {a['agentId']}")
    q = query or {}
    mid = q.get("memoryId")
    if method == "GET":
        if q.get("memoryType") != "SESSION_SUMMARY":
            raise _bad("1 validation error detected: Value at 'memoryType' failed to satisfy constraint: Member must satisfy enum value set: [SESSION_SUMMARY]")
        if not mid:
            raise _bad("memoryId is required")
        items = sorted(_live_memories(a, alias_id, mid), key=lambda m: m["sessionSummary"]["sessionStartTime"], reverse=True)
        n = int(q.get("maxItems") or 100)
        off = int(q["nextToken"]) if str(q.get("nextToken") or "").isdigit() else 0
        doc = {"memoryContents": [{"sessionSummary": m["sessionSummary"]} for m in items[off:off + n]]}
        if off + n < len(items):
            doc["nextToken"] = str(off + n)
        return _j(200, doc)
    mem = (a.get("memories") or {}).get(alias_id, {})
    sid = q.get("sessionId")
    for k in ([mid] if mid else list(mem)):
        if k in mem:
            mem[k] = [m for m in mem[k] if m["sessionSummary"]["sessionId"] != sid] if sid else []
    return _j(202, {})


# ── guardrail / memory config validation (CreateAgent / UpdateAgent) ──
def _check_agent_cfg(p):
    g = p.get("guardrailConfiguration")
    if g is not None:
        if not g.get("guardrailIdentifier") or not g.get("guardrailVersion"):
            raise _bad("guardrailConfiguration requires guardrailIdentifier and guardrailVersion")
        gr = _gr()
        try:
            gr.resolve_policy(g["guardrailIdentifier"], str(g["guardrailVersion"]))
        except gr.GErr as e:
            raise _Err(e.code, e.msg, e.status)
    m = p.get("memoryConfiguration")
    if m is not None:
        types = m.get("enabledMemoryTypes")
        if not isinstance(types, list) or not types or any(t != "SESSION_SUMMARY" for t in types):
            raise _bad("memoryConfiguration.enabledMemoryTypes must be [SESSION_SUMMARY]")
        if not 0 <= int(m.get("storageDays", 30)) <= 365:
            raise _bad("memoryConfiguration.storageDays must be between 0 and 365")


def _check_action_group(p, update=False):
    if not update and not p.get("actionGroupName"):
        raise _bad("actionGroupName is required")
    if p.get("apiSchema") and p.get("functionSchema"):
        raise _bad("Provide either apiSchema or functionSchema, not both")
    ex = p.get("actionGroupExecutor")
    if ex is not None:
        if ex.get("customControl") is not None:
            if ex["customControl"] != "RETURN_CONTROL":
                raise _bad("actionGroupExecutor.customControl must be RETURN_CONTROL")
        elif not re.match(r"^arn:aws(-[a-z]+)*:lambda:[a-z0-9-]+:\d{12}:function:[A-Za-z0-9_-]+(:[A-Za-z0-9_$-]+)?$", str(ex.get("lambda") or "")):
            raise _bad("actionGroupExecutor.lambda must be a Lambda function ARN (or use customControl RETURN_CONTROL)")
    if p.get("apiSchema"):
        _load_openapi(p)
    fs = (p.get("functionSchema") or {}).get("functions")
    if p.get("functionSchema") is not None and (not isinstance(fs, list) or not fs):
        raise _bad("functionSchema.functions must list at least one function")
    for fn in fs or []:
        if not fn.get("name"):
            raise _bad("each function needs a name")
        for pn, ps in (fn.get("parameters") or {}).items():
            if ps.get("type") not in _TYPES:
                raise _bad(f"parameter {pn} of {fn['name']}: type must be one of {sorted(_TYPES)}")


def _action_group(a, p, gid=None):
    _check_action_group(p)
    now = _iso()
    g = {"agentId": a["agentId"], "agentVersion": "DRAFT", "actionGroupId": gid or _rid(), "actionGroupName": p["actionGroupName"], "description": p.get("description", ""),
         "actionGroupState": p.get("actionGroupState", "ENABLED"), "actionGroupExecutor": p.get("actionGroupExecutor"),
         "apiSchema": p.get("apiSchema"), "functionSchema": p.get("functionSchema"), "createdAt": now, "updatedAt": now}
    if p.get("parentActionGroupSignature"):
        g["parentActionGroupSignature"] = p["parentActionGroupSignature"]
    return g


# ── the orchestration loop ──
def _evt(kind, payload):
    try:
        from core import ai_models_core as am
    except ImportError:
        import ai_models_core as am  # type: ignore
    return am.eventstream_frame(kind, payload)


def _tid(n=0):
    return f"{_rid(8, string.ascii_lowercase + string.digits)}-{_rid(4, string.ascii_lowercase + string.digits)}-{n}"


def _unavailable(e):
    return {"status": 424, "headers": {"content-type": "application/json", "x-amzn-errortype": "DependencyFailedException"},
            "body": json.dumps({"message": f"{e} (the local model has not been started)"}).encode()}


def _invoke_agent(st, s3, aid, alias_id, sid, p, lam=None):
    try:
        out = _invoke_agent_run(st, s3, aid, alias_id, sid, p, lam)
    except llm.NeedAsync:
        raise                                         # the request will be replayed: keep the memoised Lambda results
    except BaseException:
        _REPLAY.clear()
        raise
    _REPLAY.clear()
    return out


def _invoke_agent_run(st, s3, aid, alias_id, sid, p, lam):
    a = _find_agent(st, aid)
    sstate = p.get("sessionState") or {}
    results = sstate.get("returnControlInvocationResults")
    text = (p.get("inputText") or "").strip()
    if not text and not results:
        raise _bad("inputText is required")
    if alias_id == "TSTALIASID":     # the built-in test alias runs the DRAFT version
        snap = {"instruction": a["instruction"], "foundationModel": a["foundationModel"], "kbs": list(a["kbs"].values()),
                "actionGroups": [dict(g) for g in a["actionGroups"].values()], "guardrailConfiguration": a.get("guardrailConfiguration"),
                "memoryConfiguration": a.get("memoryConfiguration")}
        version = "DRAFT"
        if a["agentStatus"] != "PREPARED":
            raise _conflict("The agent is not in PREPARED state; call PrepareAgent first")
    else:
        al = a["aliases"].get(alias_id)
        if not al:
            raise _nf(f"Could not find resource: Alias {alias_id} of agent {aid}")
        version = str(al["routingConfiguration"][0]["agentVersion"])
        snap = (a.get("snapshots") or {}).get(version)
        if not snap:
            raise _nf("Agent version not found")
    mid = p.get("memoryId")
    if mid is not None and not 1 <= len(mid) <= 100:
        raise _bad("memoryId must be between 1 and 100 characters")
    sess = a.setdefault("sessions", {}).get(sid)
    if isinstance(sess, list):
        sess = {"history": sess}
    sess = json.loads(json.dumps(sess)) if sess else {}          # work on a copy: committed only when the request completes (replay-safe)
    sess.setdefault("history", [])
    sess.setdefault("started", time.time())
    if sstate.get("sessionAttributes"):
        sess["attrs"] = dict(sstate["sessionAttributes"])
    ctx = {"agent": a, "alias": alias_id, "version": version, "sid": sid, "sess": sess, "text": text, "prompt_attrs": dict(sstate.get("promptSessionAttributes") or {}),
           "req": hashlib.md5(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()[:12]}
    trace_on = bool(p.get("enableTrace"))
    frames: list = []
    base = {"agentId": aid, "agentAliasId": alias_id, "agentVersion": version, "sessionId": sid}

    def tr(part, body):
        if trace_on:
            frames.append(_evt("trace", dict(base, eventTime=_iso(), trace={part: body})))

    tools = []
    for g in snap.get("actionGroups") or []:
        tools += _group_tools(g)
    reg = {t["name"]: t for t in tools}
    gcfg = snap.get("guardrailConfiguration")
    gr = _gr() if gcfg else None
    fm = snap["foundationModel"]
    infer = {"maximumLength": 400, "stopSequences": [], "temperature": 0.4, "topK": 250, "topP": 1.0}
    blocked_in = [False]

    def guard(txt, source):
        try:
            r = gr.evaluate(gr.resolve_policy(gcfg["guardrailIdentifier"], str(gcfg["guardrailVersion"])), txt, source)
        except gr.GErr as e:
            raise _Err(e.code, e.msg, e.status)
        tr("guardrailTrace", {"traceId": _tid(), "action": "INTERVENED" if r["action"] != "NONE" else "NONE",
                              ("inputAssessments" if source == "INPUT" else "outputAssessments"): [r["assessment"]] if r["assessment"] else []})
        return r

    def commit():
        hdr = {"content-type": "application/vnd.amazon.eventstream", "x-amz-bedrock-agent-session-id": sid, "x-amzn-bedrock-agent-content-type": "application/json"}
        if mid:
            hdr["x-amz-bedrock-agent-memory-id"] = mid
        return {"status": 200, "headers": hdr, "body": b"".join(frames)}

    def finish(final, refs=None):
        refs = refs or []
        tr("postProcessingTrace", {"modelInvocationInput": {"traceId": _tid(), "type": "POST_PROCESSING", "foundationModel": fm,
                                                           "text": "Vyomi post-processing: deterministic finalisation of the orchestration answer (no model call)."}})
        tr("postProcessingTrace", {"modelInvocationOutput": {"traceId": _tid(), "parsedResponse": {"text": final}, "rawResponse": {"content": final}}})
        if gcfg and final and not blocked_in[0]:
            r = guard(final, "OUTPUT")
            final = r["text"] if r["action"] != "NONE" else final
        part = {"bytes": base64.b64encode(final.encode()).decode()}
        if refs:
            part["attribution"] = {"citations": [{"generatedResponsePart": {"textResponsePart": {"text": final, "span": {"start": 0, "end": len(final)}}},
                                                  "retrievedReferences": [{k: v for k, v in x.items() if k != "score"} for x in refs[:3]]}]}
        frames.append(_evt("chunk", part))
        sess["history"] += [{"role": "user", "content": ctx["text"]}, {"role": "assistant", "content": final}]
        del sess["history"][:-20]
        sess["pending"] = None
        mc = _mem_cfg(snap)
        if p.get("endSession"):
            if mid and mc:
                days = int(mc.get("storageDays", 30))
                tx = "\n".join(f"{m['role']}: {m['content']}" for m in sess["history"])
                ent = {"sessionId": sid, "memoryId": mid, "sessionStartTime": _iso(sess["started"]), "sessionExpiryTime": _iso(time.time() + days * 86400),
                       "summaryText": _summarise(tx)}
                lst = _memories(a, alias_id, mid)
                lst[:] = [m for m in lst if m["sessionSummary"]["sessionId"] != sid] + [{"sessionSummary": ent, "_expires": time.time() + days * 86400}]
                keep = int((mc.get("sessionSummaryConfiguration") or {}).get("maxRecentSessions", 20))
                lst[:] = sorted(lst, key=lambda m: m["sessionSummary"]["sessionStartTime"])[-keep:]
            a["sessions"].pop(sid, None)
        else:
            a["sessions"][sid] = sess
        return commit()

    refs, kbctx = [], ""
    pend = sess.get("pending")
    if results:                                      # ── continuation of a RETURN_CONTROL turn
        if not pend or pend.get("invocationId") != sstate.get("invocationId"):
            raise _bad("sessionState.invocationId does not match a pending RETURN_CONTROL invocation of this session")
        msgs = list(pend["msgs"])
        text = ctx["text"] = pend["text"]
        for call in pend["calls"]:
            t = reg.get(call["name"])
            res = next((r for r in results if t and _rc_match(t, r)), None)
            if res is None:
                raise _bad(f"returnControlInvocationResults is missing a result for {call['name']}")
            out = ("ERROR: " if (res.get("functionResult") or res.get("apiResult") or {}).get("responseState") == "FAILURE" else "") + _rc_text(res)
            msgs.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": out})
            tr("orchestrationTrace", {"observation": {"traceId": _tid(), "type": "ACTION_GROUP", "actionGroupInvocationOutput": {"text": _rc_text(res)}}})
        msgs += pend.get("done", [])
        refs = pend.get("refs") or []
        system = pend["system"]
        step0 = pend.get("step", 1)
    else:
        sess["pending"] = None                        # a new user turn abandons an unanswered RETURN_CONTROL request
        if gcfg:
            r = guard(text, "INPUT")
            if r["blocked"]:
                blocked_in[0] = True
                return finish(r["text"])
            text = ctx["text"] = r["text"] if r["action"] != "NONE" else text
        nkb = sum(1 for k in snap["kbs"] if k.get("knowledgeBaseState", "ENABLED") == "ENABLED")
        tr("preProcessingTrace", {"modelInvocationInput": {"traceId": _tid(), "type": "PRE_PROCESSING", "foundationModel": fm, "inferenceConfiguration": infer,
                                                           "text": "Vyomi pre-processing: input checks only (no model call)."}})
        tr("preProcessingTrace", {"modelInvocationOutput": {"traceId": _tid(), "parsedResponse": {"isValid": True, "rationale": (
            f"Input accepted ({len(text)} chars); guardrail {'applied' if gcfg else 'not configured'}; {len(tools)} action tool(s) and {nkb} knowledge base(s) available.")}}})
        for k in snap["kbs"]:
            if k.get("knowledgeBaseState", "ENABLED") != "ENABLED" or k["knowledgeBaseId"] not in st["kbs"]:
                continue
            tr("orchestrationTrace", {"invocationInput": {"traceId": _tid(), "invocationType": "KNOWLEDGE_BASE",
                                                          "knowledgeBaseLookupInput": {"knowledgeBaseId": k["knowledgeBaseId"], "text": text}}})
            res = _retrieve(st["kbs"][k["knowledgeBaseId"]], text, 3)
            tr("orchestrationTrace", {"observation": {"traceId": _tid(), "type": "KNOWLEDGE_BASE", "knowledgeBaseLookupOutput": {"retrievedReferences": [
                {kk: vv for kk, vv in r2.items() if kk != "score"} for r2 in res]}}})
            refs += res
            kbctx += "\n".join(r2["content"]["text"] for r2 in res) + "\n"
        system = snap["instruction"]
        if kbctx.strip():
            system += "\n\nUse these knowledge base passages when relevant:\n" + kbctx
        if mid and _mem_cfg(snap):
            ms = sorted(_live_memories(a, alias_id, mid), key=lambda m: m["sessionSummary"]["sessionStartTime"])
            if ms:
                system += "\n\nSummaries of this user's previous sessions:\n" + "\n".join("- " + m["sessionSummary"]["summaryText"] for m in ms)
        if ctx["prompt_attrs"]:
            system += "\n\nPrompt session attributes: " + json.dumps(ctx["prompt_attrs"])
        msgs = list(sess["history"]) + [{"role": "user", "content": text}]
        step0 = 1
    try:
        final = None
        ltools = [{"name": t["name"], "description": t["description"], "parameters": t["parameters"]} for t in tools] or None
        for step in range(step0, _MAX_STEPS + 1):
            tid = _tid(step)
            tr("orchestrationTrace", {"modelInvocationInput": {"traceId": tid, "type": "ORCHESTRATION", "foundationModel": fm, "inferenceConfiguration": infer,
                                                               "text": json.dumps({"system": system, "messages": msgs, "tools": [t["name"] for t in tools]})}})
            r = llm.chat(msgs, system=system, max_tokens=400, temperature=0.4, tools=ltools, tool_choice="auto" if ltools else None)
            calls = r.get("tool_calls") or []
            tr("orchestrationTrace", {"modelInvocationOutput": {"traceId": tid, "rawResponse": {"content": r["text"] or json.dumps({"tool_calls": calls})},
                                                                "metadata": {"usage": {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"]}}}})
            if not calls:
                final = r["text"]
                tr("orchestrationTrace", {"observation": {"traceId": _tid(), "type": "FINISH", "finalResponse": {"text": final}}})
                break
            for c in calls:      # llm_core already constrained + validated the call; re-check against OUR schema before anything is invoked
                t = reg.get(c["name"])
                errs = ["unknown tool"] if not t else llm.validate(t["parameters"], c["arguments"])
                if errs:
                    raise llm.LlmStructuredError(f"tool call {c['name']} is invalid: {'; '.join(errs[:3])}")
            msgs.append({"role": "assistant", "content": r["text"] or "", "tool_calls": calls})
            tr("orchestrationTrace", {"rationale": {"traceId": tid, "text": (r["text"] or "").strip() or
                                                    "Selected " + ", ".join(f"{c['name']}({json.dumps(c['arguments'])})" for c in calls) + " via schema-constrained tool-call output."}})
            rc, done = [], []
            for c in calls:
                t = reg[c["name"]]
                plain, body = _arg_params(t, c["arguments"])
                is_rc = t["executor"].get("customControl") == "RETURN_CONTROL"
                agi = {"actionGroupName": t["group"], "parameters": plain, "executionType": "RETURN_CONTROL" if is_rc else "LAMBDA"}
                agi.update({"function": t["meta"]["function"]} if t["kind"] == "function" else {"apiPath": t["meta"]["apiPath"], "verb": t["meta"]["httpMethod"]})
                if body:
                    agi["requestBody"] = {"content": {"application/json": body}}
                tr("orchestrationTrace", {"invocationInput": {"traceId": tid, "invocationType": "ACTION_GROUP", "actionGroupInvocationInput": agi}})
                if is_rc:
                    rc.append((c, t))
                    continue
                if not t["executor"].get("lambda"):
                    raise _bad(f"Action group {t['group']} has no executor: set a Lambda ARN or customControl RETURN_CONTROL")
                out, sattrs, is_err = _run_lambda(lam, t, c["arguments"], ctx)
                if sattrs:
                    sess["attrs"] = sattrs
                tr("orchestrationTrace", {"observation": {"traceId": _tid(), "type": "ACTION_GROUP", "actionGroupInvocationOutput": {"text": out}}})
                done.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": ("ERROR: " if is_err else "") + out})
            if rc:
                invid = _rid(16, string.ascii_lowercase + string.digits)
                sess["pending"] = {"invocationId": invid, "msgs": msgs, "text": text, "system": system, "refs": refs, "step": step + 1,
                                   "calls": [{"id": c["id"], "name": c["name"]} for c, _t in rc], "done": done}
                a["sessions"][sid] = sess
                frames.append(_evt("returnControl", {"invocationId": invid, "invocationInputs": [_rc_inputs(t, c["arguments"]) for c, t in rc]}))
                return commit()
            msgs += done
        if final is None:
            final = "Sorry, I am unable to assist you with this request."
            tr("failureTrace", {"traceId": _tid(), "failureReason": f"The agent did not reach a final answer within {_MAX_STEPS} orchestration steps."})
        return finish(final, refs)
    except llm.LlmStructuredError as e:
        tr("failureTrace", {"traceId": _tid(), "failureReason": str(e)})
        return finish("Sorry, I am unable to assist you with this request.", refs)
    except llm.LlmUnavailable as e:
        return _unavailable(e)


# ═══════════════════════════ dispatch: bedrock-agent / agent-runtime ═══════════════════════════
def handles(path: str) -> bool:
    p = path.lower()
    return bool(re.match(r"^/(agents|knowledgebases|retrieveandgenerate|rerank|_vyomi/kb)(/|$)", p))


def dispatch(s3, method, path, query, headers, body, lam=None):
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
            return _invoke_agent(st, s3, segs[1], segs[3], segs[5], p, lam)
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
                        _check_agent_cfg(p)
                        a.update(agentName=p["agentName"], agentResourceRoleArn=p["agentResourceRoleArn"], updatedAt=_iso(), agentStatus="NOT_PREPARED")
                        for f in ("foundationModel", "instruction", "description", "idleSessionTTLInSeconds", "guardrailConfiguration", "memoryConfiguration"):
                            if f in p:
                                a[f] = p[f]
                        return _j(202, {"agent": _agent_view(a)})
                    if method == "DELETE":
                        if a["aliases"] and (query or {}).get("skipResourceInUseCheck") != "true":
                            raise _conflict("Agent has aliases; delete them first or set skipResourceInUseCheck")
                        del st["agents"][a["agentId"]]
                        return _j(202, {"agentId": a["agentId"], "agentStatus": "DELETING"})
                elif low[2] == "agentaliases" and len(low) == 5 and low[4] == "memories" and method in ("GET", "DELETE"):
                    return _memory_op(a, segs[3], method, query)
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
                    elif low[4] in ("actiongroups", "agentactiongroups"):   # the real SDK path is .../actiongroups/; the old spelling is kept
                        if len(low) == 5 and method == "PUT":
                            g = _action_group(a, p)
                            a["actionGroups"][g["actionGroupId"]] = g
                            a["agentStatus"] = "NOT_PREPARED"
                            return _j(200, {"agentActionGroup": g})
                        if len(low) == 6:
                            g = a["actionGroups"].get(segs[5])
                            if not g:
                                raise _nf(f"Could not find resource: ActionGroup {segs[5]}")
                            if method == "GET":
                                return _j(200, {"agentActionGroup": g})
                            if method == "PUT":
                                n = _action_group(a, p, g["actionGroupId"])
                                n["createdAt"] = g["createdAt"]
                                a["actionGroups"][g["actionGroupId"]] = n
                                a["agentStatus"] = "NOT_PREPARED"
                                return _j(200, {"agentActionGroup": n})
                            if method == "DELETE":
                                del a["actionGroups"][g["actionGroupId"]]
                                a["agentStatus"] = "NOT_PREPARED"
                                return _j(204, None)
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
