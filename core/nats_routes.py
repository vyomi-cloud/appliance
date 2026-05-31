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


# ============================================================================
# AWS EventBridge — JSON-RPC at "/" dispatched by X-Amz-Target
# ============================================================================
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
            results.append({"EventId": payload["id"]})
        return {"Entries": results, "FailedEntryCount": 0}
    if op == "ListEventBuses":
        # Read-only metadata. Return the well-known 'default' bus; real
        # EventBridge always includes it. (Simulator doesn't track custom
        # buses today — events publish freely to any subject.)
        return {"EventBuses": [{
            "Name": "default",
            "Arn": "arn:aws:events:us-east-1:000000000000:event-bus/default",
            "Description": "Default event bus (simulator-synthesized)",
        }]}
    if op == "ListRules":
        # Empty rule list — real PutRule isn't wired (PutEvents publishes
        # directly to NATS subjects without going through rule matching).
        return {"Rules": []}
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
        return {"id": payload["id"], "delivered": ok}


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
    _register_gcp(app)
    _register_azure(app)
    _register_inbox(app)
    if aws_dispatchers is not None:
        # EventBridge X-Amz-Target prefix is "AWSEvents.*"
        aws_dispatchers["AWSEvents"] = _aws_eventbridge_dispatch
