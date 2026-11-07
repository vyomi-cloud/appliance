"""Vertex AI Agent Engine (aiplatform v1/v1beta1 ``reasoningEngines``) - Dev Simplified, substrate-independent, Pyodide-loadable.

Control plane  : POST .../reasoningEngines (LRO) / GET / list / PATCH (LRO) / DELETE (LRO) + the operations those return.
Execution plane: POST ...reasoningEngines/ID:query and :streamQuery against a Vyomi agent spec (core/agent_spec_core) -
                 a tool-calling loop over the shared llm_core seam (fake/scripted model in tests, real model on the booster).

The real service hosts a pickled Python class / packaged ADK app from GCS; the simulator cannot. The "agent" is a JSON Vyomi agent
spec carried in the engine itself, either as ``spec.vyomiAgentSpec`` (REST) or - so the typed google-cloud-aiplatform gapic client
can carry it too - as a ``spec.deploymentSpec.env`` entry named ``VYOMI_AGENT_SPEC`` whose value is the spec JSON.
An engine created without a spec is a valid control-plane record whose :query returns FAILED_PRECONDITION.

Class methods (``classMethod`` in the request, as ADK-templated Agent Engines expose them): ``query`` (input.message|input),
``stream_query`` / ``async_stream_query`` (:streamQuery), and the session helpers ``create_session`` / ``get_session`` /
``list_sessions`` / ``delete_session`` (+ ``async_`` variants). Sessions keep the multi-turn history in the engine.

:streamQuery returns what the aiplatform REST transport emits for a server-streaming HttpBody method: a JSON array whose elements
are HttpBody objects ({contentType, data=base64(JSON event)}); events follow the ADK Event shape (content.parts with text /
functionCall / functionResponse, author, id, timestamp). The gapic client (transport="rest") iterates them natively.

Honest limits: no pickle / packageSpec / GCS deployment (the vertexai.agent_engines.create(<python object>) flow is not
supported - use the REST/gapic create with a spec), no Memory Bank / Example Store, no framework runtime (ADK/LangChain/LangGraph),
state is in the persisted account bag, answers come from the small local model.
"""
from __future__ import annotations

import base64
import json
import random
import re
import time
import uuid
from datetime import datetime, timezone

try:
    from core import agent_spec_core as ag
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import agent_spec_core as ag  # type: ignore
    import llm_core as llm  # type: ignore

_PATH = re.compile(r"^/(v1|v1beta1)/projects/([^/]+)/locations/([^/]+)/reasoningEngines(?:/([^/:]+)(?:/(operations)(?:/([^/:]+))?|:([A-Za-z]+))?|:([A-Za-z]+))?/?$")
_OPS_ONLY = re.compile(r"^/(v1|v1beta1)/projects/([^/]+)/locations/([^/]+)/operations/(ae-[0-9a-f]+)$")
_LRO = {"create": "CreateReasoningEngineOperationMetadata", "update": "UpdateReasoningEngineOperationMetadata", "delete": "DeleteOperationMetadata"}
_METHODS = [
    {"name": "query", "api_mode": "", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "user_id": {"type": "string"}, "session_id": {"type": "string"}}}},
    {"name": "stream_query", "api_mode": "stream", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "user_id": {"type": "string"}, "session_id": {"type": "string"}}}},
    {"name": "async_stream_query", "api_mode": "async_stream", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "user_id": {"type": "string"}, "session_id": {"type": "string"}}}},
    {"name": "create_session", "api_mode": "", "parameters": {"type": "object", "properties": {"user_id": {"type": "string"}}}},
    {"name": "list_sessions", "api_mode": "", "parameters": {"type": "object", "properties": {"user_id": {"type": "string"}}}},
    {"name": "get_session", "api_mode": "", "parameters": {"type": "object", "properties": {"user_id": {"type": "string"}, "session_id": {"type": "string"}}}},
    {"name": "delete_session", "api_mode": "", "parameters": {"type": "object", "properties": {"user_id": {"type": "string"}, "session_id": {"type": "string"}}}},
]
_STREAMING = ("stream_query", "async_stream_query")
_SYNC_MODEL_CALLS = ("query", "async_query")


class _Err(Exception):
    def __init__(self, status, st, msg):
        self.status, self.st, self.msg = status, st, msg


def _am():
    try:
        from core import ai_models_core as m
    except ImportError:  # pragma: no cover
        import ai_models_core as m  # type: ignore
    return m


def handles(path):
    p = path.split("?", 1)[0]
    return bool(_PATH.match(p) or _OPS_ONLY.match(p))


def _iso(ts=None):
    return datetime.fromtimestamp(ts if ts is not None else time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _state(store):
    st = store.account.setdefault("agent_engine", {})
    st.setdefault("engines", {})
    st.setdefault("ops", {})
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


def spec_of(engine) -> dict | None:
    """The Vyomi agent spec carried by the engine (REST field or deploymentSpec.env), or None."""
    sp = engine.get("spec") or {}
    if isinstance(sp.get("vyomiAgentSpec"), (dict, str)):
        return sp["vyomiAgentSpec"]
    for e in (sp.get("deploymentSpec") or {}).get("env") or []:
        if e.get("name") == ag.SPEC_ENV:
            return e.get("value")
    return None


def _validate_spec(engine):
    s = spec_of(engine)
    if s is None:
        return
    try:
        ag.parse_spec(s)
    except ag.SpecError as e:
        raise _Err(400, "INVALID_ARGUMENT", f"Invalid Vyomi agent spec: {e}")


def _view(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _op(st, scope, kind, response=None, name=None, rname=None):
    oid = "ae-" + uuid.uuid4().hex[:16]
    now = _iso()
    meta = {"@type": f"type.googleapis.com/google.cloud.aiplatform.v1.{_LRO[kind]}", "genericMetadata": {"createTime": now, "updateTime": now}}
    op = {"name": f"{scope}/operations/{oid}", "metadata": meta, "done": True,
          "response": dict(response, **{"@type": "type.googleapis.com/google.cloud.aiplatform.v1.ReasoningEngine"}) if response else {"@type": "type.googleapis.com/google.protobuf.Empty"}}
    st["ops"][oid] = op
    return op


# ───────────────────────────── dispatch ─────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    method = method.upper()
    path = path.split("?", 1)[0]
    q = query or {}
    try:
        st = _state(store)
        mo = _OPS_ONLY.match(path)
        if mo:
            op = st["ops"].get(mo.group(4))
            if not op or method != "GET":
                raise _Err(404, "NOT_FOUND", f"Operation {path} not found.")
            return _am()._j(200, op)
        m = _PATH.match(path)
        ver, proj, loc, eid, ops, opid, verb, coll_verb = m.groups()
        parent = f"projects/{proj}/locations/{loc}"
        if eid is None:
            if method == "POST" and not coll_verb:
                return _create(st, parent, _body(body))
            if method == "GET" and not coll_verb:
                return _list(st, parent, q)
            raise _Err(404, "NOT_FOUND", f"Unsupported Agent Engine operation: {method} {path}")
        name = f"{parent}/reasoningEngines/{eid}"
        if ops:
            op = st["ops"].get(opid) if opid else None
            if method == "GET" and op and op["name"].startswith(name + "/"):
                return _am()._j(200, op)
            if method == "GET" and not opid:
                return _am()._j(200, {"operations": [o for o in st["ops"].values() if o["name"].startswith(name + "/")]})
            raise _Err(404, "NOT_FOUND", f"Operation {path} not found.")
        eng = st["engines"].get(name)
        if verb:
            if method != "POST":
                raise _Err(404, "NOT_FOUND", f"Unsupported Agent Engine operation: {method} {path}")
            if verb not in ("query", "streamQuery"):
                raise _Err(404, "NOT_FOUND", f"Unsupported Agent Engine method :{verb}")
            if not eng:
                raise _Err(404, "NOT_FOUND", f"Reasoning Engine `{name}` not found.")
            return _query(st, eng, verb, _body(body), q)
        if not eng:
            if method == "DELETE":
                raise _Err(404, "NOT_FOUND", f"The ReasoningEngine does not exist: {name}")
            raise _Err(404, "NOT_FOUND", f"Reasoning Engine `{name}` not found.")
        if method == "GET":
            return _am()._j(200, _view(eng))
        if method == "PATCH":
            return _update(st, eng, _body(body), q)
        if method == "DELETE":
            force = str(q.get("force", "")).lower() == "true"
            if eng["_sessions"] and not force:
                raise _Err(400, "FAILED_PRECONDITION", "The ReasoningEngine has child resources (sessions). Set force=true to delete them too.")
            del st["engines"][name]
            return _am()._j(200, _op(st, name, "delete"))
        raise _Err(404, "NOT_FOUND", f"Unsupported Agent Engine operation: {method} {path}")
    except _Err as e:
        return _am()._g_err(e.status, e.st, e.msg)
    except llm.LlmUnavailable as e:
        return _am()._g_err(503, "UNAVAILABLE", f"{e}")


def _create(st, parent, p):
    dn = p.get("displayName")
    if not dn or not isinstance(dn, str) or len(dn) > 128:
        raise _Err(400, "INVALID_ARGUMENT", "reasoning_engine.display_name: must be set and at most 128 characters.")
    eid = str(random.randint(10 ** 18, 10 ** 19 - 1))
    name = f"{parent}/reasoningEngines/{eid}"
    now = _iso()
    sp = json.loads(json.dumps(p.get("spec") or {}))
    if not sp.get("classMethods"):
        sp["classMethods"] = json.loads(json.dumps(_METHODS))
    eng = {"name": name, "displayName": dn, "description": p.get("description", ""), "spec": sp, "createTime": now, "updateTime": now,
           "etag": uuid.uuid4().hex[:16], "_sessions": {}}
    if p.get("labels"):
        eng["labels"] = p["labels"]
    _validate_spec(eng)
    st["engines"][name] = eng
    return _am()._j(200, _op(st, name, "create", _view(eng)))


def _list(st, parent, q):
    items = sorted((e for n, e in st["engines"].items() if n.startswith(parent + "/")), key=lambda e: e["createTime"])
    flt = q.get("filter") or ""
    mf = re.match(r'^\s*display_name\s*=\s*"?([^"]*)"?\s*$', flt)
    if mf:
        items = [e for e in items if e["displayName"] == mf.group(1)]
    size = max(1, min(int(q.get("pageSize") or 100), 100))
    start = int(q.get("pageToken") or 0)
    page = items[start:start + size]
    out = {"reasoningEngines": [_view(e) for e in page]} if page else {}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return _am()._j(200, out)


def _update(st, eng, p, q):
    mask = [m for m in str(q.get("updateMask", "")).split(",") if m] or [k for k in ("displayName", "description", "spec", "labels") if k in p]
    for f in mask:
        top = f.split(".")[0]
        if top in ("displayName", "description", "labels"):
            eng[top] = p.get(top, eng.get(top))
        elif top == "spec":
            eng["spec"] = json.loads(json.dumps(p.get("spec") or {}))
            if not eng["spec"].get("classMethods"):
                eng["spec"]["classMethods"] = json.loads(json.dumps(_METHODS))
        else:
            raise _Err(400, "INVALID_ARGUMENT", f"Unsupported update_mask path: {f}")
    _validate_spec(eng)
    eng["updateTime"], eng["etag"] = _iso(), uuid.uuid4().hex[:16]
    return _am()._j(200, _op(st, eng["name"], "update", _view(eng)))


# ───────────────────────────── execution ─────────────────────────────
def _message_text(inp):
    m = inp.get("message", inp.get("input", inp.get("prompt")))
    if isinstance(m, dict):
        m = "".join(x.get("text", "") for x in m.get("parts") or [])
    if not isinstance(m, str) or not m:
        raise _Err(400, "INVALID_ARGUMENT", "input.message (a non-empty string, or {parts:[{text}]}) is required.")
    return m


def _session_view(s):
    return {"id": s["id"], "appName": s["appName"], "userId": s["userId"], "state": s["state"], "events": [{k: v for k, v in e.items() if not k.startswith("_")} for e in s["events"]], "lastUpdateTime": s["lastUpdateTime"]}


def _event(author, parts, role, inv):
    return {"content": {"parts": parts, "role": role}, "author": author, "id": uuid.uuid4().hex[:12], "invocation_id": inv, "timestamp": time.time(),
            "actions": {"state_delta": {}, "artifact_delta": {}}}


def _step_event(ev, author, inv):
    if ev["type"] == "model" and ev["tool_calls"]:
        return _event(author, [{"function_call": {"id": c["id"], "name": c["name"], "args": c["arguments"]}} for c in ev["tool_calls"]], "model", inv)
    if ev["type"] == "tool_result":
        r = ev["result"] if isinstance(ev["result"], dict) else {"result": ev["result"]}
        return _event(author, [{"function_response": {"id": ev["id"], "name": ev["name"], "response": r}}], "user", inv)
    return None


def _prepare(st, eng, inp, cm):
    spec = spec_of(eng)
    if spec is None:
        raise _Err(400, "FAILED_PRECONDITION", "This Reasoning Engine has no Vyomi agent spec (set spec.vyomiAgentSpec or a "
                                               f"spec.deploymentSpec.env entry named {ag.SPEC_ENV}); the simulator does not run pickled/packaged agents.")
    text = _message_text(inp)
    uid = str(inp.get("user_id") or "default-user")
    sid = inp.get("session_id")
    sess = None
    if sid:
        sess = eng["_sessions"].get(str(sid))
        if not sess:
            raise _Err(404, "NOT_FOUND", f"Session {sid} not found.")
    return spec, text, uid, sess


def _query(st, eng, verb, p, q):
    cm = p.get("classMethod") or ("stream_query" if verb == "streamQuery" else "query")
    inp = p.get("input")
    if inp is None:
        inp = {}
    if not isinstance(inp, dict):
        raise _Err(400, "INVALID_ARGUMENT", "input must be an object.")
    sess_r = _session_api(eng, cm, inp)
    if sess_r is not None:
        return _am()._j(200, {"output": sess_r}) if verb == "query" else _stream_http([sess_r])
    if verb == "query" and cm in _STREAMING or verb == "streamQuery" and cm in _SYNC_MODEL_CALLS:
        raise _Err(400, "INVALID_ARGUMENT", f"classMethod `{cm}` is not a {'streaming' if cm in _STREAMING else 'unary'} method; use "
                                            f"{':streamQuery' if cm in _STREAMING else ':query'}.")
    if cm not in _SYNC_MODEL_CALLS + _STREAMING:
        raise _Err(400, "INVALID_ARGUMENT", f"Unknown class method `{cm}`. Available: {', '.join(m['name'] for m in eng['spec']['classMethods'])}.")
    spec, text, uid, sess = _prepare(st, eng, inp, cm)
    history = [m for e in (sess["events"] if sess else []) for m in e.get("_m", [])] if sess else []
    inv = "e-" + str(uuid.uuid4())
    author = ag.parse_spec(spec).get("name") or eng["displayName"].replace(" ", "_")
    if verb == "query":
        try:
            r = ag.run(spec, text, history)
        except ag.SpecError as e:
            raise _Err(400, "INVALID_ARGUMENT", str(e))
        except ValueError as e:
            raise _Err(400, "INVALID_ARGUMENT", str(e))
        if sess:
            _remember(sess, text, r, author, inv)
        return _am()._j(200, {"output": {"output": r["text"], "steps": [{k: v for k, v in s.items() if k != "step"} for s in r["steps"]],
                                         "usage": r["usage"], "model": r["model"], "truncated": r["truncated"]}}, {"x-vyomi-local-model": r["model"]})
    gen = ag.run_events(spec, text, history)
    first = next(gen)                      # surface a dead model / bad request as a proper status, not mid-stream
    return _stream_events(_chain(first, gen), sess, text, author, inv)


def _chain(first, gen):
    yield first
    yield from gen


def _stream_http(objs):
    """objs -> JSON-array-of-HttpBody (the aiplatform REST framing for a server-streaming HttpBody method)."""
    def g():
        yield "["
        for i, o in enumerate(objs):
            yield ("," if i else "") + json.dumps({"contentType": "application/json", "data": base64.b64encode(json.dumps(o).encode()).decode()})
        yield "]"
    return _am()._stream_out(200, {}, g(), "application/json")


def _stream_events(steps, sess, text, author, inv):
    def g():
        yield "["
        n = 0
        final = None
        for ev in steps:
            if ev["type"] == "final":
                final = ev
                out = _event(author, [{"text": ev["text"]}], "model", inv)
                out["usage_metadata"] = {"prompt_token_count": ev["usage"]["input_tokens"], "candidates_token_count": ev["usage"]["output_tokens"],
                                         "total_token_count": ev["usage"]["input_tokens"] + ev["usage"]["output_tokens"]}
                out["turn_complete"] = True
            else:
                out = _step_event(ev, author, inv)
                if out is None:
                    continue
            yield ("," if n else "") + json.dumps({"contentType": "application/json", "data": base64.b64encode(json.dumps(out).encode()).decode()})
            n += 1
        if final and sess:
            _remember(sess, text, final, author, inv)
        yield "]"
    return _am()._stream_out(200, {}, g(), "application/json")


def _remember(sess, text, r, author, inv):
    sess["events"].append(dict(_event("user", [{"text": text}], "user", inv), _m=[r["messages"][0]]))
    sess["events"].append(dict(_event(author, [{"text": r["text"]}], "model", inv), _m=r["messages"][1:]))
    sess["lastUpdateTime"] = time.time()


def _session_api(eng, cm, inp):
    base = cm[len("async_"):] if cm.startswith("async_") else cm
    if base not in ("create_session", "get_session", "list_sessions", "delete_session"):
        return None
    uid = str(inp.get("user_id") or "")
    if not uid:
        raise _Err(400, "INVALID_ARGUMENT", "input.user_id is required.")
    S = eng["_sessions"]
    if base == "create_session":
        sid = str(inp.get("session_id") or random.randint(10 ** 17, 10 ** 18 - 1))
        S[sid] = {"id": sid, "appName": eng["name"].rsplit("/", 1)[-1], "userId": uid, "state": inp.get("state") or {}, "events": [], "lastUpdateTime": time.time()}
        return _session_view(S[sid])
    if base == "list_sessions":
        return {"sessions": [_session_view(s) for s in S.values() if s["userId"] == uid]}
    s = S.get(str(inp.get("session_id")))
    if not s or s["userId"] != uid:
        raise _Err(404, "NOT_FOUND", f"Session {inp.get('session_id')} not found.")
    if base == "get_session":
        return _session_view(s)
    del S[s["id"]]
    return {}
