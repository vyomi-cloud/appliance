# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""IAM management-event history for GCP and Azure (and the common view over AWS CloudTrail), pure Python, Pyodide-safe.

The cores record one event per IAM-relevant call they serve (gcp_iam_core.dispatch, gcp_iamcredentials / STS exchange, azure_arm_core.handle
for Microsoft.Authorization / Microsoft.ManagedIdentity, azure_iam_core.dispatch, the PIM routes). Each event keeps the cloud-native fields and
renders in the native shape:

  GCP    Cloud Audit Logs `LogEntry` with a `protoPayload` of type google.cloud.audit.AuditLog (serviceName, methodName, resourceName,
         authenticationInfo.principalEmail, status), logName projects/{p}/logs/cloudaudit.googleapis.com%2Factivity | %2Fdata_access
  Azure  Activity Log event (Microsoft.Insights/eventtypes/management): operationName, caller, status, resourceId, authorization, properties
  AWS    CloudTrail event (core/cloudtrail_events_core.py owns that ring; `normalize_cloudtrail` maps it to the common record)

Common record: {id, ts, time, cloud, service, name, principal, resource, readOnly, outcome (success|denied|error), errorCode, message, origin, native}.
Gate denials (core/iam_engine/audit.py decision ring) are merged by the API as `outcome=denied` events, exactly what CloudTrail
(errorCode AccessDenied), Cloud Audit Logs (status.code 7) and the Activity Log (Failed) show for a refused call.

Honest scope: a bounded in-memory ring (CAP events), process/context-local and not persisted (like the decision ring and the CloudTrail ring);
Nano keeps one per Pyodide context, so calls served by the relay worker (SDK / CLI) are in the worker's ring, console actions in the page's."""
from __future__ import annotations

import base64
import contextvars
import json
import threading
import time
import uuid

CAP = 5000
CALLER = contextvars.ContextVar("iam_event_caller_headers", default=None)   # the host sets the request headers so a core that never sees them can still name the caller
_lock = threading.Lock()
_ring: list = []
_seq = [0]


def _iso(ts, ms=False):
    base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))
    return base + (".%03dZ" % int((ts % 1) * 1000) if ms else "Z")


def principal_from_headers(cloud, headers):
    """Best-effort caller of a request: x-cloudlearn-principal, else the bearer token's email / appid / oid / sub claim, else the project /
    subscription owner (the simulator's unidentified caller)."""
    h = {str(k).lower(): str(v) for k, v in ((headers if headers else CALLER.get()) or {}).items()}
    if h.get("x-cloudlearn-principal"):
        return h["x-cloudlearn-principal"]
    auth = h.get("authorization", "")
    if auth.lower().startswith("bearer "):
        parts = auth.split(None, 1)[1].strip().split(".")
        if len(parts) == 3:
            try:
                c = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
                for k in ("email", "upn", "preferred_username", "appid", "azp", "oid", "sub"):
                    if c.get(k):
                        return str(c[k])
            except Exception:
                pass
    return "owner (unidentified caller)"


def record(cloud, service, name, principal="", resource="", outcome="success", error_code="", message="", read_only=False,
           params=None, origin="api", **extra):
    now = time.time()
    with _lock:
        _seq[0] += 1
        rec = {"id": f"{_seq[0]}-{uuid.uuid4().hex[:8]}", "seq": _seq[0], "ts": now, "time": _iso(now, True), "cloud": cloud, "service": service,
               "name": name, "principal": principal or "", "resource": resource or "", "readOnly": bool(read_only), "outcome": outcome,
               "errorCode": error_code or "", "message": message or "", "origin": origin, "params": params or {}}
        rec.update(extra)
        _ring.append(rec)
        if len(_ring) > CAP:
            del _ring[: len(_ring) - CAP]
    return rec


def clear():
    with _lock:
        _ring.clear()


def snapshot():
    with _lock:
        return list(_ring)


# ------------------------------------------------------------------ query
def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_time(v):
    if v in (None, ""):
        return None
    f = _num(v)
    if f is not None:
        return f
    import calendar
    import re
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)", str(v))
    return float(calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0))) if m else None


def matches(ev, q):
    """Filters shared by every cloud's events API: name (substring, case-insensitive), principal, resource, service, outcome, readOnly, q (any
    field), start / end (epoch seconds or ISO)."""
    def has(field, want):
        return not want or str(want).lower() in str(ev.get(field, "")).lower()
    if not (has("name", q.get("name")) and has("principal", q.get("principal")) and has("resource", q.get("resource"))):
        return False
    if q.get("service") and str(ev.get("service", "")).lower() != str(q["service"]).lower():
        return False
    if q.get("outcome") and ev.get("outcome") != q["outcome"]:
        return False
    ro = q.get("readOnly")
    if ro not in (None, "") and bool(ev.get("readOnly")) != (str(ro).lower() in ("true", "1", "yes")):
        return False
    t0, t1 = _parse_time(q.get("start")), _parse_time(q.get("end"))
    if (t0 is not None and ev["ts"] < t0) or (t1 is not None and ev["ts"] > t1):
        return False
    if q.get("q"):
        blob = json.dumps({k: v for k, v in ev.items() if k != "native"}, default=str).lower()
        if str(q["q"]).lower() not in blob:
            return False
    return True


def query(events, q, limit=100, offset=0):
    rows = sorted((e for e in events if matches(e, q or {})), key=lambda e: e["ts"], reverse=True)
    return rows[offset: offset + limit], len(rows)


def export_csv(events):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "cloud", "service", "name", "principal", "resource", "outcome", "errorCode", "readOnly", "origin", "message"])
    for e in events:
        w.writerow([e.get("time"), e.get("cloud"), e.get("service"), e.get("name"), e.get("principal"), e.get("resource"), e.get("outcome"),
                    e.get("errorCode"), "true" if e.get("readOnly") else "false", e.get("origin"), e.get("message")])
    return buf.getvalue()


# ------------------------------------------------------------------ native shapes
_GCP_STATUS = {"success": 0, "denied": 7, "error": 3}
_GCP_CODE = {"success": "OK", "denied": "PERMISSION_DENIED", "error": "INVALID_ARGUMENT"}


def to_gcp_audit(ev):
    """Cloud Audit Logs LogEntry (Admin Activity for writes, Data Access for reads)."""
    project = ""
    res = ev.get("resource") or ""
    if "projects/" in res:
        project = res.split("projects/", 1)[1].split("/", 1)[0]
    log = "data_access" if ev.get("readOnly") else "activity"
    payload = {"@type": "type.googleapis.com/google.cloud.audit.AuditLog", "serviceName": ev.get("serviceName") or "iam.googleapis.com",
               "methodName": ev.get("methodName") or ev.get("name"), "resourceName": res,
               "authenticationInfo": {"principalEmail": ev.get("principal", "")},
               "authorizationInfo": [{"resource": res, "permission": p, "granted": ev.get("outcome") == "success"} for p in ev.get("permissions") or []],
               "requestMetadata": {"callerIp": ev.get("sourceIp") or "127.0.0.1", "callerSuppliedUserAgent": ev.get("userAgent") or ""},
               "request": ev.get("params") or {}}
    if ev.get("outcome") != "success":
        payload["status"] = {"code": _GCP_STATUS.get(ev.get("outcome"), 2), "message": ev.get("message") or _GCP_CODE.get(ev.get("outcome"), "")}
    return {"logName": f"projects/{project or '-'}/logs/cloudaudit.googleapis.com%2F{log}", "insertId": ev["id"], "timestamp": _iso(ev["ts"], True),
            "receiveTimestamp": _iso(ev["ts"], True), "severity": "ERROR" if ev.get("outcome") != "success" else ("INFO" if not ev.get("readOnly") else "DEFAULT"),
            "resource": {"type": ev.get("resourceType") or "service_account", "labels": {"project_id": project}},
            "protoPayload": payload, "operation": {"id": ev["id"], "producer": payload["serviceName"], "first": True, "last": True}}


def to_azure_activity(ev):
    """Activity Log (Microsoft.Insights/eventtypes/management) event."""
    status = {"success": "Succeeded", "denied": "Failed", "error": "Failed"}.get(ev.get("outcome"), "Succeeded")
    op = ev.get("name") or ""
    return {"authorization": {"action": op, "scope": ev.get("resource") or ""}, "caller": ev.get("principal") or "", "channels": "Operation",
            "claims": {}, "correlationId": ev["id"], "description": ev.get("message") or "", "eventDataId": ev["id"],
            "eventName": {"value": "EndRequest", "localizedValue": "End request"}, "category": {"value": "Administrative", "localizedValue": "Administrative"},
            "eventTimestamp": _iso(ev["ts"], True), "id": f"{ev.get('resource') or ''}/events/{ev['id']}/ticks/{int(ev['ts'] * 1e7)}", "level": "Informational" if status == "Succeeded" else "Error",
            "operationId": ev["id"], "operationName": {"value": op, "localizedValue": op}, "resourceGroupName": "", "resourceProviderName": {"value": op.split("/", 1)[0]},
            "resourceType": {"value": "/".join(op.split("/")[:-1])}, "resourceId": ev.get("resource") or "",
            "status": {"value": status, "localizedValue": status}, "subStatus": {"value": ev.get("errorCode") or "", "localizedValue": ev.get("errorCode") or ""},
            "submissionTimestamp": _iso(ev["ts"], True), "subscriptionId": "00000000-0000-0000-0000-cloudlearn01", "tenantId": "", "properties": {"statusCode": ev.get("errorCode") or "OK"}}


def normalize_cloudtrail(ct):
    """A core/cloudtrail_events_core.py event -> the common record (native = the CloudTrail event as LookupEvents returns it)."""
    try:
        d = json.loads(ct.get("CloudTrailEvent") or "{}")
    except ValueError:
        d = {}
    err = d.get("errorCode") or ""
    ui = d.get("userIdentity") or {}
    return {"id": ct["EventId"], "ts": ct["EventTime"], "time": _iso(ct["EventTime"], False), "cloud": "aws",
            "service": str(ct.get("EventSource", "")).replace(".amazonaws.com", ""), "name": ct["EventName"],
            "principal": ui.get("arn") or ct.get("Username") or "", "resource": ", ".join(r["ResourceName"] for r in ct.get("Resources", [])),
            "readOnly": ct.get("ReadOnly") == "true", "outcome": "denied" if err in ("AccessDenied", "AccessDeniedException") or "Unauthorized" in err else ("error" if err else "success"),
            "errorCode": err, "message": d.get("errorMessage", ""), "origin": "cloudtrail", "params": d.get("requestParameters") or {}, "native": ct}


def from_decision(rec):
    """A decision-ring record (deny / would_deny) -> the common record."""
    cloud = rec.get("cloud")
    action = rec.get("action", "")
    svc = action.split(":", 1)[0] if ":" in action else (action.split(".", 1)[0] if "." in action and cloud == "gcp" else action.split("/", 1)[0])
    outcome = "denied" if rec.get("decision") == "deny" else ("success" if rec.get("decision") == "allow" else "error")
    code = {"aws": "AccessDenied", "gcp": "PERMISSION_DENIED", "azure": "AuthorizationFailed"}.get(cloud, "AccessDenied")
    return {"id": f"d{rec.get('id')}", "ts": rec.get("ts", 0), "time": rec.get("time", ""), "cloud": cloud, "service": svc, "name": action,
            "principal": rec.get("principal", ""), "resource": rec.get("resource", ""), "readOnly": False, "outcome": outcome,
            "errorCode": code if rec.get("decision") in ("deny", "would_deny") else "", "message": f"{rec.get('decision')}: {rec.get('reason', '')}",
            "origin": "decision", "params": {"mode": rec.get("mode"), "matched": rec.get("matched")}, "decision": rec.get("decision")}


# ------------------------------------------------------------------ classifiers (what each core records)
import re as _re

_GCP_RULES = (   # (method, path regex, serviceName, methodName)
    ("POST", r"serviceAccounts$", "iam.googleapis.com", "google.iam.admin.v1.CreateServiceAccount"),
    ("DELETE", r"serviceAccounts/[^/:]+$", "iam.googleapis.com", "google.iam.admin.v1.DeleteServiceAccount"),
    ("PATCH", r"serviceAccounts/[^/:]+$", "iam.googleapis.com", "google.iam.admin.v1.PatchServiceAccount"),
    ("POST", r"serviceAccounts/[^/:]+:(disable|enable)$", "iam.googleapis.com", "google.iam.admin.v1.{Verb}ServiceAccount"),
    ("POST", r"serviceAccounts/[^/:]+/keys$", "iam.googleapis.com", "google.iam.admin.v1.CreateServiceAccountKey"),
    ("DELETE", r"serviceAccounts/[^/:]+/keys/[^/:]+$", "iam.googleapis.com", "google.iam.admin.v1.DeleteServiceAccountKey"),
    ("POST", r"serviceAccounts/[^/:]+/keys/[^/:]+:(disable|enable)$", "iam.googleapis.com", "google.iam.admin.v1.{Verb}ServiceAccountKey"),
    ("POST", r"serviceAccounts/[^/:]+:setIamPolicy$", "iam.googleapis.com", "google.iam.admin.v1.SetIAMPolicy"),
    ("POST", r"roles$", "iam.googleapis.com", "google.iam.admin.v1.CreateRole"),
    ("PATCH", r"roles/[^/:]+$", "iam.googleapis.com", "google.iam.admin.v1.UpdateRole"),
    ("DELETE", r"roles/[^/:]+$", "iam.googleapis.com", "google.iam.admin.v1.DeleteRole"),
    ("POST", r"workloadIdentityPools$", "iam.googleapis.com", "google.iam.v1.WorkloadIdentityPools.CreateWorkloadIdentityPool"),
    ("DELETE", r"workloadIdentityPools/[^/:]+$", "iam.googleapis.com", "google.iam.v1.WorkloadIdentityPools.DeleteWorkloadIdentityPool"),
    ("POST", r"workloadIdentityPools/[^/:]+/providers$", "iam.googleapis.com", "google.iam.v1.WorkloadIdentityPools.CreateWorkloadIdentityPoolProvider"),
    ("DELETE", r"workloadIdentityPools/[^/:]+/providers/[^/:]+$", "iam.googleapis.com", "google.iam.v1.WorkloadIdentityPools.DeleteWorkloadIdentityPoolProvider"),
    ("POST", r"denyPolicies$|policies/[^/]+/denypolicies$", "iam.googleapis.com", "google.iam.v2.Policies.CreatePolicy"),
    ("DELETE", r"denypolicies/[^/:]+$|policies/[^/]+/denypolicies/[^/:]+$", "iam.googleapis.com", "google.iam.v2.Policies.DeletePolicy"),
    ("POST", r"(?:projects|folders|organizations)/[^/:]+:setIamPolicy$", "cloudresourcemanager.googleapis.com", "SetIamPolicy"),
    ("POST", r":setIamPolicy$", "", "SetIamPolicy"),
)


def classify_gcp(method, path):
    """-> (serviceName, methodName, resourceName, readOnly) for a GCP IAM write, or None for a call that is not recorded."""
    p = str(path or "").split("?", 1)[0]
    for pre in ("/v1beta1", "/v1", "/v2", "/v3"):
        if p.startswith(pre + "/"):
            p = p[len(pre):]
            break
    p = p.strip("/")
    for m, rx, svc, name in _GCP_RULES:
        if str(method).upper() == m and _re.search(rx, p):
            mm = _re.search(r":(disable|enable)$", p)
            name = name.replace("{Verb}", mm.group(1).capitalize() if mm else "")
            resource = p.rsplit(":", 1)[0] if ":" in p.rsplit("/", 1)[-1] else p
            if not svc:
                svc = "cloudresourcemanager.googleapis.com" if _re.match(r"^(projects|folders|organizations)/[^/]+$", resource) else f"{resource.split('/')[0]}.googleapis.com"
                name = "SetIamPolicy"
            return svc, name, resource, False
    return None


def record_gcp(method, path, status, headers=None, body=b""):
    if str(method).upper() == "POST" and str(path).split("?", 1)[0].rstrip("/").endswith("/token"):    # sts.googleapis.com /v1/token (RFC 8693)
        try:
            raw = bytes(body).decode("utf-8", "replace")
            d = json.loads(raw) if raw.strip().startswith("{") else dict(x.split("=", 1) for x in raw.split("&") if "=" in x)
        except Exception:
            d = {}
        return record_gcp_call("sts.googleapis.com", "google.identity.sts.v1.SecurityTokenService.ExchangeToken", str(d.get("audience") or ""),
                               "federated subject", status, True, {k: d[k] for k in ("audience", "grantType", "requestedTokenType", "scope") if k in d},
                               message="" if int(status) < 400 else "token exchange rejected")
    c = classify_gcp(method, path)
    if c is None:
        return None
    svc, name, resource, ro = c
    ok = int(status) < 400
    params = {}
    try:
        d = json.loads(bytes(body).decode("utf-8")) if body else {}
        if isinstance(d, dict) and "policy" in d:
            params = {"policy": {"bindings": (d["policy"] or {}).get("bindings", [])}}
    except Exception:
        pass
    return record("gcp", svc.split(".")[0], name.rsplit(".", 1)[-1], principal_from_headers("gcp", headers), resource,
                  "success" if ok else ("denied" if int(status) in (401, 403) else "error"), "" if ok else str(status), "", ro, params,
                  serviceName=svc, methodName=name)


def record_gcp_call(service_name, method_name, resource, principal, status, read_only=True, params=None, message=""):
    """Calls the IAM dispatcher does not carry (STS token exchange, IAM Credentials impersonation)."""
    ok = int(status) < 400
    return record("gcp", service_name.split(".")[0], method_name.rsplit(".", 1)[-1], principal, resource, "success" if ok else "denied", "" if ok else str(status),
                  message, read_only, params, serviceName=service_name, methodName=method_name)


def classify_azure(method, path):
    """-> operationName (Microsoft.Authorization/roleAssignments/write ...) for an Authorization / ManagedIdentity write, else None."""
    m = str(method).upper()
    p = str(path or "").split("?", 1)[0]
    mm = _re.search(r"/providers/(Microsoft\.(?:Authorization|ManagedIdentity))/([A-Za-z]+)(?:/([^/]+))?(?:/([A-Za-z]+))?(?:/([^/]+))?(?:/([A-Za-z]+))?/?$", p, _re.I)
    if not mm or m == "GET":
        return None
    ns, rtype, name, sub, subname, verb = mm.groups()
    if rtype.lower() == "checkaccess":
        return None
    if ns.lower() == "microsoft.managedidentity" and (sub or "").lower() == "federatedidentitycredentials":
        rtype = rtype + "/federatedIdentityCredentials"
    elif sub and not subname and m == "POST":                                  # .../roleAssignmentScheduleRequests/{id}/cancel
        return f"{ns}/{rtype}/{sub}/action"
    suffix = {"PUT": "write", "PATCH": "write", "POST": "action", "DELETE": "delete"}.get(m)
    return f"{ns}/{rtype}/{suffix}" if suffix else None


def record_azure(method, path, status, headers=None, body=b""):
    op = classify_azure(method, path)
    if op is None:
        return None
    ok = int(status) < 400
    params = {}
    try:
        d = json.loads(bytes(body).decode("utf-8")) if body else {}
        p = (d.get("properties") or {}) if isinstance(d, dict) else {}
        params = {k: p[k] for k in ("principalId", "roleDefinitionId", "scope", "requestType", "issuer", "subject") if k in p}
    except Exception:
        pass
    return record("azure", op.split("/")[0], op, principal_from_headers("azure", headers), str(path).split("?", 1)[0],
                  "success" if ok else ("denied" if int(status) in (401, 403) else "error"), "" if ok else str(status), "", False, params)
