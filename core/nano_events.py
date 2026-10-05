"""Nano per-resource cloudsim event / activity log (in-browser, stdlib only).

WHY: every resource's detail view should immediately show the underlying cloudsim
events (create / update / delete / sub-resource ops) — the same activity log the
full appliance surfaces, but computed entirely in the tab. NO server, NO network:
this is an in-WASM store, recorded on the page as the SW dispatches each mutating
op through providers/registry.dispatch.

────────────────────────────────────────────────────────────────────────────────
PERSISTENCE TIER (per the Nano in-browser boundary policy): DURABLE + BOUNDED.
────────────────────────────────────────────────────────────────────────────────
A resource's history must survive reload / a new tab (the user wants to SEE it),
so this is DURABLE — persisted + cross-tab-synced via the EXISTING path:

  * The singleton store exposes ONE public dict attr (`by_resource`) holding the
    whole log. nano_persist._public_state() captures any public, JSON-safe dict
    attr generically, and nano_persist.restore_store() MERGES dicts (union) on
    restore. Events are keyed by a unique monotonic id, so union-merge is exactly
    right: a restore only ADDS events from the other tab, never clobbers.
  * It is registered in core/nano_registry.get() (key "events") and listed in
    nano_persist.STORE_ATTRS, so the SAME snapshot → IndexedDB ("nano:stores") +
    BroadcastChannel("nano-stores") machinery that persists S3/DynamoDB/… also
    persists the event log. No new persistence layer is invented.

BOUNDED: each resource keeps at most CAP (200) most-recent events (a ring), so a
long-lived tab can't grow the snapshot unbounded. A separate "_global" bucket
keeps the last CAP events across all resources, for an unfiltered activity feed.

TIMESTAMPS under Pyodide: datetime.now(timezone.utc) is already used by the proven
cores on Pyodide (e.g. s3_object_core), so it is safe here — we stamp an ISO-8601
`ts` string at record time. We ALSO stamp a monotonic integer `seq` so ordering is
stable even if two events share the same wall-clock instant; callers can sort/trim
on `seq` without trusting the clock.
"""
from __future__ import annotations

from datetime import datetime, timezone

CAP = 200                 # max events retained per resource (and in the global feed)
_GLOBAL = "_global"       # bucket key for the unfiltered cross-resource feed


def _now_iso() -> str:
    try:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except Exception:       # pragma: no cover — clock unavailable; keep it best-effort
        return ""


class EventStore:
    """In-WASM cloudsim event log. ONE public dict attr (`by_resource`) so the
    generic nano_persist capture/restore picks it up with no per-class code.

    Layout:
        by_resource = {
            "<provider>/<service>/<resource>": [ {event}, … up to CAP ],
            "_global":                          [ {event}, … up to CAP ],
        }
    Each event: {id, seq, ts, provider, service, resource, action, status, detail}.
    """

    def __init__(self) -> None:
        self.by_resource: dict[str, list[dict]] = {}
        self._seq = 0            # monotonic (underscore ⇒ not persisted; derived on boot)

    # ── key helper ────────────────────────────────────────────────────────────
    @staticmethod
    def _key(provider: str, service: str, resource: str) -> str:
        return "/".join([str(provider or ""), str(service or ""), str(resource or "")])

    def _next_seq(self) -> int:
        # _seq isn't persisted (underscore attr). On a fresh context it starts at 0;
        # re-derive it above any restored event so ids stay monotonic after a reload.
        if self._seq == 0:
            mx = 0
            for evs in self.by_resource.values():
                for e in evs:
                    try:
                        mx = max(mx, int(e.get("seq", 0)))
                    except Exception:
                        pass
            self._seq = mx
        self._seq += 1
        return self._seq

    # ── record ──────────────────────────────────────────────────────────────
    def record(self, provider: str, service: str, resource: str, action: str,
               status: str = "ok", detail: str = "") -> dict:
        """Append one event to the resource's ring AND the global feed. Returns the
        event dict. Best-effort by contract — callers wrap this so it can never
        break a request (see providers/registry._emit_event)."""
        seq = self._next_seq()
        ev = {
            "id": seq,
            "seq": seq,
            "ts": _now_iso(),
            "provider": str(provider or ""),
            "service": str(service or ""),
            "resource": str(resource or ""),
            "action": str(action or ""),
            "status": str(status or "ok"),
            "detail": ("" if detail is None else str(detail))[:500],
        }
        key = self._key(provider, service, resource)
        bucket = self.by_resource.setdefault(key, [])
        bucket.append(ev)
        if len(bucket) > CAP:
            del bucket[: len(bucket) - CAP]
        feed = self.by_resource.setdefault(_GLOBAL, [])
        feed.append(ev)
        if len(feed) > CAP:
            del feed[: len(feed) - CAP]
        return ev

    # ── list ──────────────────────────────────────────────────────────────────
    def list(self, resource: str | None = None, provider: str | None = None,
             service: str | None = None, limit: int = 200) -> list[dict]:
        """Newest-first events. Filter by `resource` name (matches any service of a
        provider), `provider`, and/or `service`. With no filters → the global feed.

        `resource` matches on the resource NAME (the key's 3rd segment), so the
        console can fetch a resource's events without knowing its service key."""
        if resource:
            out = []
            for key, evs in self.by_resource.items():
                if key == _GLOBAL:
                    continue
                parts = key.split("/", 2)
                r = parts[2] if len(parts) == 3 else ""
                if r != resource:
                    continue
                out.extend(evs)
        else:
            out = list(self.by_resource.get(_GLOBAL, []))
        if provider:
            out = [e for e in out if e.get("provider") == provider]
        if service:
            out = [e for e in out if e.get("service") == service]
        out.sort(key=lambda e: e.get("seq", 0), reverse=True)
        try:
            lim = int(limit)
        except Exception:
            lim = 200
        if lim > 0:
            out = out[:lim]
        return out


# ── module-level singleton + convenience wrappers ──────────────────────────────
# A fallback singleton used only if the shared registry hasn't been built yet.
# The registry OWNS the canonical instance (key "events"); store() prefers it so
# everything (record + persistence) operates on the ONE persisted store.
_FALLBACK: EventStore | None = None


def store() -> EventStore:
    """The canonical EventStore. Prefer the shared registry's instance (so it is
    captured/restored by nano_persist); fall back to a module singleton if the
    registry isn't importable yet (keeps this core usable standalone in tests)."""
    try:
        from core import nano_registry
        reg = nano_registry.get()
        st = reg.get("events")
        if isinstance(st, EventStore):
            return st
    except Exception:
        pass
    global _FALLBACK
    if _FALLBACK is None:
        _FALLBACK = EventStore()
    return _FALLBACK


def record(provider: str, service: str, resource: str, action: str,
           status: str = "ok", detail: str = "") -> dict:
    return store().record(provider, service, resource, action, status, detail)


def list_events(resource: str | None = None, provider: str | None = None,
                service: str | None = None, limit: int = 200) -> list[dict]:
    return store().list(resource=resource, provider=provider, service=service, limit=limit)
