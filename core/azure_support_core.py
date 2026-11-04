"""Azure support requests (Nano / dev_server / unified-ingress core).

``Microsoft.Support`` is the real ARM provider behind every blade's "New support request" and
"Support + Troubleshooting" page (azure-mgmt-support / ``az support tickets``):

    GET  /subscriptions/{sub}/providers/Microsoft.Support/services
    GET  .../services/{serviceId}/problemClassifications
    POST .../checkNameAvailability
    PUT|GET|PATCH .../supportTickets/{name}      (list: GET .../supportTickets)
    PUT|GET|GET-list .../supportTickets/{name}/communications/{c}

Tickets are filed with Vyomi: the support engineer is Vyomi Support, the plan is the Vyomi
community plan, and every new ticket gets a real first outbound communication acknowledging it.
Tickets live in the simulator's own store (``state``); delivery to the Vyomi portal's
SupportTicket queue is a separate hop that is not wired in this core, and the ticket says so in
``properties.vyomiDelivery`` instead of pretending.

Each function returns ``{"status": int, "body": dict | None}``.
"""
from __future__ import annotations

import datetime
import re
import uuid

API_VERSION = "2020-04-01"
SEVERITIES = ("Minimal", "Moderate", "Critical")
STATUSES = ("Open", "Closed")
CONTACT_METHODS = ("Email", "Phone")
SLA_HOURS = {"Minimal": 24, "Moderate": 8, "Critical": 1}
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-()]{1,100}$")

# service key -> (display name, problem classifications)
_COMMON = ["Cannot create or delete the resource", "Configuration or settings question",
           "Performance or availability problem", "Billing or quota question", "Other"]
SERVICES = {
    "General": ("Subscription management", ["Billing", "Quota or limits", "Subscription access", "Other"]),
    "Microsoft.ContainerRegistry": ("Container Registry", _COMMON + ["Image push or pull fails"]),
    "Microsoft.ContainerService": ("Kubernetes Service (AKS)", _COMMON + ["Node pool problem", "kubectl or Run command problem"]),
    "Microsoft.ApiManagement": ("API Management", _COMMON + ["API policy problem"]),
    "Microsoft.AppConfiguration": ("App Configuration", _COMMON),
    "Microsoft.Web": ("App Service and Function Apps", _COMMON + ["Deployment problem", "Custom domain or TLS problem"]),
    "Microsoft.CognitiveServices": ("Azure AI services", _COMMON),
    "Microsoft.DocumentDB": ("Azure Cosmos DB", _COMMON + ["Request unit throttling"]),
    "Microsoft.CostManagement": ("Cost Management", ["Budget or alert problem", "Cost data question", "Other"]),
    "Microsoft.KeyVault": ("Key Vault", _COMMON + ["Access policy or RBAC problem"]),
    "Microsoft.Insights": ("Azure Monitor", _COMMON + ["Alert rule problem", "Missing metrics or logs"]),
    "Microsoft.Network": ("Virtual Network and security groups", _COMMON + ["Connectivity problem"]),
    "Microsoft.Resources": ("Resource groups and deployments", _COMMON + ["Template deployment fails"]),
    "Microsoft.ServiceBus": ("Service Bus", _COMMON),
    "Microsoft.Sql": ("Azure SQL Database", _COMMON + ["Connection problem"]),
    "Microsoft.Storage": ("Storage accounts", _COMMON + ["Blob, queue or table access problem"]),
    "Microsoft.Compute": ("Virtual machines", _COMMON + ["Cannot connect to the VM"]),
    "Microsoft.EventGrid": ("Event Grid", _COMMON),
}
_NS = uuid.UUID("5d6c1b6e-0a4e-4a53-9a3f-6f5a0d3c7e10")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sid(key: str) -> str:
    return str(uuid.uuid5(_NS, key))


def _service_id(key: str) -> str:
    return f"/providers/Microsoft.Support/services/{_sid(key)}"


def _classification_id(key: str, name: str) -> str:
    return f"{_service_id(key)}/problemClassifications/{_sid(key + '/' + name)}"


def _err(status, code, message):
    return {"status": status, "body": {"error": {"code": code, "message": message}}}


def _view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _tickets(state: dict, sub: str):
    return [r for r in state.values() if isinstance(r, dict) and r.get("_support") == "ticket" and r.get("_sub") == sub.lower()]


def _key(sub, name, comm=None):
    k = f"/subscriptions/{sub}/providers/Microsoft.Support/supportTickets/{name}"
    return (k + f"/communications/{comm}" if comm else k).lower()


def find_marker(chain):
    """True if ``chain`` (the path after the namespace) addresses Microsoft.Support."""
    return bool(chain) and chain[0].lower() in ("services", "supporttickets", "checknameavailability")


def list_services():
    return {"status": 200, "body": {"value": [
        {"id": _service_id(k), "name": _sid(k), "type": "Microsoft.Support/services",
         "properties": {"displayName": v[0], "resourceTypes": [k]}} for k, v in SERVICES.items()]}}


def list_classifications(service_id: str):
    for k, v in SERVICES.items():
        if _sid(k) == service_id.lower() or _service_id(k).lower() == service_id.lower():
            return {"status": 200, "body": {"value": [
                {"id": _classification_id(k, c), "name": _sid(k + "/" + c), "type": "Microsoft.Support/problemClassifications",
                 "properties": {"displayName": c}} for c in v[1]]}}
    return _err(404, "ResourceNotFound", f"The service '{service_id}' was not found.")


def _classification_known(cid: str) -> bool:
    cid = (cid or "").lower()
    return any(cid == _classification_id(k, c).lower() for k, v in SERVICES.items() for c in v[1])


def check_name(state: dict, sub: str, payload: dict) -> dict:
    name = (payload or {}).get("name")
    if (payload or {}).get("type") != "Microsoft.Support/supportTickets":
        return _err(400, "InvalidParameter", "type must be 'Microsoft.Support/supportTickets'.")
    if not name or not NAME_RE.match(name):
        return {"status": 200, "body": {"nameAvailable": False, "reason": "Invalid",
                                        "message": "Support ticket names are 1-100 letters, digits, '.', '_', '-' or parentheses."}}
    if _key(sub, name) in state:
        return {"status": 200, "body": {"nameAvailable": False, "reason": "AlreadyExists",
                                        "message": f"A support ticket named '{name}' already exists."}}
    return {"status": 200, "body": {"nameAvailable": True}}


def _validate_contact(c, partial=False):
    if not isinstance(c, dict):
        return "contactDetails is required."
    need = [] if partial else ["firstName", "lastName", "preferredContactMethod", "primaryEmailAddress",
                               "preferredTimeZone", "country", "preferredSupportLanguage"]
    for f in need:
        if not c.get(f):
            return f"contactDetails.{f} is required."
    if c.get("preferredContactMethod") and c["preferredContactMethod"] not in CONTACT_METHODS:
        return "contactDetails.preferredContactMethod must be Email or Phone."
    if "primaryEmailAddress" in c and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", c.get("primaryEmailAddress") or ""):
        return "contactDetails.primaryEmailAddress is not a valid email address."
    if c.get("preferredContactMethod") == "Phone" and not c.get("phoneNumber"):
        return "contactDetails.phoneNumber is required when the preferred contact method is Phone."
    return None


def create(state: dict, sub: str, name: str, payload: dict, resource_exists=None) -> dict:
    if not NAME_RE.match(name or ""):
        return _err(400, "InvalidParameter", "Support ticket names are 1-100 letters, digits, '.', '_', '-' or parentheses.")
    if _key(sub, name) in state:
        return _err(409, "Conflict", f"A support ticket named '{name}' already exists.")
    p = (payload or {}).get("properties") or {}
    for f in ("title", "description", "severity", "problemClassificationId", "serviceId"):
        if not p.get(f):
            return _err(400, "InvalidParameter", f"properties.{f} is required.")
    if p["severity"] not in SEVERITIES:
        return _err(400, "InvalidParameter", "properties.severity must be Minimal, Moderate or Critical.")
    if len(p["title"]) > 200:
        return _err(400, "InvalidParameter", "properties.title is limited to 200 characters.")
    svc = next((k for k in SERVICES if _service_id(k).lower() == p["serviceId"].lower()), None)
    if svc is None:
        return _err(400, "InvalidParameter", f"properties.serviceId '{p['serviceId']}' is not a known service.")
    if not _classification_known(p["problemClassificationId"]) or \
            not p["problemClassificationId"].lower().startswith(_service_id(svc).lower() + "/"):
        return _err(400, "InvalidParameter", "properties.problemClassificationId does not belong to the chosen service.")
    msg = _validate_contact(p.get("contactDetails"))
    if msg:
        return _err(400, "InvalidParameter", msg)
    tech = p.get("technicalTicketDetails") or {}
    if tech.get("resourceId") and resource_exists is not None and not resource_exists(tech["resourceId"]):
        return _err(400, "InvalidParameter", f"technicalTicketDetails.resourceId '{tech['resourceId']}' was not found in this subscription.")
    now = _now()
    n = sum(1 for _ in _tickets(state, sub)) + 1
    ref = f"VYO-{datetime.datetime.now(datetime.timezone.utc):%y%m%d}-{n:04d}"
    due = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=SLA_HOURS[p["severity"]])).strftime("%Y-%m-%dT%H:%M:%SZ")
    rid = f"/subscriptions/{sub}/providers/Microsoft.Support/supportTickets/{name}"
    props = {
        "supportTicketId": ref, "title": p["title"], "description": p["description"], "severity": p["severity"],
        "problemClassificationId": p["problemClassificationId"], "serviceId": p["serviceId"],
        "problemClassificationDisplayName": next(c for c in SERVICES[svc][1] if _classification_id(svc, c).lower() == p["problemClassificationId"].lower()),
        "serviceDisplayName": SERVICES[svc][0],
        "status": "Open", "createdDate": now, "modifiedDate": now,
        "problemStartTime": p.get("problemStartTime") or now,
        "require24X7Response": bool(p.get("require24X7Response", False)),
        "contactDetails": dict(p["contactDetails"]),
        "supportPlanType": "Vyomi Community",
        "supportEngineer": {"emailAddress": "support@vyomi.cloud"},
        "serviceLevelAgreement": {"startTime": now, "expirationTime": due, "slaMinutes": SLA_HOURS[p["severity"]] * 60},
        "advancedDiagnosticConsent": p.get("advancedDiagnosticConsent", "No"),
        "vyomiDelivery": "recorded-locally",
    }
    if tech.get("resourceId"):
        props["technicalTicketDetails"] = {"resourceId": tech["resourceId"]}
    rec = {"id": rid, "name": name, "type": "Microsoft.Support/supportTickets", "properties": props,
           "_support": "ticket", "_sub": sub.lower()}
    state[_key(sub, name)] = rec
    _add_comm(state, sub, name, f"ack-{uuid.uuid4().hex[:8]}", {
        "sender": "Vyomi Support", "subject": f"[{ref}] We received your request",
        "body": f"Your {p['severity'].lower()} request '{p['title']}' was filed with Vyomi Support under reference {ref}. "
                f"First response target: {due}.",
        "communicationDirection": "outbound", "communicationType": "web"})
    return {"status": 200, "body": _view(rec)}


def get(state: dict, sub: str, name: str) -> dict:
    rec = state.get(_key(sub, name))
    if not rec:
        return _err(404, "ResourceNotFound", f"The support ticket '{name}' was not found.")
    return {"status": 200, "body": _view(rec)}


def list_tickets(state: dict, sub: str, query: dict | None = None) -> dict:
    items = sorted(_tickets(state, sub), key=lambda r: r["properties"]["createdDate"], reverse=True)
    flt = (query or {}).get("$filter") or ""
    m = re.search(r"Status\s+eq\s+'(\w+)'", flt, re.I)
    if m:
        items = [r for r in items if r["properties"]["status"].lower() == m.group(1).lower()]
    return {"status": 200, "body": {"value": [_view(r) for r in items]}}


def update(state: dict, sub: str, name: str, payload: dict) -> dict:
    rec = state.get(_key(sub, name))
    if not rec:
        return _err(404, "ResourceNotFound", f"The support ticket '{name}' was not found.")
    p = (payload or {}).get("properties") or payload or {}
    props = rec["properties"]
    if props["status"] == "Closed" and p.get("status") != "Open":
        return _err(409, "Conflict", "A closed support ticket cannot be modified.")
    if "severity" in p:
        if p["severity"] not in SEVERITIES:
            return _err(400, "InvalidParameter", "severity must be Minimal, Moderate or Critical.")
        props["severity"] = p["severity"]
    if "status" in p:
        if p["status"] not in STATUSES:
            return _err(400, "InvalidParameter", "status must be Open or Closed.")
        if p["status"] == "Closed" and props["status"] == "Open":
            _add_comm(state, sub, name, f"closed-{uuid.uuid4().hex[:8]}", {
                "sender": "Vyomi Support", "subject": f"[{props['supportTicketId']}] Request closed",
                "body": "This request was closed.", "communicationDirection": "outbound", "communicationType": "web"})
        props["status"] = p["status"]
    if "contactDetails" in p:
        msg = _validate_contact(p["contactDetails"], partial=True)
        if msg:
            return _err(400, "InvalidParameter", msg)
        props["contactDetails"].update(p["contactDetails"])
    if "advancedDiagnosticConsent" in p:
        props["advancedDiagnosticConsent"] = p["advancedDiagnosticConsent"]
    props["modifiedDate"] = _now()
    return {"status": 200, "body": _view(rec)}


def _add_comm(state, sub, ticket, cname, p):
    rid = f"/subscriptions/{sub}/providers/Microsoft.Support/supportTickets/{ticket}/communications/{cname}"
    rec = {"id": rid, "name": cname, "type": "Microsoft.Support/communications",
           "properties": {"communicationType": p.get("communicationType", "web"),
                          "communicationDirection": p.get("communicationDirection", "inbound"),
                          "sender": p.get("sender", ""), "subject": p.get("subject", ""),
                          "body": p.get("body", ""), "createdDate": _now()},
           "_support": "comm", "_ticket": _key(sub, ticket)}
    state[_key(sub, ticket, cname)] = rec
    return rec


def communications(state: dict, sub: str, ticket: str, method: str, rest: list, payload: dict) -> dict:
    t = state.get(_key(sub, ticket))
    if not t:
        return _err(404, "ResourceNotFound", f"The support ticket '{ticket}' was not found.")
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = sorted((r for r in state.values() if isinstance(r, dict) and r.get("_ticket") == _key(sub, ticket)),
                       key=lambda r: r["properties"]["createdDate"])
        return {"status": 200, "body": {"value": [_view(r) for r in items]}}
    cname = rest[0]
    if method == "GET":
        rec = state.get(_key(sub, ticket, cname))
        return {"status": 200, "body": _view(rec)} if rec else _err(404, "ResourceNotFound", f"Communication '{cname}' was not found.")
    if method == "PUT":
        if _key(sub, ticket, cname) in state:
            return _err(409, "Conflict", f"A communication named '{cname}' already exists.")
        if t["properties"]["status"] == "Closed":
            return _err(409, "Conflict", "Cannot add a communication to a closed support ticket.")
        p = (payload or {}).get("properties") or {}
        if not p.get("subject") or not p.get("body"):
            return _err(400, "InvalidParameter", "properties.subject and properties.body are required.")
        rec = _add_comm(state, sub, ticket, cname, {**p, "communicationDirection": "inbound"})
        t["properties"]["modifiedDate"] = _now()
        return {"status": 200, "body": _view(rec)}
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def dispatch(state: dict, method: str, sub: str, chain: list, payload: dict, query: dict, resource_exists=None) -> dict:
    """``chain`` is everything after ``providers/Microsoft.Support``."""
    head = chain[0].lower()
    if head == "services":
        if method != "GET":
            return _err(405, "MethodNotAllowed", "services supports GET only.")
        if len(chain) == 1:
            return list_services()
        if len(chain) == 3 and chain[2].lower() == "problemclassifications":
            return list_classifications(chain[1])
        return _err(404, "ResourceNotFound", "Unknown services path.")
    if head == "checknameavailability":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "checkNameAvailability supports POST only.")
        return check_name(state, sub, payload)
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return list_tickets(state, sub, query)
    name = chain[1]
    if len(chain) >= 3 and chain[2].lower() == "communications":
        return communications(state, sub, name, method, chain[3:], payload)
    if len(chain) != 2:
        return _err(404, "ResourceNotFound", "Unknown supportTickets path.")
    if method == "PUT":
        return create(state, sub, name, payload, resource_exists)
    if method == "GET":
        return get(state, sub, name)
    if method == "PATCH":
        return update(state, sub, name, payload)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")
