# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Microsoft Defender for Cloud > Workflow automation: `Microsoft.Security/automations` (substrate-free, Pyodide-loadable).

A workflow automation is an ARM resource (resource-group scoped, with a location) that names a TRIGGER (sources:
eventSource + ruleSets of rules over the event's properties) and ACTIONS. This module is the engine behind it:

  * CRUD with the real validation: at least one source, a known eventSource, a known operator, scopes inside this
    subscription, at least one action, each action carrying the fields its actionType requires.
  * Evaluation (core/azure_security_core calls `evaluate` whenever alerts are read or an automation is written): every
    Security alert that Vyomi's detector currently raises is matched against each ENABLED automation whose scope covers the
    alert's resource. Rules inside a ruleSet are AND-ed, ruleSets are OR-ed (as in Azure). One run is recorded per
    (automation, alert, action) - never twice.
  * Delivery per actionType, honestly:
      Workspace -> a row in the chosen Log Analytics workspace's own store, table SecurityAlert (queryable with its KQL engine);
      LogicApp / EventHub -> the simulator has no Logic Apps runtime and no Event Hubs receiver, so the run is recorded as
                              Failed with that reason rather than pretending the workflow ran.
  * Only the Alerts event source is evaluated; the other eventSources (Assessments, SubAssessments, SecureScores,
    RegulatoryComplianceAssessment) are accepted and stored as configuration but never fire.

Vyomi extension: GET .../automations/{name}/vyomiRuns lists the recorded runs (Azure has no equivalent read, the Logic App's own run
history is where a real user looks).
"""
from __future__ import annotations

import datetime
import re

NS = "Microsoft.Security"
TYPE = "microsoft.security/automations"
API_VERSION = "2023-12-01-preview"
EVENT_SOURCES = ("Alerts", "Assessments", "AssessmentsSnapshot", "SubAssessments", "SubAssessmentsSnapshot",
                 "SecureScores", "SecureScoresSnapshot", "SecureScoreControls", "SecureScoreControlsSnapshot",
                 "RegulatoryComplianceAssessment", "RegulatoryComplianceAssessmentSnapshot")
OPERATORS = ("Equals", "GreaterThan", "GreaterThanOrEqualTo", "LesserThan", "LesserThanOrEqualTo", "NotEquals",
             "Contains", "StartsWith", "EndsWith")
ACTION_TYPES = ("LogicApp", "EventHub", "Workspace")
_NAME = re.compile(r"^[A-Za-z0-9._()\-]{1,90}$")
_SEV = {"informational": 0, "low": 1, "medium": 2, "high": 3}


class _E(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ok(body, status=200):
    return {"status": status, "headers": {}, "body": body}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _rid(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NS}/automations/{name}"


def _validate(state, sub, props):
    if not isinstance(props, dict):
        raise _E("InvalidRequestContent", "The request body needs a 'properties' object.")
    scopes = props.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise _E("InvalidRequestContent", "At least one scope is required (properties.scopes[].scopePath).")
    for s in scopes:
        path = str((s or {}).get("scopePath") or "")
        if not re.match(rf"^/subscriptions/{re.escape(sub)}(/resourceGroups/[^/]+)?$", path, re.I):
            raise _E("InvalidScope", f"scopePath '{path}' must be this subscription or a resource group in it.")
    sources = props.get("sources")
    if not isinstance(sources, list) or not sources:
        raise _E("InvalidRequestContent", "At least one source is required (properties.sources[].eventSource).")
    for src in sources:
        es = (src or {}).get("eventSource")
        if es not in EVENT_SOURCES:
            raise _E("InvalidRequestContent", f"eventSource '{es}' is not valid. Valid: {', '.join(EVENT_SOURCES)}.")
        for rs in (src.get("ruleSets") or []):
            for r in (rs or {}).get("rules") or []:
                if not r.get("propertyJPath") or r.get("operator") not in OPERATORS or "expectedValue" not in r:
                    raise _E("InvalidRequestContent", f"Each rule needs propertyJPath, expectedValue and an operator in: {', '.join(OPERATORS)}.")
    actions = props.get("actions")
    if not isinstance(actions, list) or not actions:
        raise _E("InvalidRequestContent", "At least one action is required (properties.actions[].actionType).")
    for a in actions:
        t = (a or {}).get("actionType")
        if t not in ACTION_TYPES:
            raise _E("InvalidRequestContent", f"actionType '{t}' is not valid. Valid: {', '.join(ACTION_TYPES)}.")
        need = {"LogicApp": ("logicAppResourceId", "uri"), "EventHub": ("eventHubResourceId", "connectionString"),
                "Workspace": ("workspaceResourceId",)}[t]
        miss = [f for f in need if not a.get(f)]
        if miss:
            raise _E("InvalidRequestContent", f"A {t} action needs {', '.join(miss)}.")
        if t == "Workspace":
            ws = state.get(str(a["workspaceResourceId"]).lower())
            if not ws or "operationalinsights/workspaces" not in str(ws.get("_type") or "").lower():
                raise _E("ResourceNotFound", f"The Log Analytics workspace '{a['workspaceResourceId']}' does not exist.", 404)


def _view(rec):
    p = rec["properties"]
    return {"id": rec["id"], "name": rec["name"], "type": "Microsoft.Security/automations", "location": rec.get("location"),
            "tags": rec.get("tags") or {}, "kind": rec.get("kind"), "etag": rec.get("etag"),
            "properties": {"description": p.get("description", ""), "isEnabled": p.get("isEnabled", True),
                           "scopes": p["scopes"], "sources": p["sources"],
                           "actions": [{k: v for k, v in a.items() if k not in ("connectionString",)} for a in p["actions"]]}}


def _autos(state, sub, rg=None):
    return sorted((r for r in state.values() if isinstance(r, dict) and r.get("_type") == TYPE and r.get("_sub") == sub
                   and (rg is None or (r.get("_rg") or "").lower() == rg.lower())), key=lambda r: r["name"].lower())


# ── trigger evaluation ──────────────────────────────────────────────────────────────────
def _value(alert: dict, jpath: str):
    p = alert.get("properties") or {}
    path = re.sub(r"^(properties\.)", "", jpath.strip(), flags=re.I)
    cur = p
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        hit = next((k for k in cur if k.lower() == part.lower()), None)
        if hit is None:
            return None
        cur = cur[hit]
    return cur


def _cmp(actual, op, expected, ptype) -> bool:
    if actual is None:
        return False
    a, e = str(actual), str(expected)
    if op in ("Contains", "StartsWith", "EndsWith"):
        a, e = a.lower(), e.lower()
        return e in a if op == "Contains" else a.startswith(e) if op == "StartsWith" else a.endswith(e)
    if str(ptype or "String").lower() in ("integer", "number"):
        try:
            x, y = float(a), float(e)
        except ValueError:
            return False
    elif a.lower() in _SEV and e.lower() in _SEV and op not in ("Equals", "NotEquals"):
        x, y = _SEV[a.lower()], _SEV[e.lower()]
    else:
        x, y = a.lower(), e.lower()
    return {"Equals": x == y, "NotEquals": x != y, "GreaterThan": x > y, "GreaterThanOrEqualTo": x >= y,
            "LesserThan": x < y, "LesserThanOrEqualTo": x <= y}[op]


def matches(props: dict, alert: dict) -> bool:
    """Does an enabled automation's scope + Alerts source fire for this alert?"""
    rid = str((alert.get("properties") or {}).get("compromisedEntity") or alert.get("id") or "").lower()
    alert_id = str(alert.get("id") or "").lower()
    if not any(alert_id.startswith(str(s["scopePath"]).lower()) or rid.startswith(str(s["scopePath"]).lower()) for s in props["scopes"]):
        return False
    for src in props["sources"]:
        if src.get("eventSource") != "Alerts":
            continue
        sets = src.get("ruleSets") or []
        if not sets:
            return True                    # no rules = every alert
        if any(all(_cmp(_value(alert, r["propertyJPath"]), r["operator"], r["expectedValue"], r.get("propertyType"))
                   for r in (rs.get("rules") or [])) for rs in sets):
            return True
    return False


def _deliver(state, action: dict, alert: dict):
    """-> (status, error)."""
    t = action["actionType"]
    if t == "Workspace":
        try:
            from core import azure_diag_pipeline as dp
        except ImportError:          # pragma: no cover - Pyodide flat layout
            import azure_diag_pipeline as dp  # type: ignore
        p = alert["properties"]
        row = {"TimeGenerated": _now(), "AlertName": p["alertDisplayName"], "AlertType": p["alertType"], "AlertSeverity": p["severity"],
               "Status": p["status"], "CompromisedEntity": p["compromisedEntity"], "SystemAlertId": p["systemAlertId"],
               "VendorName": p["vendorName"], "ProductName": p["productName"], "Description": p["description"]}
        err = dp._deliver_workspace(state, action["workspaceResourceId"], "SecurityAlert", row)
        return ("Failed", err) if err else ("Succeeded", "")
    what = "Logic Apps runtime" if t == "LogicApp" else "Event Hubs receiver"
    return "Failed", f"The simulator has no {what}; the trigger fired but nothing was delivered."


def evaluate(state: dict, sub: str, alerts: list) -> int:
    """Run every enabled automation over `alerts` (Security alert views). Idempotent. -> new runs recorded."""
    n = 0
    for rec in _autos(state, sub):
        p = rec["properties"]
        if not p.get("isEnabled", True):
            continue
        runs = rec.setdefault("_runs", [])
        done = {(r["alertId"], r["actionIndex"]) for r in runs}
        for al in alerts:
            if not matches(p, al):
                continue
            for i, act in enumerate(p["actions"]):
                if (al["name"], i) in done:
                    continue
                status, error = _deliver(state, act, al)
                runs.append({"time": _now(), "alertId": al["name"], "alertDisplayName": al["properties"]["alertDisplayName"],
                             "actionIndex": i, "actionType": act["actionType"], "status": status, "error": error})
                n += 1
        del runs[:-500]
    return n


# ── ARM dispatch ────────────────────────────────────────────────────────────────────────
def dispatch(state: dict, method: str, sub: str, rg, rest: list, payload: dict, alerts_fn):
    """`rest` = segments after providers/Microsoft.Security/automations."""
    try:
        if not rest:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Use PUT .../resourceGroups/{rg}/providers/Microsoft.Security/automations/{name}.")
            evaluate(state, sub, alerts_fn())
            return _ok({"value": [_view(r) for r in _autos(state, sub, rg)]})
        name = rest[0]
        if rg is None:
            return _err(400, "BadRequest", "Workflow automations live in a resource group.")
        key = _rid(sub, rg, name).lower()
        rec = state.get(key)
        if len(rest) == 2 and rest[1].lower() == "vyomiruns":
            if rec is None:
                return _err(404, "ResourceNotFound", f"Automation '{name}' was not found.")
            evaluate(state, sub, alerts_fn())
            return _ok({"value": list(reversed(rec.get("_runs") or []))})
        if len(rest) == 2 and rest[1].lower() == "validate" and method == "POST":
            try:
                _validate(state, sub, (payload or {}).get("properties"))
            except _E as e:
                return _err(e.status, e.code, e.message)
            return _ok({"isValid": True, "message": "The automation is valid."})
        if len(rest) != 1:
            return _err(404, "NotFound", "Unknown automations sub-resource.")
        if method == "GET":
            if rec is None:
                return _err(404, "ResourceNotFound", f"The automation '{name}' was not found.")
            return _ok(_view(rec))
        if method in ("PUT", "PATCH"):
            if not _NAME.match(name):
                return _err(400, "InvalidResourceName", "Names may use letters, digits and . _ ( ) - (max 90).")
            body = payload or {}
            if rec is None and not body.get("location"):
                return _err(400, "LocationRequired", "The location is required.")
            old = (rec or {}).get("properties") or {}
            merged = {**old, **(body.get("properties") or {})}
            _validate(state, sub, merged)
            new = {"id": _rid(sub, rg, name), "name": name, "location": body.get("location") or (rec or {}).get("location"),
                   "tags": body.get("tags", (rec or {}).get("tags") or {}), "kind": body.get("kind") or (rec or {}).get("kind"),
                   "etag": f'"{abs(hash(_now())) % 10**12}"', "properties": merged, "_type": TYPE, "_sub": sub, "_rg": rg,
                   "_runs": (rec or {}).get("_runs") or []}
            state[key] = new
            evaluate(state, sub, alerts_fn())
            return _ok(_view(new), 200 if rec else 201)
        if method == "DELETE":
            return _ok(None, 200 if state.pop(key, None) is not None else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    except _E as e:
        return _err(e.status, e.code, e.message)
