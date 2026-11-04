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
AgentCore runtimes are control-plane only (the simulator does not run runtime containers, InvokeAgentRuntime returns a
RuntimeClientError); gateway targets of type openApiSchema/smithyModel/mcpServer are registered but their tools are not callable.
"""
from __future__ import annotations

import base64
import json
import random
import re
import string
import time
import urllib.parse
from datetime import datetime, timezone

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

_ACCT = "123456789012"
_REGION = "us-east-1"
_ALNUM = string.ascii_uppercase + string.digits
_TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml", ".log", ".tsv", ".yaml", ".yml", ".rst")
_STORAGE_TYPES = ("OPENSEARCH_SERVERLESS", "PINECONE", "REDIS_ENTERPRISE_CLOUD", "RDS", "MONGO_DB_ATLAS", "OPENSEARCH_MANAGED_CLUSTER",
                  "NEPTUNE_ANALYTICS", "S3_VECTORS")
_EMBED_MODELS = ("amazon.titan-embed-text-v2:0", "amazon.titan-embed-text-v1")
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
    if emb.rsplit("/", 1)[-1] not in _EMBED_MODELS:
        raise _bad(f"The knowledge base embedding model {emb or '(none)'} is not supported; use amazon.titan-embed-text-v2:0")
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
    c = (ds.get("vectorIngestionConfiguration") or {}).get("chunkingConfiguration") or {}
    strat = c.get("chunkingStrategy", "FIXED_SIZE")
    if strat == "NONE":
        return None, 0
    f = c.get("fixedSizeChunkingConfiguration") or {}
    return int(f.get("maxTokens", 300)), int(f.get("overlapPercentage", 20))


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


def _ingest(s3, kb, ds):
    conf = ds["dataSourceConfiguration"]["s3Configuration"]
    bucket = conf["bucketArn"].rsplit(":", 1)[-1]
    prefixes = conf.get("inclusionPrefixes") or [""]
    mx, ov = _chunk_cfg(ds)
    s3c = _s3c()
    # drop this data source's previous chunks (a re-sync replaces them)
    kb["chunks"] = [c for c in kb["chunks"] if c["ds"] != ds["dataSourceId"]]
    scanned = failed = indexed = 0
    reasons, texts, metas = [], [], []
    seen = set()
    for pfx in prefixes:
        for key in _list_keys(s3, bucket, pfx):
            if key in seen or key.endswith("/") or key.endswith(".metadata.json"):
                continue
            seen.add(key)
            scanned += 1
            if not key.lower().endswith(_TEXT_EXT):
                failed += 1
                reasons.append(f"s3://{bucket}/{key}: unsupported document type (the simulator ingests text documents only)")
                continue
            r = s3c.get_object(s3, bucket, key, {}, {})
            if r.status != 200:
                failed += 1
                reasons.append(f"s3://{bucket}/{key}: could not read object")
                continue
            try:
                txt = r.body.decode("utf-8")
            except UnicodeDecodeError:
                failed += 1
                reasons.append(f"s3://{bucket}/{key}: not valid UTF-8 text")
                continue
            meta = {}
            mr = s3c.get_object(s3, bucket, key + ".metadata.json", {}, {})
            if mr.status == 200:
                try:
                    meta = (json.loads(mr.body) or {}).get("metadataAttributes") or {}
                except ValueError:
                    meta = {}
            for ch in _chunk_text(txt, mx, ov):
                texts.append(ch)
                metas.append((f"s3://{bucket}/{key}", meta))
            indexed += 1
    if texts:
        vecs = llm.embed(texts)["vectors"]
        for t, (uri, meta), v in zip(texts, metas, vecs):
            kb["chunks"].append({"ds": ds["dataSourceId"], "uri": uri, "text": t, "vec": v, "metadata": meta})
    return {"numberOfDocumentsScanned": scanned, "numberOfNewDocumentsIndexed": indexed, "numberOfModifiedDocumentsIndexed": 0,
            "numberOfMetadataDocumentsScanned": 0, "numberOfMetadataDocumentsModified": 0, "numberOfDocumentsDeleted": 0,
            "numberOfDocumentsFailed": failed}, reasons


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


def _retrieve(kb, text, k, flt=None):
    if not kb["chunks"]:
        return []
    qv = llm.embed(text)["vectors"][0]
    scored = []
    for c in kb["chunks"]:
        if flt and not _match_filter(flt, c["metadata"]):
            continue
        scored.append((llm.cosine(qv, c["vec"]), c))
    scored.sort(key=lambda x: -x[0])
    res = []
    for sc, c in scored[:k]:
        r = {"content": {"type": "TEXT", "text": c["text"]}, "location": {"type": "S3", "s3Location": {"uri": c["uri"]}},
             "score": round(max(sc, 0.0), 6)}
        if c["metadata"]:
            r["metadata"] = c["metadata"]
        res.append(r)
    return res


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
    return _j(200, {"retrievalResults": _retrieve(kb, q, k, vs.get("filter"))})


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
    res = _retrieve(kb, q, int(vs.get("numberOfResults", 5)), vs.get("filter"))
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
    return bool(re.match(r"^/(agents|knowledgebases|retrieveandgenerate)(/|$)", p))


def dispatch(s3, method, path, query, headers, body):
    method = method.upper()
    path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    segs = [urllib.parse.unquote(s) for s in path.strip("/").split("/")]
    low = [s.lower() for s in segs]
    try:
        st = _state(s3)
        p = _body(body) if method in ("PUT", "POST", "PATCH") else {}
        # ── runtime ──
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


def _create_runtime(st, p):
    name = p.get("agentRuntimeName")
    if not name or not _RT_NAME.match(name):
        raise _bad("1 validation error detected: Value at 'agentRuntimeName' failed to satisfy constraint: Member must satisfy regular expression pattern: [a-zA-Z][a-zA-Z0-9_]{0,47}")
    art = p.get("agentRuntimeArtifact") or {}
    uri = (art.get("containerConfiguration") or {}).get("containerUri") or ""
    if not uri:
        raise _bad("agentRuntimeArtifact.containerConfiguration.containerUri is required")
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
          "targets": {}, "_readyAt": time.time() + 1.0}
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


def _create_target(st, gw, p):
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
    if any(t["name"] == name for t in gw["targets"].values()):
        raise _conflict(f"A target named {name} already exists in this gateway")
    tid = _rid(10)
    now = _iso()
    t = {"gatewayArn": gw["gatewayArn"], "targetId": tid, "createdAt": now, "updatedAt": now, "status": "CREATING", "name": name,
         "description": p.get("description", ""), "targetConfiguration": cfg,
         "credentialProviderConfigurations": p.get("credentialProviderConfigurations") or [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
         "_readyAt": time.time() + 1.0, "_kind": kinds[0]}
    gw["targets"][tid] = t
    gw["updatedAt"] = now
    return _j(202, {k: v for k, v in t.items() if not k.startswith("_")})


def _mcp_tools(gw):
    out = []
    for t in gw["targets"].values():
        if t["_kind"] != "lambda":
            continue
        for tool in _tool_schema(t["targetConfiguration"]):
            out.append((f"{t['name']}___{tool['name']}", t, tool))
    return out


def _mcp(st, lam, gid, p, headers):
    gw = _find_gw(st, gid)
    _ac_ready(gw)
    if gw["status"] != "READY":
        return _j(503, {"message": "Gateway is not READY"})
    if gw["authorizerType"] != "NONE":
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        if not (h.get("authorization") or "").strip():
            return _j(401, {"message": "Missing Authentication Token" if gw["authorizerType"] == "AWS_IAM" else "Unauthorized"})
    rid, method = p.get("id"), p.get("method")

    def ok(result):
        return _j(200, {"jsonrpc": "2.0", "id": rid, "result": result})

    def fail(code, msg):
        return _j(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}})
    if method == "initialize":
        return ok({"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": gw["name"], "version": "1.0.0"}})
    if method in ("notifications/initialized", "ping"):
        return ok({}) if method == "ping" else _j(202, None)
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": tool["description"], "inputSchema": tool["inputSchema"]} for n, _t, tool in _mcp_tools(gw)]})
    if method == "tools/call":
        prm = p.get("params") or {}
        hit = next(((t, tool) for n, t, tool in _mcp_tools(gw) if n == prm.get("name")), None)
        if not hit:
            return fail(-32602, f"Unknown tool: {prm.get('name')}")
        t, tool = hit
        _ac_ready(t)
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


def agentcore_dispatch(s3, lam, method, path, query, headers, body):
    method = method.upper()
    path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    segs = [urllib.parse.unquote(s) for s in path.strip("/").split("/")]
    try:
        st = _state(s3)
        p = _body(body) if method in ("PUT", "POST", "PATCH") else {}
        if segs[0] == "runtimes":
            if len(segs) == 1:
                if method == "POST":
                    return _create_runtime(st, p)
                if method == "GET":
                    return _j(200, _paginate([{k: _pub(r)[k] for k in ("agentRuntimeArn", "agentRuntimeId", "agentRuntimeVersion", "agentRuntimeName", "description", "lastUpdatedAt", "status")}
                                              for r in st["runtimes"].values()], query, "agentRuntimes"))
            else:
                rid = segs[1].rsplit("/", 1)[-1]
                rid = rid.split("runtime/")[-1]
                rt = st["runtimes"].get(rid)
                if len(segs) == 3 and segs[2] == "invocations" and method == "POST":
                    if not rt:
                        raise _nf(f"Runtime {rid} not found")
                    _ac_ready(rt)
                    return {"status": 424, "headers": {"content-type": "application/json", "x-amzn-errortype": "RuntimeClientError"},
                            "body": json.dumps({"message": "The simulator does not run AgentCore runtime containers; the runtime is registered (control plane only)."}).encode()}
                if not rt:
                    raise _nf(f"Runtime {rid} not found")
                if len(segs) == 2:
                    if method == "GET":
                        return _j(200, _pub(rt))
                    if method == "PUT":
                        art = p.get("agentRuntimeArtifact") or rt["agentRuntimeArtifact"]
                        if not (art.get("containerConfiguration") or {}).get("containerUri"):
                            raise _bad("agentRuntimeArtifact.containerConfiguration.containerUri is required")
                        rt["agentRuntimeArtifact"] = art
                        rt["agentRuntimeVersion"] = str(int(rt["agentRuntimeVersion"]) + 1)
                        for f in ("roleArn", "networkConfiguration", "description", "environmentVariables"):
                            if f in p:
                                rt[f] = p[f]
                        rt["status"], rt["_readyAt"], rt["lastUpdatedAt"] = "UPDATING", time.time() + 1.0, _iso()
                        return _j(202, {k: rt[k] for k in ("agentRuntimeArn", "agentRuntimeId", "agentRuntimeVersion", "createdAt", "lastUpdatedAt", "status")})
                    if method == "DELETE":
                        del st["runtimes"][rid]
                        return _j(202, {"status": "DELETING", "agentRuntimeId": rid})
        elif segs[0] == "gateways":
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
                        for f in ("description", "authorizerConfiguration", "exceptionLevel"):
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
                            return _create_target(st, gw, p)
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
