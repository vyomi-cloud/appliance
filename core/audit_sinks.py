"""Tier-feature implementation: audit_export_sinks.

Enterprise-tier feature. Lets the operator register one or more webhook
URLs (or syslog/file sinks) that receive a copy of every recorded event.
The simulator's `_record_usage()` hook calls `emit()` here after the
event is persisted; this module then async-POSTs the event to each
configured sink.

Sinks are stored per-tenant in `STATE["audit_sinks"][tenant_id]` —
a list of dicts: {id, kind: "webhook"|"file", url|path, secret, created_at}.
"""
from __future__ import annotations

import json
import time
import threading
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _sinks_for(state: dict, tenant_id: str) -> list[dict]:
    return state.setdefault("audit_sinks", {}).setdefault(tenant_id, [])


def list_sinks(state: dict, tenant_id: str) -> list[dict]:
    """Return a redacted view (no secrets) of the tenant's configured sinks."""
    out = []
    for s in _sinks_for(state, tenant_id):
        copy_s = dict(s)
        if "secret" in copy_s:
            copy_s["secret"] = "***"  # never echo secrets back
        out.append(copy_s)
    return out


def register_sink(state: dict, tenant_id: str, spec: dict) -> dict:
    """Register a new sink. Spec must include `kind` ("webhook"|"file") and
    either `url` (webhook) or `path` (file). Optional `secret` is included as
    `X-CloudLearn-Sink-Secret` header on webhook POSTs."""
    kind = str(spec.get("kind") or "webhook").strip().lower()
    if kind not in ("webhook", "file"):
        raise ValueError(f"unknown sink kind: {kind}")
    sink_id = "asink-" + uuid.uuid4().hex[:10]
    sink: dict[str, Any] = {
        "id": sink_id,
        "kind": kind,
        "created_at": _now_iso(),
        "event_count": 0,
        "last_emit_at": None,
        "last_error": None,
    }
    if kind == "webhook":
        url = str(spec.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("webhook sink requires url=http(s)://...")
        sink["url"] = url
        sink["secret"] = str(spec.get("secret") or "")
    else:  # file
        path = str(spec.get("path") or "").strip()
        if not path:
            raise ValueError("file sink requires path=...")
        sink["path"] = path
    _sinks_for(state, tenant_id).append(sink)
    return sink


def delete_sink(state: dict, tenant_id: str, sink_id: str) -> bool:
    sinks = _sinks_for(state, tenant_id)
    before = len(sinks)
    state.setdefault("audit_sinks", {})[tenant_id] = [s for s in sinks if s.get("id") != sink_id]
    return len(state["audit_sinks"][tenant_id]) < before


def _post_webhook(sink: dict, event: dict) -> tuple[bool, str]:
    """Best-effort POST. Returns (ok, error_message)."""
    try:
        data = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            sink["url"], data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": "CloudLearn-AuditSink/1.0",
                     **({"X-CloudLearn-Sink-Secret": sink["secret"]} if sink.get("secret") else {})},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return (200 <= resp.status < 300), f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _write_file(sink: dict, event: dict) -> tuple[bool, str]:
    try:
        p = Path(sink["path"]).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(event) + "\n")
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def emit(state: dict, tenant_id: str, event: dict) -> None:
    """Fire-and-forget: spin a daemon thread for each configured sink so the
    request thread isn't blocked on slow webhooks. Failures recorded back on
    the sink object's `last_error` field."""
    sinks = _sinks_for(state, tenant_id)
    if not sinks:
        return
    payload = {**event, "tenant_id": tenant_id, "emitted_at": _now_iso()}

    def _send(sink_ref):
        ok, msg = (_post_webhook(sink_ref, payload) if sink_ref["kind"] == "webhook"
                   else _write_file(sink_ref, payload))
        sink_ref["last_emit_at"] = _now_iso()
        sink_ref["last_error"] = None if ok else msg
        if ok:
            sink_ref["event_count"] = int(sink_ref.get("event_count") or 0) + 1

    for s in sinks:
        threading.Thread(target=_send, args=(s,), daemon=True).start()
