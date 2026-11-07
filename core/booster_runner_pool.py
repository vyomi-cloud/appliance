"""Runner pool for the booster's remote LLM (SPIKE, with core/booster_remote_llm.attach(pooled=True)).

EAGER model pool: when the booster starts, EVERY catalogue runner (docker/booster-runner-llm/models.json) is dispatched at once,
one GitHub-hosted runner each (Ollama runtime; a runner may serve several models, e.g. fast = 3B chat + embeddings). The pool lives
for a fixed WALL-CLOCK window from booster start (Pro 30 h / Max 40 h) regardless of how many runners run - runner minutes are
NOT metered against the booster-hours ledger (public-repo runner minutes are free; a private repo would exhaust its 2000 free
minutes, so the runner repo must be public). Hosted jobs die at 6 h, so each runner is ROTATED at 5h30m: the portal dispatches a
successor that dials the relay with a fresh token; the relay swaps when it is ready and the old one drains (wasm/relay/runner-llm-hub.mjs).

The booster holds no GitHub credential: a Dispatcher asks the PORTAL to dispatch / cancel. Runner readiness is the relay's view
(``GET <hub>/_status``). Honesty: a model whose runner is not ready answers 503 + Retry-After; nothing falls back to a local model.
Idle rule: no inference request to any model, no VM and no console activity (touch()) for 60 min -> the whole pool is destroyed.
"""
from __future__ import annotations

import fnmatch
import json
import os
import threading
import time
import urllib.request
from typing import Callable, Optional

CATALOGUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docker", "booster-runner-llm", "models.json")
STAGGER_S = 30                      # staggered start: stage N of the catalogue is dispatched N x STAGGER_S after the first
HARD_MAX_RUNNERS = 20               # sanity bound (GitHub Free: 20 concurrent hosted-runner jobs)
WINDOW_HOURS = {"pro": 30, "max": 40, "enterprise": 40}      # SINGLE place to change the wall-clock windows
ROTATE_S = 19800                    # re-dispatch each runner at 5h30m
RUNNER_TTL_S = 21000                # a runner exits by itself at 5h50m (< 6 h job cap); overlaps its successor ~20 min
DEFAULT_IDLE_S = 3600               # 60 min of no activity -> destroy the pool
START_TIMEOUT_S = 900               # dispatched but never ready -> re-dispatch (a cold 7-9 GB pull takes minutes)
RETRY_AFTER_S = 15
STATUS_TTL_S = 2.0
WARN_AT_S = (3600, 600, 120)        # window-end warnings: 60 / 10 / 2 minutes


class PoolError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: Optional[int] = None, state: str = ""):
        self.status, self.code, self.message, self.retry_after, self.state = status, code, message, retry_after, state
        super().__init__(message)

    def body(self) -> dict:
        e = {"message": self.message, "type": "unavailable" if self.status == 503 else "invalid_request_error", "code": self.code}
        if self.state:
            e["status"] = self.state
        return {"error": e}


def load_catalogue(path: Optional[str] = None) -> dict:
    with open(path or CATALOGUE_PATH) as f:
        return json.load(f)


def window_s_for(tier: str) -> float:
    return float(WINDOW_HOURS.get(str(tier).lower(), WINDOW_HOURS["pro"])) * 3600.0


class HttpDispatcher:
    """Asks the PORTAL to start/cancel a runner (the portal owns the GitHub App and mints each runner's fresh token).
    VYOMI_RUNNER_DISPATCH_URL=https://portal/api/booster/runner ; auth = the booster session token."""

    def __init__(self, url: str = "", token_fn: Callable[[], str] = lambda: ""):
        self.url, self.token_fn = url or os.environ.get("VYOMI_RUNNER_DISPATCH_URL", ""), token_fn

    def _post(self, action: str, rid: str, extra: dict) -> None:
        if not self.url:
            raise PoolError(503, "RunnerDispatchNotConfigured", "runner dispatch is not configured on this booster")
        req = urllib.request.Request(self.url.rstrip("/") + "/" + action, data=json.dumps({"runner": rid, **extra}).encode(), method="POST",
                                     headers={"content-type": "application/json", "x-vyomi-session-token": self.token_fn()})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            raise PoolError(503, "RunnerDispatchFailed", f"could not dispatch the runner: {type(e).__name__}")

    def start(self, rid: str, spec: dict, *, rotation: bool = False) -> None:
        self._post("start", rid, {"ollama_tags": spec["ollama_tags"], "ttl_s": RUNNER_TTL_S, "rotation": rotation})

    def stop(self, rid: str) -> None:
        self._post("stop", rid, {})


class RunnerPool:
    def __init__(self, hub_base: str, token_fn: Callable[[], str], dispatcher, *, catalogue: Optional[dict] = None,
                 window_s: float = window_s_for("pro"), idle_s: Optional[float] = None, rotate_s: float = ROTATE_S,
                 clock: Callable[[], float] = time.time, runtime: str = "ollama", stagger_s: Optional[float] = None,
                 on_destroy: Optional[Callable[[str], None]] = None):
        self.hub, self.token_fn, self.dispatcher, self.clock, self.runtime = hub_base.rstrip("/"), token_fn, dispatcher, clock, runtime
        self.cat = catalogue or load_catalogue()
        self.window_s, self.rotate_s = float(window_s), float(rotate_s)
        self.idle_s = float(idle_s if idle_s is not None else os.environ.get("VYOMI_RUNNER_IDLE_S", DEFAULT_IDLE_S))
        self.stagger_s = float(stagger_s if stagger_s is not None else os.environ.get("VYOMI_RUNNER_STAGGER_S", STAGGER_S))
        self.on_destroy = on_destroy
        self._lock = threading.RLock()
        self.phase = "new"                      # new | running | destroyed
        self.window_start = self.deadline = self.last_activity = 0.0
        self.destroyed_why = ""
        self._rec: dict[str, dict] = {}         # runner id -> {gen_started, was_ready, rotating_since, dispatched_at}
        self._requests: dict[str, int] = {}
        self._tps: dict[str, dict] = {}
        self._warned: set = set()
        self._events: list = []
        self._hub = {"at": -1e9, "runners": {}, "rotating": {}, "ok": False}
        self._aliases = self._merged_aliases()
        # A catalogue runner with "slots": 2 is a POOLED entry (e.g. qwen3:30b over llama.cpp RPC on the WireGuard mesh): it occupies
        # 2 hosted-runner slots "<id>#0" (head, serves requests) and "<id>#1" (worker), each rotated / drained / idled like any runner.
        self._slots: dict[str, list] = {}
        self._slot_base: dict[str, tuple] = {}
        for rid, r in self.cat["runners"].items():
            n = int(r.get("slots", 1))
            ids = [rid] if n == 1 else [f"{rid}#{i}" for i in range(n)]
            self._slots[rid] = ids
            for i, sid in enumerate(ids):
                self._slot_base[sid] = (rid, i)
        self._model_runner = {m: self._slots[rid][0] for rid, r in self.cat["runners"].items() for m in r["models"]}
        self._model_slots = {m: self._slots[rid] for rid, r in self.cat["runners"].items() for m in r["models"]}

    # -------------------------------------------------------------------------------------------- catalogue / mapping
    def _merged_aliases(self) -> dict:
        out: dict = {}
        for cloud, m in self.cat.get("aliases", {}).items():
            if not cloud.startswith("_"):
                out.update({k: v for k, v in m.items() if not k.startswith("_")})
        for mid in self.cat["models"]:
            out.update(self._generated(mid))
        try:
            out.update(json.loads(os.environ.get("VYOMI_RUNNER_MODEL_ALIASES", "{}")))
        except ValueError:
            pass
        return out

    def _generated(self, mid: str) -> dict:
        """Every model gets a by-name id usable in every lane (Bedrock modelId / Vertex model / Azure deployment):
        'ollama.<tag>' (e.g. ollama.qwen3:8b), 'ollama.<tag without -instruct-q4...>' and the bare tag."""
        tag = self.cat["models"][mid]["ollama"]
        short = tag.split("-instruct")[0].split("-q4")[0]
        return {k: mid for k in {f"ollama.{tag}", f"ollama.{short}", tag, short, f"vyomi.{mid}"}}

    def resolve(self, api_id: Optional[str], *, embed: bool = False) -> str:
        """Cloud API model id / Azure deployment name / catalogue id -> catalogue id (defaults by path kind)."""
        if api_id in self.cat["models"]:
            return api_id
        if api_id:
            if api_id in self._aliases:
                return self._aliases[api_id]
            hits = [k for k in self._aliases if "*" in k and fnmatch.fnmatchcase(api_id, k)]
            if hits:
                return self._aliases[max(hits, key=len)]
        return self.cat["default_embed" if embed else "default_chat"]

    def model_map(self) -> dict:
        """JSON for VYOMI_LLM_MODEL_MAP (llm_core.resolve_model; plain ids and trailing-* prefixes only). The gateway re-resolves
        everything else (fnmatch) from the `model` it receives."""
        return {k: v for k, v in self._aliases.items() if "*" not in k or (k.endswith("*") and k.count("*") == 1)}

    def runner_ids(self) -> list:
        """Every hosted-runner SLOT (a pooled entry counts its slots)."""
        return [sid for ids in self._slots.values() for sid in ids]

    def _spec(self, sid: str) -> dict:
        rid, i = self._slot_base[sid]
        r = self.cat["runners"][rid]
        spec = {"runner": rid, "models": r["models"], "ollama_tags": ",".join(self.cat["models"][m]["ollama"] for m in r["models"])}
        if len(self._slots[rid]) > 1:      # pooled: placeholder transport until the WireGuard mesh (v4/ngmesh) merges
            spec.update(pooled=True, slot=i, slots=len(self._slots[rid]), slot_role="head" if i == 0 else "worker", transport="llama.cpp-rpc over WireGuard mesh (placeholder)")
        return spec

    def _due(self, sid: str, now: float) -> bool:
        """Staggered start: stage N is due N x stagger_s after the window opened (3B+embed and 7B are stage 0)."""
        return now >= self.window_start + int(self.cat["runners"][self._slot_base[sid][0]].get("stage", 0)) * self.stagger_s

    # -------------------------------------------------------------------------------------------- lifecycle
    def start_all(self) -> list:
        """EAGER: dispatch every runner now and open the wall-clock window. Dispatch failures are recorded, not fatal."""
        ids = self.runner_ids()
        if len(ids) > HARD_MAX_RUNNERS:
            raise PoolError(400, "TooManyRunners", f"{len(ids)} runners exceed the sanity max {HARD_MAX_RUNNERS}")
        with self._lock:
            now = self.clock()
            self.phase, self.window_start, self.deadline, self.last_activity = "running", now, now + self.window_s, now
            for rid in ids:
                if self._due(rid, now):
                    self._dispatch(rid, rotation=False)
            self.invalidate()
        return ids

    def _dispatch(self, rid: str, *, rotation: bool) -> None:
        now = self.clock()
        try:
            self.dispatcher.start(rid, self._spec(rid), rotation=rotation)
        except PoolError as e:
            self._event(rid, "dispatch_failed:" + e.code)
            self._rec.setdefault(rid, {"gen_started": now, "was_ready": False, "rotating_since": None})["dispatched_at"] = now - START_TIMEOUT_S + 30   # retry in 30 s
            return
        if rotation and rid in self._rec:
            self._rec[rid]["rotating_since"] = now
            self._event(rid, "rotation_dispatched")
        else:
            self._rec[rid] = {"gen_started": now, "was_ready": False, "rotating_since": None, "dispatched_at": now}
            self._event(rid, "dispatched")

    def _event(self, what: str, ev: str) -> None:
        self._events.append({"runner": what, "event": ev, "at": self.clock()})
        self._events = self._events[-60:]

    def touch(self, kind: str = "console") -> None:
        """Any activity that keeps the pool alive: console use, a VM running/used, an inference request."""
        self.last_activity = self.clock()

    def tick(self) -> dict:
        """Periodic housekeeping (the booster's reaper thread calls it every ~30 s; tests call it with a fake clock):
        window end, 60-min idle destroy, window warnings, runner rotation at 5h30m, self-heal of lost runners."""
        with self._lock:
            if self.phase != "running":
                return {"phase": self.phase}
            now = self.clock()
            if now >= self.deadline:
                self.destroy("window_end")
                return {"phase": self.phase, "why": "window_end"}
            if now - self.last_activity >= self.idle_s:
                self.destroy("idle")
                return {"phase": self.phase, "why": "idle"}
            for w in WARN_AT_S:
                if self.deadline - now <= w and w not in self._warned:
                    self._warned.add(w); self._event("pool", f"window_warning_{w // 60}m")
            hub = self._hub_states()
            for rid in self.runner_ids():
                rec = self._rec.get(rid)
                if rec is None:
                    if self._due(rid, now):
                        self._dispatch(rid, rotation=False)
                    continue
                st = hub.get(rid, "absent")
                if st == "ready":
                    if rec["rotating_since"] is not None and not self._hub["rotating"].get(rid):
                        rec.update(gen_started=rec["rotating_since"], rotating_since=None)          # successor took over
                        self._event(rid, "rotated")
                    rec["was_ready"] = True
                    if rec["rotating_since"] is None and now - rec["gen_started"] >= self.rotate_s and self.deadline - now > 600:
                        self._dispatch(rid, rotation=True)
                    elif rec["rotating_since"] is not None and now - rec["rotating_since"] > START_TIMEOUT_S:
                        rec["rotating_since"] = None; self._event(rid, "rotation_timeout")           # try again next tick
                else:                                                                                 # starting / lost / never came up
                    if rec["was_ready"] and self._hub["ok"]:
                        rec.update(was_ready=False, gen_started=now, dispatched_at=now); self._event(rid, "runner_lost")
                        self._dispatch(rid, rotation=False)
                    elif now - rec["dispatched_at"] > START_TIMEOUT_S:
                        rec["dispatched_at"] = now; self._event(rid, "start_timeout")
                        self._dispatch(rid, rotation=False)
            return {"phase": self.phase}

    def destroy(self, why: str) -> None:
        """Tear down the whole pool (window end / idle / detach): cancel every runner; mark destroyed. Idempotent."""
        with self._lock:
            if self.phase == "destroyed":
                return
            self.phase, self.destroyed_why = "destroyed", why
            for rid in list(self._rec):
                try:
                    self.dispatcher.stop(rid)
                except Exception:
                    pass                          # the runner's own TTL still ends it
            self._rec.clear()
            self._event("pool", "destroyed:" + why)
            self.invalidate()
        if self.on_destroy:
            try:
                self.on_destroy(why)              # e.g. stop the booster (idle) - supplied by the booster
            except Exception:
                pass

    # -------------------------------------------------------------------------------------------- state
    def _hub_states(self) -> dict:
        now = self.clock()
        if now - self._hub["at"] < STATUS_TTL_S:
            return self._hub["runners"]
        try:
            r = urllib.request.urlopen(urllib.request.Request(self.hub + "/_status", headers={"x-vyomi-session-token": self.token_fn()}), timeout=3)
            j = json.loads(r.read())
            self._hub.update(runners=j.get("runners", {}), rotating=j.get("rotating", {}), ok=True)
        except Exception:
            self._hub.update(runners={}, rotating={}, ok=False)
        self._hub["at"] = now
        return self._hub["runners"]

    def invalidate(self) -> None:
        self._hub["at"] = -1e9

    def state(self, model: str) -> str:
        """starting | ready | rotating | draining | stopped  (per catalogue model)."""
        rid = self._model_runner.get(model)
        with self._lock:
            if self.phase == "destroyed":
                return "stopped"
            if rid is None:
                return "stopped"
            slots = self._model_slots[model]
            if any(sl not in self._rec for sl in slots):           # not dispatched yet (staggered) or dispatch failed: still 'starting'
                return "starting"
            if self.phase == "running" and self.deadline - self.clock() <= 0:
                return "draining"
            hub = self._hub_states()
            if any(hub.get(sl, "absent") != "ready" for sl in slots):
                return "starting"
            return "rotating" if any(self._hub["rotating"].get(sl) or self._rec[sl]["rotating_since"] is not None for sl in slots) else "ready"

    # -------------------------------------------------------------------------------------------- console data
    def window(self) -> dict:
        now = self.clock()
        left = max(0.0, self.deadline - now) if self.phase == "running" else 0.0
        warn = next((f"{w // 60}m" for w in sorted(WARN_AT_S) if left <= w), None) if self.phase == "running" else None
        h, m = int(left // 3600), int(left % 3600 // 60)
        return {"phase": self.phase, "start": self.window_start or None, "deadline": self.deadline or None, "left_s": int(left),
                "window_h": self.window_s / 3600.0, "warning": warn, "destroyed_why": self.destroyed_why or None,
                "label": f"Models: {h}h {m:02d}m left of {self.window_s / 3600:g}h" if self.phase == "running" else f"Models: stopped ({self.destroyed_why or 'not started'})",
                "idle_in_s": max(0, int(self.idle_s - (now - self.last_activity))) if self.phase == "running" else None}

    def _endpoints(self, mid: str) -> dict:
        out: dict = {}
        gen = set(self._generated(mid))
        for cloud, m in self.cat.get("aliases", {}).items():
            if cloud.startswith("_"):
                continue
            ids = sorted({k for k, v in m.items() if v == mid and not k.startswith("_")} | gen)
            if ids:
                out[cloud] = ids
        return out

    def models_status(self) -> dict:
        """Data for the Nano console 'Models' panel (GET /booster/ai/models): per model name, role, ollama tag, state, per-cloud API
        ids, last measured tokens/s, plus the wall-clock window (countdown + warnings)."""
        models = []
        for mid, m in self.cat["models"].items():
            rid = self._model_runner[mid]
            r = self.cat["runners"][self._slot_base[rid][0]]
            tps = self._tps.get(mid)
            models.append({"id": mid, "runner": self._slot_base[rid][0], "role": r["role"], "kind": m["kind"], "ollama": m["ollama"], "state": self.state(mid),
                           "slots": len(self._model_slots[mid]), "pooled": len(self._model_slots[mid]) > 1, "stage": int(r.get("stage", 0)),
                           "queued": any(sl not in self._rec for sl in self._model_slots[mid]), "ram_mb": m["ram_mb"], "size_mb": m["size_mb"], "endpoints": self._endpoints(mid),
                           "tokens_per_s": tps["tps"] if tps else None, "requests": self._requests.get(mid, 0)})
        return {"window": self.window(), "models": models, "events": list(self._events[-10:]), "runtime": self.runtime}

    def usage(self) -> dict:
        w = self.window()
        running = [m["id"] for m in self.models_status()["models"] if m["state"] in ("ready", "rotating")]
        return {"phase": self.phase, "runners": len(self._rec), "running": running, "concurrent": len(self._rec), "cap": HARD_MAX_RUNNERS,
                "window": w, "requests": dict(self._requests), "metered": False}

    def observe(self, model: str, body: bytes, elapsed_s: float) -> None:
        """Record tokens/s from a non-streaming reply (OpenAI usage.completion_tokens or Ollama eval_count/eval_duration)."""
        try:
            j = json.loads(body)
            if j.get("eval_count") and j.get("eval_duration"):
                tps = j["eval_count"] / (j["eval_duration"] / 1e9)
            else:
                n = (j.get("usage") or {}).get("completion_tokens")
                tps = n / elapsed_s if n and elapsed_s > 0 else None
            if tps:
                self._tps[model] = {"tps": round(tps, 2), "at": self.clock()}
        except Exception:
            pass

    # -------------------------------------------------------------------------------------------- request path
    def route(self, method: str, path: str, body: Optional[bytes]):
        """('json', status, obj, headers) the gateway answers itself, or ('proxy', hub_base, token, runner_id, body, model)."""
        p = path.split("?", 1)[0].rstrip("/")
        if method == "GET" and p in ("/api/booster/models", "/booster/models"):
            return ("json", 200, self.models_status(), {})
        if method == "GET" and p in ("/v1/models", "/api/tags"):
            ms = self.models_status()["models"]
            if p == "/v1/models":
                return ("json", 200, {"object": "list", "data": [{"id": m["id"], "object": "model", "owned_by": "vyomi-runner", "state": m["state"]} for m in ms]}, {})
            return ("json", 200, {"models": [{"name": m["id"], "state": m["state"]} for m in ms]}, {})
        embed = p in ("/v1/embeddings", "/api/embed", "/api/embeddings")
        hint, j = None, None
        if body:
            try:
                j = json.loads(body)
                hint = j.get("model") if isinstance(j, dict) else None
            except ValueError:
                j = None
        model = self.resolve(hint, embed=embed)
        self.tick()
        with self._lock:
            if self.phase != "running":
                raise PoolError(503, "ModelPoolStopped", f"the model pool is not running ({self.destroyed_why or 'not started'})", None, "stopped")
            st = self.state(model)
            if st in ("starting", "stopped", "draining"):
                raise PoolError(503, "RunnerStarting" if st == "starting" else "RunnerUnavailable",
                                f"model '{model}' is {st} on its runner; retry in ~{RETRY_AFTER_S}s", RETRY_AFTER_S, st)
            self.touch("inference")
            self._requests[model] = self._requests.get(model, 0) + 1
        out = body
        if isinstance(j, dict) and self.runtime == "ollama":
            j["model"] = self.cat["models"][model]["ollama"]
            out = json.dumps(j).encode()
        return ("proxy", self.hub, self.token_fn(), self._model_runner[model], out, model)
