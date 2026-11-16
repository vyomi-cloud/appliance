"""Gemini Enterprise Agent Platform extras (Vertex AI) - substrate-independent, Pyodide-loadable, pure Python.

A thin WIRE ADAPTER: the engines are existing OSS / seams, nothing is hand-built beyond request and response shapes.

  RAG Engine        aiplatform `ragCorpora` / `ragFiles` / `locations/L:retrieveContexts`   chunking + BM25 = core/knowledge_core (SQLite FTS5)
  Vertex AI Search  discoveryengine `dataStores` / `documents` / `engines` / `servingConfigs:search`   BM25 = core/knowledge_core (SQLite FTS5)
  Memory Bank       `reasoningEngines/ID/memories` (+ :retrieve, :generate)                 embeddings + chat = core/llm_core (local model seam)
  Sessions          `reasoningEngines/ID/sessions` (+ events) over the Agent Engine's own multi-turn sessions (core/gcp_agentengine_core)
  Evaluation        `locations/L:evaluateInstances` (exactMatch / bleu / rouge) and `evaluationRuns` (generate with the local model, then score)

State lives in the persisted account bag, like every other core. Honest limits: ragFiles come in through `ragFiles:upload` carrying text
(JSON `text` or base64 `content`) - there is no GCS import and no multipart upload; retrieval is lexical (BM25), not a vector DB; the
discoveryengine search returns ranked documents with snippets but no generative summary or semantic reranking; memories are ranked by
cosine over the seam's embeddings (the labelled `vyomi-hash-embed` fallback when no embedding model runs); `memories:generate` asks the
local chat model for facts, so quality is the small model's and it answers 503 when no model backend is up.
"""
from __future__ import annotations

import base64
import json
import math
import random
import re
import time
import uuid
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
def dispatch(store, method, path, query=None, headers=None, body=b""):
    method = method.upper()
    path = path.split("?", 1)[0]
    q = query or {}
    try:
        st = _state(store)
        m = UPLOAD.match(path)
        if m and method == "POST":
            return _rag_upload(st, m.group(3), m.group(4), path, _body(body), _raw=body)
        m = RAG_FILES_VERB.match(path)
        if m and method == "POST":
            raise _Err(501, "UNIMPLEMENTED", "ragFiles%s is not supported: import from Cloud Storage is not simulated. Use ragFiles:upload with text." % m.group(5))
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
            return _de(st, method, m, _body(body), q)
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
    v["vyomiStats"] = {"files": len(c["_files"]), "chunks": sum(len(f["_chunks"]) for f in c["_files"].values())}
    return v


def _file_view(f):
    v = _view(f)
    v["sizeBytes"] = str(f["_size"])
    v["vyomiChunks"] = len(f["_chunks"])
    return v


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
        raise _Err(400, "INVALID_ARGUMENT", "Provide `text` (string) or `content` (base64 bytes). Cloud Storage import is not simulated.")
    cfg = ((p.get("uploadRagFileConfig") or {}).get("ragFileTransformationConfig") or {}).get("ragFileChunkingConfig", {}).get("fixedLengthChunking") or {}
    size, ov = int(cfg.get("chunkSize") or 1024), int(cfg.get("chunkOverlap") or 200)
    chunks = [t for t, _h in kc.split_text(text, max(8, size // 5), max(0, min(50, ov * 100 // max(size, 1))), "FIXED_SIZE")]
    if not chunks:
        raise _Err(400, "INVALID_ARGUMENT", "The file has no text content.")
    fid = _numid()[:16]
    now = _iso()
    f = {"name": f"{name}/ragFiles/{fid}", "displayName": dn, "description": meta.get("description", ""), "createTime": now, "updateTime": now,
         "fileStatus": {"state": "ACTIVE"}, "_size": len(text.encode()), "_chunks": chunks}
    c["_files"][fid] = f
    c["updateTime"] = now
    return _out(200, {"ragFile": _file_view(f)})


def _retrieve(st, proj, loc, p):
    qtext = ((p.get("query") or {}).get("text") or "").strip()
    if not qtext:
        raise _Err(400, "INVALID_ARGUMENT", "query.text must be set.")
    top = int(((p.get("query") or {}).get("ragRetrievalConfig") or {}).get("topK") or (p.get("query") or {}).get("similarityTopK") or 5)
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
    scores = kc.bm25([t for t, _f, _i in pool], qtext) if pool else {}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top]
    top_s = ranked[0][1] if ranked else 1.0
    ctxs = [{"sourceUri": pool[i][1]["name"], "sourceDisplayName": pool[i][1]["displayName"], "text": pool[i][0],
             "distance": round(1 - (s / top_s if top_s else 0), 6), "score": round(s, 6)} for i, s in ranked]
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


def _de(st, method, m, p, q):
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
        return _de_docs(ds, name, branch, did, verb, method, p, q)
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


def _de_docs(ds, name, branch, did, verb, method, p, q):
    base = f"{name}/branches/{branch}/documents"
    if verb == ":import":
        docs = (p.get("inlineSource") or {}).get("documents")
        if not isinstance(docs, list) or not docs:
            raise _Err(400, "INVALID_ARGUMENT", "inlineSource.documents is required; Cloud Storage / BigQuery import is not simulated.")
        n = 0
        for d in docs:
            i = d.get("id") or uuid.uuid4().hex[:16]
            ds["_docs"][i] = dict(d, id=i, name=f"{base}/{i}")
            n += 1
        return _out(200, _lro(name, {"errorSamples": [], "errorConfig": {}}, "google.cloud.discoveryengine.v1.ImportDocumentsResponse"))
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
    docs = [d for s in stores for d in s["_docs"].values()]
    texts = [_doc_text(d) for d in docs]
    scores = kc.bm25(texts, qt) if qt and docs else {}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    size = int(p.get("pageSize") or 10)
    off = int(p.get("offset") or 0)
    terms = set(kc.tokens(qt))
    res = []
    for i, _s in ranked[off:off + size]:
        d = docs[i]
        words = texts[i].split()
        at = next((k for k, w in enumerate(words) if kc.tokens(w) and kc.tokens(w)[0] in terms), 0)
        snippet = " ".join(words[max(0, at - 8):at + 24])
        res.append({"id": d["id"], "document": d, "vyomiSnippet": snippet})
    return _out(200, {"results": res, "totalSize": len(ranked), "attributionToken": uuid.uuid4().hex, "summary": {}})
