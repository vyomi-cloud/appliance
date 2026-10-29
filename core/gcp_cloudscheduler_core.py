"""GCP Cloud Scheduler core — substrate-independent. Speaks the native **Cloud
Scheduler REST API v1** (`/v1/projects/{p}/locations/{l}/jobs...`) so the native
`google-cloud-scheduler` SDKs and `gcloud scheduler` work unchanged against it
(point them at the endpoint via api_endpoint / api_endpoint_overrides).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano.

Resources (Discovery doc `cloudscheduler/v1`):
    projects/{p}/locations/{l}
    projects/{p}/locations/{l}/jobs/{job}
Methods: locations.list/get, jobs.create/get/list/patch/delete/pause/resume/run.
Custom methods ride the `:verb` suffix (`:pause`, `:resume`, `:run`). Errors use the
Google shape `{"error":{"code","message","status"}}` (ALREADY_EXISTS, NOT_FOUND,
INVALID_ARGUMENT, FAILED_PRECONDITION).

Scheduling is lazy and deterministic: there is no timer thread. Every read (get/list)
and `:run` first calls `_advance()`, which fires each ENABLED job whose `scheduleTime`
has passed (once — missed ticks are not replayed), stamps `lastAttemptTime` /
`status`, and computes the next `scheduleTime` from the cron expression in the job's
`timeZone`. A pubsub target is delivered through the optional `invoker` hook the
caller passes to `dispatch()` (the Nano / wire router publishes into the Pub/Sub core);
http / App Engine targets are recorded as attempted — this substrate-free core makes
no network calls.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

try:   # tz database (present in CPython; may be absent in a stripped Pyodide)
    from zoneinfo import ZoneInfo
except Exception:   # pragma: no cover
    ZoneInfo = None

ENABLED, PAUSED, DISABLED, UPDATE_FAILED = "ENABLED", "PAUSED", "DISABLED", "UPDATE_FAILED"
HTTP_METHODS = ("POST", "GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS")
LOCATIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1",
             "europe-west2", "europe-west3", "asia-east1", "asia-northeast1", "asia-south1",
             "asia-southeast1", "australia-southeast1", "southamerica-east1"]
DEFAULT_TIMEZONE = "Etc/UTC"
MAX_JOBS_PER_LOCATION = 1000


# ── store ──────────────────────────────────────────────────────────────────
class CloudSchedulerStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.jobs: dict = {}      # full job name -> job record (the REST resource)


_SHARED: CloudSchedulerStore | None = None


def shared_store() -> CloudSchedulerStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = CloudSchedulerStore()
    return _SHARED


@dataclass
class SchedResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _err(status, gcp_status, message):
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return SchedResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return SchedResponse(status=status, body=json.dumps(obj).encode())


def _now_dt():
    return datetime.now(timezone.utc)


def _ts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


# ── cron ───────────────────────────────────────────────────────────────────
_FIELDS = [("minute", 0, 59), ("hour", 0, 23), ("day-of-month", 1, 31), ("month", 1, 12),
           ("day-of-week", 0, 7)]
_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_DOW = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}


def _parse_field(text, lo, hi, names):
    out = set()
    for part in text.split(","):
        if not part:
            raise ValueError("empty list element")
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            if not s.isdigit() or int(s) < 1:
                raise ValueError("bad step")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        else:
            def val(x):
                x = x.lower()
                if x in names:
                    return names[x]
                if not x.isdigit():
                    raise ValueError("bad value %r" % x)
                return int(x)
            if "-" in part:
                x, y = part.split("-", 1)
                a, b = val(x), val(y)
            else:
                a = val(part)
                b = hi if step > 1 else a
        if a < lo or b > hi or a > b:
            raise ValueError("value out of range %d-%d" % (lo, hi))
        out.update(range(a, b + 1, step))
    return out


def parse_cron(expr):
    """5-field unix-cron → (minutes, hours, doms, months, dows, dom_star, dow_star)."""
    expr = (expr or "").strip()
    m = re.match(r"^@(yearly|annually|monthly|weekly|daily|midnight|hourly)$", expr)
    if m:
        expr = {"yearly": "0 0 1 1 *", "annually": "0 0 1 1 *", "monthly": "0 0 1 * *",
                "weekly": "0 0 * * 0", "daily": "0 0 * * *", "midnight": "0 0 * * *",
                "hourly": "0 * * * *"}[m.group(1)]
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("schedule must have 5 fields (minute hour day-of-month month day-of-week)")
    sets = []
    for (name, lo, hi), p in zip(_FIELDS, parts):
        try:
            sets.append(_parse_field(p, lo, hi, _MONTHS if name == "month" else _DOW if name == "day-of-week" else {}))
        except ValueError as e:
            raise ValueError("invalid %s field %r: %s" % (name, p, e))
    sets[4] = {d % 7 for d in sets[4]}
    return (*sets, parts[2].startswith("*"), parts[4].startswith("*"))


def _tz(name):
    if not name or name.upper() in ("UTC", "ETC/UTC", "GMT", "Z"):
        return timezone.utc
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        raise ValueError("unknown time zone %r" % name)


def next_run(schedule, tzname, after):
    """First instant strictly after `after` (aware datetime) matching the cron in tzname."""
    mins, hours, doms, months, dows, dom_star, dow_star = parse_cron(schedule)
    tz = _tz(tzname)
    t = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60 * 5):   # 5 years of minutes is more than enough
        if t.month not in months:
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        dom_ok, dow_ok = t.day in doms, ((t.weekday() + 1) % 7) in dows
        day_ok = (dom_ok and dow_ok) if (dom_star or dow_star) else (dom_ok or dow_ok)
        if not day_ok:
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in hours:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute not in mins:
            t += timedelta(minutes=1)
            continue
        return t.astimezone(timezone.utc)
    raise ValueError("schedule never fires")


# ── names / validation ─────────────────────────────────────────────────────
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,500}$")
_DUR = re.compile(r"^-?\d+(\.\d{1,9})?s$")


def job_name(project, location, job_id):
    return "projects/%s/locations/%s/jobs/%s" % (project, location, job_id)


def _dur_seconds(s):
    return float(s[:-1])


def _validate_duration(field_name, v, lo=None, hi=None):
    if not isinstance(v, str) or not _DUR.match(v):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at '%s' (type.googleapis.com/google.protobuf.Duration), Field '%s', Illegal duration format; duration must end with 's'" % (field_name, field_name.split(".")[-1]))
    sec = _dur_seconds(v)
    if (lo is not None and sec < lo) or (hi is not None and sec > hi):
        raise _E(400, "INVALID_ARGUMENT", "%s must be between %ss and %ss." % (field_name, lo, hi))


def _validate_target(job):
    targets = [k for k in ("httpTarget", "pubsubTarget", "appEngineHttpTarget") if job.get(k)]
    if not targets:
        raise _E(400, "INVALID_ARGUMENT", "Job must have a target: one of httpTarget, pubsubTarget, appEngineHttpTarget.")
    if len(targets) > 1:
        raise _E(400, "INVALID_ARGUMENT", "Only one target may be set on a job (got %s)." % ", ".join(targets))
    t = targets[0]
    body = job[t]
    if not isinstance(body, dict):
        raise _E(400, "INVALID_ARGUMENT", "Invalid %s." % t)
    if t == "httpTarget":
        uri = body.get("uri", "")
        if not re.match(r"^https?://[^\s/]+", uri or ""):
            raise _E(400, "INVALID_ARGUMENT", "httpTarget.uri must be an absolute http or https URL.")
        m = body.get("httpMethod") or "POST"
        if m not in HTTP_METHODS and m != "HTTP_METHOD_UNSPECIFIED":
            raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'job.http_target.http_method' (type.googleapis.com/google.cloud.scheduler.v1.HttpMethod), \"%s\"" % m)
        if body.get("oauthToken") and body.get("oidcToken"):
            raise _E(400, "INVALID_ARGUMENT", "httpTarget may set only one of oauthToken and oidcToken.")
        if m in ("GET", "HEAD") and body.get("body"):
            raise _E(400, "INVALID_ARGUMENT", "HTTP method %s must not have a body." % m)
    elif t == "pubsubTarget":
        if not re.match(r"^projects/[^/]+/topics/[^/]+$", body.get("topicName", "") or ""):
            raise _E(400, "INVALID_ARGUMENT", "pubsubTarget.topicName must be of the form projects/{project}/topics/{topic}.")
    for k in ("body", "data"):
        if body.get(k):
            try:
                base64.b64decode(body[k], validate=True)
            except Exception:
                raise _E(400, "INVALID_ARGUMENT", "%s.%s must be base64-encoded." % (t, k))
    return t


def _validate_retry(rc):
    if not isinstance(rc, dict):
        raise _E(400, "INVALID_ARGUMENT", "Invalid retryConfig.")
    n = rc.get("retryCount")
    if n is not None and (not isinstance(n, int) or n < 0 or n > 5):
        raise _E(400, "INVALID_ARGUMENT", "retryConfig.retryCount must be between 0 and 5.")
    md = rc.get("maxDoublings")
    if md is not None and (not isinstance(md, int) or md < 0):
        raise _E(400, "INVALID_ARGUMENT", "retryConfig.maxDoublings must be >= 0.")
    for f in ("maxRetryDuration", "minBackoffDuration", "maxBackoffDuration"):
        if f in rc:
            _validate_duration("retryConfig." + f, rc[f], 0)
    if "minBackoffDuration" in rc and "maxBackoffDuration" in rc and \
            _dur_seconds(rc["minBackoffDuration"]) > _dur_seconds(rc["maxBackoffDuration"]):
        raise _E(400, "INVALID_ARGUMENT", "retryConfig.minBackoffDuration must be <= maxBackoffDuration.")


def _validate_job(job):
    if not (job.get("schedule") or "").strip():
        raise _E(400, "INVALID_ARGUMENT", "Job schedule is required.")
    try:
        parse_cron(job["schedule"])
        _tz(job.get("timeZone") or DEFAULT_TIMEZONE)
    except ValueError as e:
        raise _E(400, "INVALID_ARGUMENT", "Invalid schedule or timeZone: %s." % e)
    if len(job.get("description", "") or "") > 500:
        raise _E(400, "INVALID_ARGUMENT", "description must be at most 500 characters.")
    _validate_target(job)
    if "retryConfig" in job:
        _validate_retry(job["retryConfig"])
    if "attemptDeadline" in job:
        _validate_duration("attemptDeadline", job["attemptDeadline"], 15, 1800)


_WRITABLE = ("description", "schedule", "timeZone", "retryConfig", "attemptDeadline",
             "httpTarget", "pubsubTarget", "appEngineHttpTarget")


def _compute_next(job, after=None):
    try:
        return _ts(next_run(job["schedule"], job.get("timeZone") or DEFAULT_TIMEZONE, after or _now_dt()))
    except ValueError:
        return None


# ── execution ──────────────────────────────────────────────────────────────
def _fire(job, invoker, now):
    """Run one attempt; stamps lastAttemptTime/status. Never raises."""
    job["lastAttemptTime"] = _ts(now)
    status = {}
    if job.get("pubsubTarget") and invoker:
        t = job["pubsubTarget"]
        try:
            res = invoker("pubsub", {"topicName": t["topicName"], "data": t.get("data", ""),
                                     "attributes": t.get("attributes") or {}, "job": job["name"]})
            if res is not True and res is not None and res != "":
                status = {"code": 5, "message": str(res)}   # NOT_FOUND etc. from the topic
        except Exception as e:   # noqa: BLE001
            status = {"code": 13, "message": str(e)}
    elif job.get("httpTarget") and invoker:
        t = job["httpTarget"]
        try:   # the invoker (appliance only) sends the request; Nano has none -> recorded only
            res = invoker("http", {"uri": t.get("uri", ""), "httpMethod": t.get("httpMethod") or "POST",
                                   "headers": t.get("headers") or {}, "body": t.get("body", ""),
                                   "oidcToken": t.get("oidcToken"), "oauthToken": t.get("oauthToken"),
                                   "attemptDeadline": job.get("attemptDeadline"),
                                   "retryConfig": job.get("retryConfig") or {}, "job": job["name"]})
            if res is not True and res is not None and res != "":
                status = {"code": 13, "message": str(res)}
        except Exception as e:   # noqa: BLE001
            status = {"code": 13, "message": str(e)}
    job["status"] = status
    return status


def _advance(store, now=None, invoker=None, only=None):
    now = now or _now_dt()
    for name, job in list(store.jobs.items()):
        if only and name != only:
            continue
        if job.get("state") != ENABLED or not job.get("scheduleTime"):
            continue
        if _parse_ts(job["scheduleTime"]) <= now:
            _fire(job, invoker, now)
            job["scheduleTime"] = _compute_next(job, now)


# ── views ──────────────────────────────────────────────────────────────────
def job_view(job):
    """The REST Job resource (output-only fields only when set, like the real API)."""
    v = {k: json.loads(json.dumps(x)) for k, x in job.items() if x not in (None, "")}
    v.setdefault("status", {})
    return v


def _target_kind(job):
    return ("HTTP" if job.get("httpTarget") else "Pub/Sub" if job.get("pubsubTarget")
            else "App Engine HTTP" if job.get("appEngineHttpTarget") else "-")


def _target_text(job):
    if job.get("httpTarget"):
        return "%s %s" % (job["httpTarget"].get("httpMethod") or "POST", job["httpTarget"].get("uri", ""))
    if job.get("pubsubTarget"):
        return job["pubsubTarget"].get("topicName", "")
    a = job.get("appEngineHttpTarget") or {}
    return "%s %s" % (a.get("httpMethod") or "POST", a.get("relativeUri", "/"))


def console_view(job):
    """Flat row for the console grid / detail: every column filled (the real console
    shows 'Has not run yet' for a job that has not fired)."""
    name = job["name"]
    parts = name.split("/")
    v = job_view(job)
    status = job.get("status") or {}
    ran = bool(job.get("lastAttemptTime"))
    v.update({
        "name": parts[-1], "id": parts[-1], "resourceName": name, "project": parts[1], "region": parts[3],
        "location": parts[3],
        "frequency": job.get("schedule", ""),
        "target": _target_text(job), "target_type": _target_kind(job),
        "last_run": job.get("lastAttemptTime") or "Has not run yet",
        "next_run": (job.get("scheduleTime") or "Not scheduled") if job.get("state") == ENABLED else "Not scheduled (paused)",
        "last_status": ("Failed: " + status.get("message", "") if status.get("code") else "Success") if ran else "Has not run yet",
        "retry_summary": _retry_summary(job),
        "timezone": job.get("timeZone") or DEFAULT_TIMEZONE,
        "description_text": job.get("description") or "No description",
        "attempt_deadline": job.get("attemptDeadline") or "180s",
        "created": job.get("userUpdateTime", ""),
    })
    return v


def _retry_summary(job):
    rc = job.get("retryConfig") or {}
    return "%s retries, backoff %s-%s, %s doublings" % (
        rc.get("retryCount", 0), rc.get("minBackoffDuration", "5s"),
        rc.get("maxBackoffDuration", "3600s"), rc.get("maxDoublings", 5))


# ── operations ─────────────────────────────────────────────────────────────
def create_job(store, project, location, payload):
    if location not in LOCATIONS:
        raise _E(404, "NOT_FOUND", "Location '%s' is not a valid location." % location)
    job = dict(payload or {})
    _validate_job(job)
    full = job.get("name") or ""
    if full:
        m = re.match(r"^projects/([^/]+)/locations/([^/]+)/jobs/([A-Za-z0-9_-]+)$", full)
        if not m or m.group(1) != project or m.group(2) != location:
            raise _E(400, "INVALID_ARGUMENT", "Job name must be of the form projects/%s/locations/%s/jobs/{job}." % (project, location))
    else:
        raise _E(400, "INVALID_ARGUMENT", "Job name is required: projects/%s/locations/%s/jobs/{job}." % (project, location))
    if not _JOB_ID.match(full.rsplit("/", 1)[1]):
        raise _E(400, "INVALID_ARGUMENT", "Job ID may contain only letters, numbers, hyphens, and underscores.")
    if full in store.jobs:
        raise _E(409, "ALREADY_EXISTS", "Job %s already exists." % full)
    if sum(1 for n in store.jobs if n.startswith("projects/%s/locations/%s/" % (project, location))) >= MAX_JOBS_PER_LOCATION:
        raise _E(429, "RESOURCE_EXHAUSTED", "Quota exceeded for jobs per location.")
    now = _now_dt()
    rec = {k: job[k] for k in _WRITABLE if k in job and job[k] not in (None, "")}
    rec.update({"name": full, "state": ENABLED, "userUpdateTime": _ts(now), "status": {}})
    rec.setdefault("timeZone", DEFAULT_TIMEZONE)
    rec.setdefault("retryConfig", {})
    if rec.get("httpTarget"):
        rec["httpTarget"].setdefault("httpMethod", "POST")
    rec["scheduleTime"] = _compute_next(rec, now)
    store.jobs[full] = rec
    return rec


def _get(store, project, location, job_id):
    full = job_name(project, location, job_id)
    job = store.jobs.get(full)
    if not job:
        raise _E(404, "NOT_FOUND", "Job not found.")
    return job


def patch_job(store, project, location, job_id, payload, update_mask):
    job = _get(store, project, location, job_id)
    payload = dict(payload or {})
    payload.pop("name", None)
    fields = [f.strip() for f in (update_mask or "").split(",") if f.strip()] or [k for k in payload if k in _WRITABLE]
    merged = dict(job)
    for f in fields:
        top = f.split(".")[0]
        if top not in _WRITABLE:
            raise _E(400, "INVALID_ARGUMENT", "Invalid update mask: field '%s' is not updatable." % f)
        if "." in f:
            sub = f.split(".", 1)[1]
            cur = dict(merged.get(top) or {})
            if sub in (payload.get(top) or {}):
                cur[sub] = payload[top][sub]
            else:
                cur.pop(sub, None)
            merged[top] = cur
        elif top in payload and payload[top] not in (None, ""):
            merged[top] = payload[top]
        else:
            merged.pop(top, None)
    if any(f.split(".")[0] in ("httpTarget", "pubsubTarget", "appEngineHttpTarget") for f in fields):
        for k in ("httpTarget", "pubsubTarget", "appEngineHttpTarget"):   # patching a target replaces the oneof
            if k not in {f.split(".")[0] for f in fields}:
                merged.pop(k, None)
    _validate_job(merged)
    merged["userUpdateTime"] = _ts(_now_dt())
    if merged.get("state") == ENABLED:
        merged["scheduleTime"] = _compute_next(merged)
    store.jobs[job["name"]] = merged
    return merged


def _set_state(store, project, location, job_id, state):
    job = _get(store, project, location, job_id)
    if state == PAUSED:
        if job["state"] == PAUSED:
            return job
        job["state"] = PAUSED
        job.pop("scheduleTime", None)
    else:
        if job["state"] == ENABLED:
            return job
        job["state"] = ENABLED
        job["scheduleTime"] = _compute_next(job)
    job["userUpdateTime"] = _ts(_now_dt())
    return job


def run_job(store, project, location, job_id, invoker=None):
    job = _get(store, project, location, job_id)
    if job.get("state") != ENABLED:
        raise _E(400, "FAILED_PRECONDITION", "Job %s is not ENABLED (state: %s); cannot be run." % (job["name"], job.get("state")))
    _fire(job, invoker, _now_dt())
    return job


def list_jobs(store, project, location, query):
    prefix = "projects/%s/locations/%s/jobs/" % (project, location)
    jobs = sorted((j for n, j in store.jobs.items() if n.startswith(prefix)), key=lambda j: j["name"])
    try:
        size = int(query.get("pageSize") or 0)
    except ValueError:
        raise _E(400, "INVALID_ARGUMENT", "Invalid pageSize.")
    if size < 0:
        raise _E(400, "INVALID_ARGUMENT", "pageSize must be non-negative.")
    start = 0
    tok = query.get("pageToken") or ""
    if tok:
        try:
            start = int(base64.urlsafe_b64decode(tok.encode()).decode())
        except Exception:
            raise _E(400, "INVALID_ARGUMENT", "Invalid pageToken.")
    size = size or 500
    page = jobs[start:start + size]
    out = {"jobs": [job_view(j) for j in page]} if page else {}
    if start + size < len(jobs):
        out["nextPageToken"] = base64.urlsafe_b64encode(str(start + size).encode()).decode()
    return out


def list_all(store, project=None):
    """Console grid: every job (optionally for a project), advanced to now."""
    _advance(store)
    return [console_view(j) for n, j in sorted(store.jobs.items())
            if project is None or n.startswith("projects/%s/" % project)]


def job_from_form(b, project="demo"):
    """Console create form (catalog createFields) → REST Job, shared by the offline
    console REST and the Nano adapter so both consoles create identical jobs."""
    region = str(b.get("region") or "us-central1")
    job = {"name": job_name(project, region, str(b.get("name") or "").strip()),
           "schedule": str(b.get("schedule") or "").strip(),
           "timeZone": str(b.get("timeZone") or DEFAULT_TIMEZONE).strip()}
    if b.get("description"):
        job["description"] = str(b["description"])
    kind = str(b.get("targetType") or "HTTP").upper().replace("/", "")
    if kind == "PUBSUB":
        job["pubsubTarget"] = {"topicName": str(b.get("topic") or "").strip(),
                               "data": base64.b64encode(str(b.get("message") or "").encode()).decode()}
    else:
        job["httpTarget"] = {"uri": str(b.get("url") or "").strip(),
                             "httpMethod": str(b.get("httpMethod") or "POST").upper()}
    return job


# ── dispatch ───────────────────────────────────────────────────────────────
def _location_view(project, loc):
    return {"name": "projects/%s/locations/%s" % (project, loc), "locationId": loc,
            "labels": {"cloud.googleapis.com/region": loc}}


# Proto enums are strings on the wire by default, but the Java / .NET / Go-gapic REST clients
# send `$alt=json;enum-encoding=int` and expect integers back (and send integers in bodies).
_STATE_INT = {ENABLED: 1, PAUSED: 2, DISABLED: 3, UPDATE_FAILED: 4}
_METHOD_INT = {"HTTP_METHOD_UNSPECIFIED": 0, "POST": 1, "GET": 2, "HEAD": 3, "PUT": 4, "DELETE": 5,
               "PATCH": 6, "OPTIONS": 7}
_METHOD_NAME = {v: k for k, v in _METHOD_INT.items()}


def _enum_int(obj):
    if isinstance(obj, dict) and "jobs" in obj:
        return dict(obj, jobs=[_enum_int(j) for j in obj["jobs"]])
    if isinstance(obj, dict) and "name" in obj and "/jobs/" in obj["name"]:
        obj = dict(obj)
        if obj.get("state") in _STATE_INT:
            obj["state"] = _STATE_INT[obj["state"]]
        for t in ("httpTarget", "appEngineHttpTarget"):
            if isinstance(obj.get(t), dict) and obj[t].get("httpMethod") in _METHOD_INT:
                obj[t] = dict(obj[t], httpMethod=_METHOD_INT[obj[t]["httpMethod"]])
    return obj


def _wants_int_enums(query):
    return "enum-encoding=int" in (query.get("$alt") or query.get("alt") or "").replace("%3D", "=")


def _normalize_in(payload):
    """Accept integer enums in request bodies (httpMethod) as the wire clients send them."""
    for t in ("httpTarget", "appEngineHttpTarget"):
        tgt = payload.get(t)
        if isinstance(tgt, dict) and isinstance(tgt.get("httpMethod"), int):
            tgt["httpMethod"] = _METHOD_NAME.get(tgt["httpMethod"], tgt["httpMethod"])
    return payload


def dispatch(store, method, path, query=None, headers=None, body=b"", invoker=None):
    query = query or {}
    r = _dispatch(store, method, path, query, headers or {}, body, invoker)
    if r.status == 200 and _wants_int_enums(query):
        try:
            r.body = json.dumps(_enum_int(json.loads(r.body))).encode()
        except Exception:
            pass
    return r


def _dispatch(store, method, path, query, headers, body, invoker):
    method = method.upper()
    for k, v in headers.items():   # REST clients without PATCH (JDK HttpURLConnection) tunnel it over POST
        if k.lower() == "x-http-method-override" and method == "POST" and v:
            method = str(v).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    payload = _normalize_in(payload)
    p = path.split("?", 1)[0]
    for pre in ("/v1beta1", "/v1"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    if len(segs) < 2 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    project = segs[1]
    try:
        if len(segs) == 3 and segs[2] == "locations" and method == "GET":
            return _json(200, {"locations": [_location_view(project, l) for l in LOCATIONS]})
        if len(segs) < 4 or segs[2] != "locations":
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        location = segs[3]
        if len(segs) == 4 and method == "GET":
            if location not in LOCATIONS:
                return _err(404, "NOT_FOUND", "Location '%s' is not a valid location." % location)
            return _json(200, _location_view(project, location))
        if len(segs) < 5 or segs[4] != "jobs":
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        _advance(store, invoker=invoker)
        if len(segs) == 5:
            if method == "POST":
                return _json(200, job_view(create_job(store, project, location, payload)))
            if method == "GET":
                if location not in LOCATIONS:
                    return _err(404, "NOT_FOUND", "Location '%s' is not a valid location." % location)
                return _json(200, list_jobs(store, project, location, query))
            return _err(405, "UNIMPLEMENTED", "Method %s not allowed on jobs collection." % method)
        if len(segs) == 6:
            job_id = segs[5]
            if verb == "pause" and method == "POST":
                return _json(200, job_view(_set_state(store, project, location, job_id, PAUSED)))
            if verb == "resume" and method == "POST":
                return _json(200, job_view(_set_state(store, project, location, job_id, ENABLED)))
            if verb == "run" and method == "POST":
                return _json(200, job_view(run_job(store, project, location, job_id, invoker)))
            if verb:
                return _err(404, "NOT_FOUND", "Unknown method :%s" % verb)
            if method == "GET":
                return _json(200, job_view(_get(store, project, location, job_id)))
            if method == "PATCH":
                return _json(200, job_view(patch_job(store, project, location, job_id, payload, query.get("updateMask", ""))))
            if method == "DELETE":
                job = _get(store, project, location, job_id)
                del store.jobs[job["name"]]
                return _json(200, {})
            return _err(405, "UNIMPLEMENTED", "Method %s not allowed on job." % method)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
