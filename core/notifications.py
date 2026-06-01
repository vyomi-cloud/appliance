"""Tier-feature implementation: notifications.

Developer tier = "webhook" channels only (per tier_policy).
Enterprise tier = "all_channels" (webhook + email-via-relay + slack).

For MVP fidelity we POST a webhook for all kinds — Slack-compatible payload
shape so a Slack incoming-webhook URL just works. "Email" mode treats a
mailto: URL as a no-op-with-log (real SMTP send needs an MTA we don't
ship).

State: `STATE["notification_channels"][tenant_id]` → list of dicts:
{id, kind: "webhook"|"slack"|"email", url, name, events, created_at, ...}
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
import uuid


# Events that the platform can emit. Each channel subscribes to a subset
# via the `events` field; "*" means all.
KNOWN_EVENTS = (
    "license.expiring_soon",
    "license.expired",
    "tier.limit_denied",
    "tier.upgrade_recommended",
    "space.created",
    "space.deleted",
    "audit.spike",
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _channels_for(state: dict, tenant_id: str) -> list[dict]:
    return state.setdefault("notification_channels", {}).setdefault(tenant_id, [])


def list_channels(state: dict, tenant_id: str) -> list[dict]:
    out = []
    for c in _channels_for(state, tenant_id):
        view = dict(c)
        if "secret" in view:
            view["secret"] = "***"
        out.append(view)
    return out


def register_channel(state: dict, tenant_id: str, spec: dict) -> dict:
    kind = str(spec.get("kind") or "webhook").strip().lower()
    if kind not in ("webhook", "slack", "email"):
        raise ValueError(f"unknown notification kind: {kind}")
    url = str(spec.get("url") or "").strip()
    if kind in ("webhook", "slack") and not url.startswith(("http://", "https://")):
        raise ValueError(f"{kind} channel requires url=http(s)://...")
    if kind == "email" and not url.startswith("mailto:"):
        raise ValueError("email channel requires url=mailto:user@host")
    events = spec.get("events") or ["*"]
    if not isinstance(events, list):
        events = [str(events)]
    ch = {
        "id": "nch-" + uuid.uuid4().hex[:10],
        "kind": kind,
        "name": str(spec.get("name") or kind),
        "url": url,
        "events": events,
        "secret": str(spec.get("secret") or ""),
        "created_at": _now_iso(),
        "sent_count": 0,
        "last_sent_at": None,
        "last_error": None,
    }
    _channels_for(state, tenant_id).append(ch)
    return ch


def delete_channel(state: dict, tenant_id: str, channel_id: str) -> bool:
    chs = _channels_for(state, tenant_id)
    before = len(chs)
    state.setdefault("notification_channels", {})[tenant_id] = [c for c in chs if c.get("id") != channel_id]
    return len(state["notification_channels"][tenant_id]) < before


def _shape_for_slack(event_name: str, body: dict) -> dict:
    """Slack incoming-webhook shape: a single `text` field is required; we add
    a `blocks` array with title + structured fields so it renders nicely."""
    summary = body.get("summary") or body.get("reason") or ""
    fields = []
    for k in ("active_tier", "code", "feature", "upgrade_to"):
        if body.get(k):
            fields.append({"type": "mrkdwn", "text": f"*{k}*: `{body[k]}`"})
    return {
        "text": f"[CloudLearn] {event_name}: {summary}"[:1500],
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": event_name}},
            *( [{"type": "section", "text": {"type": "mrkdwn", "text": summary}}] if summary else []),
            *( [{"type": "section", "fields": fields[:10]}] if fields else []),
        ],
    }


def _post(channel: dict, event_name: str, body: dict) -> tuple[bool, str]:
    try:
        kind = channel["kind"]
        if kind == "slack":
            data = json.dumps(_shape_for_slack(event_name, body)).encode("utf-8")
        elif kind == "webhook":
            payload = {"event": event_name, "body": body, "sent_at": _now_iso(),
                       "channel_id": channel.get("id")}
            data = json.dumps(payload).encode("utf-8")
        else:  # email — treat as no-op-success (no MTA shipped)
            return True, "email-channel-noop"
        req = urllib.request.Request(
            channel["url"], data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": "CloudLearn-Notifier/1.0",
                     **({"X-CloudLearn-Notif-Secret": channel["secret"]} if channel.get("secret") else {})},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return (200 <= resp.status < 300), f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def emit(state: dict, tenant_id: str, event_name: str, body: dict) -> int:
    """Send `event_name` (with body) to every subscribed channel for tenant.
    Returns the count of channels sent to (async — actual delivery happens in
    background threads).
    """
    channels = _channels_for(state, tenant_id)
    count = 0
    for ch in channels:
        events = ch.get("events") or ["*"]
        if "*" not in events and event_name not in events:
            continue
        count += 1

        def _send(ch_ref):
            ok, msg = _post(ch_ref, event_name, body)
            ch_ref["last_sent_at"] = _now_iso()
            ch_ref["last_error"] = None if ok else msg
            if ok:
                ch_ref["sent_count"] = int(ch_ref.get("sent_count") or 0) + 1

        threading.Thread(target=_send, args=(ch,), daemon=True).start()
    return count


def send_test(state: dict, tenant_id: str, channel_id: str) -> dict:
    """Synchronously POST a test event to a specific channel; useful from a
    'Send test' button. Returns delivery status."""
    for ch in _channels_for(state, tenant_id):
        if ch.get("id") != channel_id:
            continue
        ok, msg = _post(ch, "test.notification", {
            "summary": "CloudLearn notification test",
            "channel_kind": ch["kind"], "tenant_id": tenant_id,
        })
        ch["last_sent_at"] = _now_iso()
        ch["last_error"] = None if ok else msg
        if ok:
            ch["sent_count"] = int(ch.get("sent_count") or 0) + 1
        return {"ok": ok, "result": msg, "channel_id": channel_id}
    return {"ok": False, "result": "channel-not-found"}
