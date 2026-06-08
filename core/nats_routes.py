"""Provider-native eventing endpoints, all backed by NATS.

Mirrors ``core/vault_routes.py`` in shape: AWS uses X-Amz-Target dispatch (wired
into ``server.aws_query_root``); GCP + Azure get REST endpoints registered at
module load (before any catch-alls).

Subject convention:
  aws.eventbridge.<busName>.<source>      e.g. aws.eventbridge.default.my.app
  gcp.eventarc.<trigger>                  e.g. gcp.eventarc.on-storage-upload
  azure.eventgrid.<topic>                 e.g. azure.eventgrid.my-topic

Inbox read endpoint (simulator-only, for tooling/conformance):
  GET /__nats/inbox?prefix=aws.eventbridge.default
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import nats_client as nc


# Module-level Eventarc trigger store: (project, location, name) -> trigger dict
_eventarc_triggers: dict[tuple, dict] = {}

# Module-level EventBridge rule store: rule_name -> rule dict
_eventbridge_rules: dict[str, dict] = {}
# Module-level EventBridge rule targets: rule_name -> [target dicts]
_eventbridge_targets: dict[str, list] = {}


# ============================================================================
# AWS EventBridge — JSON-RPC at "/" dispatched by X-Amz-Target
# ============================================================================
def _eventbridge_match_event(rule: dict, event: dict) -> bool:
    """Check if an event matches a rule's EventPattern (simple field matching)."""
    pattern = rule.get("EventPattern")
    if not pattern:
        return False
    if isinstance(pattern, str):
        try:
            pattern = json.loads(pattern)
        except Exception:
            return False
    if not isinstance(pattern, dict):
        return False
    for field, expected_values in pattern.items():
        if not isinstance(expected_values, list):
            expected_values = [expected_values]
        event_value = event.get(field) or event.get(field.replace("-", "_"))
        if event_value is None:
            # Try detail sub-fields for nested patterns
            detail = event.get("detail", {})
            if isinstance(detail, dict):
                event_value = detail.get(field)
        if event_value is None:
            return False
        if event_value not in expected_values:
            return False
    return True


async def _aws_eventbridge_dispatch(target: str, body: dict, space: str) -> dict | None:
    """Return response dict for an EventBridge X-Amz-Target, or None if unhandled."""
    op = target.split(".", 1)[-1]  # "AWSEvents.PutEvents" → "PutEvents"

    if op == "PutEvents":
        entries = body.get("Entries", []) or []
        results = []
        for entry in entries:
            source = entry.get("Source", "default")
            bus = entry.get("EventBusName", "default")
            subject = f"aws.eventbridge.{bus}.{source}"
            payload = {
                "version": "0",
                "id": uuid.uuid4().hex,
                "detail-type": entry.get("DetailType", ""),
                "source": source,
                "account": "000000000000",
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "region": "us-east-1",
                "resources": entry.get("Resources", []),
                "detail": _maybe_parse_json(entry.get("Detail", "{}")),
            }
            nc.publish(subject, payload)
            # Basic pattern matching: check all rules for matches
            for rule_name, rule in _eventbridge_rules.items():
                if rule.get("State") != "ENABLED":
                    continue
                rule_bus = rule.get("EventBusName", "default")
                if rule_bus != bus:
                    continue
                if _eventbridge_match_event(rule, payload):
                    targets = _eventbridge_targets.get(rule_name, [])
                    for tgt in targets:
                        tgt_subject = f"aws.eventbridge.rule.{rule_name}.{tgt.get('Id', 'default')}"
                        nc.publish(tgt_subject, payload)
            results.append({"EventId": payload["id"]})
        return {"Entries": results, "FailedEntryCount": 0}
    if op == "ListEventBuses":
        return {"EventBuses": [{
            "Name": "default",
            "Arn": "arn:aws:events:us-east-1:000000000000:event-bus/default",
            "Description": "Default event bus (simulator-synthesized)",
        }]}
    if op == "PutRule":
        rule_name = body.get("Name", "")
        if not rule_name:
            return {"__type": "ValidationException", "message": "Name is required."}
        rule = {
            "Name": rule_name,
            "Arn": f"arn:aws:events:us-east-1:000000000000:rule/{rule_name}",
            "State": body.get("State", "ENABLED"),
            "EventBusName": body.get("EventBusName", "default"),
            "EventPattern": body.get("EventPattern"),
            "ScheduleExpression": body.get("ScheduleExpression", ""),
            "Description": body.get("Description", ""),
            "CreatedBy": "000000000000",
        }
        _eventbridge_rules[rule_name] = rule
        return {"RuleArn": rule["Arn"]}
    if op == "DeleteRule":
        rule_name = body.get("Name", "")
        removed = _eventbridge_rules.pop(rule_name, None)
        _eventbridge_targets.pop(rule_name, None)
        if not removed:
            return {"__type": "ResourceNotFoundException", "message": f"Rule {rule_name} does not exist."}
        return {}
    if op == "ListRules":
        bus = body.get("EventBusName", "default")
        prefix = body.get("NamePrefix", "")
        rules = []
        for name, rule in _eventbridge_rules.items():
            if rule.get("EventBusName", "default") != bus:
                continue
            if prefix and not name.startswith(prefix):
                continue
            rules.append(rule)
        return {"Rules": rules}
    if op == "DescribeRule":
        rule_name = body.get("Name", "")
        rule = _eventbridge_rules.get(rule_name)
        if not rule:
            return {"__type": "ResourceNotFoundException", "message": f"Rule {rule_name} does not exist."}
        return rule
    if op == "PutTargets":
        rule_name = body.get("Rule", "")
        if rule_name not in _eventbridge_rules:
            return {"__type": "ResourceNotFoundException", "message": f"Rule {rule_name} does not exist."}
        new_targets = body.get("Targets", [])
        existing = _eventbridge_targets.setdefault(rule_name, [])
        existing_ids = {t.get("Id") for t in existing}
        for tgt in new_targets:
            if tgt.get("Id") in existing_ids:
                existing[:] = [t if t.get("Id") != tgt.get("Id") else tgt for t in existing]
            else:
                existing.append(tgt)
        return {"FailedEntryCount": 0, "FailedEntries": []}
    if op == "ListTargetsByRule":
        rule_name = body.get("Rule", "")
        if rule_name not in _eventbridge_rules:
            return {"__type": "ResourceNotFoundException", "message": f"Rule {rule_name} does not exist."}
        return {"Targets": _eventbridge_targets.get(rule_name, [])}
    if op == "RemoveTargets":
        rule_name = body.get("Rule", "")
        if rule_name not in _eventbridge_rules:
            return {"__type": "ResourceNotFoundException", "message": f"Rule {rule_name} does not exist."}
        ids_to_remove = set(body.get("Ids", []))
        existing = _eventbridge_targets.get(rule_name, [])
        _eventbridge_targets[rule_name] = [t for t in existing if t.get("Id") not in ids_to_remove]
        return {"FailedEntryCount": 0, "FailedEntries": []}
    return None


def _maybe_parse_json(s: str | dict) -> Any:
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {"raw": s}


# ============================================================================
# GCP Eventarc — REST under /v1/projects/{p}/...
# ============================================================================
def _register_gcp(app: FastAPI) -> None:
    @app.post("/v1/projects/{project}/locations/{loc}/channels/{channel}:publish")
    async def gcp_eventarc_channel_publish(project: str, loc: str, channel: str, request: Request):
        body = await request.json()
        events = body.get("events", []) or []
        published = 0
        for ev in events:
            subject = f"gcp.eventarc.{channel}"
            payload = {
                "id": ev.get("id") or uuid.uuid4().hex,
                "source": ev.get("source", "//cloudlearn.local"),
                "specversion": ev.get("specversion", "1.0"),
                "type": ev.get("type", "google.cloud.eventarc.event"),
                "time": ev.get("time") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": ev.get("data", {}),
            }
            if nc.publish(subject, payload):
                published += 1
        return {"published": published, "count": len(events)}

    # ── Eventarc Trigger CRUD ──────────────────────────────────────────
    # Stored in a module-level dict keyed by (project, location, trigger_name).
    # These complement the generic gcp_rail_extras CRUD with first-class
    # routes that wire NATS publish + Cloud Function invocation on fire.

    @app.get("/v1/projects/{project}/locations/{loc}/triggers")
    async def gcp_eventarc_list_triggers(project: str, loc: str):
        triggers = []
        for (p, l, n), t in _eventarc_triggers.items():
            if p == project and l == loc:
                triggers.append(t)
        return {"triggers": triggers}

    @app.post("/v1/projects/{project}/locations/{loc}/triggers")
    async def gcp_eventarc_create_trigger(project: str, loc: str, request: Request):
        body = await request.json()
        name = body.get("name") or body.get("triggerId") or f"trigger-{uuid.uuid4().hex[:8]}"
        trigger = {
            "name": f"projects/{project}/locations/{loc}/triggers/{name}",
            "uid": uuid.uuid4().hex,
            "createTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updateTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "eventFilters": body.get("eventFilters", []),
            "destination": body.get("destination", {}),
            "transport": body.get("transport", {}),
            "state": "ACTIVE",
        }
        _eventarc_triggers[(project, loc, name)] = trigger
        return trigger

    @app.get("/v1/projects/{project}/locations/{loc}/triggers/{trigger}")
    async def gcp_eventarc_get_trigger(project: str, loc: str, trigger: str):
        t = _eventarc_triggers.get((project, loc, trigger))
        if not t:
            return JSONResponse(status_code=404, content={
                "error": {"code": 404, "message": f"Trigger '{trigger}' not found", "status": "NOT_FOUND"}})
        return t

    @app.delete("/v1/projects/{project}/locations/{loc}/triggers/{trigger}")
    async def gcp_eventarc_delete_trigger(project: str, loc: str, trigger: str):
        removed = _eventarc_triggers.pop((project, loc, trigger), None)
        if not removed:
            return JSONResponse(status_code=404, content={
                "error": {"code": 404, "message": f"Trigger '{trigger}' not found", "status": "NOT_FOUND"}})
        return {}

    # Convenience: trigger fire (simulator-only — real Eventarc routes via
    # internal mechanisms; the SDK never calls this directly, but ``gcloud
    # eventarc triggers fire-event`` and demo scripts use it).
    @app.post("/v1/projects/{project}/locations/{loc}/triggers/{trigger}:fire")
    async def gcp_eventarc_trigger_fire(project: str, loc: str, trigger: str, request: Request):
        body = await request.json()
        subject = f"gcp.eventarc.{trigger}"
        payload = {
            "id": uuid.uuid4().hex,
            "trigger": f"projects/{project}/locations/{loc}/triggers/{trigger}",
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data": body,
        }
        ok = nc.publish(subject, payload)

        # If the trigger has a Cloud Function destination, invoke it.
        invoked_function = None
        trigger_rec = _eventarc_triggers.get((project, loc, trigger))
        if trigger_rec:
            dest = trigger_rec.get("destination") or {}
            cf_name = dest.get("cloudFunction") or dest.get("cloud_function") or ""
            if cf_name:
                try:
                    from core import gcp_function_runtime
                    result = gcp_function_runtime.execute(
                        "", "main", "python", payload, timeout=30)
                    invoked_function = cf_name
                except Exception:
                    pass

        return {"id": payload["id"], "delivered": ok, "invoked_function": invoked_function}


# ============================================================================
# AWS EventBridge — REST endpoints for rule management
# ============================================================================
def _register_eventbridge_rest(app: FastAPI) -> None:
    @app.put("/api/eventbridge/rules/{rule_name}")
    async def eventbridge_put_rule(rule_name: str, request: Request):
        body = await request.json()
        rule = {
            "Name": rule_name,
            "Arn": f"arn:aws:events:us-east-1:000000000000:rule/{rule_name}",
            "State": body.get("State", "ENABLED"),
            "EventBusName": body.get("EventBusName", "default"),
            "EventPattern": body.get("EventPattern"),
            "ScheduleExpression": body.get("ScheduleExpression", ""),
            "Description": body.get("Description", ""),
            "CreatedBy": "000000000000",
        }
        _eventbridge_rules[rule_name] = rule
        return rule

    @app.get("/api/eventbridge/rules")
    async def eventbridge_list_rules():
        return {"Rules": list(_eventbridge_rules.values())}

    @app.get("/api/eventbridge/rules/{rule_name}")
    async def eventbridge_get_rule(rule_name: str):
        rule = _eventbridge_rules.get(rule_name)
        if not rule:
            return JSONResponse(status_code=404, content={"error": f"Rule {rule_name} not found"})
        return rule

    @app.delete("/api/eventbridge/rules/{rule_name}")
    async def eventbridge_delete_rule(rule_name: str):
        removed = _eventbridge_rules.pop(rule_name, None)
        _eventbridge_targets.pop(rule_name, None)
        if not removed:
            return JSONResponse(status_code=404, content={"error": f"Rule {rule_name} not found"})
        return {"deleted": True, "rule_name": rule_name}

    @app.put("/api/eventbridge/rules/{rule_name}/targets")
    async def eventbridge_put_targets(rule_name: str, request: Request):
        if rule_name not in _eventbridge_rules:
            return JSONResponse(status_code=404, content={"error": f"Rule {rule_name} not found"})
        body = await request.json()
        new_targets = body.get("Targets", [])
        existing = _eventbridge_targets.setdefault(rule_name, [])
        existing_ids = {t.get("Id") for t in existing}
        for tgt in new_targets:
            if tgt.get("Id") in existing_ids:
                existing[:] = [t if t.get("Id") != tgt.get("Id") else tgt for t in existing]
            else:
                existing.append(tgt)
        return {"FailedEntryCount": 0, "FailedEntries": []}

    @app.get("/api/eventbridge/rules/{rule_name}/targets")
    async def eventbridge_list_targets(rule_name: str):
        if rule_name not in _eventbridge_rules:
            return JSONResponse(status_code=404, content={"error": f"Rule {rule_name} not found"})
        return {"Targets": _eventbridge_targets.get(rule_name, [])}


# ============================================================================
# Azure Event Grid — REST under /azure-data/eventgrid/{topic}/...
# ============================================================================
def _register_azure(app: FastAPI) -> None:
    @app.post("/azure-data/eventgrid/{topic}/events")
    async def az_eventgrid_publish(topic: str, request: Request):
        body = await request.json()
        events = body if isinstance(body, list) else [body]
        published = 0
        for ev in events:
            subject = f"azure.eventgrid.{topic}"
            payload = {
                "id": ev.get("id") or uuid.uuid4().hex,
                "topic": ev.get("topic", topic),
                "subject": ev.get("subject", ""),
                "eventType": ev.get("eventType", "Default"),
                "eventTime": ev.get("eventTime") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": ev.get("data", {}),
                "dataVersion": ev.get("dataVersion", "1.0"),
                "metadataVersion": "1",
            }
            if nc.publish(subject, payload):
                published += 1
        # Real Event Grid returns 200 with no body on success.
        return JSONResponse({"published": published, "count": len(events)}, status_code=200)


# ============================================================================
# Inbox read endpoint (simulator-only)
# ============================================================================
def _register_inbox(app: FastAPI) -> None:
    @app.get("/__nats/inbox", include_in_schema=False)
    async def nats_inbox(prefix: str = "", limit: int = 50):
        """Drain (copy, non-destructive) recent NATS messages whose subject
        starts with ``prefix``. Conformance + tooling only — not a real cloud
        surface."""
        return {"messages": nc.get_inbox(subject_prefix=prefix, limit=limit)}

    @app.get("/__nats/status", include_in_schema=False)
    async def nats_status():
        """Tooling: is NATS reachable?"""
        return {"available": nc.available()}


# ============================================================================
# Public
# ============================================================================
def register(app: FastAPI, aws_dispatchers: dict | None = None) -> None:
    _register_eventbridge_rest(app)
    _register_gcp(app)
    _register_azure(app)
    _register_inbox(app)
    if aws_dispatchers is not None:
        # EventBridge X-Amz-Target prefix is "AWSEvents.*"
        aws_dispatchers["AWSEvents"] = _aws_eventbridge_dispatch
