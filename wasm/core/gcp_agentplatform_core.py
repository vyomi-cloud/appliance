# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Gemini Enterprise Agent Platform extras (Vertex AI) - substrate-independent, Pyodide-loadable, pure Python.

A thin WIRE ADAPTER: the engines are existing OSS / seams, nothing is hand-built beyond request and response shapes.

  RAG Engine        aiplatform `ragCorpora` / `ragFiles` / `locations/L:retrieveContexts`   chunking + BM25 = core/knowledge_core (SQLite FTS5)
  Vertex AI Search  discoveryengine `dataStores` / `documents` / `engines` / `servingConfigs:search`   BM25 = core/knowledge_core (SQLite FTS5)
  Memory Bank       `reasoningEngines/ID/memories` (+ :retrieve, :generate)                 embeddings + chat = core/llm_core (local model seam)
  Sessions          `reasoningEngines/ID/sessions` (+ events) over the Agent Engine's own multi-turn sessions (core/gcp_agentengine_core)
  Evaluation        `locations/L:evaluateInstances` (exactMatch / bleu / rouge) and `evaluationRuns` (generate with the local model, then score)

State lives in the persisted account bag, like every other core. RAG Engine ingests through `ragFiles:upload` (JSON `text` / base64
`content`, or the real multipart/related and multipart/form-data bodies) and `ragFiles:import` from the SIMULATED Cloud Storage
(`gcsSource.uris`, object or prefix); chunks are embedded with the local embedding seam (core/llm_core.embed) and retrieved by exact cosine
kNN (default, like Google's), hybrid dense + BM25 (`ragRetrievalConfig.hybridSearch.alpha`, weighted RRF) with distance/similarity
thresholds, and optional embedding+lexical reranking. Vertex AI Search ranks by hybrid BM25 + embedding RRF and answers `summarySpec`
with a cited summary from the local chat model. Honest limits: no HNSW (exact scan), no Drive / Slack / Jira / SharePoint / BigQuery
sources, the reranker is not Google's rank service, summaries are the small local model's (503-free: `summarySkippedReasons` says when no model
runs), no PDF layout parser (pure-Python text extraction), memories are ranked by cosine over the seam's embeddings (the labelled
`vyomi-hash-embed` fallback when no embedding model runs); `memories:generate` asks the local chat model for facts, so quality is the
small model's and it answers 503 when no model backend is up.
"""
from __future__ import annotations

import base64
import json
import math
import random
import re
import time
import uuid
import zlib
from datetime import datetime, timezone

try:
    from core import knowledge_core as kc
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import knowledge_core as kc  # type: ignore
    import llm_core as llm  # type: ignore

_V = r"(?:v1|v1beta1|v1alpha|v1beta)"
RAG = re.compile(r"^/(%s)/projects/([^/]+)/locations/([^/]+)/ragCorpora(?:/([^/:]+)(?:/ragFiles(?:/([^/:]+))?|/operations/([^/:]+))?)?(:[A-Za-z]+)?/?$" % _V)
RAG_FILES_VERB = re.compile(r"^/(%s)/projects/([^/]+)/locations/([^/]+)/ragCorpora/([^/:]+)/ragFiles(:[A-Za-z]+)$" % _V)
UPLOAD = re.compile(r"^/upload/(%s)/projects/([^/]+)/locations/([^/]+)/ragCorpora/([^/:]+)/ragFiles:upload$" % _V)
LOC_VERB = re.compile(r"^/(%s)/projects/([^/]+)/locations/([^/]+):(retrieveContexts|evaluateInstances)$" % _V)
EVAL = re.compile(r"^/(%s)/projects/([^/]+)/locations/([^/]+)/evaluationRuns(?:/([^/:]+))?(:cancel)?/?$" % _V)
CHILD = re.compile(r"^/(%s)/projects/([^/]+)/locations/([^/]+)/reasoningEngines/([^/:]+)/(memories|sessions)(?:/([^/:]+))?(?:/(events))?(:[A-Za-z]+)?/?$" % _V)
DE = re.compile(r"^/(%s)/projects/([^/]+)/locations/([^/]+)/collections/([^/]+)/(dataStores|engines)(?:/([^/:]+))?"
                r"(?:/branches/([^/]+)/documents(?:/([^/:]+))?|/servingConfigs/([^/:]+))?(:[A-Za-z]+)?/?$" % _V)
DE_OP = re.compile(r"^/(%s)/projects/([^/]+)/locations/([^/]+)/collections/([^/]+)/(?:dataStores|engines)/[^/]+/(?:branches/[^/]+/)?operations/[^/]+$" % _V)


class _Err(Exception):
    def __init__(self, status, st, msg):
        self.status, self.st, self.msg = status, st, msg


def handles(path):
    p = path.split("?", 1)[0]
    return bool(RAG.match(p) or RAG_FILES_VERB.match(p) or UPLOAD.match(p) or LOC_VERB.match(p) or EVAL.match(p) or DE.match(p) or DE_OP.match(p))


def handles_child(path):
    return bool(CHILD.match(path.split("?", 1)[0]))


def _am():
    try:
        from core import ai_models_core as m
    except ImportError:  # pragma: no cover
        import ai_models_core as m  # type: ignore
    return m


def _iso():
    return datetime.fromtimestamp(time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _state(store):
    st = store.account.setdefault("agent_platform", {})
    for k in ("corpora", "stores", "des_engines", "memories", "runs"):
        st.setdefault(k, {})
    return st


def _body(raw):
    if not raw:
        return {}
    try:
        p = json.loads(raw)
    except ValueError:
        raise _Err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(p, dict):
        raise _Err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    return p


def _out(status, obj):
    return _am()._j(status, obj)


def _lro(name, response, rtype, done=True):
    meta = {"@type": "type.googleapis.com/google.cloud.aiplatform.v1.GenericOperationMetadata", "createTime": _iso(), "updateTime": _iso()}
    op = {"name": name + "/operations/" + uuid.uuid4().hex[:16], "metadata": meta, "done": done}
    op["response"] = dict(response or {}, **{"@type": "type.googleapis.com/" + rtype}) if response is not None else {"@type": "type.googleapis.com/google.protobuf.Empty"}
    return op


def _page(items, q, key):
    size = max(1, min(int(q.get("pageSize") or 100), 1000))
    start = int(q.get("pageToken") or 0)
    page = items[start:start + size]
    out = {key: page} if page else {}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _numid():
    return str(random.randint(10 ** 18, 10 ** 19 - 1))


# ═════════════════════════════ entry points ═════════════════════════════
def dispatch(store, method, path, query=None, headers=None, body=b"", gcs=None):
    method = method.upper()
    path = path.split("?", 1)[0]
    q = query or {}
    hd = {(k or "").lower(): v for k, v in (headers or {}).items()}
    try:
        st = _state(store)
        m = UPLOAD.match(path)
        if m and method == "POST":
            ctype = hd.get("content-type", "")
            payload = _multipart(ctype, body) if ctype.lower().startswith("multipart/") else _body(body)
            return _rag_upload(st, m.group(3), m.group(4), path, payload, _raw=body)
        m = RAG_FILES_VERB.match(path)
        if m and method == "POST":
            if m.group(5) != ":import":
                raise _Err(404, "NOT_FOUND", "Unsupported ragFiles operation %s." % m.group(5))
            return _rag_import(st, m.group(2), m.group(3), m.group(4), _body(body), gcs)
        m = LOC_VERB.match(path)
        if m:
            if method != "POST":
                raise _Err(405, "METHOD_NOT_ALLOWED", "Use POST.")
            return _retrieve(st, m.group(2), m.group(3), _body(body)) if m.group(4) == "retrieveContexts" else _evaluate_instances(_body(body))
        m = RAG.match(path)
        if m:
            return _rag(st, method, m, _body(body), q)
        m = EVAL.match(path)
        if m:
            return _eval_runs(st, method, m, _body(body), q)
        m = DE_OP.match(path)
        if m:
            return _out(200, {"name": path, "done": True, "response": {"@type": "type.googleapis.com/google.protobuf.Empty"}})
        m = DE.match(path)
        if m:
            return _de(st, method, m, _body(body), q, gcs)
        raise _Err(404, "NOT_FOUND", "Unsupported Agent Platform path: " + path)
    except _Err as e:
        return _am()._g_err(e.status, e.st, e.msg)
    except llm.LlmUnavailable as e:
        return _am()._g_err(503, "UNAVAILABLE", str(e))


def dispatch_child(store, ae_state, method, path, query=None, headers=None, body=b""):
    """memories / sessions under a reasoningEngine; `ae_state` = the Agent Engine state ({"engines": ...})."""
    method = method.upper()
    path = path.split("?", 1)[0]
    try:
        st = _state(store)
        m = CHILD.match(path)
        ver, proj, loc, eid, kind, cid, events, verb = m.groups()
        ename = f"projects/{proj}/locations/{loc}/reasoningEngines/{eid}"
        eng = ae_state["engines"].get(ename)
        if not eng:
            raise _Err(404, "NOT_FOUND", f"Reasoning Engine `{ename}` not found.")
        if kind == "memories":
            return _memories(st, method, ename, cid, verb, _body(body), query or {})
        return _sessions(eng, method, ename, cid, events, verb, _body(body), query or {})
    except _Err as e:
        return _am()._g_err(e.status, e.st, e.msg)
    except llm.LlmUnavailable as e:
        return _am()._g_err(503, "UNAVAILABLE", str(e))


# ═════════════════════════════ sessions ═════════════════════════════
def _sess_view(eng, ename, s):
    return {"name": f"{ename}/sessions/{s['id']}", "userId": s["userId"], "sessionState": s["state"], "updateTime": datetime.fromtimestamp(s["lastUpdateTime"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "createTime": s.get("createTime", _iso())}


def _sessions(eng, method, ename, sid, events, verb, p, q):
    S = eng["_sessions"]
    if sid is None:
        if method == "POST":
            uid = p.get("userId")
            if not uid:
                raise _Err(400, "INVALID_ARGUMENT", "session.user_id is required.")
            new = str(p.get("sessionId") or q.get("sessionId") or random.randint(10 ** 17, 10 ** 18 - 1))
            S[new] = {"id": new, "appName": ename.rsplit("/", 1)[-1], "userId": uid, "state": p.get("sessionState") or {}, "events": [], "lastUpdateTime": time.time(), "createTime": _iso()}
            return _out(200, _lro(ename + "/sessions/" + new, _sess_view(eng, ename, S[new]), "google.cloud.aiplatform.v1beta1.Session"))
        if method == "GET":
            items = [_sess_view(eng, ename, s) for s in S.values()]
            flt = q.get("filter") or ""
            mf = re.match(r'^\s*user_id\s*=\s*"?([^"]*)"?\s*$', flt)
            if mf:
                items = [i for i in items if i["userId"] == mf.group(1)]
            return _out(200, _page(items, q, "sessions"))
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    s = S.get(sid)
    if not s:
        raise _Err(404, "NOT_FOUND", f"Session {ename}/sessions/{sid} not found.")
    if events:
        evs = [{"name": f"{ename}/sessions/{sid}/events/{e['id']}", "author": e.get("author"), "invocationId": e.get("invocation_id"),
                "timestamp": datetime.fromtimestamp(e.get("timestamp", time.time()), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "content": e.get("content")} for e in s["events"]]
        return _out(200, _page(evs, q, "sessionEvents"))
    if method == "GET":
        return _out(200, _sess_view(eng, ename, s))
    if method == "DELETE":
        del S[sid]
        return _out(200, _lro(ename + "/sessions/" + sid, None, "google.protobuf.Empty"))
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


# ═════════════════════════════ memory bank ═════════════════════════════
def _mem_view(mem):
    return {k: v for k, v in mem.items() if not k.startswith("_")}


def _scope_ok(mem, scope):
    return all(mem.get("scope", {}).get(k) == v for k, v in (scope or {}).items())


def _memories(st, method, ename, mid, verb, p, q):
    M = st["memories"].setdefault(ename, {})
    if verb == ":retrieve":
        scope = p.get("scope") or {}
        if not scope:
            raise _Err(400, "INVALID_ARGUMENT", "scope is required (e.g. {\"user_id\": \"u1\"}).")
        pool = [m for m in M.values() if _scope_ok(m, scope)]
        sp = p.get("similaritySearchParams")
        if sp:
            top = int(sp.get("topK") or 3)
            e = llm.embed([sp.get("searchQuery") or ""])["vectors"][0]
            ranked = sorted(((1 - llm.cosine(e, m["_vec"]), m) for m in pool if m.get("_vec")), key=lambda x: x[0])[:top]
            return _out(200, {"retrievedMemories": [{"memory": _mem_view(m), "distance": round(d, 6)} for d, m in ranked]})
        top = int((p.get("simpleRetrievalParams") or {}).get("pageSize") or 100)
        return _out(200, {"retrievedMemories": [{"memory": _mem_view(m)} for m in pool[:top]]})
    if verb == ":generate":
        scope = p.get("scope") or {}
        if not scope:
            raise _Err(400, "INVALID_ARGUMENT", "scope is required.")
        evs = (p.get("directContentsSource") or {}).get("events") or []
        text = "\n".join(f"{(e.get('content') or {}).get('role', 'user')}: " + "".join(x.get("text", "") for x in (e.get("content") or {}).get("parts") or []) for e in evs).strip()
        if not text:
            raise _Err(400, "INVALID_ARGUMENT", "directContentsSource.events must contain at least one content with text.")
        r = llm.chat([{"role": "user", "content": "Conversation:\n" + text + "\n\nList the durable facts about the user worth remembering, one per line, no numbering. "
                                                                              "If there are none, answer NONE."}],
                     system="You extract short standalone facts about a user from a conversation.", max_tokens=200, temperature=0.0)
        facts = [re.sub(r"^[-*\d.\s]+", "", ln).strip() for ln in str(r.get("text") or r.get("content") or "").splitlines()]
        facts = [f for f in facts if f and f.upper() != "NONE"][:8]
        out = []
        for f in facts:
            mem = _new_mem(ename, f, scope)
            M[mem["name"].rsplit("/", 1)[-1]] = mem
            out.append({"memory": _mem_view(mem), "action": "CREATED"})
        return _out(200, _lro(ename, {"generatedMemories": out}, "google.cloud.aiplatform.v1beta1.GenerateMemoriesResponse"))
    if mid is None:
        if method == "POST":
            fact = p.get("fact")
            if not isinstance(fact, str) or not fact.strip():
                raise _Err(400, "INVALID_ARGUMENT", "memory.fact must be a non-empty string.")
            scope = p.get("scope") or {}
            if not isinstance(scope, dict) or not scope:
                raise _Err(400, "INVALID_ARGUMENT", "memory.scope is required (e.g. {\"user_id\": \"u1\"}).")
            mem = _new_mem(ename, fact.strip(), scope, p.get("displayName"))
            M[mem["name"].rsplit("/", 1)[-1]] = mem
            return _out(200, _lro(mem["name"], _mem_view(mem), "google.cloud.aiplatform.v1beta1.Memory"))
        if method == "GET":
            items = [_mem_view(m) for m in M.values()]
            flt = q.get("filter") or ""
            for k, v in re.findall(r'scope\.(\w+)\s*=\s*"?([^"\s]+)"?', flt):
                items = [i for i in items if i.get("scope", {}).get(k) == v]
            return _out(200, _page(items, q, "memories"))
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    mem = M.get(mid)
    if not mem:
        raise _Err(404, "NOT_FOUND", f"Memory {ename}/memories/{mid} not found.")
    if method == "GET":
        return _out(200, _mem_view(mem))
    if method == "DELETE":
        del M[mid]
        return _out(200, _lro(ename + "/memories/" + mid, None, "google.protobuf.Empty"))
    if method == "PATCH":
        if isinstance(p.get("fact"), str) and p["fact"].strip():
            mem["fact"], mem["_vec"] = p["fact"].strip(), llm.embed([p["fact"]])["vectors"][0]
            mem["updateTime"] = _iso()
        return _out(200, _lro(mem["name"], _mem_view(mem), "google.cloud.aiplatform.v1beta1.Memory"))
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _new_mem(ename, fact, scope, display=None):
    now = _iso()
    mid = _numid()
    return {"name": f"{ename}/memories/{mid}", "displayName": display or fact[:60], "fact": fact, "scope": {str(k): str(v) for k, v in scope.items()},
            "createTime": now, "updateTime": now, "_vec": llm.embed([fact])["vectors"][0]}


# ═════════════════════════════ RAG Engine ═════════════════════════════
def _rag(st, method, m, p, q):
    ver, proj, loc, cid, fid, opid, verb = m.groups()
    parent = f"projects/{proj}/locations/{loc}"
    path_has_files = "/ragFiles" in m.string
    if cid is None:
        if method == "POST" and not verb:
            dn = p.get("displayName")
            if not isinstance(dn, str) or not dn or len(dn) > 128:
                raise _Err(400, "INVALID_ARGUMENT", "rag_corpus.display_name: must be set and at most 128 characters.")
            if any(c["displayName"] == dn for n, c in st["corpora"].items() if n.startswith(parent + "/")):
                raise _Err(409, "ALREADY_EXISTS", f"A RagCorpus with display name `{dn}` already exists.")
            name = f"{parent}/ragCorpora/{_numid()[:16]}"
            now = _iso()
            c = {"name": name, "displayName": dn, "description": p.get("description", ""), "createTime": now, "updateTime": now, "corpusStatus": {"state": "ACTIVE"},
                 "vectorDbConfig": p.get("vectorDbConfig") or {"ragManagedDb": {}}, "_files": {}}
            st["corpora"][name] = c
            return _out(200, _lro(name, _corpus_view(c), "google.cloud.aiplatform.v1.RagCorpus"))
        if method == "GET" and not verb:
            items = sorted((c for n, c in st["corpora"].items() if n.startswith(parent + "/")), key=lambda c: c["createTime"])
            return _out(200, _page([_corpus_view(c) for c in items], q, "ragCorpora"))
        raise _Err(404, "NOT_FOUND", "Unsupported RAG Engine operation.")
    name = f"{parent}/ragCorpora/{cid}"
    c = st["corpora"].get(name)
    if opid:
        return _out(200, {"name": f"{name}/operations/{opid}", "done": True, "response": {"@type": "type.googleapis.com/google.protobuf.Empty"}})
    if not c:
        raise _Err(404, "NOT_FOUND", f"RagCorpus `{name}` not found.")
    if path_has_files:
        if fid is None:
            if method == "GET":
                files = sorted((_file_view(f) for f in c["_files"].values()), key=lambda f: f["createTime"])
                return _out(200, _page(files, q, "ragFiles"))
            raise _Err(404, "NOT_FOUND", "Unsupported ragFiles operation.")
        f = c["_files"].get(fid)
        if not f:
            raise _Err(404, "NOT_FOUND", f"RagFile `{name}/ragFiles/{fid}` not found.")
        if method == "GET":
            return _out(200, _file_view(f))
        if method == "DELETE":
            del c["_files"][fid]
            return _out(200, _lro(name, None, "google.protobuf.Empty"))
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    if method == "GET":
        return _out(200, _corpus_view(c))
    if method == "DELETE":
        del st["corpora"][name]
        return _out(200, _lro(name, None, "google.protobuf.Empty"))
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _corpus_view(c):
    v = _view(c)
    v["vyomiStats"] = {"files": len(c["_files"]), "chunks": sum(len(f["_chunks"]) for f in c["_files"].values()),
                       "embedded": sum(len(f.get("_vecs") or []) for f in c["_files"].values())}
    return v


def _file_view(f):
    v = _view(f)
    v["sizeBytes"] = str(f["_size"])
    v["vyomiChunks"] = len(f["_chunks"])
    return v


def _multipart(ctype, raw):
    """multipart/related (metadata JSON + file bytes, the RAG Engine upload) or multipart/form-data (`metadata` + `file`) -> upload payload."""
    from email.parser import BytesParser
    from email.policy import HTTP
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + (raw or b""))
    parts = list(msg.iter_parts()) if msg.is_multipart() else []
    if len(parts) < 2:
        raise _Err(400, "INVALID_ARGUMENT", "A multipart upload needs a metadata part and a file part.")
    meta, data, fname = None, None, None
    for i, part in enumerate(parts):
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        is_json = part.get_content_type() == "application/json" or name in ("metadata", "ragFile")
        if meta is None and (is_json or (i == 0 and name is None)):
            try:
                meta = json.loads(payload.decode("utf-8") or "{}")
            except ValueError:
                raise _Err(400, "INVALID_ARGUMENT", "The metadata part is not valid JSON.")
        elif data is None:
            data = payload
            fname = part.get_filename()
    if data is None or not isinstance(meta, dict):
        raise _Err(400, "INVALID_ARGUMENT", "A multipart upload needs a JSON metadata part and a file part.")
    rf = dict(meta.get("ragFile") or meta.get("rag_file") or {})
    if not rf.get("displayName") and fname:
        rf["displayName"] = fname
    out = {"ragFile": rf, "content": base64.b64encode(data).decode()}
    cfg = meta.get("uploadRagFileConfig") or meta.get("upload_rag_file_config")
    if cfg:
        out["uploadRagFileConfig"] = cfg
    return out


def _chunk_cfg(p):
    """Chunk size / overlap in characters from either the new ragFileTransformationConfig or the older ragFileChunkingConfig."""
    cfg = {}
    for holder in (p.get("uploadRagFileConfig") or {}, p.get("importRagFilesConfig") or {}, p):
        tc = (holder.get("ragFileTransformationConfig") or {}).get("ragFileChunkingConfig") or holder.get("ragFileChunkingConfig") or {}
        cfg = tc.get("fixedLengthChunking") or tc or cfg
        if cfg:
            break
    size, ov = int(cfg.get("chunkSize") or 1024), int(cfg.get("chunkOverlap") or 200)
    if size < 16 or ov < 0 or ov >= size:
        raise _Err(400, "INVALID_ARGUMENT", "chunk_size must be at least 16 and chunk_overlap must be smaller than chunk_size.")
    return size, ov


def _make_file(name, dn, desc, text, size_bytes, cfg, extra=None):
    size, ov = cfg
    chunks = [t for t, _h in kc.split_text(text, max(8, size // 5), max(0, min(50, ov * 100 // max(size, 1))), "FIXED_SIZE")]
    if not chunks:
        raise _Err(400, "INVALID_ARGUMENT", "The file has no text content.")
    now = _iso()
    f = {"name": name, "displayName": dn, "description": desc, "createTime": now, "updateTime": now, "fileStatus": {"state": "ACTIVE"},
         "_size": size_bytes, "_chunks": chunks, "_vecs": llm.embed(chunks)["vectors"]}
    f.update(extra or {})
    return f


def _rag_upload(st, loc, cid, path, p, _raw=b""):
    proj = re.search(r"/projects/([^/]+)/", path).group(1)
    name = f"projects/{proj}/locations/{loc}/ragCorpora/{cid}"
    c = st["corpora"].get(name)
    if not c:
        raise _Err(404, "NOT_FOUND", f"RagCorpus `{name}` not found.")
    meta = p.get("ragFile") or {}
    dn = meta.get("displayName")
    if not isinstance(dn, str) or not dn:
        raise _Err(400, "INVALID_ARGUMENT", "rag_file.display_name must be set.")
    if isinstance(p.get("text"), str):
        text = p["text"]
    elif isinstance(p.get("content"), str):
        try:
            data = base64.b64decode(p["content"])
        except ValueError:
            raise _Err(400, "INVALID_ARGUMENT", "content must be base64.")
        try:
            text = kc.parse_document(dn, data)
        except kc.ParseError as e:
            raise _Err(400, "INVALID_ARGUMENT", str(e))
    else:
        raise _Err(400, "INVALID_ARGUMENT", "Provide `text` (string), `content` (base64 bytes) or a multipart body.")
    fid = _numid()[:16]
    f = _make_file(f"{name}/ragFiles/{fid}", dn, meta.get("description", ""), text, len(text.encode()), _chunk_cfg(p), {"directUploadSource": {}})
    c["_files"][fid] = f
    c["updateTime"] = f["updateTime"]
    return _out(200, {"ragFile": _file_view(f)})


# ───────────── Cloud Storage import (the simulated GCS store) ─────────────
def _gcs_mod():
    try:
        from core import gcp_storage_core as m
    except ImportError:  # pragma: no cover
        import gcp_storage_core as m  # type: ignore
    return m


def _gcs_objects(gcs, uri):
    """gs://bucket/object | gs://bucket/prefix[/] -> [(bucket, name, bytes)]; raises _Err for a bad uri / missing bucket."""
    from urllib.parse import quote
    m = re.match(r"^gs://([^/]+)(?:/(.*))?$", uri or "")
    if not m:
        raise _Err(400, "INVALID_ARGUMENT", f"`{uri}` is not a Cloud Storage uri of the form gs://bucket/path.")
    bucket, key = m.group(1), m.group(2) or ""
    if gcs is None:
        raise _Err(400, "FAILED_PRECONDITION", "Cloud Storage is not attached to this RAG Engine.")
    g = _gcs_mod()
    if not gcs.bucket_exists(bucket):
        raise _Err(404, "NOT_FOUND", f"Bucket `{bucket}` does not exist.")
    out = []
    exact = g.dispatch(gcs, "GET", "/storage/v1/b/%s/o/%s" % (bucket, quote(key, safe="")), {}, {}, b"") if key and not key.endswith("/") else None
    names = [key] if exact is not None and exact.status == 200 else []
    if not names:
        lst = g.dispatch(gcs, "GET", "/storage/v1/b/%s/o" % bucket, {"prefix": key}, {}, b"")
        names = [o["name"] for o in (json.loads(lst.body).get("items") or []) if not o["name"].endswith("/")]
    for n in names:
        r = g.dispatch(gcs, "GET", "/storage/v1/b/%s/o/%s" % (bucket, quote(n, safe="")), {"alt": "media"}, {}, b"")
        if r.status == 200:
            out.append((bucket, n, r.body))
    return out


_UNSUPPORTED_SRC = ("googleDriveSource", "slackSource", "jiraSource", "sharePointSources")


def _rag_import(st, proj, loc, cid, p, gcs):
    name = f"projects/{proj}/locations/{loc}/ragCorpora/{cid}"
    c = st["corpora"].get(name)
    if not c:
        raise _Err(404, "NOT_FOUND", f"RagCorpus `{name}` not found.")
    cfg = p.get("importRagFilesConfig")
    if not isinstance(cfg, dict):
        raise _Err(400, "INVALID_ARGUMENT", "import_rag_files_config must be set.")
    for k in _UNSUPPORTED_SRC:
        if cfg.get(k):
            raise _Err(400, "INVALID_ARGUMENT", f"import_rag_files_config.{k} is not supported by Vyomi; use gcs_source (Cloud Storage).")
    uris = (cfg.get("gcsSource") or {}).get("uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
        raise _Err(400, "INVALID_ARGUMENT", "import_rag_files_config.gcs_source.uris must list at least one gs:// uri.")
    chunk = _chunk_cfg({"importRagFilesConfig": cfg})
    imported = failed = skipped = 0
    fails = []
    now = _iso()
    for uri in uris:
        objs = _gcs_objects(gcs, uri)
        if not objs:
            raise _Err(404, "NOT_FOUND", f"No Cloud Storage objects match `{uri}`.")
        for bucket, key, data in objs:
            full = f"gs://{bucket}/{key}"
            prior = next((fid for fid, f in c["_files"].items() if (f.get("gcsSource") or {}).get("uris") == [full]), None)
            if prior and c["_files"][prior]["_size"] == len(data) and c["_files"][prior].get("_sha") == hash(data):
                skipped += 1
                continue
            try:
                text = kc.parse_document(key, data)
                fid = prior or _numid()[:16]
                f = _make_file(f"{name}/ragFiles/{fid}", key.rsplit("/", 1)[-1], "", text, len(data), chunk, {"gcsSource": {"uris": [full]}, "_sha": hash(data)})
                if prior:
                    f["createTime"] = c["_files"][prior]["createTime"]
                c["_files"][fid] = f
                imported += 1
            except (kc.ParseError, _Err) as e:
                failed += 1
                fails.append({"uri": full, "error": getattr(e, "msg", None) or str(e)})
    c["updateTime"] = now
    resp = {"importedRagFilesCount": str(imported), "failedRagFilesCount": str(failed), "skippedRagFilesCount": str(skipped)}
    op = _lro(name, resp, "google.cloud.aiplatform.v1.ImportRagFilesResponse")
    op["metadata"] = {"@type": "type.googleapis.com/google.cloud.aiplatform.v1.ImportRagFilesOperationMetadata", "ragCorpusId": cid,
                      "createTime": now, "updateTime": _iso(), "genericMetadata": {"createTime": now, "updateTime": _iso()}}
    if fails:
        op["metadata"]["vyomiFailures"] = fails
    return _out(200, op)


def _dense_scores(qtext, pool_vecs, dims_ok=True):
    qv = llm.embed(qtext)["vectors"][0]
    return qv, [llm.cosine(qv, v) for v in pool_vecs]


def _retrieve(st, proj, loc, p):
    qtext = ((p.get("query") or {}).get("text") or "").strip()
    if not qtext:
        raise _Err(400, "INVALID_ARGUMENT", "query.text must be set.")
    qd = p.get("query") or {}
    rc = qd.get("ragRetrievalConfig") or {}
    top = int(rc.get("topK") or qd.get("similarityTopK") or 5)
    if not 1 <= top <= 1000:
        raise _Err(400, "INVALID_ARGUMENT", "rag_retrieval_config.top_k must be between 1 and 1000.")
    flt = rc.get("filter") or {}
    dthr, sthr = flt.get("vectorDistanceThreshold"), flt.get("vectorSimilarityThreshold")
    hyb = rc.get("hybridSearch")
    alpha = None
    if hyb is not None:
        alpha = float(hyb.get("alpha", 0.5))
        if not 0.0 <= alpha <= 1.0:
            raise _Err(400, "INVALID_ARGUMENT", "hybrid_search.alpha must be between 0 and 1.")
    res = (p.get("vertexRagStore") or {}).get("ragResources") or []
    parent = f"projects/{proj}/locations/{loc}"
    corpora = []
    if not res:
        raise _Err(400, "INVALID_ARGUMENT", "vertex_rag_store.rag_resources must name a rag_corpus.")
    for r in res:
        n = r.get("ragCorpus") or ""
        if n.split("/")[-1].isdigit() and not n.startswith("projects/"):
            n = f"{parent}/ragCorpora/{n}"
        c = st["corpora"].get(n)
        if not c:
            raise _Err(404, "NOT_FOUND", f"RagCorpus `{n}` not found.")
        corpora.append((c, set(r.get("ragFileIds") or [])))
    pool = []
    for c, only in corpora:
        for fid, f in c["_files"].items():
            if only and fid not in only:
                continue
            for i, t in enumerate(f["_chunks"]):
                pool.append((t, f, i))
    if not pool:
        return _out(200, {"contexts": {"contexts": []}})
    texts = [t for t, _f, _i in pool]
    qv = llm.embed(qtext)["vectors"][0]
    for f in {id(f): f for _t, f, _i in pool}.values():       # an index built by another embedder (dimension mismatch) is re-embedded lazily
        if not f.get("_vecs") or len(f["_vecs"][0]) != len(qv):
            f["_vecs"] = llm.embed(f["_chunks"], dimensions=len(qv))["vectors"]
    cos = [llm.cosine(qv, f["_vecs"][i]) for _t, f, i in pool]
    lex = kc.bm25(texts, qtext)
    dense_rank = [i for i, _ in sorted(enumerate(cos), key=lambda x: -x[1])]
    if alpha is None or alpha >= 1.0:
        order = dense_rank
    else:
        lex_rank = [i for i, _ in sorted(lex.items(), key=lambda x: -x[1])]
        fused = {}
        for r, i in enumerate(dense_rank):
            fused[i] = fused.get(i, 0.0) + alpha / (60 + r + 1)
        for r, i in enumerate(lex_rank):
            fused[i] = fused.get(i, 0.0) + (1.0 - alpha) / (60 + r + 1)
        order = [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])]
        if alpha <= 0.0:
            order = [i for i in order if i in lex]       # alpha 0 = sparse (BM25) only
    if dthr is not None:
        order = [i for i in order if 1.0 - cos[i] <= float(dthr)]
    if sthr is not None:
        order = [i for i in order if cos[i] >= float(sthr)]
    rk = rc.get("ranking") or {}
    ranked = bool(rk.get("rankService") or rk.get("llmRanker"))
    if ranked:
        cand = order[:max(top * 3, top)]
        rr = kc.rerank(qtext, [texts[i] for i in cand], top)
        order = [cand[j] for j, _s in rr]
        rr_score = {cand[j]: sc for j, sc in rr}
    order = order[:top]
    ctxs = []
    for i in order:
        t, f, ci = pool[i]
        ctx = {"sourceUri": f["name"], "sourceDisplayName": f["displayName"], "text": t, "distance": round(1.0 - cos[i], 6), "score": round(cos[i], 6)}
        if f.get("gcsSource"):
            ctx["sourceUri"] = f["gcsSource"]["uris"][0]
        if alpha is not None:
            ctx["sparseDistance"] = round(1.0 / (1.0 + lex.get(i, 0.0)), 6)
        if ranked:
            ctx["vyomiRerankScore"] = round(rr_score[i], 6)
        ctxs.append(ctx)
    return _out(200, {"contexts": {"contexts": ctxs}})


# ═════════════════════════════ evaluation ═════════════════════════════
def _toks(s):
    return re.findall(r"\w+", str(s or "").lower())


def _ngrams(t, n):
    return [tuple(t[i:i + n]) for i in range(len(t) - n + 1)]


def _bleu(pred, ref, max_n=4):
    p, r = _toks(pred), _toks(ref)
    if not p or not r:
        return 0.0
    max_n = min(max_n, len(p), len(r))                  # a short answer is scored on the n-gram orders it has
    logs = 0.0
    for n in range(1, max_n + 1):
        pg, rg = _ngrams(p, n), _ngrams(r, n)
        if not pg:
            return 0.0
        rc = {}
        for g in rg:
            rc[g] = rc.get(g, 0) + 1
        hit = 0
        for g in pg:
            if rc.get(g, 0) > 0:
                hit += 1
                rc[g] -= 1
        logs += math.log((hit or 0.1) / len(pg))        # +smoothing so a short answer is not 0
    bp = 1.0 if len(p) > len(r) else math.exp(1 - len(r) / len(p))
    return round(bp * math.exp(logs / max_n), 6)


def _lcs(a, b):
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def _rouge(pred, ref, typ="rougeL"):
    p, r = _toks(pred), _toks(ref)
    if not p or not r:
        return 0.0
    if typ == "rougeL":
        ov = _lcs(p, r)
    else:
        n = int(re.sub(r"\D", "", typ) or 1)
        pg, rg = _ngrams(p, n), _ngrams(r, n)
        rc = {}
        for g in rg:
            rc[g] = rc.get(g, 0) + 1
        ov = 0
        for g in pg:
            if rc.get(g, 0) > 0:
                ov += 1
                rc[g] -= 1
        p, r = pg, rg
        if not p or not r:
            return 0.0
    if not ov:
        return 0.0
    pr, rc_ = ov / len(p), ov / len(r)
    return round(2 * pr * rc_ / (pr + rc_), 6)


def _score(metric, pred, ref, rouge_type="rougeL"):
    if metric == "exact_match":
        return 1.0 if str(pred).strip() == str(ref).strip() else 0.0
    if metric == "bleu":
        return _bleu(pred, ref)
    if metric == "rouge":
        return _rouge(pred, ref, rouge_type)
    raise _Err(400, "INVALID_ARGUMENT", f"Unsupported metric `{metric}`. Available: exact_match, bleu, rouge.")


def _evaluate_instances(p):
    m = {"exactMatchInput": "exact_match", "bleuInput": "bleu", "rougeInput": "rouge"}
    key = next((k for k in m if k in p), None)
    if not key:
        raise _Err(400, "INVALID_ARGUMENT", "Unsupported metric input. Available: exactMatchInput, bleuInput, rougeInput (computation-based metrics).")
    inp = p[key]
    insts = inp.get("instances") or ([inp["instance"]] if inp.get("instance") else [])
    if not insts:
        raise _Err(400, "INVALID_ARGUMENT", "instances must contain at least one {prediction, reference}.")
    rt = (inp.get("metricSpec") or {}).get("rougeType") or "rougeL"
    vals = [{"score": _score(m[key], i.get("prediction", ""), i.get("reference", ""), rt)} for i in insts]
    res = {"exactMatchInput": ("exactMatchResults", "exactMatchMetricValues"), "bleuInput": ("bleuResults", "bleuMetricValues"), "rougeInput": ("rougeResults", "rougeMetricValues")}[key]
    return _out(200, {res[0]: {res[1]: vals}})


def _run_view(r):
    return _view(r)


def _eval_runs(st, method, m, p, q):
    ver, proj, loc, rid, verb = m.groups()
    parent = f"projects/{proj}/locations/{loc}"
    if rid is None:
        if method == "POST":
            return _eval_create(st, parent, p)
        if method == "GET":
            items = sorted((r for n, r in st["runs"].items() if n.startswith(parent + "/")), key=lambda r: r["createTime"])
            return _out(200, _page([_run_view(r) for r in items], q, "evaluationRuns"))
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{parent}/evaluationRuns/{rid}"
    r = st["runs"].get(name)
    if not r:
        raise _Err(404, "NOT_FOUND", f"EvaluationRun `{name}` not found.")
    if method == "GET":
        return _out(200, _run_view(r))
    if method == "DELETE":
        del st["runs"][name]
        return _out(200, _lro(name, None, "google.protobuf.Empty"))
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _eval_create(st, parent, p):
    dn = p.get("displayName")
    if not isinstance(dn, str) or not dn:
        raise _Err(400, "INVALID_ARGUMENT", "evaluation_run.display_name must be set.")
    rows = (p.get("dataset") or {}).get("rows") or []
    if not rows or len(rows) > 100:
        raise _Err(400, "INVALID_ARGUMENT", "dataset.rows must hold 1 to 100 rows of {prompt, reference[, response]}.")
    metrics = p.get("metrics") or ["rouge"]
    bad = [x for x in metrics if x not in ("exact_match", "bleu", "rouge")]
    if bad:
        raise _Err(400, "INVALID_ARGUMENT", f"Unsupported metric `{bad[0]}`. Available: exact_match, bleu, rouge.")
    model = p.get("model") or ""
    out_rows = []
    for i, row in enumerate(rows):
        ref = str(row.get("reference", ""))
        resp = row.get("response")
        if resp is None:
            if not row.get("prompt"):
                raise _Err(400, "INVALID_ARGUMENT", f"rows[{i}] needs `prompt` (to generate) or `response`.")
            r = llm.chat([{"role": "user", "content": str(row["prompt"])}], max_tokens=int(p.get("maxOutputTokens") or 200), temperature=0.0)
            resp = str(r.get("text") or r.get("content") or "")
        out_rows.append({"prompt": row.get("prompt", ""), "reference": ref, "response": resp,
                         "scores": {mt: _score(mt, resp, ref) for mt in metrics}})
    summary = {mt: round(sum(r["scores"][mt] for r in out_rows) / len(out_rows), 6) for mt in metrics}
    now = _iso()
    name = f"{parent}/evaluationRuns/{_numid()[:16]}"
    st["runs"][name] = {"name": name, "displayName": dn, "state": "SUCCEEDED", "createTime": now, "updateTime": now, "model": model or llm.model_name(),
                        "metrics": metrics, "summary": summary, "rows": out_rows,
                        "vyomiNote": "Generated by the local model (or your supplied responses) and scored by exact_match / BLEU / ROUGE; not a Gemini autorater."}
    return _out(200, _run_view(st["runs"][name]))


# ═════════════════════════════ Vertex AI Search (discoveryengine) ═════════════════════════════
def _doc_text(d):
    parts = []
    sd = d.get("structData") or d.get("jsonData") or {}
    if isinstance(sd, str):
        try:
            sd = json.loads(sd)
        except ValueError:
            sd = {}
    for k, v in (sd.items() if isinstance(sd, dict) else []):
        parts.append(f"{k} {v}")
    c = d.get("content") or {}
    if c.get("rawBytes"):
        try:
            parts.append(base64.b64decode(c["rawBytes"]).decode("utf-8", "ignore"))
        except ValueError:
            pass
    if isinstance(c.get("text"), str):
        parts.append(c["text"])
    return " \n".join(parts)


def _de(st, method, m, p, q, gcs=None):
    ver, proj, loc, coll, kind, rid, branch, did, serving, verb = m.groups()
    scope = f"projects/{proj}/locations/{loc}/collections/{coll}"
    if kind == "engines":
        return _de_engine(st, method, scope, rid, serving, verb, p, q)
    if rid is None:
        if method == "POST":
            sid = q.get("dataStoreId")
            if not sid or not re.match(r"^[a-z0-9][a-z0-9_-]{0,62}$", sid):
                raise _Err(400, "INVALID_ARGUMENT", "dataStoreId is required (lowercase letters, digits, - and _).")
            name = f"{scope}/dataStores/{sid}"
            if name in st["stores"]:
                raise _Err(409, "ALREADY_EXISTS", f"DataStore `{name}` already exists.")
            ds = {"name": name, "displayName": p.get("displayName") or sid, "industryVertical": p.get("industryVertical") or "GENERIC",
                  "solutionTypes": p.get("solutionTypes") or ["SOLUTION_TYPE_SEARCH"], "contentConfig": p.get("contentConfig") or "NO_CONTENT",
                  "createTime": _iso(), "_docs": {}}
            st["stores"][name] = ds
            return _out(200, _lro(name, _ds_view(ds), "google.cloud.discoveryengine.v1.DataStore"))
        if method == "GET":
            items = sorted((d for n, d in st["stores"].items() if n.startswith(scope + "/")), key=lambda d: d["createTime"])
            return _out(200, _page([_ds_view(d) for d in items], q, "dataStores"))
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{scope}/dataStores/{rid}"
    ds = st["stores"].get(name)
    if not ds:
        raise _Err(404, "NOT_FOUND", f"DataStore `{name}` not found.")
    if serving:
        return _search(st, ds, [ds], p)
    if branch is not None:
        return _de_docs(ds, name, branch, did, verb, method, p, q, gcs)
    if method == "GET":
        return _out(200, _ds_view(ds))
    if method == "DELETE":
        del st["stores"][name]
        return _out(200, _lro(name, None, "google.protobuf.Empty"))
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _ds_view(d):
    v = _view(d)
    v["vyomiStats"] = {"documents": len(d["_docs"])}
    return v


def _de_docs(ds, name, branch, did, verb, method, p, q, gcs=None):
    base = f"{name}/branches/{branch}/documents"
    if verb == ":import":
        if p.get("bigquerySource") or p.get("bigtableSource") or p.get("spannerSource") or p.get("firestoreSource") or p.get("cloudSqlSource") or p.get("fhirStoreSource"):
            raise _Err(400, "INVALID_ARGUMENT", "Only inlineSource and gcsSource are supported by Vyomi imports (not BigQuery / Bigtable / Spanner / Firestore / Cloud SQL / FHIR).")
        errs = []
        if p.get("gcsSource"):
            docs, errs = _gcs_documents(p["gcsSource"], gcs, ds)
        else:
            docs = (p.get("inlineSource") or {}).get("documents")
        if not isinstance(docs, list) or not docs:
            raise _Err(400, "INVALID_ARGUMENT", "inlineSource.documents or gcsSource.inputUris is required.")
        n = 0
        for d in docs:
            d = dict(d)
            txt = d.pop("_text", None)
            i = d.get("id") or uuid.uuid4().hex[:16]
            ds["_docs"][i] = dict(d, id=i, name=f"{base}/{i}")
            if txt is not None:
                ds.setdefault("_texts", {})[i] = txt
            n += 1
        op = _lro(name, {"errorSamples": [{"message": e} for e in errs[:5]], "errorConfig": {}}, "google.cloud.discoveryengine.v1.ImportDocumentsResponse")
        op["metadata"] = {"@type": "type.googleapis.com/google.cloud.discoveryengine.v1.ImportDocumentsMetadata", "createTime": _iso(), "updateTime": _iso(),
                          "successCount": str(n), "failureCount": str(len(errs))}
        return _out(200, op)
    if did is None:
        if method == "POST":
            i = q.get("documentId")
            if not i:
                raise _Err(400, "INVALID_ARGUMENT", "documentId is required.")
            if i in ds["_docs"]:
                raise _Err(409, "ALREADY_EXISTS", f"Document `{base}/{i}` already exists.")
            ds["_docs"][i] = dict(p, id=i, name=f"{base}/{i}")
            return _out(200, ds["_docs"][i])
        if method == "GET":
            return _out(200, _page(list(ds["_docs"].values()), q, "documents"))
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    d = ds["_docs"].get(did)
    if not d:
        raise _Err(404, "NOT_FOUND", f"Document `{base}/{did}` not found.")
    if method == "GET":
        return _out(200, d)
    if method == "DELETE":
        del ds["_docs"][did]
        return _out(200, {})
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _gcs_documents(src, gcs, ds):
    """gcsSource {inputUris, dataSchema: content | custom | document} -> ([document dicts], [error strings])."""
    schema = src.get("dataSchema") or ("content" if ds.get("contentConfig") != "NO_CONTENT" else "document")
    if schema not in ("content", "custom", "document"):
        raise _Err(400, "INVALID_ARGUMENT", f"gcs_source.data_schema `{schema}` is not supported (content, custom, document).")
    uris = src.get("inputUris")
    if not isinstance(uris, list) or not uris:
        raise _Err(400, "INVALID_ARGUMENT", "gcs_source.input_uris must list at least one gs:// uri.")
    docs, errs = [], []
    for uri in uris:
        objs = _gcs_objects(gcs, uri.rstrip("*"))
        if not objs:
            raise _Err(404, "NOT_FOUND", f"No Cloud Storage objects match `{uri}`.")
        for bucket, key, data in objs:
            full = f"gs://{bucket}/{key}"
            if schema == "content":
                try:
                    text = kc.parse_document(key, data)
                except kc.ParseError as e:
                    errs.append(f"{full}: {e}")
                    continue
                did = re.sub(r"[^A-Za-z0-9_-]", "-", key)[:63] or uuid.uuid4().hex[:16]
                docs.append({"id": did, "content": {"uri": full, "mimeType": "text/plain" if key.lower().endswith((".txt", ".md")) else "application/octet-stream"},
                             "structData": {"title": key.rsplit("/", 1)[-1]}, "_text": text})
                continue
            for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                    if not isinstance(o, dict):
                        raise ValueError("not an object")
                except ValueError as e:
                    errs.append(f"{full}:{n}: {e}")
                    continue
                if schema == "document":
                    docs.append(o)
                else:
                    docs.append({"id": str(o.get("id") or uuid.uuid4().hex[:16]), "structData": {k: v for k, v in o.items() if k != "id"}})
    return docs, errs


def _de_engine(st, method, scope, rid, serving, verb, p, q):
    if rid is None:
        if method == "POST":
            eid = q.get("engineId")
            if not eid or not re.match(r"^[a-z0-9][a-z0-9_-]{0,62}$", eid):
                raise _Err(400, "INVALID_ARGUMENT", "engineId is required (lowercase letters, digits, - and _).")
            name = f"{scope}/engines/{eid}"
            if name in st["des_engines"]:
                raise _Err(409, "ALREADY_EXISTS", f"Engine `{name}` already exists.")
            links = p.get("dataStoreIds") or []
            for l in links:
                if f"{scope}/dataStores/{l}" not in st["stores"]:
                    raise _Err(404, "NOT_FOUND", f"DataStore `{l}` not found.")
            e = {"name": name, "displayName": p.get("displayName") or eid, "solutionType": p.get("solutionType") or "SOLUTION_TYPE_SEARCH", "dataStoreIds": links,
                 "createTime": _iso(), "searchEngineConfig": p.get("searchEngineConfig") or {"searchTier": "STANDARD_TIER"}}
            st["des_engines"][name] = e
            return _out(200, _lro(name, e, "google.cloud.discoveryengine.v1.Engine"))
        if method == "GET":
            items = sorted((e for n, e in st["des_engines"].items() if n.startswith(scope + "/")), key=lambda e: e["createTime"])
            return _out(200, _page(items, q, "engines"))
        raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")
    name = f"{scope}/engines/{rid}"
    e = st["des_engines"].get(name)
    if not e:
        raise _Err(404, "NOT_FOUND", f"Engine `{name}` not found.")
    if serving:
        return _search(st, e, [st["stores"][f"{scope}/dataStores/{l}"] for l in e["dataStoreIds"] if f"{scope}/dataStores/{l}" in st["stores"]], p)
    if method == "GET":
        return _out(200, e)
    if method == "DELETE":
        del st["des_engines"][name]
        return _out(200, _lro(name, None, "google.protobuf.Empty"))
    raise _Err(405, "METHOD_NOT_ALLOWED", "Unsupported.")


def _search(st, owner, stores, p):
    qt = (p.get("query") or "").strip()
    pairs = [(d, s_) for s_ in stores for d in s_["_docs"].values()]
    texts = [(_doc_text(d) + " " + s_.get("_texts", {}).get(d["id"], "")).strip() for d, s_ in pairs]
    docs = [d for d, _s in pairs]
    owners = [s_ for _d, s_ in pairs]
    lex = kc.bm25(texts, qt) if qt and docs else {}
    lex_rank = [i for i, _ in sorted(lex.items(), key=lambda kv: -kv[1])]
    note = None
    dense_rank = []
    if qt and docs:
        try:
            qv = llm.embed(qt)["vectors"][0]
            ck = [f"{docs[i]['id']}|{len(qv)}|{zlib.crc32(texts[i].encode())}" for i in range(len(docs))]
            need = [i for i in range(len(docs)) if texts[i] and ck[i] not in owners[i].setdefault("_vecs", {})]
            if need:
                for i, v in zip(need, llm.embed([texts[i][:2000] for i in need], dimensions=len(qv))["vectors"]):
                    owners[i]["_vecs"][ck[i]] = v
            cos = {i: llm.cosine(qv, owners[i]["_vecs"][ck[i]]) for i in range(len(docs)) if ck[i] in owners[i]["_vecs"]}
            dense_rank = [i for i, c in sorted(cos.items(), key=lambda x: -x[1]) if c >= 0.3][:20]
        except llm.LlmUnavailable as e:
            note = f"embedding model unavailable ({e}); lexical ranking only"
    fused = {}
    for rank in (lex_rank, dense_rank):
        for r, i in enumerate(rank):
            fused[i] = fused.get(i, 0.0) + 1.0 / (60 + r + 1)
    ranked = sorted(fused.items(), key=lambda kv: -kv[1])
    size = int(p.get("pageSize") or 10)
    off = int(p.get("offset") or 0)
    terms = set(kc.tokens(qt))
    res = []
    for i, _s in ranked[off:off + size]:
        d = docs[i]
        words = texts[i].split()
        at = next((k for k, w in enumerate(words) if kc.tokens(w) and kc.tokens(w)[0] in terms), 0)
        snippet = " ".join(words[max(0, at - 8):at + 24])
        res.append({"id": d["id"], "document": d, "vyomiSnippet": snippet, "vyomiRank": {"lexical": (lex_rank.index(i) + 1) if i in lex_rank else None,
                                                                                         "semantic": (dense_rank.index(i) + 1) if i in dense_rank else None}})
    out = {"results": res, "totalSize": len(ranked), "attributionToken": uuid.uuid4().hex, "summary": {}}
    if note:
        out["vyomiNote"] = note
    spec = ((p.get("contentSearchSpec") or {}).get("summarySpec"))
    if spec is not None:
        out["summary"] = _summary(qt, [(docs[i], texts[i]) for i, _ in ranked[:max(1, int(spec.get("summaryResultCount") or 3))]], spec)
    return _out(200, out)


def _summary(q, top, spec):
    """Generated answer over the top results via the local chat model (llm_core), with [n] citations mapped to Vertex's citationMetadata."""
    if not top or not q:
        return {"summarySkippedReasons": ["NO_RELEVANT_CONTENT"]}
    ctx = "\n\n".join(f"[{n + 1}] {t[:1200]}" for n, (_d, t) in enumerate(top))
    cite = spec.get("includeCitations", False)
    sysm = ("Answer the question using ONLY the numbered search results. If they do not contain the answer, say you could not find it. "
            + ("Cite results inline like [1]." if cite else "Do not cite."))
    try:
        r = llm.chat([{"role": "user", "content": f"Search results:\n{ctx}\n\nQuestion: {q}"}], system=sysm, max_tokens=300, temperature=0.2)
    except llm.LlmUnavailable as e:
        return {"summarySkippedReasons": ["LLM_ADDON_NOT_ENABLED"], "vyomiNote": f"no local chat model is running: {e}"}
    text = (r.get("text") or "").strip()
    out = {"summaryText": re.sub(r"\s*\[\d+\]", "", text) if not cite else text, "vyomiModel": "local chat model (llm_core), not Gemini"}
    if cite:
        cits = []
        for sent in re.finditer(r"[^.!?\n]+[.!?]?", text):
            refs = sorted({int(x) - 1 for x in re.findall(r"\[(\d+)\]", sent.group(0)) if 0 < int(x) <= len(top)})
            if refs:
                cits.append({"startIndex": str(len(text[:sent.start()].encode())), "endIndex": str(len(text[:sent.end()].encode())),
                             "sources": [{"referenceIndex": str(x)} for x in refs]})
        out["summaryWithMetadata"] = {"summary": text, "citationMetadata": {"citations": cits},
                                      "references": [{"title": (d.get("structData") or {}).get("title") or d["id"], "document": d.get("name") or d["id"],
                                                      "chunkContents": [{"content": t[:400]}]} for d, t in top]}
    return out
