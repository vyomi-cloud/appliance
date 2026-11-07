"""Booster AI pack glue: model catalogue, RAM admission against the AI bucket, usage ledger, status (v4/aiboost).

The booster runs a local OpenAI-compatible model server (llama.cpp ``llama-server``, two containers behind
``core/booster_llm_gateway``: one chat model, one embeddings model) and the booster appliance points
``VYOMI_LLM_ENDPOINT`` at the gateway. WebLLM stays the Nano-only fallback (``llm_core`` backend order is unchanged).

This module does NOT touch ``core/llm_core`` source (owned by the seam work); it observes it:

  * ``install()`` wraps ``llm_core.chat`` / ``llm_core.embed`` once and records every call into the ledger. The cloud
    comes from a ContextVar the booster middleware sets from the request path (``cloud_of_path``). If the seam later
    returns something that is not a dict (a stream generator), the call is passed through untouched and only counted
    as a request.
  * the ledger is a TALLY for display and fair-use, not billing: per session, per cloud API, tokens in/out, requests,
    errors, latency, and ``compute_seconds`` (wall clock spent inside the model - the real cost to us).
  * ``admit()`` reserves the model's RAM in ``booster.allocate("ai", ...)``; over budget -> ``ModelAdmissionError``
    with a plain-language reason (never a silent OOM).
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import threading
import time
from collections import deque
from typing import Optional

# id -> {hf: llama.cpp -hf spec, kind, file_mb (download), ram_mb (resident at the default context), ctx, note}
# ram_mb = weights x ~1.15 + KV cache at the stated context. ESTIMATES (not measured on a booster) - see go-live checklist.
MODELS: dict[str, dict] = {
    "qwen2.5-1.5b": {"hf": "Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M", "kind": "chat", "file_mb": 1100, "ram_mb": 1500, "ctx": 4096,
                     "note": "smoke-test option: ~2x faster, tool calls flakier"},
    "qwen2.5-3b": {"hf": "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M", "kind": "chat", "file_mb": 2100, "ram_mb": 2500, "ctx": 4096,
                   "note": "default: best small-model tool-call behaviour under llama.cpp --jinja"},
    "qwen2.5-7b": {"hf": "Qwen/Qwen2.5-7B-Instruct-GGUF:Q4_K_M", "kind": "chat", "file_mb": 4700, "ram_mb": 6200, "ctx": 4096,
                   "note": "opt-in: higher fidelity, 1.5-3 tok/s on 2 cores; needs a >=16 GB host to be admitted"},
    "bge-small": {"hf": "CompendiumLabs/bge-small-en-v1.5-gguf:Q8_0", "kind": "embed", "file_mb": 130, "ram_mb": 250, "ctx": 512, "dims": 384,
                  "note": "default embeddings (384-d); replaces the feature-hash fallback"},
    "nomic-embed-text": {"hf": "nomic-ai/nomic-embed-text-v1.5-GGUF:Q4_K_M", "kind": "embed", "file_mb": 274, "ram_mb": 450, "ctx": 2048, "dims": 768,
                         "note": "better retrieval quality (768-d)"},
}
DEFAULT_CHAT, DEFAULT_EMBED = "qwen2.5-3b", "bge-small"
GATEWAY_ENDPOINT = "http://llm:8080"        # compose service name of core/booster_llm_gateway
PROBE_TTL_S = 5.0


class ModelAdmissionError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


# --------------------------------------------------------------------------- admission
def selected() -> dict:
    return {"chat": os.environ.get("VYOMI_BOOSTER_AI_MODEL", DEFAULT_CHAT).strip().lower() or DEFAULT_CHAT,
            "embed": os.environ.get("VYOMI_BOOSTER_AI_EMBED", DEFAULT_EMBED).strip().lower() or DEFAULT_EMBED}


_ADMIT_LOCK = threading.Lock()
_ADMITTED: dict[str, dict] = {}      # kind -> catalogue entry + id
_ERRORS: dict[str, dict] = {}        # kind -> {code, message}


def _mb(n: int) -> str:
    return f"{n / 1024:.1f} GB" if n >= 1024 else f"{n} MB"


def admit(model_id: str, kind: str = "chat", *, enforce: Optional[bool] = None) -> dict:
    """Reserve `model_id`'s RAM in the AI bucket (replacing any previously admitted model of the same kind)."""
    from core import booster as B
    from core import booster_remote_llm as R
    if R.active():          # the LLM runs on a remote runner: never reserve the local AI bucket (and never load the pack)
        raise ModelAdmissionError("remote_llm_attached", "The LLM is served by a remote runner; the in-booster AI pack stays unloaded. Detach the remote LLM first.")
    m = MODELS.get(model_id)
    if not m or m["kind"] != kind:
        known = ", ".join(sorted(k for k, v in MODELS.items() if v["kind"] == kind))
        raise ModelAdmissionError("unknown_model", f"Unknown {kind} model '{model_id}'. Available {kind} models: {known}.")
    ident = f"model:{kind}"
    try:
        B.allocate("ai", ident, m["ram_mb"], enforce=enforce)
    except B.BoosterCapacityError as e:
        bud = B.resource_budget()
        ai_total = bud["memory_split_mb"]["ai"]
        others = B.usage()["ai"] - B._LEDGER["ai"].get(ident, 0)
        smaller = sorted((k for k, v in MODELS.items() if v["kind"] == kind and v["ram_mb"] < m["ram_mb"]), key=lambda k: -MODELS[k]["ram_mb"])
        hint = f" Try '{smaller[0]}' instead." if smaller else " No smaller model of this kind is available; use a bigger booster host."
        raise ModelAdmissionError(
            "ai_memory_exceeded",
            f"Model '{model_id}' needs about {_mb(m['ram_mb'])} of RAM but only {_mb(e.free_mb)} is free in the booster's AI memory "
            f"({_mb(ai_total)} total = {int(B.CAP_FRACTION * 100)}% of the {_mb(bud['host_memory_mb'])} host x {int(B.AI_SHARE * 100)}% AI share; "
            f"{_mb(others)} already used by other models).{hint}") from e
    with _ADMIT_LOCK:
        _ADMITTED[kind] = {"id": model_id, **m}
        _ERRORS.pop(kind, None)
    return _ADMITTED[kind]


def admit_configured(*, enforce: Optional[bool] = None) -> dict:
    """Admit the env-selected chat + embeddings models. Never raises: failures land in status()['ai']['errors'] so the
    boot script (and the Nano chip) can show the reason."""
    from core import booster_remote_llm as R
    if R.active():
        return plan()
    sel = selected()
    for kind in ("chat", "embed"):
        try:
            admit(sel[kind], kind, enforce=enforce)
        except ModelAdmissionError as e:
            with _ADMIT_LOCK:
                _ADMITTED.pop(kind, None)
                _ERRORS[kind] = {"code": e.code, "message": e.message, "model": sel[kind]}
    return plan()


def release_all() -> None:
    from core import booster as B
    for kind in ("chat", "embed"):
        B.release("ai", f"model:{kind}")
    with _ADMIT_LOCK:
        _ADMITTED.clear()


def plan() -> dict:
    """What the boot script should start: only admitted models. `ok` is False if the chat model was refused."""
    with _ADMIT_LOCK:
        chat, emb = _ADMITTED.get("chat"), _ADMITTED.get("embed")
        from core import booster_remote_llm as R
        if R.active():      # boot script must start NO local model servers
            return {"ok": False, "remote": True, "chat": None, "embed": None, "errors": {}, "endpoint": R.info()["endpoint"]}
        return {"ok": bool(chat), "chat": _pub(chat), "embed": _pub(emb), "errors": dict(_ERRORS), "endpoint": GATEWAY_ENDPOINT}


def _pub(m):
    return {k: m[k] for k in ("id", "hf", "ram_mb", "ctx", "file_mb") if k in m} if m else None


# --------------------------------------------------------------------------- ledger
class Ledger:
    def __init__(self, session: Optional[str] = None):
        self.lock = threading.Lock()
        self.reset(session)

    def reset(self, session: Optional[str] = None) -> None:
        with getattr(self, "lock", threading.Lock()):
            self.session = session or _session_id()
            self.started = time.time()
            self.totals = {"requests": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "estimated_requests": 0, "compute_seconds": 0.0}
            self.by_cloud: dict[str, dict] = {}
            self.by_op: dict[str, dict] = {}
            self.recent: deque = deque(maxlen=50)

    def record(self, *, cloud: str, op: str, model: str, input_tokens: int = 0, output_tokens: int = 0,
               latency_ms: float = 0.0, status: str = "ok", estimated: bool = False) -> None:
        with self.lock:
            for bucket in (self.totals, self.by_cloud.setdefault(cloud, _zero()), self.by_op.setdefault(f"{cloud}:{op}", _zero())):
                bucket["requests"] += 1
                bucket["errors"] += 0 if status == "ok" else 1
                bucket["input_tokens"] += int(input_tokens)
                bucket["output_tokens"] += int(output_tokens)
                bucket["estimated_requests"] += 1 if estimated else 0
                bucket["compute_seconds"] = round(bucket["compute_seconds"] + latency_ms / 1000.0, 3)
            self.recent.append({"ts": round(time.time(), 3), "cloud": cloud, "op": op, "model": model, "input_tokens": int(input_tokens),
                                "output_tokens": int(output_tokens), "latency_ms": round(latency_ms, 1), "status": status,
                                "estimated": estimated})

    def summary(self, recent: int = 20) -> dict:
        with self.lock:
            return {"session": self.session, "started": round(self.started, 3), "uptime_s": round(time.time() - self.started, 1),
                    "totals": {**self.totals, "total_tokens": self.totals["input_tokens"] + self.totals["output_tokens"]},
                    "by_cloud": {k: dict(v) for k, v in self.by_cloud.items()},
                    "by_op": {k: dict(v) for k, v in self.by_op.items()},
                    "recent": list(self.recent)[-recent:] if recent else [],
                    "note": "A tally for display and fair-use, not billing. 'estimated' = the backend reported no token counts (len/4)."}


def _zero() -> dict:
    return {"requests": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0, "estimated_requests": 0, "compute_seconds": 0.0}


def _session_id() -> str:
    seed = os.environ.get("VYOMI_BOOSTER_SESSION_END") or os.environ.get("VYOMI_BOOSTER_SESSION_TOKEN") or ""
    return hashlib.sha256(f"{seed}|{os.environ.get('VYOMI_INSTALL_ID', '')}|{int(time.time())}".encode()).hexdigest()[:12] if not seed else \
        hashlib.sha256(seed.encode()).hexdigest()[:12]


LEDGER = Ledger()
CLOUD: "contextvars.ContextVar[str]" = contextvars.ContextVar("booster_ai_cloud", default="unknown")
OP: "contextvars.ContextVar[str]" = contextvars.ContextVar("booster_ai_op", default="")


def cloud_of_path(path: str) -> str:
    """Which cloud's AI front end a request path belongs to ('' when it is not an AI path)."""
    p = (path or "").split("?", 1)[0]
    if "/publishers/" in p and "/models/" in p or "/aiplatform" in p or "/endpoints/" in p and "/projects/" in p:
        return "gcp"
    if p.startswith(("/openai/", "/azure-data/openai/")) or "/openai/deployments/" in p:
        return "azure"
    if p.startswith(("/model/", "/agents", "/knowledgebases", "/retrieveAndGenerate", "/agent-runtime", "/guardrail", "/inference-profiles")) \
            or p.startswith("/agents/") or "/knowledgebases/" in p or p.startswith(("/foundation-models", "/async-invoke")):
        return "aws"
    return ""


def op_of_path(path: str) -> str:
    p = (path or "").split("?", 1)[0].rstrip("/")
    tail = p.rsplit("/", 1)[-1]
    return tail.split(":", 1)[-1] if ":" in tail else tail


_INSTALLED = {"done": False}


def install() -> bool:
    """Wrap llm_core.chat/embed once so every model call lands in the ledger. Idempotent. Returns True if newly installed."""
    from core import llm_core
    if getattr(llm_core.chat, "_vyomi_ledger", False):
        return False
    real_chat, real_embed = llm_core.chat, llm_core.embed

    def _rec(kind, fn, args, kwargs):
        t0 = time.monotonic()
        cloud, op = CLOUD.get(), OP.get() or kind
        try:
            r = fn(*args, **kwargs)
        except llm_core.LlmUnavailable:
            LEDGER.record(cloud=cloud, op=op, model=llm_core.model_name(), latency_ms=(time.monotonic() - t0) * 1000, status="unavailable")
            raise
        except Exception:
            LEDGER.record(cloud=cloud, op=op, model=llm_core.model_name(), latency_ms=(time.monotonic() - t0) * 1000, status="error")
            raise
        ms = (time.monotonic() - t0) * 1000
        if isinstance(r, dict):
            backend = str(r.get("backend") or "")
            LEDGER.record(cloud=cloud, op=op, model=str(r.get("model") or llm_core.model_name()),
                          input_tokens=r.get("input_tokens") or 0, output_tokens=r.get("output_tokens") or 0, latency_ms=ms,
                          estimated=backend in ("registered", "webllm", "vyomi-hash-embed"))
        else:   # a streaming generator or other shape from a newer seam: count the request, cannot know tokens yet
            LEDGER.record(cloud=cloud, op=op, model=llm_core.model_name(), latency_ms=ms, estimated=True)
        return r

    def chat(*a, **k):
        return _rec("chat", real_chat, a, k)

    def embed(*a, **k):
        return _rec("embed", real_embed, a, k)

    chat._vyomi_ledger = embed._vyomi_ledger = True
    chat.__wrapped__, embed.__wrapped__ = real_chat, real_embed
    llm_core.chat, llm_core.embed = chat, embed
    return True


def uninstall() -> None:
    from core import llm_core
    if getattr(llm_core.chat, "_vyomi_ledger", False):
        llm_core.chat, llm_core.embed = llm_core.chat.__wrapped__, llm_core.embed.__wrapped__


def point_llm_at_gateway() -> Optional[str]:
    """Booster appliance -> local model server. Honour an explicit VYOMI_LLM_ENDPOINT; otherwise, on a booster with an
    admitted chat model, use the gateway. Returns the endpoint now in effect (None = untouched)."""
    if os.environ.get("VYOMI_LLM_ENDPOINT"):
        return os.environ["VYOMI_LLM_ENDPOINT"]
    from core import booster_remote_llm as R
    if R.active():
        return R.info()["endpoint"]
    if _ADMITTED.get("chat"):
        os.environ["VYOMI_LLM_ENDPOINT"] = GATEWAY_ENDPOINT
        os.environ.setdefault("VYOMI_LLM_MODEL", _ADMITTED["chat"]["id"])
        return GATEWAY_ENDPOINT
    return None


# --------------------------------------------------------------------------- status
_PROBE = {"at": 0.0, "up": False}


def _probe() -> bool:
    now = time.monotonic()
    if now - _PROBE["at"] < PROBE_TTL_S:
        return _PROBE["up"]
    from core import llm_core
    try:
        up = bool(llm_core.status(probe=True).get("available"))
    except Exception:
        up = False
    _PROBE.update(at=now, up=up)
    return up


def status(recent: int = 10) -> dict:
    from core import llm_core
    from core import booster_remote_llm as R
    if R.active():
        ri = R.info()
        st = ri["runner"]
        u = LEDGER.summary(recent)
        state = {"ready": "ready", "starting": "starting"}.get(st, "unavailable")
        return {"state": state, "endpoint": ri["endpoint"], "backend": "remote-runner", "mode": "remote", "runner": st,
                "label": ri["label"], "models": {}, "errors": {}, "usage": u,
                "chip": "AI: remote (runner)" + ("" if state == "ready" else f" - {st}")}
    with _ADMIT_LOCK:
        models = {k: _pub(v) for k, v in _ADMITTED.items()}
        errors = dict(_ERRORS)
    ep = llm_core._endpoint()
    state = "ready" if _probe() else ("refused" if errors.get("chat") else ("starting" if models.get("chat") else "off"))
    u = LEDGER.summary(recent)
    return {"state": state, "endpoint": ep, "backend": "booster-llama.cpp" if ep else "none", "models": models, "errors": errors,
            "usage": u, "chip": chip_line(u, state)}


def chip_line(u: dict, state: str) -> str:
    t = u["totals"]
    if state == "refused":
        return "AI: model refused (see status)"
    if state != "ready":
        return "AI: " + state
    return f"AI: {t['requests']} req · {_human(t['total_tokens'])} tok"


def _human(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
