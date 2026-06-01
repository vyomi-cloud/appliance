"""Tier-feature implementation: ci_integration (Developer+ tiers).

Real CRUD for CI pipeline registrations + inbound webhook receiver + outbound
trigger POST. Designed to integrate with GitHub Actions / GitLab CI / Jenkins
via their incoming-webhook URLs.

State: `STATE["ci_pipelines"][tenant_id]` → list of dicts.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
import uuid


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _pipelines_for(state: dict, tenant_id: str) -> list[dict]:
    return state.setdefault("ci_pipelines", {}).setdefault(tenant_id, [])


def list_pipelines(state: dict, tenant_id: str) -> list[dict]:
    out = []
    for p in _pipelines_for(state, tenant_id):
        view = dict(p)
        if "secret" in view:
            view["secret"] = "***"
        out.append(view)
    return out


def register_pipeline(state: dict, tenant_id: str, spec: dict) -> dict:
    name = str(spec.get("name") or "").strip()
    trigger_url = str(spec.get("trigger_url") or "").strip()
    if not name:
        raise ValueError("pipeline requires `name`")
    if not trigger_url.startswith(("http://", "https://")):
        raise ValueError("pipeline `trigger_url` must be http(s)://...")
    pipeline = {
        "id": "pipe-" + uuid.uuid4().hex[:10],
        "name": name,
        "kind": str(spec.get("kind") or "github").strip().lower(),  # github | gitlab | jenkins | custom
        "trigger_url": trigger_url,
        "secret": str(spec.get("secret") or ""),
        # Inbound: an incoming webhook URL that THIS pipeline calls to notify
        # CloudLearn of a CI event. Token is shared with the pipeline so they
        # can POST /api/runtime/ci/webhook/{token}.
        "inbound_token": uuid.uuid4().hex,
        "events_subscribed": spec.get("events_subscribed") or ["deploy.complete", "tier.upgraded"],
        "created_at": _now_iso(),
        "last_triggered_at": None,
        "last_inbound_at": None,
        "trigger_count": 0,
        "inbound_count": 0,
        "last_error": None,
    }
    _pipelines_for(state, tenant_id).append(pipeline)
    return pipeline


def delete_pipeline(state: dict, tenant_id: str, pipeline_id: str) -> bool:
    pipes = _pipelines_for(state, tenant_id)
    before = len(pipes)
    state.setdefault("ci_pipelines", {})[tenant_id] = [p for p in pipes if p.get("id") != pipeline_id]
    return len(state["ci_pipelines"][tenant_id]) < before


def trigger_pipeline(state: dict, tenant_id: str, pipeline_id: str, payload: dict | None = None) -> dict:
    """POST `payload` to the pipeline's trigger_url synchronously; returns
    delivery status. Standard payload shape mirrors GitHub's repository_dispatch
    event so the pipeline can react accordingly."""
    for p in _pipelines_for(state, tenant_id):
        if p.get("id") != pipeline_id:
            continue
        body = {
            "event_type": "cloudlearn.trigger",
            "client_payload": payload or {},
            "tenant_id": tenant_id,
            "pipeline_id": pipeline_id,
            "sent_at": _now_iso(),
        }
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                p["trigger_url"], data=data, method="POST",
                headers={"Content-Type": "application/json",
                         "User-Agent": "CloudLearn-CI/1.0",
                         **({"X-CloudLearn-CI-Secret": p["secret"]} if p.get("secret") else {})},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                ok = 200 <= resp.status < 300
                status_str = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            ok, status_str = False, f"HTTP {e.code}"
        except Exception as e:
            ok, status_str = False, f"{type(e).__name__}: {e}"
        p["last_triggered_at"] = _now_iso()
        p["last_error"] = None if ok else status_str
        if ok:
            p["trigger_count"] = int(p.get("trigger_count") or 0) + 1
        return {"ok": ok, "result": status_str, "pipeline_id": pipeline_id}
    return {"ok": False, "result": "pipeline-not-found"}


def receive_inbound(state: dict, token: str, payload: dict) -> dict | None:
    """Lookup the pipeline whose `inbound_token` matches; record the inbound
    event. Returns the pipeline (for usage logging) or None if no match."""
    for tenant_id, pipes in (state.get("ci_pipelines") or {}).items():
        for p in pipes:
            if p.get("inbound_token") == token:
                p["last_inbound_at"] = _now_iso()
                p["inbound_count"] = int(p.get("inbound_count") or 0) + 1
                # Tail the last 20 inbounds for the SPA to display.
                tail = p.setdefault("inbound_log", [])
                tail.append({"at": _now_iso(), "payload": payload})
                p["inbound_log"] = tail[-20:]
                return {"tenant_id": tenant_id, **p}
    return None
