"""GCP Workflows core — substrate-independent. Speaks the native **Workflows API v1**
(`/v1/projects/{p}/locations/{l}/workflows...`) and the sibling **Workflow Executions API v1**
(`.../workflows/{w}/executions...`) so `google-cloud-workflows` SDKs and `gcloud workflows` work
unchanged against it (point them at the endpoint via api_endpoint / api_endpoint_overrides).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano.

Resources (Discovery docs `workflows/v1`, `workflowexecutions/v1`):
    projects/{p}/locations/{l}
    projects/{p}/locations/{l}/workflows/{w}
    projects/{p}/locations/{l}/workflows/{w}/executions/{e}
    projects/{p}/locations/{l}/operations/{op}
Methods: locations.list/get, workflows.create/get/list/patch/delete/listRevisions,
executions.create/get/list/cancel, operations.get/list/delete/cancel. Workflow create / patch /
delete return a long-running Operation (completed immediately, like a control plane that has
already converged). Errors use the Google shape `{"error":{"code","message","status"}}`.

Executions run synchronously and deterministically: a tiny evaluator resolves the workflow's
final `return:` (a literal, or `${var}` of a literal `assign` step) — otherwise the result is the
execution argument echoed back. No network calls are made (http.* steps are not performed).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

ACTIVE, UNAVAILABLE = "ACTIVE", "UNAVAILABLE"
LOCATIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1",
             "europe-west2", "europe-west3", "europe-west4", "asia-east1", "asia-northeast1",
             "asia-south1", "asia-southeast1", "australia-southeast1", "southamerica-east1"]
CALL_LOG_LEVELS = ("CALL_LOG_LEVEL_UNSPECIFIED", "LOG_ALL_CALLS", "LOG_ERRORS_ONLY", "LOG_NONE")
HISTORY_LEVELS = ("EXECUTION_HISTORY_LEVEL_UNSPECIFIED", "EXECUTION_HISTORY_BASIC", "EXECUTION_HISTORY_DETAILED")
MAX_SOURCE_BYTES = 128 * 1024
MAX_WORKFLOWS_PER_LOCATION = 1000
DEFAULT_SOURCE = (
    "main:\n"
    "  steps:\n"
    "    - init:\n"
    "        assign:\n"
    "          - greeting: \"Hello from Vyomi\"\n"
    "    - done:\n"
    "        return: ${greeting}\n"
)


# ── store ──────────────────────────────────────────────────────────────────
class WorkflowsStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.workflows: dict = {}     # full workflow name -> Workflow resource
        self.revisions: dict = {}     # full workflow name -> [Workflow snapshots, oldest first]
        self.executions: dict = {}    # full execution name -> Execution resource
        self.operations: dict = {}    # full operation name -> Operation resource
        self.seq: dict = {"op": 0, "exec": 0}


_SHARED: WorkflowsStore | None = None


def shared_store() -> WorkflowsStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = WorkflowsStore()
    return _SHARED


@dataclass
class WorkflowsResponse:
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
    return WorkflowsResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return WorkflowsResponse(status=status, body=json.dumps(obj).encode())


def _copy(x):
    return json.loads(json.dumps(x))


def _now():
    return datetime.now(timezone.utc)


def _ts(dt=None):
    return (dt or _now()).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ── names / validation ─────────────────────────────────────────────────────
_WF_ID = re.compile(r"^[a-zA-Z]([-_a-zA-Z0-9]{0,61}[a-zA-Z0-9])?$")
_LABEL_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_LABEL_VAL = re.compile(r"^[a-z0-9_-]{0,63}$")
_SA = re.compile(r"^(projects/[^/]+/serviceAccounts/)?[^@\s/]+@[^@\s/]+$")
_KMS = re.compile(r"^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$")


def workflow_name(project, location, wid):
    return "projects/%s/locations/%s/workflows/%s" % (project, location, wid)


def _project_number(project):
    return str(int(hashlib.sha1(project.encode()).hexdigest()[:8], 16) % 900000000000 + 100000000000)


def default_service_account(project):
    return "%s-compute@developer.gserviceaccount.com" % _project_number(project)


def _missing(name, project, location):
    return _E(404, "NOT_FOUND", "Resource '%s' of kind 'WORKFLOW' in region '%s' in project '%s' does not exist."
              % (name, location, project))


def _valid_location(location):
    return location in LOCATIONS


def _check_source(src):
    if not isinstance(src, str) or not src.strip():
        raise _E(400, "INVALID_ARGUMENT", "Workflow source code is required: set sourceContents.")
    if len(src.encode()) > MAX_SOURCE_BYTES:
        raise _E(400, "INVALID_ARGUMENT", "Workflow source code exceeds the maximum size of 128 KB.")
    s = src.strip()
    if s.startswith("{"):
        try:
            doc = json.loads(s)
        except Exception as e:
            raise _E(400, "INVALID_ARGUMENT", "Failed to parse the workflow source as JSON: %s" % e)
        if not isinstance(doc, dict) or "main" not in doc:
            raise _E(400, "INVALID_ARGUMENT", "Workflow source must define a 'main' workflow.")
        return
    if "\t" in re.sub(r'"[^"\n]*"', "", src):
        raise _E(400, "INVALID_ARGUMENT", "Failed to parse the workflow source as YAML: tab characters are not allowed for indentation.")
    if not re.search(r"^main\s*:", src, re.M):
        raise _E(400, "INVALID_ARGUMENT", "Workflow source must define a 'main' workflow (a top-level 'main:' key).")
    if not re.search(r"^\s+(steps|params)\s*:", src, re.M):
        raise _E(400, "INVALID_ARGUMENT", "The 'main' workflow must define 'steps'.")


def _check_labels(labels):
    if not isinstance(labels, dict):
        raise _E(400, "INVALID_ARGUMENT", "labels must be a map of strings.")
    if len(labels) > 64:
        raise _E(400, "INVALID_ARGUMENT", "A workflow may have at most 64 labels.")
    for k, v in labels.items():
        if not _LABEL_KEY.match(str(k)) or not isinstance(v, str) or not _LABEL_VAL.match(v):
            raise _E(400, "INVALID_ARGUMENT", "Invalid label %r: keys must start with a lowercase letter; keys and values may contain lowercase letters, digits, '_' and '-' (max 63 chars)." % k)


def _check_env(env):
    if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
        raise _E(400, "INVALID_ARGUMENT", "userEnvVars must be a map of strings.")
    if len(env) > 20:
        raise _E(400, "INVALID_ARGUMENT", "A workflow may have at most 20 user environment variables.")
    for k in env:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k) or k.upper().startswith("GOOGLE_"):
            raise _E(400, "INVALID_ARGUMENT", "Invalid user environment variable name %r." % k)


def _validate_fields(w):
    if "description" in w and len(w["description"] or "") > 1000:
        raise _E(400, "INVALID_ARGUMENT", "description must be at most 1000 characters.")
    if w.get("serviceAccount") and not _SA.match(w["serviceAccount"]):
        raise _E(400, "INVALID_ARGUMENT", "serviceAccount must be a service account email or projects/{project}/serviceAccounts/{email}.")
    if w.get("cryptoKeyName") and not _KMS.match(w["cryptoKeyName"]):
        raise _E(400, "INVALID_ARGUMENT", "cryptoKeyName must be of the form projects/*/locations/*/keyRings/*/cryptoKeys/*.")
    if w.get("callLogLevel") and w["callLogLevel"] not in CALL_LOG_LEVELS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'workflow.call_log_level' (type.googleapis.com/google.cloud.workflows.v1.Workflow.CallLogLevel), \"%s\"" % w["callLogLevel"])
    if w.get("executionHistoryLevel") and w["executionHistoryLevel"] not in HISTORY_LEVELS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'workflow.execution_history_level', \"%s\"" % w["executionHistoryLevel"])
    if "labels" in w:
        _check_labels(w["labels"] or {})
    if "userEnvVars" in w:
        _check_env(w["userEnvVars"] or {})


_WRITABLE = ("description", "labels", "serviceAccount", "sourceContents", "cryptoKeyName",
             "callLogLevel", "userEnvVars", "executionHistoryLevel")


# ── operations ─────────────────────────────────────────────────────────────
def _operation(store, project, location, verb, target, response=None, response_type="google.cloud.workflows.v1.Workflow"):
    store.seq["op"] += 1
    oid = "operation-%d-%s" % (store.seq["op"], hashlib.sha1(("%s%d" % (target, store.seq["op"])).encode()).hexdigest()[:10])
    name = "projects/%s/locations/%s/operations/%s" % (project, location, oid)
    now = _ts()
    op = {"name": name,
          "metadata": {"@type": "type.googleapis.com/google.cloud.workflows.v1.OperationMetadata", "createTime": now,
                       "endTime": now, "target": target, "verb": verb, "statusDetail": "",
                       "cancelRequested": False, "apiVersion": "v1"},
          "done": True}
    resp = {"@type": "type.googleapis.com/" + response_type}
    if response_type == "google.protobuf.Empty":
        resp["value"] = {}   # Empty has a special JSON form inside Any: the payload sits under "value"
    else:
        resp.update(response if response is not None else {})
    op["response"] = resp
    store.operations[name] = op
    return _copy(op)


def _get_op(store, project, location, oid):
    name = "projects/%s/locations/%s/operations/%s" % (project, location, oid)
    op = store.operations.get(name)
    if not op:
        raise _E(404, "NOT_FOUND", "Not found: %s." % name)
    return name, op


# ── workflows ──────────────────────────────────────────────────────────────
def _revision_id(n, name, src):
    return "%06d-%s" % (n, hashlib.sha1((name + src + str(n)).encode()).hexdigest()[:3])


def _public(w):
    return _copy(w)


def _snapshot(store, w):
    store.revisions.setdefault(w["name"], []).append(_copy(w))


def create_workflow(store, project, location, wid, payload):
    if not _valid_location(location):
        raise _E(404, "NOT_FOUND", "Location '%s' is not a valid location." % location)
    if not wid:
        raise _E(400, "INVALID_ARGUMENT", "workflowId is required.")
    if not _WF_ID.match(wid):
        raise _E(400, "INVALID_ARGUMENT", "Invalid workflow ID '%s': must start with a letter, contain only letters, numbers, underscores and hyphens, end with a letter or number, and be at most 64 characters." % wid)
    payload = dict(payload or {})
    for k in payload:
        if k not in _WRITABLE and k not in ("name", "state", "revisionId", "createTime", "updateTime",
                                            "revisionCreateTime", "stateError", "allKmsKeys",
                                            "allKmsKeysVersions", "cryptoKeyVersion", "tags", "sourceContents"):
            raise _E(400, "INVALID_ARGUMENT", "Invalid JSON payload received. Unknown name \"%s\" at 'workflow': Cannot find field." % k)
    _check_source(payload.get("sourceContents"))
    _validate_fields(payload)
    full = workflow_name(project, location, wid)
    if full in store.workflows:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
    if sum(1 for n in store.workflows if n.startswith("projects/%s/locations/%s/" % (project, location))) >= MAX_WORKFLOWS_PER_LOCATION:
        raise _E(429, "RESOURCE_EXHAUSTED", "Quota exceeded for workflows per location.")
    now = _ts()
    w = {k: payload[k] for k in _WRITABLE if payload.get(k) not in (None, "")}
    w.update({"name": full, "state": ACTIVE, "revisionId": _revision_id(1, full, w["sourceContents"]),
              "createTime": now, "updateTime": now, "revisionCreateTime": now})
    w.setdefault("serviceAccount", default_service_account(project))
    w.setdefault("callLogLevel", "CALL_LOG_LEVEL_UNSPECIFIED")
    w.setdefault("executionHistoryLevel", "EXECUTION_HISTORY_LEVEL_UNSPECIFIED")
    w.setdefault("labels", {})
    w.setdefault("userEnvVars", {})
    w.setdefault("description", "")
    store.workflows[full] = w
    store.revisions[full] = []
    _snapshot(store, w)
    return _operation(store, project, location, "create", full, _public(w))


def _get(store, project, location, wid):
    full = workflow_name(project, location, wid)
    w = store.workflows.get(full)
    if not w:
        raise _missing(full, project, location)
    return w


def patch_workflow(store, project, location, wid, payload, mask):
    w = _get(store, project, location, wid)
    payload = dict(payload or {})
    fields = [f.strip() for f in (mask or "").split(",") if f.strip()]
    if not fields:
        fields = [k for k in payload if k in _WRITABLE]
    new = _copy(w)
    for f in fields:
        top = f.split(".")[0]
        if top not in _WRITABLE:
            raise _E(400, "INVALID_ARGUMENT", "Invalid update mask: field '%s' is not updatable." % f)
        if "." in f and top not in ("labels", "userEnvVars"):
            raise _E(400, "INVALID_ARGUMENT", "Invalid update mask: '%s'." % f)
        if "." in f:
            sub = f.split(".", 1)[1]
            cur = dict(new.get(top) or {})
            if sub in (payload.get(top) or {}):
                cur[sub] = payload[top][sub]
            else:
                cur.pop(sub, None)
            new[top] = cur
        elif payload.get(top) not in (None, ""):
            new[top] = payload[top]
        elif top == "sourceContents":
            raise _E(400, "INVALID_ARGUMENT", "Workflow source code is required: set sourceContents.")
        else:
            new[top] = {} if top in ("labels", "userEnvVars") else ""
    _validate_fields(new)
    if "sourceContents" in fields:
        _check_source(new.get("sourceContents"))
    if not new.get("serviceAccount"):
        new["serviceAccount"] = default_service_account(project)
    now = _ts()
    new["updateTime"] = now
    if new.get("sourceContents") != w.get("sourceContents"):
        n = len(store.revisions.get(w["name"], [])) + 1
        new["revisionId"] = _revision_id(n, w["name"], new["sourceContents"])
        new["revisionCreateTime"] = now
        store.revisions.setdefault(w["name"], []).append(_copy(new))
    store.workflows[w["name"]] = new
    return _operation(store, project, location, "update", w["name"], _public(new))


def delete_workflow(store, project, location, wid):
    w = _get(store, project, location, wid)
    name = w["name"]
    del store.workflows[name]
    store.revisions.pop(name, None)
    for en in [n for n in store.executions if n.startswith(name + "/executions/")]:
        del store.executions[en]
    return _operation(store, project, location, "delete", name, {}, "google.protobuf.Empty")


def _page(items, query, key):
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
    out = {key: _copy(items[start:start + size])} if items[start:start + size] else {}
    if start + size < len(items):
        out["nextPageToken"] = base64.urlsafe_b64encode(str(start + size).encode()).decode()
    return out


def list_workflows(store, project, location, query):
    if location != "-" and not _valid_location(location):
        raise _E(404, "NOT_FOUND", "Location '%s' is not a valid location." % location)
    pre = "projects/%s/locations/%s/workflows/" % (project, location)
    ws = [w for n, w in store.workflows.items()
          if n.startswith(pre) or (location == "-" and n.startswith("projects/%s/locations/" % project))]
    order = (query.get("orderBy") or "name").strip()
    field_, desc = (order.split()[0], order.endswith(" desc"))
    if field_ not in ("name", "createTime", "updateTime"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid orderBy '%s': supported fields are name, createTime, updateTime." % order)
    ws.sort(key=lambda w: w[field_], reverse=desc)
    flt = (query.get("filter") or "").strip()
    m = re.match(r"^state\s*=\s*(\w+)$", flt)
    if m:
        ws = [w for w in ws if w["state"] == m.group(1)]
    elif flt:
        ws = [w for w in ws if flt in w["name"] or flt in (w.get("description") or "")]
    return _page(ws, query, "workflows")


def list_revisions(store, project, location, wid, query):
    w = _get(store, project, location, wid)
    revs = list(reversed(store.revisions.get(w["name"], [])))   # newest first
    return _page(revs, query, "workflows")


# ── executions (workflowexecutions v1) ─────────────────────────────────────
EXEC_ACTIVE, EXEC_SUCCEEDED, EXEC_FAILED, EXEC_CANCELLED = "ACTIVE", "SUCCEEDED", "FAILED", "CANCELLED"


def _literal(text):
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    try:
        return json.loads(t)
    except Exception:
        return t


def evaluate(src, argument):
    """Result of running `src` with `argument` (JSON text or None): the workflow's last
    top-level `return:` — a literal, or `${var}` resolved from a literal `assign` — else the
    argument echoed back. Returns (result_json_text, error_dict_or_None)."""
    if src.strip().startswith("{"):
        return json.dumps(argument if argument is None else _try_json(argument)), None
    assigns = {}
    for m in re.finditer(r"^\s*-\s+([A-Za-z_]\w*)\s*:\s*(.+?)\s*$", src, re.M):
        if m.group(1) not in ("init", "done") and not m.group(2).startswith("$"):
            assigns[m.group(1)] = _literal(m.group(2))
    rets = re.findall(r"^\s*return\s*:\s*(.+?)\s*$", src, re.M)
    raises = re.findall(r"^\s*raise\s*:\s*(.+?)\s*$", src, re.M)
    if raises and not rets:
        return None, {"payload": json.dumps(_literal(raises[-1])), "context": "step raise"}
    if rets:
        r = rets[-1]
        m = re.match(r"^\$\{\s*([A-Za-z_]\w*)\s*\}$", r)
        if m and m.group(1) in assigns:
            return json.dumps(assigns[m.group(1)]), None
        if m and m.group(1) == "args":
            return json.dumps(_try_json(argument)), None
        if not r.startswith("$") and not r.startswith(("{", "[")):
            return json.dumps(_literal(r)), None
    return json.dumps(_try_json(argument)), None


def _try_json(arg):
    if arg in (None, ""):
        return None
    try:
        return json.loads(arg)
    except Exception:
        return arg


def create_execution(store, project, location, wid, payload):
    w = _get(store, project, location, wid)
    payload = dict(payload or {})
    arg = payload.get("argument")
    if arg not in (None, ""):
        if not isinstance(arg, str):
            raise _E(400, "INVALID_ARGUMENT", "argument must be a JSON-encoded string.")
        try:
            json.loads(arg)
        except Exception:
            raise _E(400, "INVALID_ARGUMENT", "Invalid execution argument: it must be a valid JSON string.")
    lvl = payload.get("callLogLevel") or "CALL_LOG_LEVEL_UNSPECIFIED"
    if lvl not in CALL_LOG_LEVELS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'execution.call_log_level', \"%s\"" % lvl)
    store.seq["exec"] += 1
    h = hashlib.sha1(("%s%d" % (w["name"], store.seq["exec"])).encode()).hexdigest()
    eid = "%s-%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:32])
    name = "%s/executions/%s" % (w["name"], eid)
    now = _now()
    result, error = evaluate(w["sourceContents"], arg)
    ex = {"name": name, "startTime": _ts(now), "endTime": _ts(now), "duration": "0.001s",
          "state": EXEC_SUCCEEDED if error is None else EXEC_FAILED,
          "workflowRevisionId": w["revisionId"], "callLogLevel": lvl}
    if arg not in (None, ""):
        ex["argument"] = arg
    if error is None:
        ex["result"] = result
    else:
        ex["error"] = error
    ex["status"] = {"currentSteps": []}
    store.executions[name] = ex
    return _copy(ex)


def _get_exec(store, project, location, wid, eid):
    _get(store, project, location, wid)
    name = "%s/executions/%s" % (workflow_name(project, location, wid), eid)
    e = store.executions.get(name)
    if not e:
        raise _E(404, "NOT_FOUND", "Execution %s not found." % name)
    return e


def list_executions(store, project, location, wid, query):
    w = _get(store, project, location, wid)
    pre = w["name"] + "/executions/"
    es = sorted((e for n, e in store.executions.items() if n.startswith(pre)), key=lambda e: e["startTime"], reverse=True)
    return _page(es, query, "executions")


def cancel_execution(store, project, location, wid, eid):
    e = _get_exec(store, project, location, wid, eid)
    if e["state"] != EXEC_ACTIVE:
        raise _E(400, "FAILED_PRECONDITION", "Execution %s is already in a terminal state (%s) and cannot be cancelled." % (e["name"], e["state"]))
    e["state"] = EXEC_CANCELLED
    return _copy(e)


# ── console views ──────────────────────────────────────────────────────────
def workflow_view(w):
    return _copy(w)


def console_view(store, w):
    """Flat row for the console grid / detail: every column filled."""
    parts = w["name"].split("/")
    execs = [e for n, e in store.executions.items() if n.startswith(w["name"] + "/executions/")]
    execs.sort(key=lambda e: e["startTime"])
    last = execs[-1] if execs else None
    labels = w.get("labels") or {}
    envs = w.get("userEnvVars") or {}
    v = workflow_view(w)
    v.update({
        "name": parts[-1], "id": parts[-1], "resourceName": w["name"], "project": parts[1], "region": parts[3],
        "location": parts[3],
        "revision": w["revisionId"],
        "revision_count": len(store.revisions.get(w["name"], [])) or 1,
        "service_account": w.get("serviceAccount") or default_service_account(parts[1]),
        "description_text": w.get("description") or "No description",
        "created": w["createTime"], "updated": w["updateTime"], "revision_created": w["revisionCreateTime"],
        "call_log_level": {"CALL_LOG_LEVEL_UNSPECIFIED": "Not specified", "LOG_ALL_CALLS": "Log all calls",
                           "LOG_ERRORS_ONLY": "Log errors only", "LOG_NONE": "No logging"}[w.get("callLogLevel", CALL_LOG_LEVELS[0])],
        "history_level": {"EXECUTION_HISTORY_LEVEL_UNSPECIFIED": "Not specified", "EXECUTION_HISTORY_BASIC": "Basic",
                          "EXECUTION_HISTORY_DETAILED": "Detailed"}[w.get("executionHistoryLevel", HISTORY_LEVELS[0])],
        "encryption": w.get("cryptoKeyName") or "Google-managed key",
        "labels_text": ", ".join("%s=%s" % kv for kv in sorted(labels.items())) or "None",
        "env_text": ", ".join(sorted(envs)) or "None",
        "source_lines": len(w["sourceContents"].splitlines()),
        "source_language": "JSON" if w["sourceContents"].lstrip().startswith("{") else "YAML",
        "execution_count": len(execs),
        "last_execution": ("%s (%s)" % (last["startTime"], last["state"])) if last else "Has not run yet",
    })
    return v


def view_by_name(store, full):
    return console_view(store, store.workflows[full])


def list_all(store, project=None):
    return [console_view(store, w) for n, w in sorted(store.workflows.items())
            if project is None or n.startswith("projects/%s/" % project)]


def workflow_from_form(b, project="demo"):
    """Console create form (catalog createFields) → create request, shared by the offline
    console REST and the Nano adapter so both consoles create identical workflows."""
    location = str(b.get("region") or "us-central1")
    wf = {"sourceContents": str(b.get("source") or b.get("sourceContents") or DEFAULT_SOURCE)}
    if b.get("description"):
        wf["description"] = str(b["description"])
    if b.get("serviceAccount"):
        wf["serviceAccount"] = str(b["serviceAccount"]).strip()
    if b.get("callLogLevel"):
        wf["callLogLevel"] = str(b["callLogLevel"]).strip()
    return {"parent": "projects/%s/locations/%s" % (project, location), "location": location,
            "workflowId": str(b.get("name") or "").strip(), "workflow": wf}


# ── enum encoding ──────────────────────────────────────────────────────────
# Proto enums are strings on the wire by default, but the Java / Go-gapic REST clients send
# `$alt=json;enum-encoding=int` and expect integers back (and send integers in bodies).
_WF_ENUMS = {
    "state": {ACTIVE: 1, UNAVAILABLE: 2},
    "callLogLevel": {n: i for i, n in enumerate(CALL_LOG_LEVELS)},
    "executionHistoryLevel": {n: i for i, n in enumerate(HISTORY_LEVELS)},
}
_EX_ENUMS = {
    "state": {"STATE_UNSPECIFIED": 0, EXEC_ACTIVE: 1, EXEC_SUCCEEDED: 2, EXEC_FAILED: 3, EXEC_CANCELLED: 4,
              "UNAVAILABLE": 5, "QUEUED": 6},
    "callLogLevel": {n: i for i, n in enumerate(CALL_LOG_LEVELS)},
}


def _enum_walk(o, to_int):
    if isinstance(o, list):
        return [_enum_walk(x, to_int) for x in o]
    if not isinstance(o, dict):
        return o
    o = {k: _enum_walk(v, to_int) for k, v in o.items()}
    table = _EX_ENUMS if ("startTime" in o or "workflowRevisionId" in o) else _WF_ENUMS if "revisionId" in o or "sourceContents" in o else None
    if table:
        for k, m in table.items():
            if k in o:
                if to_int and isinstance(o[k], str) and o[k] in m:
                    o[k] = m[o[k]]
                elif not to_int and isinstance(o[k], int):
                    inv = {v: n for n, v in m.items()}
                    o[k] = inv.get(o[k], o[k])
    return o


def _wants_int_enums(query):
    return "enum-encoding=int" in (query.get("$alt") or query.get("alt") or "").replace("%3D", "=")


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    query = query or {}
    r = _dispatch(store, method, path, query, headers or {}, body)
    if r.status == 200 and _wants_int_enums(query):
        try:
            r.body = json.dumps(_enum_walk(json.loads(r.body), True)).encode()
        except Exception:
            pass
    return r


def _dispatch(store, method, path, query, headers, body):
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
    payload = _enum_walk(payload, False)
    p = path.split("?", 1)[0]
    for pre in ("/v1beta", "/v1"):
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
        if len(segs) >= 5 and segs[4] == "operations":
            return _operations(store, method, project, location, segs[5:], verb)
        if len(segs) < 5 or segs[4] != "workflows":
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        if len(segs) == 5:
            if method == "POST":
                return _json(200, create_workflow(store, project, location, query.get("workflowId", ""), payload))
            if method == "GET":
                return _json(200, list_workflows(store, project, location, query))
            raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on workflows collection." % method)
        wid = segs[5]
        if len(segs) == 6:
            if verb == "listRevisions" and method == "GET":
                return _json(200, list_revisions(store, project, location, wid, query))
            if verb:
                return _err(404, "NOT_FOUND", "Unknown method :%s" % verb)
            if method == "GET":
                return _json(200, workflow_view(_get(store, project, location, wid)))
            if method in ("PATCH", "PUT"):
                return _json(200, patch_workflow(store, project, location, wid, payload, query.get("updateMask") or ""))
            if method == "DELETE":
                return _json(200, delete_workflow(store, project, location, wid))
            raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on workflow." % method)
        if segs[6] != "executions":
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        if len(segs) == 7:
            if method == "POST":
                return _json(200, create_execution(store, project, location, wid, payload))
            if method == "GET":
                return _json(200, list_executions(store, project, location, wid, query))
            raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on executions collection." % method)
        if len(segs) == 8:
            if verb == "cancel" and method == "POST":
                return _json(200, cancel_execution(store, project, location, wid, segs[7]))
            if verb:
                return _err(404, "NOT_FOUND", "Unknown method :%s" % verb)
            if method == "GET":
                return _json(200, _get_exec(store, project, location, wid, segs[7]))
            raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on execution." % method)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _err(404, "NOT_FOUND", "Unknown path: %s" % path)


def _location_view(project, loc):
    return {"name": "projects/%s/locations/%s" % (project, loc), "locationId": loc,
            "displayName": loc, "labels": {"cloud.googleapis.com/region": loc}}


def _operations(store, method, project, location, rest, verb):
    if not rest:
        if method == "GET":
            pre = "projects/%s/locations/%s/operations/" % (project, location)
            ops = [o for n, o in sorted(store.operations.items())
                   if n.startswith(pre) or (location == "-" and n.startswith("projects/%s/locations/" % project))]
            return _json(200, {"operations": _copy(ops)} if ops else {})
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
    name, op = _get_op(store, project, location, rest[0])
    if verb == "cancel" and method == "POST":
        raise _E(400, "FAILED_PRECONDITION", "Operation %s is already done and cannot be cancelled." % name)
    if verb:
        raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
    if method == "GET":
        return _json(200, _copy(op))
    if method == "DELETE":
        del store.operations[name]
        return _json(200, {})
    raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)


def dispatch_operations_chain(dispatchers, method, path, query=None, headers=None, body=b""):
    """`projects/*/locations/*/operations` is one URL family shared by Kubernetes Engine,
    Memorystore and Workflows. `dispatchers` are each service's dispatch callables
    (method, path, query, headers, body); a collection GET merges them all, a single-operation
    request goes to the first one that owns the id."""
    query = query or {}
    p = path.split("?", 1)[0].rstrip("/")
    if method.upper() == "GET" and p.endswith("/operations"):
        ops = []
        for d in dispatchers:
            r = d(method, path, query, headers or {}, body)
            if r.status == 200:
                ops += json.loads(r.body or b"{}").get("operations", [])
        return WorkflowsResponse(status=200, body=json.dumps({"operations": ops} if ops else {}).encode())
    r = None
    for d in dispatchers:
        r = d(method, path, query, headers or {}, body)
        if r.status != 404:
            return r
    return r
