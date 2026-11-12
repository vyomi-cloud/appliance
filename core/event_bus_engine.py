"""Shared event-bus engine — ONE substrate-free delivery core for every cloud (GCP Eventarc, AWS EventBridge,
Azure Event Grid). Pure stdlib, Pyodide-loadable; everything that touches the world is injected, exactly like
core/apigatewayv2_gateway.py:

  * `deliver(target, event[, ctx]) -> bool | int HTTP status | dict{"status"|"ok", "error"}` (raises = failed attempt).
    The cloud adapter decides what a target is (Cloud Run service/job, HTTP endpoint, Lambda, Function, Pub/Sub, SQS ...);
    `http_deliver()` below is a ready stdlib implementation of the HTTP-endpoint kind.
  * `clock()` and (optional) `sleep()` — so tests/Nano control time.

What the engine owns:
  * subscriptions with generic filters (exact / prefix / suffix / exists / path-pattern / any-of), `publish(event)` fan-out
  * CloudEvents 1.0 envelope (`cloud_event()`)
  * delivery with exponential-backoff retries (`min_backoff * multiplier^(n-1)`, capped at `max_backoff`), `max_attempts`,
    and a dead-letter destination (delivered through the same `deliver` callable, flagged `ctx["dead_letter"]`)
  * per-ordering-key ordering: deliveries of the same (subscription, ordering key) are strictly FIFO; a failing head blocks
    its lane until it is delivered or dead-lettered (other keys and unordered events are not blocked)
  * a persistent, JSON-serialisable delivery log with the full per-attempt history (`history()` / `get()` / `stats()`)

Time model: the first attempt runs inline in `dispatch()`; failures are rescheduled at `now + backoff` and run by `tick()`
(`start_pump()` runs it on a daemon thread where threads exist; on Nano the adapter ticks lazily on every bus call).
A policy with `sync: true` retries inline (immediately, or after the injected `sleep`) so a caller that needs the final
outcome in the same call (EventBridge PutEvents, Event Grid publish) gets it.
"""
from __future__ import annotations

import fnmatch
import inspect
import json
import re
import threading
import time
import uuid
import urllib.request
from datetime import datetime, timezone

DELIVERED, RETRYING, PENDING, DEAD_LETTERED, FAILED = "DELIVERED", "RETRYING", "PENDING", "DEAD_LETTERED", "FAILED"
TERMINAL = (DELIVERED, DEAD_LETTERED, FAILED)

DEFAULT_RETRY = {"max_attempts": 5, "min_backoff": 1.0, "max_backoff": 600.0, "multiplier": 2.0, "sync": False}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def cloud_event(etype: str, source: str, data=None, subject: str = "", eid: str | None = None, ts: float | None = None, **ext) -> dict:
    """CloudEvents 1.0 structured envelope (extension attributes, e.g. orderingkey, ride along as top-level keys)."""
    ce = {"specversion": "1.0", "id": eid or uuid.uuid4().hex[:16], "type": etype, "source": source,
          "time": _iso(ts if ts is not None else time.time()), "datacontenttype": "application/json", "data": data if data is not None else {}}
    if subject:
        ce["subject"] = subject
    ce.update(ext)
    return ce


def normalize_retry(p: dict | None) -> dict:
    r = dict(DEFAULT_RETRY)
    for k, v in (p or {}).items():
        if k in r and v is not None:
            r[k] = v
    r["max_attempts"] = max(1, int(r["max_attempts"]))
    r["min_backoff"] = max(0.0, float(r["min_backoff"]))
    r["max_backoff"] = max(r["min_backoff"], float(r["max_backoff"]))
    r["multiplier"] = max(1.0, float(r["multiplier"]))
    r["sync"] = bool(r["sync"])
    return r


def backoff_for(policy: dict, attempt: int) -> float:
    """Delay before attempt `attempt + 1` (attempt = the number that just failed, 1-based)."""
    return min(policy["max_backoff"], policy["min_backoff"] * (policy["multiplier"] ** (attempt - 1)))


# ── filters ─────────────────────────────────────────────────────────────────
def _attr(event: dict, name: str):
    if name in event:
        return event[name]
    cur = event
    for part in name.split("."):      # dotted path into data (e.g. data.detail.state)
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _path_pattern(pat: str, val: str) -> bool:
    rx = "^" + re.sub(r"\\\{[^/}]+=\\\*\\\*\\\}", ".+", re.sub(r"\\\{[^/}]+\\\}", "[^/]+", re.escape(pat))) + "$"
    return re.match(rx, val) is not None


def match_filters(filters, event: dict) -> bool:
    """`filters`: list of {attribute, value, operator?}; operators: eq (default), prefix, suffix, exists, any-of, wildcard,
    match-path-pattern. All must hold. An empty list matches everything."""
    for f in filters or []:
        a, op, want = f.get("attribute"), (f.get("operator") or "eq"), f.get("value")
        got = _attr(event, a) if a else None
        if op == "exists":
            if (got is not None) != bool(want if want is not None else True):
                return False
            continue
        if got is None:
            return False
        got = str(got)
        if op == "eq" and got != str(want):
            return False
        elif op == "prefix" and not got.startswith(str(want)):
            return False
        elif op == "suffix" and not got.endswith(str(want)):
            return False
        elif op == "any-of" and got not in [str(x) for x in (want or [])]:
            return False
        elif op == "wildcard" and not fnmatch.fnmatchcase(got, str(want)):
            return False
        elif op == "match-path-pattern" and not _path_pattern(str(want), got):
            return False
    return True


# ── stdlib HTTP target (real sockets, offline appliance) ────────────────────
def http_deliver(target: dict, event: dict, ctx: dict | None = None) -> dict:
    """Deliver to `target = {"url": ..., "headers": {...}, "timeout": 10}` as a CloudEvent (binary content mode headers +
    JSON body... structured mode: the whole envelope). 2xx = delivered. Never raises."""
    ctx = ctx or {}
    hdrs = {"content-type": "application/cloudevents+json; charset=utf-8", "ce-id": str(event.get("id", "")),
            "ce-type": str(event.get("type", "")), "ce-specversion": "1.0",
            "x-vyomi-delivery-attempt": str(ctx.get("attempt", 1))}
    hdrs.update(target.get("headers") or {})
    req = urllib.request.Request(target["url"], data=json.dumps(event).encode(), method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=float(target.get("timeout", 10))) as r:
            return {"status": r.status}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": "HTTP %d" % e.code}
    except Exception as e:   # noqa: BLE001
        return {"status": 0, "error": str(e)[:200]}


def _outcome(res) -> tuple[bool, str, str]:
    """-> (ok, status, error) from whatever `deliver` returned."""
    if isinstance(res, bool) or res is None:
        return bool(res), "", "" if res else "delivery returned false"
    if isinstance(res, int):
        return 200 <= res < 300, str(res), "" if 200 <= res < 300 else "HTTP %d" % res
    if isinstance(res, dict):
        if "ok" in res:
            ok = bool(res["ok"])
        else:
            st = res.get("status")
            ok = isinstance(st, int) and 200 <= st < 300
        return ok, str(res.get("status", "")), "" if ok else str(res.get("error") or "delivery failed")
    return bool(res), "", ""


class EventBus:
    def __init__(self, deliver, state: dict | None = None, clock=time.time, sleep=None, max_records: int = 500, auto_pump: bool = True):
        self.deliver_fn = deliver
        self.clock = clock
        self.sleep = sleep
        self.max_records = max_records
        self.auto_pump = auto_pump
        self.state = state if state is not None else {}
        self.state.setdefault("subs", {})
        self.state.setdefault("deliveries", {})
        self.state.setdefault("order", [])
        self._lock = threading.RLock()
        self._pump = None
        try:
            self._ctx_arg = len(inspect.signature(deliver).parameters) >= 3
        except (TypeError, ValueError):
            self._ctx_arg = False

    # -- subscriptions -------------------------------------------------------
    def add_subscription(self, sid: str, target, filters=None, retry=None, dead_letter=None, ordered: bool = False) -> dict:
        with self._lock:
            sub = {"id": sid, "target": target, "filters": list(filters or []), "retry": normalize_retry(retry),
                   "dead_letter": dead_letter, "ordered": bool(ordered)}
            self.state["subs"][sid] = sub
            return sub

    def remove_subscription(self, sid: str) -> bool:
        with self._lock:
            return self.state["subs"].pop(sid, None) is not None

    def publish(self, event: dict, ordering_key: str | None = None) -> list:
        """Fan `event` out to every matching registered subscription. -> list of delivery ids."""
        with self._lock:
            subs = [s for s in self.state["subs"].values() if match_filters(s["filters"], event)]
            recs = [self._enqueue(s, event, ordering_key) for s in subs]
        self.tick()
        return [r["id"] for r in recs]

    # -- dispatch ------------------------------------------------------------
    def _enqueue(self, sub: dict, event: dict, key) -> dict:
        key = key if key is not None else (event.get("orderingkey") if sub.get("ordered") else None)
        now = self.clock()
        rec = {"id": uuid.uuid4().hex[:16], "subscription": sub["id"], "target": sub["target"], "dead_letter": sub.get("dead_letter"),
               "retry": normalize_retry(sub.get("retry")), "orderingKey": key, "eventId": event.get("id"), "eventType": event.get("type"),
               "event": event, "status": PENDING, "attempts": [], "createTime": _iso(now), "next_at": now}
        self.state["deliveries"][rec["id"]] = rec
        self.state["order"].append(rec["id"])
        return rec

    def dispatch(self, sub: dict, event: dict, ordering_key: str | None = None) -> dict:
        """Deliver `event` to one ad-hoc subscription dict {id, target, retry?, dead_letter?, ordered?}. The first attempt runs
        inline (sync policies run to completion); returns the delivery record (status DELIVERED / RETRYING / DEAD_LETTERED ...)."""
        with self._lock:
            rec = self._enqueue(sub, event, ordering_key)
        self.tick()
        return rec

    # -- the scheduler -------------------------------------------------------
    def _lane_blocked(self, rec: dict) -> bool:
        if rec["orderingKey"] is None:
            return False
        for rid in self.state["order"]:
            if rid == rec["id"]:
                return False
            o = self.state["deliveries"].get(rid)
            if o and o["status"] not in TERMINAL and o["subscription"] == rec["subscription"] and o["orderingKey"] == rec["orderingKey"]:
                return True
        return False

    def _call(self, target, event, ctx):
        try:
            res = self.deliver_fn(target, event, ctx) if self._ctx_arg else self.deliver_fn(target, event)
            return _outcome(res)
        except Exception as e:   # noqa: BLE001
            return False, "", (getattr(e, "message", None) or str(e) or e.__class__.__name__)[:300]

    def _attempt(self, rec: dict, now: float) -> None:
        n = len(rec["attempts"]) + 1
        ctx = {"attempt": n, "delivery_id": rec["id"], "subscription": rec["subscription"], "dead_letter": False}
        try:
            res = self.deliver_fn(rec["target"], rec["event"], ctx) if self._ctx_arg else self.deliver_fn(rec["target"], rec["event"])
        except Exception as e:   # noqa: BLE001
            res = {"ok": False, "error": (getattr(e, "message", None) or str(e) or e.__class__.__name__)[:300]}
        if isinstance(res, dict) and isinstance(res.get("deferred"), dict):
            # A runtime with no sockets (Nano/Pyodide): the hop is awaited by the host (apump) and finished by complete().
            rec["deferred"], rec["next_at"], rec["_t0"] = res["deferred"], None, now
            return
        self._finish(rec, now, _outcome(res))

    def _finish(self, rec: dict, t0: float, outcome) -> None:
        n = len(rec["attempts"]) + 1
        ok, status, err = outcome
        rec["attempts"].append({"attempt": n, "time": _iso(t0), "ok": ok, "status": status, "error": err})
        pol = rec["retry"]
        if ok:
            rec["status"], rec["next_at"] = DELIVERED, None
            return
        if n >= pol["max_attempts"]:
            dl = rec.get("dead_letter")
            if dl is not None:
                dok, dstatus, derr = self._call(dl, rec["event"], {"attempt": 1, "delivery_id": rec["id"], "subscription": rec["subscription"], "dead_letter": True})
                rec["deadLetter"] = {"time": _iso(self.clock()), "ok": dok, "status": dstatus, "error": derr}
                rec["status"] = DEAD_LETTERED if dok else FAILED
            else:
                rec["status"] = FAILED
            rec["next_at"] = None
            return
        rec["status"] = RETRYING
        rec["next_at"] = t0 + backoff_for(pol, n)

    def tick(self, now: float | None = None) -> int:
        """Run every attempt that is due (and whose ordering lane head it is). -> number of attempts made."""
        made = 0
        with self._lock:
            now = self.clock() if now is None else now
            progress = True
            while progress:
                progress = False
                tried = set()
                for rid in list(self.state["order"]):
                    rec = self.state["deliveries"].get(rid)
                    if not rec or rec["status"] in TERMINAL or rid in tried or rec.get("inflight") or rec.get("deferred"):
                        continue
                    if rec["next_at"] is not None and rec["next_at"] > now:
                        continue
                    if self._lane_blocked(rec):
                        continue
                    tried.add(rid)
                    while True:
                        rec["inflight"] = True      # a re-entrant tick (target -> another bus) must not re-attempt this delivery
                        try:
                            self._attempt(rec, now)
                        finally:
                            rec["inflight"] = False
                        made += 1
                        progress = True
                        if rec["status"] in TERMINAL or rec.get("deferred") or not rec["retry"]["sync"]:
                            break
                        d = backoff_for(rec["retry"], len(rec["attempts"]))
                        if self.sleep and d:
                            self.sleep(d)
                        rec["next_at"] = now
            self._trim()
            pending = any(r["status"] not in TERMINAL for r in self.state["deliveries"].values())
        if pending and self.auto_pump:
            self.start_pump()
        return made

    # -- async hop (Nano) ----------------------------------------------------
    def deferred(self) -> list:
        """Deliveries whose current attempt waits for the host to perform an HTTP hop: [(delivery_id, fetch_dict)]."""
        with self._lock:
            return [(r["id"], r["deferred"]) for r in self.state["deliveries"].values() if r.get("deferred") and r["status"] not in TERMINAL]

    def complete(self, delivery_id: str, res) -> None:
        """Finish a deferred attempt with the hop's outcome (same shapes `deliver` may return) and continue the retry policy."""
        with self._lock:
            rec = self.state["deliveries"].get(delivery_id)
            if not rec or not rec.get("deferred"):
                return
            rec.pop("deferred", None)
            t0 = rec.pop("_t0", self.clock())
            if rec["status"] in TERMINAL:
                return
            rec["inflight"] = True
            try:
                self._finish(rec, t0, _outcome(res))
            finally:
                rec["inflight"] = False

    async def apump(self, afetch, rounds: int = 20) -> int:
        """Nano's tick: run what is due, await each deferred hop with `afetch(fetch_dict) -> result`, finish it. -> hops made."""
        hops = 0
        for _ in range(rounds):
            self.tick()
            todo = self.deferred()
            if not todo:
                break
            for did, f in todo:
                try:
                    res = await afetch(f)
                except Exception as e:   # noqa: BLE001
                    res = {"ok": False, "error": (getattr(e, "message", None) or str(e) or e.__class__.__name__)[:300]}
                self.complete(did, res)
                hops += 1
        return hops

    def cancel(self, sub_id: str, reason: str = "subscription deleted") -> int:
        """Terminate every in-flight delivery of a subscription (FAILED, attempt history kept)."""
        n = 0
        with self._lock:
            for r in self.state["deliveries"].values():
                if r["subscription"] == sub_id and r["status"] not in TERMINAL:
                    r["status"], r["next_at"] = FAILED, None
                    r["attempts"].append({"attempt": len(r["attempts"]) + 1, "time": _iso(self.clock()), "ok": False, "status": "", "error": reason})
                    n += 1
        return n

    def next_due(self):
        with self._lock:
            ts = [r["next_at"] for r in self.state["deliveries"].values() if r["status"] not in TERMINAL and r["next_at"] is not None]
            return min(ts) if ts else None

    def drain(self, max_steps: int = 10000) -> int:
        """Test/Nano helper: advance through every pending retry by sleeping/jumping to `next_due` until nothing is pending."""
        total = 0
        for _ in range(max_steps):
            nd = self.next_due()
            if nd is None:
                break
            wait = nd - self.clock()
            if wait > 0:
                if self.sleep:
                    self.sleep(wait)
                else:
                    time.sleep(wait)
            total += self.tick()
        return total

    def start_pump(self, interval: float = 0.25) -> bool:
        """Daemon thread that ticks until nothing is pending. False where threads are unavailable (Pyodide): the adapter then
        ticks lazily on every bus call."""
        with self._lock:
            if self._pump is not None and self._pump.is_alive():
                return True

            def loop():
                while self.next_due() is not None:
                    time.sleep(interval)
                    try:
                        self.tick()
                    except Exception:   # noqa: BLE001
                        pass
            try:
                self._pump = threading.Thread(target=loop, daemon=True, name="event-bus-pump")
                self._pump.start()
                return True
            except Exception:   # noqa: BLE001
                self._pump = None
                return False

    def _trim(self) -> None:
        order = self.state["order"]
        if len(order) <= self.max_records:
            return
        keep = []
        extra = len(order) - self.max_records
        for rid in order:
            rec = self.state["deliveries"].get(rid)
            if extra > 0 and rec and rec["status"] in TERMINAL:
                self.state["deliveries"].pop(rid, None)
                extra -= 1
            else:
                keep.append(rid)
        self.state["order"] = keep

    # -- observability -------------------------------------------------------
    @staticmethod
    def _view(rec: dict) -> dict:
        v = {k: rec[k] for k in ("id", "subscription", "orderingKey", "eventId", "eventType", "status", "attempts", "createTime", "target")}
        v["attemptCount"] = len(rec["attempts"])
        v["maxAttempts"] = rec["retry"]["max_attempts"]
        v["nextAttemptAt"] = _iso(rec["next_at"]) if rec["next_at"] is not None else None
        v["lastError"] = next((a["error"] for a in reversed(rec["attempts"]) if a["error"]), "")
        if "deadLetter" in rec:
            v["deadLetter"] = rec["deadLetter"]
        return v

    def get(self, delivery_id: str) -> dict | None:
        with self._lock:
            r = self.state["deliveries"].get(delivery_id)
            return self._view(r) if r else None

    def history(self, sub_id: str | None = None, limit: int = 50) -> list:
        """Newest first."""
        with self._lock:
            out = [self._view(self.state["deliveries"][i]) for i in reversed(self.state["order"])
                   if i in self.state["deliveries"] and (sub_id is None or self.state["deliveries"][i]["subscription"] == sub_id)]
            return out[:limit]

    def stats(self, sub_id: str | None = None) -> dict:
        with self._lock:
            c = {"delivered": 0, "retrying": 0, "pending": 0, "deadLettered": 0, "failed": 0, "attempts": 0}
            key = {DELIVERED: "delivered", RETRYING: "retrying", PENDING: "pending", DEAD_LETTERED: "deadLettered", FAILED: "failed"}
            for r in self.state["deliveries"].values():
                if sub_id is None or r["subscription"] == sub_id:
                    c[key[r["status"]]] += 1
                    c["attempts"] += len(r["attempts"])
            return c
