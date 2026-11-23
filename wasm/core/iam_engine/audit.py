"""Bounded ring buffer of IAM decision records (same record shape on Mesh and Nano). Pure Python."""
from __future__ import annotations

import threading
import time
from collections import deque

DEFAULT_CAPACITY = 1000


def summarize_matched(matched) -> list:
    """Keep source/id/effect only (statements can be large)."""
    out = []
    for m in (matched or [])[:10]:
        if isinstance(m, dict):
            out.append({"source": m.get("source"), "id": m.get("id"), "effect": m.get("effect")})
    return out


class AuditLog:
    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self._buf: deque = deque(maxlen=max(1, int(capacity)))
        self._lock = threading.Lock()
        self._seq = 0

    def record(self, cloud, principal, action, resource, mode, decision, reason="", matched=None, **extra) -> dict:
        """decision: allow | deny | would_deny | unmapped | error."""
        now = time.time()
        with self._lock:
            self._seq += 1
            rec = {"id": self._seq, "ts": now,
                   "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                   "cloud": cloud, "principal": principal, "action": action, "resource": resource,
                   "mode": mode, "decision": decision, "reason": reason, "matched": summarize_matched(matched)}
            rec.update(extra)
            self._buf.append(rec)
        return rec

    def list(self, limit: int = 100, cloud=None, decision=None, principal=None) -> list:
        """Newest first."""
        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError):
            limit = 100
        with self._lock:
            items = list(self._buf)
        out = []
        for r in reversed(items):
            if cloud and r["cloud"] != cloud:
                continue
            if decision and r["decision"] != decision:
                continue
            if principal and r["principal"] != principal:
                continue
            out.append(r)
            if len(out) >= limit:
                break
        return out

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def __len__(self):
        return len(self._buf)


default_log = AuditLog()
