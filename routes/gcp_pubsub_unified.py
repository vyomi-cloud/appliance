"""v4 C0g — GCP Pub/Sub on the offline appliance, ONE engine.

Native wire, served by the shared core Nano uses (core/gcp_pubsub_core.py) over the
appliance's space-scoped, persisted state (core/appliance_stores.AppStatePubsubStore,
whose records live in the pre-v4 `gcp_pubsub_state` slot):

  * /v1/projects/{p}/topics…         create (PUT) / get / list / patch / delete / :publish,
                                      topics/{t}/subscriptions, topics/{t}/snapshots, IAM
  * /v1/projects/{p}/subscriptions…  create (PUT) / get / list / patch / delete / :pull /
                                      :acknowledge / :modifyAckDeadline / :modifyPushConfig /
                                      :seek / :detach, IAM
  * /v1/projects/{p}/snapshots…      create (PUT) / get / list / patch / delete
  * /v1/projects/{p}/schemas…        create / get / list / delete / :validate / :validateMessage

(and the same under /_wire/, which routes/wire_prefix.py rewrites). Every path under those
four collections is answered by the core — an unknown one with a google.rpc JSON error,
never the S3 catch-all.

Classic console paths are aliases onto the SAME store, keeping their pre-v4 contract where a
console depends on it: /api/gcp/pubsub/v1/… (POST-with-body create, a default subscription on
topic create, topic delete cascading to its subscriptions, `{done}` deletes, `kind` lists),
/api/gcp/sqs/queues… and /api/gcp/pubsub/schemas…, plus the pre-v4 non-native helpers on
/v1 (POST …/topics|subscriptions with the id in the body, …/messages peeks, :purge).

Cloud Scheduler pubsubTarget deliveries publish through `publish()` here
(providers/gcp_cloudscheduler_console.py).

Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without gcp_pubsub (or VYOMI_LEGACY_WIRE=1) leaves
every path on the pre-v4 handlers (providers/gcp_services.py).
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from urllib.parse import quote

from fastapi import Request, Response

from core import wire_ingress as _wi

_log = logging.getLogger("vyomi.engine")
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
_COLLECTIONS = ("topics", "subscriptions", "snapshots", "schemas")


# ── helpers ──────────────────────────────────────────────────────────────────
def _path(request: Request) -> str:
    p = (request.scope.get("path") or request.url.path).split("?", 1)[0]
    if p.startswith("/_wire/"):
        p = p[len("/_wire"):]
    return p


def _query(request: Request) -> dict:
    return dict(request.query_params)


def _resp(out: dict) -> Response:
    return _wi.to_response(out)


def _json_out(status: int, obj) -> dict:
    return {"status": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(obj).encode()}


def _load(body) -> dict:
    try:
        d = json.loads(body or b"{}")
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def _gerr(status: int, message: str, code: str = "") -> dict:
    return _json_out(status, {"error": {"code": status, "message": message, "status": code or {
        400: "INVALID_ARGUMENT", 404: "NOT_FOUND", 409: "ALREADY_EXISTS"}.get(status, "FAILED_PRECONDITION")}})


def _default_project(request: Request | None = None) -> str:
    from core.app_context import gcp_project_name
    return gcp_project_name(request.query_params.get("project") if request is not None else None)


@contextmanager
def _gcp():
    """Resolve the space-scoped state as a GCP request (background callers, console
    summary) — the Pub/Sub slot is the GCP space's."""
    from core import app_context as _ctx
    tok = _ctx.REQUEST_PROVIDER.set("gcp")
    try:
        yield
    finally:
        _ctx.REQUEST_PROVIDER.reset(tok)


def _store():
    from core import appliance_stores as aps
    st = aps.gcp_pubsub_store()
    st.adopt()
    return st


def _server():
    import server
    return server


# ── the engine call + the v3 side effects (CloudSim inventory sync, usage) ────
def _sync(kind: str, name: str, rec: dict | None, delete: bool = False) -> None:
    try:
        s = _server()
        if delete:
            s._cloudsim_sync_service_resource("gcp", "pubsub", kind, name, {}, "gcp_pubsub", action="delete")
        else:
            s._cloudsim_sync_service_resource("gcp", "pubsub", kind, name, dict(rec or {}, name=name), "gcp_pubsub")
        s._record_usage(f"gcp.pubsub.{'delete' if delete else 'create'}_{kind}", {"name": name})
    except Exception as exc:   # never fail the API call over the inventory mirror
        _log.debug("pubsub: cloudsim sync skipped: %s", exc)


def ps(method: str, native: str, query: dict | None = None, body: bytes = b"") -> dict:
    """Serve one native Pub/Sub call on the core (the GCP space's state)."""
    with _gcp():
        out = _wi.dispatch_service("gcp_pubsub", method, native, query or {},
                                   {"content-type": "application/json"}, body or b"")
    if out["status"] == 200 and method in ("PUT", "DELETE"):
        segs = native.split("?", 1)[0].strip("/").split("/")
        if len(segs) == 5 and segs[0] == "v1" and segs[3] in ("topics", "subscriptions") and ":" not in segs[4]:
            kind = "topic" if segs[3] == "topics" else "subscription"
            _sync(kind, "/".join(segs[1:]), _load(out["body"]), delete=(method == "DELETE"))
    return out


def publish(project: str, topic: str, data: str, attributes: dict | None = None) -> int:
    """Publish one message (base64 `data`) — the Cloud Scheduler pubsubTarget hook.
    Returns the HTTP status of the core's publish."""
    body = json.dumps({"messages": [{"data": data or "", "attributes": dict(attributes or {})}]}).encode()
    return ps("POST", f"/v1/projects/{quote(project)}/topics/{quote(topic)}:publish", {}, body)["status"]


# ── pre-v4 contracts ─────────────────────────────────────────────────────────
def _view(native: str) -> dict | None:
    out = ps("GET", native)
    return _load(out["body"]) if out["status"] == 200 else None


def _classic_create_topic(project: str, data: dict, default_sub: bool) -> dict:
    """POST …/topics with the id in the body (`topicId` / `name` / `topic`). The pre-v4
    console create also made a pull subscription of the same id (or `subscriptionId`)."""
    tid = str(data.get("topicId") or data.get("name") or data.get("topic") or "").split("/")[-1].strip()
    if not tid:
        return _gerr(400, "Topic id is required")
    body = {k: data[k] for k in ("labels", "kmsKeyName", "messageRetentionDuration", "schemaSettings") if data.get(k)}
    out = ps("PUT", f"/v1/projects/{quote(project)}/topics/{quote(tid)}", {}, json.dumps(body).encode())
    if out["status"] != 200 or not default_sub:
        return out
    sid = str(data.get("subscriptionId") or tid).split("/")[-1].strip()
    sub = {"topic": f"projects/{project}/topics/{tid}", "ackDeadlineSeconds": int(data.get("ackDeadlineSeconds") or 10)}
    if isinstance(data.get("labels"), dict):
        sub["labels"] = data["labels"]
    ps("PUT", f"/v1/projects/{quote(project)}/subscriptions/{quote(sid)}", {}, json.dumps(sub).encode())  # 409 = kept
    return out


def _classic_create_subscription(project: str, data: dict, sub_id: str = "") -> dict:
    sid = str(sub_id or data.get("subscriptionId") or data.get("name") or "").split("/")[-1].strip()
    if not sid:
        return _gerr(400, "Subscription id is required")
    topic = str(data.get("topic") or "").strip()
    if not topic:
        return _gerr(400, "Topic is required")
    if not topic.startswith("projects/"):
        data = dict(data, topic=f"projects/{project}/topics/{topic}")
    data = {k: v for k, v in data.items() if k not in ("name", "subscriptionId", "project")}
    return ps("PUT", f"/v1/projects/{quote(project)}/subscriptions/{quote(sid)}", {}, json.dumps(data).encode())


def _peek(project: str, coll: str, rid: str) -> dict:
    """GET …/topics/{t}/messages | …/subscriptions/{s}/messages — the pre-v4 console's
    non-native backlog view (nothing is leased or acknowledged)."""
    with _gcp():
        return _peek_in(project, coll, rid)


def _peek_in(project: str, coll: str, rid: str) -> dict:
    st = _store()
    name = f"projects/{project}/{coll}/{rid}"
    from core import gcp_pubsub_core as core

    def _msg(m: dict) -> dict:
        v = {"data": m.get("data", ""), "attributes": m.get("attributes") or {},
             "messageId": m.get("messageId", ""), "publishTime": m.get("publishTime", "")}
        if m.get("orderingKey"):
            v["orderingKey"] = m["orderingKey"]
        return v

    if coll == "subscriptions":
        sub = st.get_queue(name)
        if not sub:
            return _gerr(404, f"Subscription not found: {name}")
        core._prune_retention(st, sub)
        msgs = [{"message": _msg(m)} for m in sub.get("messages", []) if not m.get("_acked")]
        return _json_out(200, {"receivedMessages": msgs, "kind": "pubsub#receivedMessageList"})
    topic = st.get_topic(name)
    if not topic:
        return _gerr(404, f"Topic not found: {name}")
    seen: dict = {}
    for m in topic.get("_retained", []):
        seen.setdefault(m.get("messageId"), _msg(m))
    for sn in topic.get("subscriptions", []):
        for m in (st.get_queue(sn) or {}).get("messages", []):
            seen.setdefault(m.get("messageId"), _msg(m))
    msgs = sorted(seen.values(), key=lambda m: m.get("publishTime", ""))
    return _json_out(200, {"messages": msgs, "kind": "pubsub#messageList"})


def _purge(project: str, rid: str) -> dict:
    with _gcp():
        return _purge_in(project, rid)


def _purge_in(project: str, rid: str) -> dict:
    st = _store()
    name = f"projects/{project}/subscriptions/{rid}"
    sub = st.get_queue(name)
    if not sub:
        return _gerr(404, f"Subscription not found: {name}")
    sub["messages"], sub["ackids"] = [], {}
    return _json_out(200, {"done": True})


def _compat(method: str, native: str, query: dict, body: bytes) -> dict | None:
    """The pre-v4 non-native helpers the /v1 prefix also answered (None = not one)."""
    segs = native.strip("/").split("/")                  # v1 projects p coll [id [sub]]
    if len(segs) < 4 or segs[0] != "v1" or segs[1] != "projects":
        return None
    project, coll = segs[2], segs[3]
    if len(segs) == 4 and method == "POST" and coll in ("topics", "subscriptions"):
        data = _load(body)
        return (_classic_create_topic(project, data, default_sub=True) if coll == "topics"
                else _classic_create_subscription(project, data))
    if len(segs) == 4 and method == "POST" and coll == "schemas" and not query.get("schemaId"):
        data = _load(body)
        sid = str(data.get("schemaId") or data.get("name") or "").split("/")[-1].strip()
        if sid:
            data.setdefault("type", "AVRO")
            return ps("POST", native, dict(query, schemaId=sid), json.dumps(data).encode())
    if len(segs) == 6 and method == "GET" and segs[5] == "messages" and coll in ("topics", "subscriptions"):
        return _peek(project, coll, segs[4])
    if len(segs) == 5 and method == "POST" and coll == "subscriptions" and segs[4].endswith(":purge"):
        return _purge(project, segs[4][:-len(":purge")])
    return None


def _classic(method: str, native: str, query: dict, body: bytes) -> dict:
    """/api/gcp/pubsub/v1/… — the native call with the pre-v4 console contract kept."""
    compat = _compat(method, native, query, body)
    if compat is not None:
        return compat
    segs = native.strip("/").split("/")
    if len(segs) < 4 or segs[0] != "v1" or segs[1] != "projects":
        return ps(method, native, query, body)
    project, coll = segs[2], segs[3]
    if len(segs) == 4 and method == "GET":
        out = ps(method, native, query, body)
        if out["status"] == 200:
            d = _load(out["body"])
            d.setdefault(coll, [])
            d.update(nextPageToken="", kind={"topics": "pubsub#topicList", "subscriptions": "pubsub#subscriptionList",
                                             "snapshots": "pubsub#snapshotList", "schemas": "pubsub#schemaList"}.get(coll, ""))
            out = _json_out(200, d)
        return out
    if len(segs) == 5 and method == "DELETE" and coll in ("topics", "subscriptions"):
        if coll == "topics":                              # pre-v4: a topic took its subscriptions with it
            with _gcp():
                topic = _store().get_topic(f"projects/{project}/topics/{segs[4]}")
            for sn in list((topic or {}).get("subscriptions", [])):
                ps("DELETE", "/v1/" + sn)
        out = ps(method, native, query, body)
        return _json_out(200, {"done": True}) if out["status"] == 200 else out
    if len(segs) == 5 and method == "POST" and segs[4].endswith(":publish"):
        data = _load(body)
        if not data.get("messages"):
            return _json_out(200, {"messageIds": []})
    if len(segs) == 5 and method == "POST" and segs[4].endswith(":pull"):
        data = _load(body)
        data["maxMessages"] = int(data.get("maxMessages") or data.get("max_messages")
                                  or data.get("max_number_of_messages") or 10)
        body = json.dumps(data).encode()
    if len(segs) == 5 and method == "POST" and segs[4].endswith(":acknowledge"):
        out = ps(method, native, query, body)
        return _json_out(200, {"acknowledged": True}) if out["status"] == 200 else out
    return ps(method, native, query, body)


# ── route handlers ───────────────────────────────────────────────────────────
async def _native(request: Request):
    native = _path(request)
    query, body = _query(request), await request.body()
    compat = _compat(request.method, native, query, body)
    return _resp(compat if compat is not None else ps(request.method, native, query, body))


async def _classic_v1(request: Request):
    native = _path(request)[len("/api/gcp/pubsub"):]
    return _resp(_classic(request.method, native, _query(request), await request.body()))


async def _sqs_alias(request: Request):
    """/api/gcp/sqs/queues[/{id}[/messages|/receive|/messages/{receipt}/delete]] — the pre-v4
    SQS-shaped aliases (project from the query string): the collection lists / creates
    TOPICS, `POST /{id}` creates a SUBSCRIPTION, GET / PATCH / DELETE `/{id}` act on a topic."""
    project = _default_project(request)
    p = quote(project)
    tail = [s for s in _path(request)[len("/api/gcp/sqs/queues"):].split("/") if s]
    method, body = request.method, await request.body()
    q = {k: v for k, v in _query(request).items() if k != "project"}
    if not tail:
        if method == "GET":
            return _resp(_classic("GET", f"/v1/projects/{p}/topics", q, b""))
        if method == "POST":
            return _resp(_classic_create_topic(project, _load(body), default_sub=True))
    elif len(tail) == 1:
        rid = quote(tail[0])
        if method == "POST":
            return _resp(_classic_create_subscription(project, _load(body), sub_id=tail[0]))
        if method in ("GET", "PATCH", "DELETE"):
            return _resp(_classic(method, f"/v1/projects/{p}/topics/{rid}", q, body))
    elif len(tail) == 2 and method == "POST" and tail[1] == "messages":
        return _resp(_classic("POST", f"/v1/projects/{p}/topics/{quote(tail[0])}:publish", q, body))
    elif len(tail) == 2 and method == "POST" and tail[1] == "receive":
        return _resp(_classic("POST", f"/v1/projects/{p}/subscriptions/{quote(tail[0])}:pull", q, body))
    elif len(tail) == 4 and method == "POST" and tail[1] == "messages" and tail[3] == "delete":
        data = _load(body)
        ids = [str(a) for a in (data.get("ackIds") or [])] + [tail[2]]
        return _resp(_classic("POST", f"/v1/projects/{p}/subscriptions/{quote(tail[0])}:acknowledge", q,
                              json.dumps({"ackIds": ids}).encode()))
    return _resp(_gerr(404, f"Unknown path: {_path(request)}", "NOT_FOUND"))


async def _schemas_alias(request: Request):
    """/api/gcp/pubsub/schemas[/{id}] — the pre-v4 schema aliases (project from the query)."""
    project = quote(_default_project(request))
    tail = [s for s in _path(request)[len("/api/gcp/pubsub/schemas"):].split("/") if s]
    q = {k: v for k, v in _query(request).items() if k != "project"}
    if not tail:
        return _resp(_classic(request.method, f"/v1/projects/{project}/schemas", q, await request.body()))
    if len(tail) == 1 and request.method in ("GET", "DELETE"):
        out = _classic(request.method, f"/v1/projects/{project}/schemas/{quote(tail[0])}", q, b"")
        if request.method == "DELETE" and out["status"] == 200:
            out = _json_out(200, {"kind": "pubsub#schema", "deleted": True, "name": tail[0]})
        return _resp(out)
    return _resp(_gerr(404, f"Unknown path: {_path(request)}", "NOT_FOUND"))


# ── registration ─────────────────────────────────────────────────────────────
def register(app) -> list:
    """Mount the unified routes (call BEFORE the provider routes so these win).
    Returns the unified services it mounted."""
    if not _wi.is_unified("gcp_pubsub"):
        return []
    for pre in ("/v1/projects/{project}", "/pubsub/v1/projects/{project}"):
        for coll in _COLLECTIONS:
            app.add_route(f"{pre}/{coll}", _native if pre.startswith("/v1") else _pubsub_prefixed, methods=_METHODS)
            app.add_route(f"{pre}/{coll}:{{verb}}", _native if pre.startswith("/v1") else _pubsub_prefixed, methods=_METHODS)
            app.add_route(f"{pre}/{coll}/{{rest:path}}", _native if pre.startswith("/v1") else _pubsub_prefixed, methods=_METHODS)
    app.add_route("/api/gcp/pubsub/v1/{rest:path}", _classic_v1, methods=_METHODS)
    app.add_route("/api/gcp/sqs/queues", _sqs_alias, methods=_METHODS)
    app.add_route("/api/gcp/sqs/queues/{rest:path}", _sqs_alias, methods=_METHODS)
    app.add_route("/api/gcp/pubsub/schemas", _schemas_alias, methods=_METHODS)
    app.add_route("/api/gcp/pubsub/schemas/{rest:path}", _schemas_alias, methods=_METHODS)
    return ["gcp_pubsub"]


async def _pubsub_prefixed(request: Request):
    """/pubsub/v1/… — the host-prefixed spelling (base URL `…/pubsub`) of the same API."""
    native = _path(request)[len("/pubsub"):]
    query, body = _query(request), await request.body()
    compat = _compat(request.method, native, query, body)
    return _resp(compat if compat is not None else ps(request.method, native, query, body))


# ── readers for the console summary ──────────────────────────────────────────
def summary_counts(target_project: str = "") -> dict:
    """Override for /api/gcp/console/summary: gcp-pubsub = the project's topics."""
    if not _wi.is_unified("gcp_pubsub"):
        return {}
    pre = f"projects/{target_project}/topics/" if target_project else "projects/"
    with _gcp():
        return {"gcp-pubsub": sum(1 for k in _store().topics if str(k).startswith(pre))}
