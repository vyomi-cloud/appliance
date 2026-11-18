"""Real Google Pub/Sub + Firestore emulators as the simulator's GCP data plane (offline / Mesh only).

Switch: VYOMI_GCP_REAL_BACKENDS=1 plus the standard PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST
(or the CLOUDLEARN_* twins the compose files already set). Off (the default) this module does nothing.
Never enabled on Nano: the emulators are JVM processes and need a container runtime.

How: install() replaces `gcp_pubsub_core.dispatch` and `gcp_firestore_core.dispatch` with wrappers.
Every caller already goes through those two functions (the wire front door, the console's classic
routes, Eventarc, Cloud Run triggers, Cloud Scheduler, SCC notifications, log sinks, Secret Manager
notifications), so one seam covers them all and the cores themselves stay untouched (Nano keeps them).

  * the emulator holds ALL topic/subscription/snapshot/message state and ALL (default)-database
    documents, so unmodified gRPC clients (PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST) and the
    simulator's REST surface and console read and write the same data;
  * the simulator's own Pub/Sub store keeps a METADATA-ONLY shadow of topics/subscriptions (no
    messages) because simulator features read it directly (store.get_topic / get_queue: Eventarc
    topic checks, the Eventarc-owned subscription flag); the wrapper writes the shadow on create/
    patch/delete and the store's get_topic imports a topic created by a gRPC client on first miss;
  * messages published through the simulator call the caller's on_publish hook exactly as the core
    does, so Eventarc / Cloud Run triggers keep firing; messages published by a gRPC client are
    delivered to those triggers by a small poller (tap) that owns one hidden subscription per
    trigger topic (hidden from every listing), de-duplicated against the REST publishes;
  * Firestore document events (Eventarc document triggers) fire for writes that go through the
    simulator's REST surface (old/new document read around the write); writes made directly by a
    gRPC client do not fire simulator-side triggers (the emulator has no change stream).

What stays on the simulator's own core (the emulators do not implement it): Pub/Sub schemas, IAM
policies, message transforms and schema validation on publish; Firestore admin plane (databases,
indexes, backups, TTL policies, security rules) and every non-(default) database.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_log = logging.getLogger("vyomi.realbackends")
ENV = "VYOMI_GCP_REAL_BACKENDS"
_TAP_PREFIX = "vyomi-tap-"
_installed = False
_lock = threading.RLock()          # serialises REST publish (+ id bookkeeping) against the tap's pull
_rest_ids: dict[str, float] = {}   # messageId -> time; published through the simulator, so already delivered
_tap_topics: set[str] = set()      # full topic names whose hidden tap subscription exists


def _truthy(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _host(kind: str) -> str:
    v = "PUBSUB" if kind == "pubsub" else "FIRESTORE"
    return os.environ.get(f"{v}_EMULATOR_HOST") or os.environ.get(f"CLOUDLEARN_{v}_EMULATOR_HOST") or ""


def enabled(kind: str = "") -> bool:
    """True when the real-backend mode is on and (for `kind`) the emulator host is configured."""
    if sys.platform == "emscripten" or not _truthy(os.environ.get(ENV, "")):
        return False
    return bool(_host(kind)) if kind else bool(_host("pubsub") or _host("firestore"))


def status() -> dict:
    return {"enabled": enabled(), "pubsub": _host("pubsub") if enabled("pubsub") else "",
            "firestore": _host("firestore") if enabled("firestore") else "", "installed": _installed}


# ── HTTP to the emulators ────────────────────────────────────────────────────
def _http(kind: str, method: str, path: str, query: dict | None = None, body: bytes | None = None,
          timeout: float = 30.0) -> tuple[int, bytes, str]:
    host = _host(kind)
    url = f"http://{host}{path}"
    if query:
        url += "?" + urllib.parse.urlencode([(k, v) for k, v in query.items() if v is not None and v != ""])
    req = urllib.request.Request(url, data=body if body is not None else (b"" if method in ("POST", "PUT", "PATCH") else None),
                                 method=method, headers={"Content-Type": "application/json", "Authorization": "Bearer owner"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "application/json")
    except Exception as exc:  # noqa: BLE001 - connection refused / timeout: say so, never pretend
        msg = {"error": {"code": 503, "status": "UNAVAILABLE",
                         "message": f"the real {kind} emulator at {host} is not reachable ({type(exc).__name__}: {exc}); "
                                    f"{ENV}=1 needs it"}}
        return 503, json.dumps(msg).encode(), "application/json"


# ── Pub/Sub ──────────────────────────────────────────────────────────────────
_PS_RE = re.compile(r"^/(?:v1|v1beta2)/projects/([^/]+)/(topics|subscriptions|snapshots)(?:/([^/:]+))?(/subscriptions|/snapshots)?(?::([A-Za-z]+))?$")
_IAM_VERBS = {"getIamPolicy", "setIamPolicy", "testIamPermissions"}


def _tap_name(topic_full: str) -> str:
    return _TAP_PREFIX + hashlib.md5(topic_full.encode()).hexdigest()[:12]


def _hidden(full: str) -> bool:
    return full.rsplit("/", 1)[-1].startswith(_TAP_PREFIX)


def _strip_internal_push(payload: dict) -> dict:
    """Simulator-internal push endpoints (Eventarc `https://eventarc-*.vyomi.internal/`) are delivered by
    the simulator, not pushed by the emulator: make the emulator copy a pull subscription."""
    pc = payload.get("pushConfig") or {}
    ep = str(pc.get("pushEndpoint") or "")
    if ep and urllib.parse.urlparse(ep).hostname and urllib.parse.urlparse(ep).hostname.endswith(".vyomi.internal"):
        payload = {k: v for k, v in payload.items() if k != "pushConfig"}
    return payload


def _ps_response(orig_mod, status: int, body: bytes, ctype: str):
    return orig_mod.PubsubResponse(status=status, body=body, media_type=ctype or "application/json")


def _filter_hidden(body: bytes, key: str) -> bytes:
    try:
        d = json.loads(body or b"{}")
        if isinstance(d.get(key), list):
            d[key] = [x for x in d[key] if not _hidden(x if isinstance(x, str) else str(x.get("name", "")))]
            return json.dumps(d).encode()
    except Exception:  # noqa: BLE001
        pass
    return body


def _remember(ids: list[str]) -> None:
    now = time.time()
    for i in ids:
        _rest_ids[i] = now
    if len(_rest_ids) > 5000:
        for k in [k for k, t in _rest_ids.items() if now - t > 600]:
            _rest_ids.pop(k, None)


def _ps_wrapper(orig):
    from core import gcp_pubsub_core as mod

    def dispatch(store, method, path, query=None, headers=None, body=b"", on_publish=None):
        if not enabled("pubsub"):
            return orig(store, method, path, query, headers, body, on_publish=on_publish)
        clean = path.split("?", 1)[0]
        m = _PS_RE.match(clean)
        if not m:
            return orig(store, method, path, query, headers, body, on_publish=on_publish)
        project, coll, rid, sub_coll, verb = m.groups()
        _seen_projects.add(project)
        if verb in _IAM_VERBS:
            return orig(store, method, path, query, headers, body, on_publish=on_publish)
        method = method.upper()
        query = dict(query or {})
        try:
            payload = json.loads(body or b"{}") if body else {}
        except Exception:  # noqa: BLE001
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        send = body or b""
        if coll == "subscriptions" and method in ("PUT", "PATCH") and rid and not verb:
            sub = payload.get("subscription") if method == "PATCH" and isinstance(payload.get("subscription"), dict) else payload
            stripped = _strip_internal_push(sub)
            if stripped is not sub:
                send = json.dumps(stripped if method == "PUT" else dict(payload, subscription=stripped)).encode()
        if verb == "publish":
            topic_full = f"projects/{project}/topics/{rid}"
            ensure_tap(topic_full)
            with _lock:
                st, out, ct = _http("pubsub", method, clean, query, send)
                ids = []
                if st == 200:
                    try:
                        ids = list(json.loads(out).get("messageIds") or [])
                    except Exception:  # noqa: BLE001
                        ids = []
                    _remember(ids)
            if st == 200 and on_publish:
                prepared = []
                pt = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000000Z"
                for i, msg in enumerate(payload.get("messages") or []):
                    rec = {"data": msg.get("data", ""), "attributes": dict(msg.get("attributes") or {}),
                           "messageId": ids[i] if i < len(ids) else "", "publishTime": pt}
                    if msg.get("orderingKey"):
                        rec["orderingKey"] = msg["orderingKey"]
                    prepared.append(rec)
                try:
                    on_publish(topic_full, prepared)
                except Exception:  # noqa: BLE001 - a trigger failure never fails the publish (as in the core)
                    _log.debug("realbackends: on_publish hook failed", exc_info=True)
            return _ps_response(mod, st, out, ct)
        admin = bool(rid) and not verb and not sub_coll and method in ("PUT", "DELETE") and coll in ("topics", "subscriptions")
        full_name = f"projects/{project}/{coll}/{rid}"
        if admin:
            _audit_inflight.add(full_name)
        try:
            st, out, ct = _http("pubsub", method, clean, query, send)
            if admin and 200 <= st < 300:       # the simulator front audits this REST call itself: keep the reconciler off it
                (_known.setdefault(coll, set()).add if method == "PUT" else _known.setdefault(coll, set()).discard)(full_name)
        finally:
            if admin:
                _audit_inflight.discard(full_name)
        if st == 200 and method == "GET" and not rid:
            out = _filter_hidden(out, coll)
        if st == 200 and method == "GET" and sub_coll == "/subscriptions":
            out = _filter_hidden(out, "subscriptions")
        if 200 <= st < 300 and rid and not verb and not sub_coll and method in ("PUT", "PATCH", "DELETE") and coll in ("topics", "subscriptions"):
            _mirror(orig, store, method, path, query, headers, body)   # metadata-only shadow for simulator-side readers
        return _ps_response(mod, st, out, ct)

    dispatch._vyomi_real = True
    return dispatch


# ── Cloud Audit Logs for admin calls the emulator handles itself (gRPC clients) ─────────────────────────
# The core path audits every REST admin call at the simulator's front door (core/gcp_audit_core.py). A gRPC client (CreateTopic,
# CreateSubscription, DeleteTopic ...) talks to the emulator directly and never touches the simulator, and the emulator emits no
# audit entries: the poller below diffs the emulator's topic/subscription lists and writes the SAME Admin Activity entries.
_known: dict[str, set] = {}          # "topics"/"subscriptions" -> full names already accounted for (audited or REST-handled)
_audit_inflight: set[str] = set()
_audit_ready = False


_seen_projects: set[str] = set()


def _projects() -> list[str]:
    """Projects to watch: the default plus every project a Pub/Sub REST call named (no router lookup: install() runs inside its construction)."""
    return sorted({os.environ.get("GOOGLE_CLOUD_PROJECT") or "vyomi-project", "vyomi-project"} | _seen_projects)


def _emulator_names(project: str, coll: str) -> set | None:
    names, token = set(), ""
    while True:
        st, out, _ = _http("pubsub", "GET", f"/v1/projects/{project}/{coll}", {"pageToken": token} if token else None, timeout=5)
        if st != 200:
            return None
        try:
            d = json.loads(out)
        except Exception:  # noqa: BLE001
            return None
        names |= {x if isinstance(x, str) else x.get("name", "") for x in d.get(coll, [])}
        token = d.get("nextPageToken", "")
        if not token:
            return {n for n in names if n and not _hidden(n)}


def _audit_call(method: str, name: str) -> None:
    try:
        from core import wire_ingress as _wi
        r = _wi.new_services_router() or _wi.appliance_router()
        r.gcp_audit(method, "/v1/" + name, {}, {}, b"", 200)
    except Exception:  # noqa: BLE001
        _log.debug("realbackends: audit emit failed", exc_info=True)


def _audit_reconcile() -> int:
    """Emit CreateTopic/DeleteTopic/CreateSubscription/DeleteSubscription entries for emulator changes made by gRPC clients."""
    global _audit_ready
    n, complete = 0, True
    for project in _projects():
        for coll in ("topics", "subscriptions"):
            cur = _emulator_names(project, coll)
            if cur is None:
                complete = False
                continue
            with _lock:
                known = _known.setdefault(coll, set())
                mine = {k for k in known if k.startswith(f"projects/{project}/")}
                if not _audit_ready:
                    known |= cur      # baseline: what was there before we started watching is not "created" now
                    continue
                for name in sorted(cur - mine):
                    if name not in _audit_inflight:
                        known.add(name)
                        _audit_call("PUT", name)
                        n += 1
                for name in sorted(mine - cur):
                    if name not in _audit_inflight:
                        known.discard(name)
                        _audit_call("DELETE", name)
                        n += 1
    if complete:
        _audit_ready = True
    return n


def _mirror(orig, store, method, path, query, headers, body) -> None:
    try:
        if method == "PUT" and "/subscriptions/" in path:
            # shadow subscriptions need their topic's shadow
            try:
                t = (json.loads(body or b"{}") or {}).get("topic", "")
            except Exception:  # noqa: BLE001
                t = ""
            if t and store.get_topic(t) is None:
                orig(store, "PUT", "/v1/" + t, {}, {}, b"{}")
        orig(store, method, path, query, headers, body)
    except Exception:  # noqa: BLE001
        _log.debug("realbackends: shadow mirror skipped", exc_info=True)


def _import_topic(store, topic_full: str) -> dict | None:
    """A topic that exists in the emulator (created by a gRPC client) but not in the shadow: import its metadata."""
    st, out, _ = _http("pubsub", "GET", "/v1/" + topic_full, timeout=5)
    if st != 200:
        return None
    try:
        d = json.loads(out)
    except Exception:  # noqa: BLE001
        return None
    from core import gcp_pubsub_core as mod
    body = {k: d[k] for k in ("labels", "messageRetentionDuration", "kmsKeyName") if d.get(k)}
    mod_orig = getattr(mod.dispatch, "_orig", mod.dispatch)
    mod_orig(store, "PUT", "/v1/" + topic_full, {}, {}, json.dumps(body).encode())
    return store.topics.get(topic_full)


def _patch_store() -> None:
    from core import appliance_stores as aps
    cls = aps.AppStatePubsubStore
    if getattr(cls.get_topic, "_vyomi_real", False):
        return
    base = cls.get_topic

    guard = threading.local()

    def get_topic(self, arn):
        t = base(self, arn)
        if (t is None and enabled("pubsub") and isinstance(arn, str) and arn.startswith("projects/")
                and "/topics/" in arn and not getattr(guard, "busy", False)):
            guard.busy = True      # the import itself creates the shadow through the core (which reads get_topic)
            try:
                t = _import_topic(self, arn)
            finally:
                guard.busy = False
        return t
    get_topic._vyomi_real = True
    cls.get_topic = get_topic


# ── the tap: gRPC-published messages -> simulator triggers ──────────────────
def ensure_tap(topic_full: str) -> None:
    if topic_full in _tap_topics:
        return
    if not _trigger_topics().get(topic_full):
        return
    sub = f"projects/{topic_full.split('/')[1]}/subscriptions/{_tap_name(topic_full)}"
    st, _, _ = _http("pubsub", "PUT", "/v1/" + sub, None, json.dumps({"topic": topic_full, "ackDeadlineSeconds": 60}).encode(), timeout=10)
    if st in (200, 409):
        _tap_topics.add(topic_full)


def _trigger_topics() -> dict[str, bool]:
    """Topics that a simulator trigger listens on (Cloud Run + Eventarc-core Pub/Sub triggers)."""
    out: dict[str, bool] = {}
    try:
        from routes import gcp_run as _run_routes
        for trg in list(_run_routes.store().triggers.values()):
            t = ((trg.get("transport") or {}).get("pubsub") or {}).get("topic")
            if t:
                out[t] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        from core import wire_ingress as _wi
        r = _wi.new_services_router() or _wi.appliance_router()
        for trg in ((getattr(r.gcp_mon, "ext", None) or {}).get("eventarc_triggers") or {}).values():
            t = ((trg.get("transport") or {}).get("pubsub") or {}).get("topic")
            if t:
                out[t] = True
    except Exception:  # noqa: BLE001
        pass
    return out


def _tap_once() -> int:
    n = 0
    topics = _trigger_topics()
    for topic_full in topics:
        ensure_tap(topic_full)
    for topic_full in list(_tap_topics):
        project = topic_full.split("/")[1]
        sub = f"projects/{project}/subscriptions/{_tap_name(topic_full)}"
        with _lock:
            st, out, _ = _http("pubsub", "POST", f"/v1/{sub}:pull", None,
                               json.dumps({"maxMessages": 50, "returnImmediately": True}).encode(), timeout=10)
            if st == 404:
                _tap_topics.discard(topic_full)
                continue
            if st != 200:
                continue
            recv = (json.loads(out or b"{}") or {}).get("receivedMessages") or []
            if not recv:
                continue
            _http("pubsub", "POST", f"/v1/{sub}:acknowledge", None,
                  json.dumps({"ackIds": [r["ackId"] for r in recv]}).encode(), timeout=10)
            fresh = [r["message"] for r in recv if r["message"].get("messageId") not in _rest_ids]
        if fresh and topics.get(topic_full):
            try:
                from routes import gcp_pubsub_unified as _pu
                with _pu._gcp():
                    _pu._deliver_eventarc(topic_full, [{"data": m.get("data", ""), "attributes": m.get("attributes") or {},
                                                        "messageId": m.get("messageId", ""), "publishTime": m.get("publishTime", "")}
                                                       for m in fresh])
                n += len(fresh)
            except Exception:  # noqa: BLE001
                _log.debug("realbackends: tap delivery failed", exc_info=True)
    return n


def _tap_loop() -> None:
    try:
        _audit_reconcile()      # baseline first (a miss is retried below)
    except Exception:  # noqa: BLE001
        pass
    while True:
        time.sleep(0.5)
        try:
            _tap_once()
        except Exception:  # noqa: BLE001
            _log.debug("realbackends: tap loop", exc_info=True)
        try:
            _audit_reconcile()
        except Exception:  # noqa: BLE001
            _log.debug("realbackends: audit reconcile", exc_info=True)


# ── Firestore ────────────────────────────────────────────────────────────────
def _fs_response(mod, status: int, body: bytes, ctype: str):
    return mod.FirestoreResponse(status=status, body=body, media_type=ctype or "application/json")


def _doc_entry(d: dict | None) -> dict | None:
    if not d or "fields" not in d and "name" not in d:
        return None
    return {"fields": d.get("fields", {}), "createTime": d.get("createTime"), "updateTime": d.get("updateTime")}


def _batch_get(project: str, db: str, names: list[str]) -> dict[str, dict | None]:
    if not names:
        return {}
    st, out, _ = _http("firestore", "POST", f"/v1/projects/{project}/databases/{db}/documents:batchGet", None,
                       json.dumps({"documents": names}).encode(), timeout=10)
    res: dict[str, dict | None] = {n: None for n in names}
    if st == 200:
        try:
            for item in json.loads(out):
                if item.get("found"):
                    res[item["found"]["name"]] = _doc_entry(item["found"])
        except Exception:  # noqa: BLE001
            pass
    return res


def _affected(method: str, rel: str, suffix: str, payload: dict, base: str, query: dict) -> list[str]:
    if suffix == "commit":
        out = []
        for w in payload.get("writes") or []:
            n = (w.get("update") or {}).get("name") or w.get("delete") or (w.get("transform") or {}).get("document")
            if n:
                out.append(n)
        return out
    if method == "PATCH" and rel:
        return [f"{base}/{rel}"]
    if method == "DELETE" and rel:
        return [f"{base}/{rel}"]
    if method == "POST" and rel and not suffix:        # createDocument: id from ?documentId=
        did = query.get("documentId")
        return [f"{base}/{rel}/{did}"] if did else []
    return []


def _fs_wrapper(orig):
    from core import gcp_firestore_core as mod

    def dispatch(store, method, path, query=None, headers=None, body=b"", gcs_store=None):
        if not enabled("firestore"):
            return orig(store, method, path, query, headers, body, gcs_store=gcs_store)
        parsed = mod._parse_documents_path(path)
        if parsed is None or parsed[1] != "(default)":
            return orig(store, method, path, query, headers, body, gcs_store=gcs_store)
        project, database, base, rel, suffix = parsed
        method = method.upper()
        query = dict(query or {})
        try:
            mod._ensure_db(store, project, database)    # keep the shadow admin record so the console lists (default)
        except Exception:  # noqa: BLE001
            pass
        hook = getattr(store, "on_doc_event", None)
        names, before = [], {}
        write = method != "GET" and suffix in ("", "commit")
        if hook and write:
            try:
                payload = json.loads(body or b"{}") if body else {}
                names = _affected(method, rel, suffix, payload if isinstance(payload, dict) else {}, base, query)
                before = _batch_get(project, database, names)
            except Exception:  # noqa: BLE001
                names = []
        # the emulator wants a literal `(default)`; SDKs percent-encode it
        clean = urllib.parse.quote(urllib.parse.unquote(path.split("?", 1)[0]), safe="/:()$=,@-_.~!*'")
        st, out, ct = _http("firestore", method, clean, query, body or b"")
        if st == 200 and names and hook:
            try:
                after = _batch_get(project, database, names)
                for n in names:
                    o, nw = before.get(n), after.get(n)
                    if o != nw and (o is not None or nw is not None):
                        hook(database, n.split("/documents/", 1)[1], o, nw)
            except Exception:  # noqa: BLE001
                _log.debug("realbackends: firestore event hook failed", exc_info=True)
        return _fs_response(mod, st, out, ct)

    dispatch._vyomi_real = True
    return dispatch


# ── install ──────────────────────────────────────────────────────────────────
def install() -> bool:
    """Idempotent. Returns True when the real-backend wrappers are active."""
    global _installed
    if not enabled():
        return False
    with _lock:
        if _installed:
            return True
        from core import gcp_firestore_core as fs, gcp_pubsub_core as ps
        if enabled("pubsub"):
            o = ps.dispatch
            w = _ps_wrapper(o)
            w._orig = o
            ps.dispatch = w
            _patch_store()
            threading.Thread(target=_tap_loop, name="vyomi-gcp-pubsub-tap", daemon=True).start()
        if enabled("firestore"):
            o = fs.dispatch
            w = _fs_wrapper(o)
            w._orig = o
            fs.dispatch = w
        _installed = True
        _log.info("GCP real backends ON: pubsub=%s firestore=%s", _host("pubsub"), _host("firestore"))
    return True
