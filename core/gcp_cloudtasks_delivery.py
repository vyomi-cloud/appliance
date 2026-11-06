"""Cloud Tasks dispatch for the offline appliance — durable, through NATS JetStream.

The engine (core/gcp_cloudtasks_core.py) stays substrate-free: it owns queues, tasks, retry
configuration and the outcome of each attempt (`record_attempt`). This module is the data plane:

  * one JetStream stream (`VYOMI_CLOUDTASKS`, file storage) holds a dispatch message per task, so
    tasks created before an appliance restart are still delivered afterwards;
  * one durable pull consumer per queue — a slow or failing target never blocks other queues;
    pausing a queue stops fetching, purging/deleting drops the queued messages;
  * workers really call the target: HTTP method, headers, body, OIDC / OAuth bearer tokens;
    App Engine targets go to VYOMI_CLOUDTASKS_APPENGINE_URL (default http://127.0.0.1:8080);
  * the queue's rateLimits are enforced (token bucket for maxDispatchesPerSecond, a slot count for
    maxConcurrentDispatches) and its retryConfig decides retry timing and when to give up;
  * `scheduleTime` is honoured: a task is not dispatched before it is due.

If no NATS broker is reachable (CLI-only runs, unit tests) the same workers run on in-process
queues — same behaviour, just not durable across a restart.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

try:
    import nats
    from nats.js.api import ConsumerConfig, StreamConfig
except ImportError:      # pragma: no cover - nats-py is a runtime dependency of the appliance
    nats = None          # type: ignore[assignment]

from core import gcp_cloudtasks_core as ct

STREAM = "VYOMI_CLOUDTASKS"
SUBJECT_PREFIX = "cloudtasks.dispatch."
APPENGINE_URL = os.environ.get("VYOMI_CLOUDTASKS_APPENGINE_URL", "http://127.0.0.1:8080")
_POLL = 0.5          # seconds between looks at a paused / idle / waiting queue


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


_KEY = None
_KEY_LOCK = threading.Lock()


def _oidc_token(email: str, audience: str, base: str) -> str:
    """A real RS256 JWT, as Cloud Tasks would mint for the service account."""
    global _KEY
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    with _KEY_LOCK:
        if _KEY is None:
            _KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    head = _b64u(json.dumps({"alg": "RS256", "typ": "JWT", "kid": "vyomi-cloudtasks"}).encode())
    claims = _b64u(json.dumps({"iss": "https://accounts.google.com", "sub": email, "email": email,
                               "email_verified": True, "aud": audience, "iat": now, "exp": now + 3600}).encode())
    sig = _KEY.sign(f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{claims}.{_b64u(sig)}"


def _parse_eta(task: dict) -> float:
    try:
        return ct._parse_ts(task["scheduleTime"], "scheduleTime").timestamp()
    except Exception:
        return 0.0


class _Lane:
    """A queue's pending dispatch messages: JetStream pull consumer, or an in-process fallback."""

    def __init__(self, key: str, loop, js):
        self.key, self.loop, self.js = key, loop, js
        self.psub = None
        self.q: asyncio.Queue = asyncio.Queue()

    async def open(self):
        if self.js is not None:
            try:
                self.psub = await self.js.pull_subscribe(
                    SUBJECT_PREFIX + self.key, durable=self.key,
                    config=ConsumerConfig(ack_wait=1900, max_deliver=-1, inactive_threshold=30 * 24 * 3600))
            except Exception:
                self.psub = None

    async def get(self):
        """(task name, handle) or None when nothing arrived within a short wait."""
        if self.psub is not None:
            try:
                msg = (await self.psub.fetch(1, timeout=1))[0]
                return msg.data.decode(), msg
            except Exception:
                return None
        try:
            return await asyncio.wait_for(self.q.get(), 1), None
        except asyncio.TimeoutError:
            return None

    async def ack(self, handle):
        if handle is not None:
            try:
                await handle.ack()
            except Exception:
                pass

    async def retry(self, name: str, handle, delay: float):
        if handle is not None:
            try:
                await handle.nak(delay=max(delay, 0.05))
                return
            except Exception:
                pass
        self.loop.call_later(max(delay, 0.0), self.q.put_nowait, name)


class Delivery:
    def __init__(self, store: Callable[[], object], save: Callable[[], None] | None = None,
                 nats_url: str | None = None):
        self._store = store
        self._save = save or (lambda: None)
        self.nats_url = nats_url or os.environ.get("CLOUDLEARN_NATS_URL", "nats://vyomi-nats:4222")
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self._nc = None
        self._js = None
        self._lanes: dict[str, _Lane] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._inflight: set[str] = set()
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self.mode = "starting"           # "jetstream" | "memory"
        self.stats: dict[str, dict] = {}  # queue name -> observable dispatch counters

    # lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self.thread is not None:
                return
            self.loop = asyncio.new_event_loop()
            self.thread = threading.Thread(target=self._run, daemon=True, name="cloudtasks-delivery")
            self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._boot())
        self.loop.run_forever()

    async def _boot(self) -> None:
        pending: dict[str, int] = {}
        try:
            if nats is None:
                raise RuntimeError("nats-py missing")
            from urllib.parse import urlparse
            u = urlparse(self.nats_url)
            _r, _w = await asyncio.wait_for(asyncio.open_connection(u.hostname, u.port or 4222), 2)   # fail fast
            _w.close()

            async def _quiet(_e):      # reconnect noise is not an error worth a traceback
                return
            self._nc = await asyncio.wait_for(
                nats.connect(self.nats_url, connect_timeout=3, max_reconnect_attempts=-1, error_cb=_quiet), 6)
            self._js = self._nc.jetstream()
            cfg = StreamConfig(name=STREAM, subjects=[SUBJECT_PREFIX + ">"], storage="file", retention="workqueue")
            try:
                await self._js.add_stream(cfg)
            except Exception:
                await self._js.stream_info(STREAM)
            self.mode = "jetstream"
            try:
                for ci in await self._js.consumers_info(STREAM):
                    pending[ci.name] = ci.num_pending + ci.num_ack_pending
            except Exception:
                pass
        except Exception:
            self._nc = self._js = None
            self.mode = "memory"
        # Resume: tasks that survived a restart in the store but have no queued message get one.
        st = self._store()
        for tname in list(st.tasks):
            qn = tname.split("/tasks/")[0]
            key = self._key(qn)
            if pending.get(key):
                self._ensure_worker(qn)
            else:
                await self._enqueue(tname)
        self._ready.set()

    @staticmethod
    def _key(qname: str) -> str:
        """JetStream-safe token for a queue: projects/p/locations/l/queues/q → p.l.q (dots are subject separators,
        project ids may not contain them but `:` domains do, so map them too)."""
        parts = qname.split("/")
        return "-".join(x.replace(".", "_").replace(":", "_") for x in (parts[1], parts[3], parts[5]))

    # enqueue -----------------------------------------------------------------------------
    def enqueue(self, task_name: str) -> None:
        self.start()
        asyncio.run_coroutine_threadsafe(self._wait_enqueue(task_name), self.loop)

    async def _wait_enqueue(self, task_name: str) -> None:
        while not self._ready.is_set():
            await asyncio.sleep(0.05)
        await self._enqueue(task_name)

    async def _enqueue(self, task_name: str) -> None:
        qn = task_name.split("/tasks/")[0]
        key = self._key(qn)
        lane = self._ensure_worker(qn)
        if self._js is not None:
            try:
                await self._js.publish(SUBJECT_PREFIX + key, task_name.encode())
                return
            except Exception:
                pass
        lane.q.put_nowait(task_name)

    def _ensure_worker(self, qn: str) -> _Lane:
        key = self._key(qn)
        lane = self._lanes.get(key)
        if lane is None:
            lane = self._lanes[key] = _Lane(key, self.loop, self._js)
        t = self._workers.get(key)
        if t is None or t.done():
            self._workers[key] = self.loop.create_task(self._worker(qn, lane))
        return lane

    # worker ------------------------------------------------------------------------------
    def _stat(self, qn: str) -> dict:
        return self.stats.setdefault(qn, {"dispatched": 0, "succeeded": 0, "failed": 0, "inFlight": 0,
                                          "maxInFlight": 0, "lastDispatchTimes": []})

    async def _worker(self, qn: str, lane: _Lane) -> None:
        await lane.open()
        st = self._store()
        slots = 0                      # in-flight dispatches for this queue
        tokens, last = None, time.monotonic()
        idle = 0
        pending_tasks: set[asyncio.Task] = set()
        while True:
            q = st.queues.get(qn)
            if q is None:                                   # queue deleted
                if self._js is not None:
                    try:
                        await self._js.delete_consumer(STREAM, lane.key)
                    except Exception:
                        pass
                self._lanes.pop(lane.key, None)
                self._workers.pop(lane.key, None)
                return
            if q.get("state") != "RUNNING":                  # paused / disabled: the consumer stops fetching
                await asyncio.sleep(_POLL)
                continue
            rl = q.get("rateLimits") or {}
            max_conc = int(rl.get("maxConcurrentDispatches", 1000)) or 10 ** 6
            rate = float(rl.get("maxDispatchesPerSecond", 500.0))
            burst = max(1, int(rl.get("maxBurstSize", 100)))
            if slots >= max_conc:
                await asyncio.sleep(0.02)
                continue
            now = time.monotonic()
            if rate > 0:
                tokens = float(burst) if tokens is None else min(float(burst), tokens + (now - last) * rate)
                last = now
                if tokens < 1:
                    await asyncio.sleep(max((1 - tokens) / rate, 0.005))
                    continue
            got = await lane.get()
            if got is None:
                idle += 1
                continue
            name, handle = got
            if (st.queues.get(qn) or {}).get("state") != "RUNNING":    # paused while the fetch was waiting
                await lane.retry(name, handle, _POLL)
                continue
            task = st.tasks.get(name)
            if task is None or name in self._inflight:      # deleted / purged / already running
                await lane.ack(handle)
                continue
            wait = _parse_eta(task) - time.time()
            if wait > 0:                                    # not due yet
                await lane.retry(name, handle, min(wait, 3600))
                await asyncio.sleep(0.02)
                continue
            if rate > 0:
                tokens -= 1
            slots += 1
            self._inflight.add(name)
            s = self._stat(qn)
            s["inFlight"] += 1
            s["maxInFlight"] = max(s["maxInFlight"], s["inFlight"])

            async def run(name=name, handle=handle):
                nonlocal slots
                try:
                    await self._dispatch_one(qn, lane, name, handle)
                finally:
                    slots -= 1
                    self._inflight.discard(name)
                    s["inFlight"] -= 1

            t = self.loop.create_task(run())
            pending_tasks.add(t)
            t.add_done_callback(pending_tasks.discard)

    async def _dispatch_one(self, qn: str, lane: _Lane, name: str, handle) -> None:
        st = self._store()
        task = st.tasks.get(name)
        if task is None:
            await lane.ack(handle)
            return
        s = self._stat(qn)
        started = time.time()
        try:
            status, detail = await asyncio.get_running_loop().run_in_executor(None, self._call, qn, task)
        except Exception as e:                              # noqa: BLE001 — any failure is a failed attempt
            status, detail = 500, str(e)[:300] or e.__class__.__name__
        s["dispatched"] += 1
        s["lastDispatchTimes"] = (s["lastDispatchTimes"] + [started])[-200:]
        outcome, delay = ct.record_attempt(st, name, status, detail)
        s["succeeded" if outcome == "done" else "failed"] += 1
        try:
            self._save()
        except Exception:
            pass
        if outcome == "retry":
            await lane.retry(name, handle, delay)
        else:
            await lane.ack(handle)

    # one attempt (blocking; runs in a worker thread) -------------------------------------
    def _call(self, qn: str, task: dict) -> tuple[int, str]:
        if task.get("httpRequest"):
            h = task["httpRequest"]
            url, method = h["url"], h.get("httpMethod", "POST")
            headers = dict(h.get("headers") or {})
            body = base64.b64decode(h["body"]) if h.get("body") else None
            auth = None
            if h.get("oidcToken"):
                o = h["oidcToken"]
                auth = _oidc_token(o.get("serviceAccountEmail", ""), o.get("audience") or url, url)
            elif h.get("oauthToken"):
                auth = "ya29.vyomi-" + _b64u(os.urandom(24))
            if auth:
                headers["Authorization"] = "Bearer " + auth
        else:
            a = task["appEngineHttpRequest"]
            url = APPENGINE_URL.rstrip("/") + "/" + a.get("relativeUri", "/").lstrip("/")
            method = a.get("httpMethod", "POST")
            headers = dict(a.get("headers") or {})
            body = base64.b64decode(a["body"]) if a.get("body") else None
            headers.setdefault("X-AppEngine-QueueName", qn.rsplit("/", 1)[-1])
        short = task["name"].rsplit("/", 1)[-1]
        headers.update({
            "X-CloudTasks-QueueName": qn.rsplit("/", 1)[-1], "X-CloudTasks-TaskName": short,
            "X-CloudTasks-TaskRetryCount": str(task.get("dispatchCount", 0)),
            "X-CloudTasks-TaskExecutionCount": str(task.get("responseCount", 0)),
            "X-CloudTasks-TaskETA": str(_parse_eta(task))})
        if task.get("lastAttempt"):
            headers["X-CloudTasks-TaskPreviousResponse"] = str(task["lastAttempt"]["responseStatus"].get("code", 0))
        timeout = ct._parse_duration(task.get("dispatchDeadline", "600s"), "dispatchDeadline")
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
                return r.status, f"HTTP {r.status} from {url}"
        except urllib.error.HTTPError as e:
            return e.code, f"HTTP {e.code} from {url}"
        except Exception as e:                              # noqa: BLE001
            return 503, f"{url}: {e}"

    # observability -----------------------------------------------------------------------
    def queue_stats(self, qn: str) -> dict:
        s = dict(self._stat(qn))
        times = s.pop("lastDispatchTimes")
        recent = [t for t in times if t > time.time() - 5]
        s["dispatchesPerSecond"] = round(len(recent) / 5.0, 2)
        s["mode"] = self.mode
        return s
