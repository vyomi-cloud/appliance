# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Vyomi Marketplace for Azure (Nano / dev_server / unified-ingress core).

Vyomi publishes its OWN catalog of SaaS-simulator "spaces" (decision: V4-GAP-BACKENDS-DECISIONS #8) -- there is no
third-party publisher, billing or identity. Two surfaces:

* Catalog: ``GET {sub}/providers/Microsoft.Marketplace/offers[?category=&search=][/{offerId}]`` and ``.../categories`` --
  offers carry publisher, category, plans (all $0 -- nothing is ever billed) and the Azure services they integrate with.
* Subscriptions: ``Microsoft.SaaS/resources`` (the real ARM type a SaaS offer creates), ``PUT/GET/PATCH/DELETE
  {rg}/providers/Microsoft.SaaS/resources/{name}`` -- name rule, offer + plan existence, ``termId`` of a plan, one active
  subscription per (resource group, offer, plan-name) pair, plan change by PATCH, ``listAccessInfo`` (space id + generated API
  key, rotated by ``regenerateAccessKey``), unsubscribe by DELETE. The subscription is a normal ARM resource: it shows up in the
  resource group, activity log, tags, locks, cost (listed at $0) and Resource Graph.

NOT modelled: the vendors' own service APIs (a "Datadog" space does not ingest metrics, a "Stripe" space does not take charges) --
the offers register the integration point, credentials and lifecycle; the third-party data plane is a separate wave. No private
offers, no publisher portal, no marketplace billing.

Pure python, no framework imports. Functions return ``{"status": int, "body": ...}``.
"""
from __future__ import annotations

import datetime
import re
import secrets
import uuid

PUBLISHER = "vyomi"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,62}[A-Za-z0-9]$|^[A-Za-z0-9]$")


def _plan(pid, name, desc="Free in Vyomi -- nothing is billed."):
    return {"planId": pid, "displayName": name, "description": desc, "price": {"currency": "USD", "amount": 0.0}, "termId": f"{pid}-monthly"}


OFFERS = [
    {"offerId": "vyomi-stripe-space", "displayName": "Stripe payments space", "category": "Payments", "integratesWith": ["functionapp", "apim", "servicebus"],
     "summary": "Test-mode payments, customers and webhooks for building checkout flows against Azure compute.", "plans": [_plan("sandbox", "Sandbox"), _plan("team", "Team")]},
    {"offerId": "vyomi-auth0-space", "displayName": "Auth0 identity space", "category": "Identity", "integratesWith": ["appservices", "apim", "entra"],
     "summary": "OIDC tenants, users and tokens to put in front of App Service and API Management.", "plans": [_plan("sandbox", "Sandbox"), _plan("team", "Team")]},
    {"offerId": "vyomi-datadog-space", "displayName": "Datadog observability space", "category": "Observability", "integratesWith": ["monitor", "loganalytics", "aks"],
     "summary": "Metrics, logs and monitors fed from Azure Monitor diagnostic settings.", "plans": [_plan("sandbox", "Sandbox")]},
    {"offerId": "vyomi-twilio-space", "displayName": "Twilio messaging space", "category": "Messaging", "integratesWith": ["functionapp", "eventgrid"],
     "summary": "SMS and voice sandbox numbers triggered from Functions and Event Grid.", "plans": [_plan("sandbox", "Sandbox")]},
    {"offerId": "vyomi-sendgrid-space", "displayName": "SendGrid email space", "category": "Messaging", "integratesWith": ["functionapp", "servicebus"],
     "summary": "A capture-only mail relay: every message is kept for inspection, none leaves the machine.", "plans": [_plan("sandbox", "Sandbox")]},
    {"offerId": "vyomi-mongodb-space", "displayName": "MongoDB Atlas space", "category": "Databases", "integratesWith": ["aks", "appservices", "cosmos"],
     "summary": "Atlas-style clusters and connection strings for apps that also use Cosmos DB for MongoDB.", "plans": [_plan("sandbox", "Sandbox"), _plan("team", "Team")]},
    {"offerId": "vyomi-elastic-space", "displayName": "Elastic search space", "category": "Storage", "integratesWith": ["storage", "aks", "loganalytics"],
     "summary": "Elastic-compatible indices for log and document search over Blob data.", "plans": [_plan("sandbox", "Sandbox")]},
    {"offerId": "vyomi-confluent-space", "displayName": "Confluent Kafka space", "category": "Messaging", "integratesWith": ["aks", "eventgrid", "servicebus"],
     "summary": "Kafka topics with Schema Registry for event-driven apps on AKS and Functions.", "plans": [_plan("sandbox", "Sandbox")]},
    {"offerId": "vyomi-cloudian-space", "displayName": "Cloudian S3-compatible store space", "category": "Storage", "integratesWith": ["storage"],
     "summary": "A second S3-compatible object store to practise migrating to and from Blob storage.", "plans": [_plan("sandbox", "Sandbox")]},
    {"offerId": "vyomi-pagerduty-space", "displayName": "PagerDuty incident space", "category": "Observability", "integratesWith": ["monitor"],
     "summary": "Incident routing target for Azure Monitor action groups (webhook receivers).", "plans": [_plan("sandbox", "Sandbox")]},
]
for _o in OFFERS:
    _o.update({"publisherId": PUBLISHER, "publisherDisplayName": "Vyomi", "type": "SaaS", "pricing": "Free"})
BY_ID = {o["offerId"]: o for o in OFFERS}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "body": body}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def handles_catalog(namespace):
    return namespace.lower() == "microsoft.marketplace"


def handles_saas(namespace):
    return namespace.lower() == "microsoft.saas"


def catalog(chain, query):
    if chain and chain[0].lower() == "categories":
        cats = sorted({o["category"] for o in OFFERS})
        return _ok({"value": [{"name": c, "count": sum(1 for o in OFFERS if o["category"] == c)} for c in cats]})
    if not chain or chain[0].lower() != "offers":
        return _err(404, "ResourceNotFound", "Unknown Microsoft.Marketplace collection.")
    if len(chain) == 2:
        o = BY_ID.get(chain[1])
        return _ok(o) if o else _err(404, "OfferNotFound", f"The offer '{chain[1]}' does not exist in the Vyomi Marketplace.")
    cat = (query.get("category") or "").lower()
    q = (query.get("search") or query.get("$search") or "").lower()
    rows = [o for o in OFFERS if (not cat or o["category"].lower() == cat)
            and (not q or q in o["displayName"].lower() or q in o["summary"].lower() or q in o["offerId"])]
    return _ok({"value": rows})


def _rec_of(state, sub, rg):
    return [r for r in state.values() if isinstance(r, dict) and str(r.get("_type", "")).lower() == "microsoft.saas/resources"
            and r.get("_sub") == sub and (rg is None or str(r.get("_rg", "")).lower() == rg.lower())]


def saas_dispatch(state, method, sub, rg, chain, payload):
    if not chain or chain[0].lower() != "resources":
        return _err(404, "ResourceNotFound", "Unknown Microsoft.SaaS resource type.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(r) for r in _rec_of(state, sub, rg)]})
    name = chain[1]
    rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.SaaS/resources/{name}" if rg else f"/subscriptions/{sub}/providers/Microsoft.SaaS/resources/{name}"
    rec = state.get(rid.lower())
    if len(chain) == 3 and method == "POST" and rec is not None:
        if chain[2].lower() == "listaccessinfo":
            return _ok({"spaceId": rec["properties"]["spaceId"], "accessKey": rec["_key"], "offerId": rec["properties"]["offerId"]})
        if chain[2].lower() == "regenerateaccesskey":
            rec["_key"] = secrets.token_hex(24)
            return _ok({"spaceId": rec["properties"]["spaceId"], "accessKey": rec["_key"], "offerId": rec["properties"]["offerId"]})
    if len(chain) > 2:
        return _err(404, "ResourceNotFound", f"Unknown SaaS operation '{chain[2]}'." if rec else f"The SaaS resource '{name}' was not found.")
    if method == "GET":
        return _ok(_view(rec)) if rec else _err(404, "ResourceNotFound", f"The Resource 'Microsoft.SaaS/resources/{name}' under resource group '{rg}' was not found.")
    if method in ("PUT", "PATCH"):
        p = (payload or {}).get("properties") or {}
        if rec is None:
            if method == "PATCH":
                return _err(404, "ResourceNotFound", f"The SaaS resource '{name}' was not found.")
            if not NAME_RE.match(name):
                return _err(400, "InvalidResourceName", "SaaS resource names are 1-64 characters: letters, digits, '-', '_' and '.'.")
            if rg is None:
                return _err(400, "InvalidRequestContent", "A SaaS resource must be created in a resource group.")
            o = BY_ID.get(p.get("offerId"))
            if o is None:
                return _err(400, "OfferNotFound", f"The offer '{p.get('offerId')}' does not exist in the Vyomi Marketplace.")
            if p.get("publisherId", PUBLISHER) != PUBLISHER:
                return _err(400, "InvalidPublisher", "Only the Vyomi publisher is available.")
            plan = next((x for x in o["plans"] if x["planId"] == p.get("planId")), None)
            if plan is None:
                return _err(400, "PlanNotFound", f"The offer '{o['offerId']}' has no plan '{p.get('planId')}'. Plans: {', '.join(x['planId'] for x in o['plans'])}.")
            if p.get("termId") not in (None, plan["termId"]):
                return _err(400, "InvalidTerm", f"termId must be '{plan['termId']}'.")
            if any(r["properties"]["offerId"] == o["offerId"] for r in _rec_of(state, sub, rg)):
                return _err(409, "SubscriptionAlreadyExists", f"This resource group already has an active subscription to '{o['displayName']}'.")
            rec = {"id": rid, "name": name, "type": "Microsoft.SaaS/resources", "location": (payload or {}).get("location") or "global",
                   "tags": (payload or {}).get("tags") or {},
                   "properties": {"publisherId": PUBLISHER, "offerId": o["offerId"], "offerDisplayName": o["displayName"], "planId": plan["planId"],
                                  "termId": plan["termId"], "quantity": 1, "saasResourceName": name, "status": "Subscribed",
                                  "paymentChannelType": "None", "billingStatus": "Free", "spaceId": f"vsp-{uuid.uuid4().hex[:12]}",
                                  "subscribeTime": _now(), "provisioningState": "Succeeded", "integratesWith": o["integratesWith"]},
                   "systemData": {"createdAt": _now(), "lastModifiedAt": _now()},
                   "_type": "microsoft.saas/resources", "_sub": sub, "_rg": rg, "_created": _now(), "_key": secrets.token_hex(24)}
            state[rid.lower()] = rec
            return _ok(_view(rec), 201)
        if "planId" in p and p["planId"] != rec["properties"]["planId"]:
            o = BY_ID[rec["properties"]["offerId"]]
            plan = next((x for x in o["plans"] if x["planId"] == p["planId"]), None)
            if plan is None:
                return _err(400, "PlanNotFound", f"The offer '{o['offerId']}' has no plan '{p['planId']}'.")
            rec["properties"].update({"planId": plan["planId"], "termId": plan["termId"]})
        if "offerId" in p and p["offerId"] != rec["properties"]["offerId"]:
            return _err(400, "OfferChangeNotAllowed", "The offer of an existing subscription cannot be changed.")
        if isinstance((payload or {}).get("tags"), dict):
            rec["tags"] = payload["tags"]
        rec["systemData"]["lastModifiedAt"] = _now()
        return _ok(_view(rec))
    if method == "DELETE":
        if rec is None:
            return {"status": 204, "body": None}
        state.pop(rid.lower())
        return _ok(None)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")
