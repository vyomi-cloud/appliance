"""GCP Cloud Tasks core — substrate-independent engine for the native
**Cloud Tasks API v2** REST surface (`/v2/projects/{p}/locations/{l}/queues...`), so
the official `google-cloud-tasks` clients (Go / Java / Python) and `gcloud tasks`
work unchanged against it with only the endpoint overridden.

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, and
the same file runs offline and in Nano.

State lives in public dict attrs on `CloudTasksStore` so core/nano_persist captures
and restores it like every other store. Delivery is pluggable: a task is dispatched
(`:run`) through `store`-independent `set_deliverer(fn)`; with no deliverer the
engine simulates a successful 2xx so the task is handed off and removed exactly like
the real service after a successful attempt.

Wire recap (v2):
  - locations     : GET  /v2/projects/{p}/locations[/{l}]
  - create queue  : POST /v2/projects/{p}/locations/{l}/queues         body Queue
  - get/delete    : GET|DELETE /v2/{name=projects/*/locations/*/queues/*}
  - list queues   : GET  .../queues?filter=&pageSize=&pageToken=
  - patch queue   : PATCH /v2/{queue.name}?updateMask=  (creates when missing)
  - pause/resume/purge : POST .../queues/{q}:pause|:resume|:purge
  - IAM           : POST .../queues/{q}:getIamPolicy|:setIamPolicy|:testIamPermissions
  - create task   : POST .../queues/{q}/tasks  body {task, responseView}
  - get/list/del  : GET|DELETE .../tasks/{t}, GET .../tasks?responseView=
  - run task      : POST .../tasks/{t}:run  body {responseView}

All errors use the native GCP {"error":{"code","message","status"}} body.
"""
from __future__ import annotations

import base64
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

DEFAULT_PROJECT = "cloudlearn"

# A representative subset of the regions Cloud Tasks is offered in.
LOCATIONS = [
    ("us-central1", "Iowa"), ("us-east1", "South Carolina"), ("us-east4", "Northern Virginia"),
    ("us-west1", "Oregon"), ("europe-west1", "Belgium"), ("europe-west2", "London"),
    ("europe-west3", "Frankfurt"), ("asia-east1", "Taiwan"), ("asia-northeast1", "Tokyo"),
    ("asia-south1", "Mumbai"), ("asia-southeast1", "Singapore"), ("australia-southeast1", "Sydney"),
]

HTTP_METHODS = ("POST", "GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS")
_QUEUE_ID = re.compile(r"^[A-Za-z0-9-]{1,100}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,500}$")
_LOC_ID = re.compile(r"^[a-z0-9-]{1,63}$")
MAX_BODY_BYTES = 1024 * 1024
MAX_TASKS_PER_QUEUE = 1_000_000

DEFAULT_RATE_LIMITS = {"maxDispatchesPerSecond": 500.0, "maxBurstSize": 100, "maxConcurrentDispatches": 1000}
DEFAULT_RETRY_CONFIG = {"maxAttempts": 100, "maxRetryDuration": "0s", "minBackoff": "0.100s",
                        "maxBackoff": "3600s", "maxDoublings": 16}
IAM_PERMISSIONS = [
    "cloudtasks.queues.create", "cloudtasks.queues.delete", "cloudtasks.queues.get", "cloudtasks.queues.list",
    "cloudtasks.queues.pause", "cloudtasks.queues.purge", "cloudtasks.queues.resume", "cloudtasks.queues.update",
    "cloudtasks.queues.getIamPolicy", "cloudtasks.queues.setIamPolicy",
    "cloudtasks.tasks.create", "cloudtasks.tasks.delete", "cloudtasks.tasks.fullView", "cloudtasks.tasks.get",
    "cloudtasks.tasks.list", "cloudtasks.tasks.run",
]


@dataclass
class GcpResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class CloudTasksStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.queues: dict = {}      # full queue name -> queue record
        self.tasks: dict = {}       # full task name  -> task record
        self.policies: dict = {}    # full queue name -> IAM policy
        self.events: dict = {}      # full queue name -> [{time, action, detail}]


_SHARED: CloudTasksStore | None = None
_DELIVER = None


def shared_store() -> CloudTasksStore:
    """The appliance-wide store: native wire and console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = CloudTasksStore()
    return _SHARED


def set_deliverer(fn) -> None:
    """fn(task_dict) -> (http_status:int, detail:str). None → simulated 200."""
    global _DELIVER
    _DELIVER = fn


# ── primitives ────────────────────────────────────────────────────────────
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now() -> str:
    return _ts(_utcnow())


def _json(status: int, obj: dict) -> GcpResponse:
    return GcpResponse(status=status, body=json.dumps(obj).encode())


_STATUS_TOKEN = {400: "INVALID_ARGUMENT", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 409: "ALREADY_EXISTS",
                 412: "FAILED_PRECONDITION", 500: "INTERNAL"}


class _E(Exception):
    def __init__(self, status, message, token=None):
        super().__init__(message)
        self.status, self.message = status, message
        self.token = token or _STATUS_TOKEN.get(status, "UNKNOWN")


def _err_resp(e: _E) -> GcpResponse:
    return _json(e.status, {"error": {"code": e.status, "message": e.message, "status": e.token}})


def _parse_duration(s, field_name):
    if not isinstance(s, str) or not re.fullmatch(r"-?\d+(\.\d{1,9})?s", s):
        raise _E(400, f"Invalid value at '{field_name}': duration must be a decimal number of seconds ending in 's'.")
    return float(s[:-1])


def _fmt_duration(sec: float) -> str:
    if sec == int(sec):
        return f"{int(sec)}s"
    frac = f"{sec:.9f}".split(".")[1].rstrip("0")
    frac = frac.ljust(3 if len(frac) <= 3 else 6 if len(frac) <= 6 else 9, "0")   # protobuf Duration: 0/3/6/9 digits
    return f"{int(sec)}.{frac}s"


def _qname(project, loc, queue) -> str:
    return f"projects/{project}/locations/{loc}/queues/{queue}"


def _parse_ts(s, field_name):
    try:
        t = s.replace("Z", "+00:00")
        m = re.match(r"^(.*?)(\.\d+)?([+-]\d\d:\d\d)$", t)
        if m and m.group(2):
            t = m.group(1) + m.group(2)[:7] + m.group(3)
        d = datetime.fromisoformat(t)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        raise _E(400, f"Invalid value at '{field_name}': invalid timestamp {s!r}.")


# ── validation / normalisation ────────────────────────────────────────────
def _normalise_rate(rl: dict) -> dict:
    out = dict(DEFAULT_RATE_LIMITS)
    for k, v in (rl or {}).items():
        if k not in DEFAULT_RATE_LIMITS:
            if k == "maxTasksDispatchedPerSecond":
                continue
            raise _E(400, f'Invalid JSON payload received. Unknown name "{k}" at \'queue.rate_limits\': Cannot find field.')
        out[k] = v
    out["maxDispatchesPerSecond"] = float(out["maxDispatchesPerSecond"])
    for k in ("maxBurstSize", "maxConcurrentDispatches"):
        out[k] = int(out[k])
    if not (0 <= out["maxDispatchesPerSecond"] <= 500):
        raise _E(400, "Rate limit max_dispatches_per_second must be between 0 and 500.")
    if out["maxConcurrentDispatches"] < 0 or out["maxConcurrentDispatches"] > 5000:
        raise _E(400, "Rate limit max_concurrent_dispatches must be between 0 and 5000.")
    return out


def _normalise_retry(rc: dict) -> dict:
    out = dict(DEFAULT_RETRY_CONFIG)
    for k, v in (rc or {}).items():
        if k not in DEFAULT_RETRY_CONFIG:
            raise _E(400, f'Invalid JSON payload received. Unknown name "{k}" at \'queue.retry_config\': Cannot find field.')
        out[k] = v
    out["maxAttempts"] = int(out["maxAttempts"])
    out["maxDoublings"] = int(out["maxDoublings"])
    mn = _parse_duration(out["minBackoff"], "queue.retry_config.min_backoff")
    mx = _parse_duration(out["maxBackoff"], "queue.retry_config.max_backoff")
    _parse_duration(out["maxRetryDuration"], "queue.retry_config.max_retry_duration")
    if out["maxAttempts"] < -1:
        raise _E(400, "Retry config max_attempts must be >= -1.")
    if mn > mx:
        raise _E(400, "Retry config min_backoff must be less than or equal to max_backoff.")
    for k in ("minBackoff", "maxBackoff", "maxRetryDuration"):
        out[k] = _fmt_duration(_parse_duration(out[k], k))
    return out


def _log(store, qname, action, detail=""):
    ev = store.events.setdefault(qname, [])
    ev.insert(0, {"time": _now(), "action": action, "detail": detail or "-"})
    del ev[200:]


def _queue_view(q: dict) -> dict:
    out = {"name": q["name"], "rateLimits": dict(q["rateLimits"]), "retryConfig": dict(q["retryConfig"]),
           "state": q["state"]}
    if q.get("appEngineRoutingOverride"):
        out["appEngineRoutingOverride"] = dict(q["appEngineRoutingOverride"])
    if q.get("purgeTime"):
        out["purgeTime"] = q["purgeTime"]
    if q.get("stackdriverLoggingConfig"):
        out["stackdriverLoggingConfig"] = dict(q["stackdriverLoggingConfig"])
    if q.get("httpTarget"):
        out["httpTarget"] = dict(q["httpTarget"])
    return out


def _task_view(t: dict, full: bool) -> dict:
    out = {k: v for k, v in t.items() if k not in ("httpRequest", "appEngineHttpRequest", "_attempts")}
    for key in ("httpRequest", "appEngineHttpRequest"):
        if t.get(key):
            r = {k: v for k, v in t[key].items()}
            if not full:
                r.pop("body", None)
            out[key] = r
    out["view"] = "FULL" if full else "BASIC"
    return out


# Generated REST clients (Go/Java) send proto enums as numbers; accept numbers and names.
_ENUMS = {"httpMethod": ["HTTP_METHOD_UNSPECIFIED", "POST", "GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"],
          "state": ["STATE_UNSPECIFIED", "RUNNING", "PAUSED", "DISABLED"],
          "view": ["VIEW_UNSPECIFIED", "BASIC", "FULL"]}


def _enum(kind, v):
    if isinstance(v, bool):
        return v
    names = _ENUMS[kind]
    if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
        i = int(v)
        if 0 <= i < len(names):
            return names[i]
    return v


def _is_full(view) -> bool:
    view = _enum("view", view)
    if view in (None, "", "BASIC", "VIEW_UNSPECIFIED"):
        return False
    if view == "FULL":
        return True
    raise _E(400, f"Invalid value at 'response_view': unknown enum value {view!r}.")


# ── name helpers ──────────────────────────────────────────────────────────
def _check_loc(project, loc):
    if not project:
        raise _E(400, "Project is required.")
    if not _LOC_ID.match(loc or ""):
        raise _E(400, f"Location {loc!r} is not a valid location id.")


def _get_queue(store, name) -> dict:
    q = store.queues.get(name)
    if q is None:
        raise _E(404, "Queue does not exist. If you just created the queue, wait at least a minute for the queue to initialize.")
    return q


# ── queue operations ──────────────────────────────────────────────────────
def create_queue(store, parent: str, body: dict) -> dict:
    m = re.fullmatch(r"projects/([^/]+)/locations/([^/]+)", parent)
    if not m:
        raise _E(400, f"Invalid parent {parent!r}; expected projects/*/locations/*.")
    project, loc = m.groups()
    _check_loc(project, loc)
    name = body.get("name") or ""
    qm = re.fullmatch(r"projects/([^/]+)/locations/([^/]+)/queues/([^/]+)", name)
    if not qm:
        raise _E(400, "Queue name must be formatted: \"projects/<PROJECT_ID>/locations/<LOCATION_ID>/queues/<QUEUE_ID>\"")
    if (qm.group(1), qm.group(2)) != (project, loc):
        raise _E(400, "Queue name does not match the parent location.")
    if not _QUEUE_ID.match(qm.group(3)):
        raise _E(400, "Queue ID can contain only letters ([A-Za-z]), numbers ([0-9]), or hyphens (-). The maximum length is 100 characters.")
    if name in store.queues:
        raise _E(409, "Queue already exists")
    q = _build_queue(name, body)
    store.queues[name] = q
    _log(store, name, "CreateQueue", "queue created")
    return _queue_view(q)


def _build_queue(name, body, base=None) -> dict:
    q = base or {"name": name, "state": "RUNNING", "createTime": _now()}
    allowed = {"name", "rateLimits", "retryConfig", "state", "purgeTime", "appEngineRoutingOverride",
               "stackdriverLoggingConfig", "httpTarget"}
    for k in body:
        if k not in allowed:
            raise _E(400, f'Invalid JSON payload received. Unknown name "{k}" at \'queue\': Cannot find field.')
    q["rateLimits"] = _normalise_rate({**(q.get("rateLimits") or {}), **(body.get("rateLimits") or {})})
    q["retryConfig"] = _normalise_retry({**(q.get("retryConfig") or {}), **(body.get("retryConfig") or {})})
    if "state" in body:
        body = {**body, "state": _enum("state", body["state"])}
    if "state" in body and base is None:
        if body["state"] not in ("RUNNING", "PAUSED", "DISABLED", "STATE_UNSPECIFIED"):
            raise _E(400, f"Invalid value at 'queue.state': unknown enum value {body['state']!r}.")
        if body["state"] not in ("STATE_UNSPECIFIED", None):
            q["state"] = body["state"]
    for k in ("appEngineRoutingOverride", "stackdriverLoggingConfig", "httpTarget"):
        if body.get(k) is not None:
            q[k] = body[k]
    slc = q.get("stackdriverLoggingConfig")
    if slc is not None:
        ratio = float(slc.get("samplingRatio", 0))
        if not 0 <= ratio <= 1:
            raise _E(400, "Logging config sampling_ratio must be between 0 and 1.")
        q["stackdriverLoggingConfig"] = {"samplingRatio": ratio}
    return q


def patch_queue(store, name: str, body: dict, update_mask: str = "") -> dict:
    body = dict(body or {})
    body_name = body.get("name") or name
    if body_name != name:
        raise _E(400, "Queue name in the body does not match the request path.")
    q = store.queues.get(name)
    if q is None:   # UpdateQueue creates the queue when it does not exist
        m = re.fullmatch(r"(projects/[^/]+/locations/[^/]+)/queues/[^/]+", name)
        if not m:
            raise _E(400, "Queue name must be formatted: \"projects/<PROJECT_ID>/locations/<LOCATION_ID>/queues/<QUEUE_ID>\"")
        body["name"] = name
        return create_queue(store, m.group(1), body)
    fields = [f.strip() for f in update_mask.split(",") if f.strip()] if update_mask else None
    body.pop("name", None)
    if fields is not None:
        keep = {}
        for f in fields:
            top = f.split(".", 1)[0]
            top = {"rate_limits": "rateLimits", "retry_config": "retryConfig",
                   "stackdriver_logging_config": "stackdriverLoggingConfig",
                   "app_engine_routing_override": "appEngineRoutingOverride",
                   "http_target": "httpTarget"}.get(top, top)
            if top in body:
                if "." in f:
                    sub = f.split(".", 1)[1]
                    sub = re.sub(r"_([a-z])", lambda mm: mm.group(1).upper(), sub)
                    keep.setdefault(top, {})[sub] = (body[top] or {}).get(sub)
                else:
                    keep[top] = body[top]
        body = {k: v for k, v in keep.items()}
        for k in list(body):
            if isinstance(body[k], dict) and k in ("rateLimits", "retryConfig"):
                body[k] = {a: b for a, b in body[k].items() if b is not None}
    body.pop("state", None)   # state is only changed through pause/resume
    _build_queue(name, body, base=q)
    _log(store, name, "UpdateQueue", "queue configuration updated")
    return _queue_view(q)


def list_queues(store, parent: str, query: dict) -> dict:
    m = re.fullmatch(r"projects/([^/]+)/locations/([^/]+)", parent)
    if not m:
        raise _E(400, f"Invalid parent {parent!r}; expected projects/*/locations/*.")
    rows = sorted((q for n, q in store.queues.items() if n.startswith(parent + "/queues/")), key=lambda q: q["name"])
    flt = query.get("filter") or ""
    if flt:
        mm = re.fullmatch(r"\s*(\w+)\s*[=:]\s*\"?([^\"]*)\"?\s*", flt)
        if mm and mm.group(1) == "state":
            rows = [q for q in rows if q["state"] == mm.group(2)]
        elif mm and mm.group(1) == "name":
            rows = [q for q in rows if q["name"].endswith("/" + mm.group(2))]
    return _page(rows, query, "queues", _queue_view)


def _page(rows, query, key, view):
    size = int(query.get("pageSize") or 0) or 0
    if size < 0:
        raise _E(400, "Page size must be non-negative.")
    start = 0
    tok = query.get("pageToken") or ""
    if tok:
        try:
            start = int(base64.urlsafe_b64decode(tok.encode()).decode())
        except Exception:
            raise _E(400, "Invalid page token.")
    chunk = rows[start:start + size] if size else rows[start:]
    out = {key: [view(r) for r in chunk]}
    if size and start + size < len(rows):
        out["nextPageToken"] = base64.urlsafe_b64encode(str(start + size).encode()).decode()
    return out


def delete_queue(store, name: str) -> dict:
    _get_queue(store, name)
    for tn in [t for t in store.tasks if t.startswith(name + "/tasks/")]:
        del store.tasks[tn]
    del store.queues[name]
    store.policies.pop(name, None)
    store.events.pop(name, None)
    return {}


def set_state(store, name: str, state: str) -> dict:
    q = _get_queue(store, name)
    q["state"] = state
    _log(store, name, {"RUNNING": "ResumeQueue", "PAUSED": "PauseQueue"}.get(state, "UpdateQueue"), f"state → {state}")
    return _queue_view(q)


def purge_queue(store, name: str) -> dict:
    q = _get_queue(store, name)
    n = 0
    for tn in [t for t in store.tasks if t.startswith(name + "/tasks/")]:
        del store.tasks[tn]
        n += 1
    q["purgeTime"] = _now()
    _log(store, name, "PurgeQueue", f"{n} task(s) purged")
    return _queue_view(q)


# ── IAM ───────────────────────────────────────────────────────────────────
def get_iam_policy(store, name: str) -> dict:
    _get_queue(store, name)
    return store.policies.get(name) or {"version": 1, "etag": "ACAB"}


def set_iam_policy(store, name: str, body: dict) -> dict:
    _get_queue(store, name)
    pol = body.get("policy")
    if not isinstance(pol, dict):
        raise _E(400, "Policy is required.")
    etag = base64.b64encode(str(random.getrandbits(32)).encode()).decode()
    store.policies[name] = {"version": pol.get("version", 1), "etag": etag,
                            **({"bindings": pol["bindings"]} if pol.get("bindings") else {})}
    _log(store, name, "SetIamPolicy", f"{len(pol.get('bindings') or [])} binding(s)")
    return store.policies[name]


def test_iam_permissions(store, name: str, body: dict) -> dict:
    _get_queue(store, name)
    return {"permissions": [p for p in (body.get("permissions") or []) if p in IAM_PERMISSIONS]}


# ── task operations ───────────────────────────────────────────────────────
def _validate_target(body: dict) -> None:
    http, ae = body.get("httpRequest"), body.get("appEngineHttpRequest")
    if http and ae:
        raise _E(400, "Task must have exactly one of http_request or app_engine_http_request.")
    if not http and not ae:
        raise _E(400, "Task must have a target: http_request or app_engine_http_request.")
    if http:
        url = http.get("url") or ""
        if not re.match(r"^https?://[^/\s]+", url):
            raise _E(400, "Invalid url: the url must be absolute and use the http or https scheme.")
        method = _enum("httpMethod", http.get("httpMethod")) or "POST"
        if method not in HTTP_METHODS and method != "HTTP_METHOD_UNSPECIFIED":
            raise _E(400, f"Invalid value at 'task.http_request.http_method': unknown enum value {method!r}.")
        if http.get("oauthToken") and http.get("oidcToken"):
            raise _E(400, "Task can have only one of oauth_token or oidc_token.")
        for tok in ("oauthToken", "oidcToken"):
            if http.get(tok) and not http[tok].get("serviceAccountEmail"):
                raise _E(400, f"{tok}.service_account_email is required.")
        if http.get("body"):
            try:
                raw = base64.b64decode(http["body"], validate=True)
            except Exception:
                raise _E(400, "Invalid value at 'task.http_request.body': base64 decoding error.")
            if len(raw) > MAX_BODY_BYTES:
                raise _E(400, "Task size too large: tasks must be 1MB or smaller.")
            if method == "GET" or method == "HEAD":
                raise _E(400, f"HTTP method {method} must not have a body.")


def create_task(store, parent: str, body: dict) -> dict:
    q = _get_queue(store, parent)
    task = dict(body.get("task") or {})
    full = _is_full(body.get("responseView"))
    allowed = {"name", "httpRequest", "appEngineHttpRequest", "scheduleTime", "dispatchDeadline"}
    for k in task:
        if k not in allowed:
            raise _E(400, f'Invalid JSON payload received. Unknown name "{k}" at \'task\': Cannot find field.')
    _validate_target(task)
    name = task.get("name") or ""
    if name:
        tm = re.fullmatch(re.escape(parent) + r"/tasks/([^/]+)", name)
        if not tm:
            raise _E(400, "Task name must be formatted: \"projects/<PROJECT_ID>/locations/<LOCATION_ID>/queues/<QUEUE_ID>/tasks/<TASK_ID>\"")
        if not _TASK_ID.match(tm.group(1)):
            raise _E(400, "Task ID can contain only letters, numbers, hyphens and underscores; max length is 500 characters.")
        if name in store.tasks:
            raise _E(409, "Requested entity already exists")
    else:
        name = f"{parent}/tasks/{random.getrandbits(63)}"
    if sum(1 for t in store.tasks if t.startswith(parent + "/tasks/")) >= MAX_TASKS_PER_QUEUE:
        raise _E(400, "Queue has too many tasks.", "RESOURCE_EXHAUSTED")
    now = _utcnow()
    if task.get("scheduleTime"):
        sched = _parse_ts(task["scheduleTime"], "task.schedule_time")
        if sched > now + timedelta(days=30):
            raise _E(400, "The schedule time cannot be more than 30 days in the future.")
    else:
        sched = now
    dd = task.get("dispatchDeadline")
    if dd is not None:
        d = _parse_duration(dd, "task.dispatch_deadline")
        if not 15 <= d <= 1800:
            raise _E(400, "The dispatch deadline must be between 15 seconds and 30 minutes.")
    rec = {"name": name, "scheduleTime": _ts(sched), "createTime": _ts(now),
           "dispatchDeadline": _fmt_duration(_parse_duration(dd, "dispatchDeadline")) if dd else "600s",
           "dispatchCount": 0, "responseCount": 0}
    if task.get("httpRequest"):
        h = dict(task["httpRequest"])
        h["httpMethod"] = _enum("httpMethod", h.get("httpMethod"))
        if h["httpMethod"] in (None, "HTTP_METHOD_UNSPECIFIED"):
            h["httpMethod"] = "POST"
        for tok in ("oauthToken", "oidcToken"):
            if h.get(tok) is None:
                h.pop(tok, None)
        hdrs = dict(h.get("headers") or {})
        if h.get("body") and not any(k.lower() == "content-type" for k in hdrs):
            hdrs["Content-Type"] = "application/octet-stream"
        hdrs.setdefault("User-Agent", "Google-Cloud-Tasks")
        h["headers"] = hdrs
        rec["httpRequest"] = h
    else:
        a = dict(task["appEngineHttpRequest"])
        a["httpMethod"] = _enum("httpMethod", a.get("httpMethod")) or "POST"
        if a["httpMethod"] == "HTTP_METHOD_UNSPECIFIED":
            a["httpMethod"] = "POST"
        a.setdefault("relativeUri", "/")
        rec["appEngineHttpRequest"] = a
    store.tasks[name] = rec
    _log(store, parent, "CreateTask", name.rsplit("/", 1)[-1])
    return _task_view(rec, full)


def _get_task(store, name) -> dict:
    t = store.tasks.get(name)
    if t is None:
        raise _E(404, "Task does not exist.")
    return t


def get_task(store, name: str, query: dict) -> dict:
    return _task_view(_get_task(store, name), _is_full(query.get("responseView")))


def list_tasks(store, parent: str, query: dict) -> dict:
    _get_queue(store, parent)
    full = _is_full(query.get("responseView"))
    rows = sorted((t for n, t in store.tasks.items() if n.startswith(parent + "/tasks/")),
                  key=lambda t: (t["scheduleTime"], t["name"]))
    return _page(rows, query, "tasks", lambda t: _task_view(t, full))


def delete_task(store, name: str) -> dict:
    _get_task(store, name)
    del store.tasks[name]
    qn = name.split("/tasks/")[0]
    _log(store, qn, "DeleteTask", name.rsplit("/", 1)[-1])
    return {}


def run_task(store, name: str, body: dict) -> dict:
    """Force an immediate dispatch attempt (RunTask). A 2xx response completes the
    task (it is removed, like the real service); anything else keeps it queued with
    the attempt recorded."""
    t = _get_task(store, name)
    full = _is_full(body.get("responseView"))
    qn = name.split("/tasks/")[0]
    now = _now()
    status, detail = 200, "OK"
    if _DELIVER is not None:
        try:
            status, detail = _DELIVER(t)
        except Exception as e:   # delivery errors count as a failed attempt
            status, detail = 500, str(e)
    ok = 200 <= int(status) < 300
    attempt = {"scheduleTime": t["scheduleTime"], "dispatchTime": now, "responseTime": now,
               "responseStatus": {"code": 0 if ok else (5 if int(status) == 404 else 13),
                                  "message": "" if ok else str(detail)}}
    t["dispatchCount"] += 1
    t["responseCount"] += 1
    t.setdefault("firstAttempt", attempt)
    t["lastAttempt"] = attempt
    view = _task_view(t, full)
    if ok:
        del store.tasks[name]
        _log(store, qn, "RunTask", f"{name.rsplit('/', 1)[-1]} → HTTP {status} (completed)")
    else:
        _log(store, qn, "RunTask", f"{name.rsplit('/', 1)[-1]} → HTTP {status} (will retry)")
    return view


# ── locations ─────────────────────────────────────────────────────────────
def _loc_view(project, loc_id, display):
    return {"name": f"projects/{project}/locations/{loc_id}", "locationId": loc_id, "displayName": display,
            "labels": {"cloud.googleapis.com/region": loc_id}}


def list_locations(project: str, query: dict) -> dict:
    rows = [_loc_view(project, i, d) for i, d in LOCATIONS]
    return _page(rows, query, "locations", lambda r: r)


def get_location(project: str, loc: str) -> dict:
    for i, d in LOCATIONS:
        if i == loc:
            return _loc_view(project, i, d)
    raise _E(404, f"Location {loc!r} is not found.")


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store, method: str, path: str, query: dict | None = None,
             headers: dict | None = None, body: bytes = b"") -> GcpResponse:
    query = dict(query or {})
    method = method.upper()
    if method == "POST":   # java.net clients cannot send PATCH: they POST with X-HTTP-Method-Override
        for hk, hv in (headers or {}).items():
            if str(hk).lower() == "x-http-method-override" and str(hv).upper() in ("PATCH", "PUT", "DELETE"):
                method = str(hv).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err_resp(_E(400, "Invalid JSON payload received. Unexpected token."))
    if not isinstance(payload, dict):
        payload = {}
    p = path.split("?", 1)[0]
    for pre in ("/v2beta3", "/v2beta2", "/v2"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    try:
        out = _route(store, method, segs, verb, query, payload)
    except _E as e:
        return _err_resp(e)
    return _json(200, out)


def _route(store, method, segs, verb, query, payload):
    if len(segs) < 2 or segs[0] != "projects":
        raise _E(404, "Unknown path.")
    project = segs[1]
    if len(segs) == 3 and segs[2] == "locations" and method == "GET" and not verb:
        return list_locations(project, query)
    if len(segs) < 4 or segs[2] != "locations":
        raise _E(404, "Unknown path.")
    loc = segs[3]
    if len(segs) == 4 and method == "GET" and not verb:
        return get_location(project, loc)
    if len(segs) < 5 or segs[4] != "queues":
        raise _E(404, "Unknown path.")
    parent = f"projects/{project}/locations/{loc}"
    if len(segs) == 5:
        if method == "POST" and not verb:
            return create_queue(store, parent, payload)
        if method == "GET" and not verb:
            return list_queues(store, parent, query)
        raise _E(404, "Unknown path.")
    qname = f"{parent}/queues/{segs[5]}"
    if len(segs) == 6:
        if verb == "pause" and method == "POST":
            return set_state(store, qname, "PAUSED")
        if verb == "resume" and method == "POST":
            return set_state(store, qname, "RUNNING")
        if verb == "purge" and method == "POST":
            return purge_queue(store, qname)
        if verb == "getIamPolicy" and method == "POST":
            return get_iam_policy(store, qname)
        if verb == "setIamPolicy" and method == "POST":
            return set_iam_policy(store, qname, payload)
        if verb == "testIamPermissions" and method == "POST":
            return test_iam_permissions(store, qname, payload)
        if verb:
            raise _E(404, "Unknown method.")
        if method == "GET":
            return _queue_view(_get_queue(store, qname))
        if method == "DELETE":
            return delete_queue(store, qname)
        if method == "PATCH":
            return patch_queue(store, qname, payload, query.get("updateMask", ""))
        raise _E(404, "Unknown path.")
    if segs[6] != "tasks":
        raise _E(404, "Unknown path.")
    if len(segs) == 7:
        if method == "POST" and not verb:
            return create_task(store, qname, payload)
        if method == "GET" and not verb:
            return list_tasks(store, qname, query)
        raise _E(404, "Unknown path.")
    tname = f"{qname}/tasks/{segs[7]}"
    if len(segs) == 8:
        if verb == "run" and method == "POST":
            return run_task(store, tname, payload)
        if verb:
            raise _E(404, "Unknown method.")
        if method == "GET":
            return get_task(store, tname, query)
        if method == "DELETE":
            return delete_task(store, tname)
    raise _E(404, "Unknown path.")


# ═══════════════════════════ console views ═══════════════════════════════
def queue_console_view(store, q: dict) -> dict:
    """Console grid/detail row for a queue — every grid column populated."""
    m = re.fullmatch(r"projects/([^/]+)/locations/([^/]+)/queues/([^/]+)", q["name"])
    project, loc, short = m.groups()
    tasks = [t for n, t in store.tasks.items() if n.startswith(q["name"] + "/tasks/")]
    rl, rc = q["rateLimits"], q["retryConfig"]
    return {"id": short, "name": short, "resourceName": q["name"], "project": project, "location": loc,
            "state": q["state"], "type": "HTTP target" if q.get("httpTarget") else "Push",
            "max_dispatches_per_second": rl["maxDispatchesPerSecond"],
            "max_concurrent_dispatches": rl["maxConcurrentDispatches"],
            "max_burst_size": rl["maxBurstSize"],
            "max_attempts": "Unlimited" if rc["maxAttempts"] == -1 else rc["maxAttempts"],
            "min_backoff": rc["minBackoff"], "max_backoff": rc["maxBackoff"],
            "max_doublings": rc["maxDoublings"], "max_retry_duration": rc["maxRetryDuration"],
            "tasks_in_queue": len(tasks),
            "tasks_dispatched": sum(t["dispatchCount"] for t in tasks),
            "created": q["createTime"],
            "last_purged": q.get("purgeTime") or "Never",
            "logging_sampling_ratio": (q.get("stackdriverLoggingConfig") or {}).get("samplingRatio", 0.0)}


def task_console_view(t: dict) -> dict:
    r = t.get("httpRequest") or t.get("appEngineHttpRequest") or {}
    return {"id": t["name"].rsplit("/", 1)[-1], "name": t["name"].rsplit("/", 1)[-1],
            "method": r.get("httpMethod") or "POST", "url": r.get("url") or r.get("relativeUri") or "/",
            "schedule_time": t["scheduleTime"], "created": t["createTime"],
            "dispatch_count": t["dispatchCount"], "response_count": t["responseCount"],
            "last_attempt": (t.get("lastAttempt") or {}).get("dispatchTime") or "Not attempted yet",
            "dispatch_deadline": t["dispatchDeadline"]}


def console_queue(store, project: str, location: str, queue: str) -> dict:
    return queue_console_view(store, _get_queue(store, _qname(project, location, queue)))


def console_list(store, project: str | None = None) -> list[dict]:
    qs = sorted(store.queues.values(), key=lambda q: (q["createTime"], q["name"]))
    return [queue_console_view(store, q) for q in qs if not project or q["name"].startswith(f"projects/{project}/")]


def children(store, q: dict, kind: str) -> dict:
    """Console detail-tab rows for a queue: {items: [...]}; every cell populated."""
    if kind == "tasks":
        rows = [task_console_view(t) for n, t in store.tasks.items() if n.startswith(q["name"] + "/tasks/")]
        rows.sort(key=lambda r: (r["schedule_time"], r["name"]))
        return {"items": rows}
    if kind == "activity":
        return {"items": [dict(e) for e in store.events.get(q["name"], [])]}
    return {"items": []}
