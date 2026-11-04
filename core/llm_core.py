"""Shared lightweight local-LLM seam (decision family 11). Substrate-independent: no fastapi/boto3 imports, Pyodide-loadable.

One tiny API that every AI surface (Bedrock InvokeModel/Converse, Vertex AI Gemini endpoints, Azure OpenAI deployments,
AI Search vectorization, Document AI enrichment, AgentCore targets, the Copilot) calls:

    chat(messages, system=None, max_tokens=256, temperature=0.7, stop=None) -> {text, input_tokens, output_tokens,
                                                                               finish_reason, backend, model}
    embed(texts) -> {vectors, dimensions, input_tokens, backend, model}
    status() -> {available, backend, model, endpoint, honest_limit}

Backends (first that is configured wins):
  1. a Python callable registered with ``set_backend(fn)``  (tests; Nano's WebLLM bridge when the page provides one),
  2. an OpenAI-compatible HTTP endpoint (``VYOMI_LLM_ENDPOINT``, default offline ``http://vyomi-llm:8080``): llama.cpp
     ``llama-server`` (SmolLM2-360M-Instruct GGUF, ~270 MB) or Ollama's ``/v1`` shim - both speak ``/v1/chat/completions``
     and ``/v1/embeddings``. Reached with urllib (offline substrate only).
No backend -> ``LlmUnavailable`` (callers translate it to the cloud's own ServiceUnavailable/ModelNotReady error). There is
NO canned/echo fallback: a model that is not running never pretends to answer. ``embed`` has one declared exception: when the
backend has no embedding model it returns a deterministic feature-hash embedding (stable, normalised, cosine-comparable,
labelled backend ``vyomi-hash-embed``) so vector search / vectorization keep working without the LLM container.

Honest limit: a <1 GB model is a toy next to the production models these services name; answers are for exercising code
paths (prompting, tool loops, streaming, token accounting), not for quality.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re

DEFAULT_ENDPOINT = "http://vyomi-llm:8080"
DEFAULT_MODEL = "smollm2-360m-instruct"
HASH_DIM = 256
HONEST_LIMIT = ("Answers come from a small (<1 GB) local model - llama.cpp on the offline appliance, WebLLM on Nano when the "
                "browser provides it - so quality is toy-grade; use it to exercise prompts, tool loops, streaming and token accounting.")


class LlmUnavailable(Exception):
    """No local model is reachable (container not started / WebLLM not loaded)."""


_state = {"fn": None, "embed_fn": None, "endpoint": None, "model": None}


def set_backend(fn=None, embed_fn=None, model: str | None = None, endpoint: str | None = None) -> None:
    """Register a Python backend. ``fn(messages, system, max_tokens, temperature, stop) -> str | dict`` (dict may carry
    input_tokens/output_tokens/finish_reason). ``embed_fn(texts) -> list[list[float]]``. Pass nothing to clear."""
    _state.update(fn=fn, embed_fn=embed_fn, model=model, endpoint=endpoint)


def _endpoint() -> str | None:
    if _state["endpoint"]:
        return _state["endpoint"]
    ep = os.environ.get("VYOMI_LLM_ENDPOINT") if hasattr(os, "environ") else None
    if ep:
        return ep.rstrip("/")
    if os.environ.get("VYOMI_LLM_DISABLE") == "1":
        return None
    try:
        import js  # noqa: F401  (Pyodide / Nano: no urllib network path - needs a registered backend)
        return None
    except ImportError:
        return DEFAULT_ENDPOINT


def model_name() -> str:
    return _state["model"] or os.environ.get("VYOMI_LLM_MODEL") or DEFAULT_MODEL


def _http(path: str, payload: dict | None, timeout: float = 120.0):
    import urllib.request
    ep = _endpoint()
    if not ep:
        raise LlmUnavailable("No local LLM backend is available on this substrate.")
    req = urllib.request.Request(ep + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"content-type": "application/json"}, method="GET" if payload is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:  # URLError, timeout, refused, bad JSON
        raise LlmUnavailable(f"Local LLM endpoint {ep} is not reachable ({type(e).__name__}). Start it from the appliance "
                             f"(core/llm_runtime: `vyomi llm start`) or set VYOMI_LLM_ENDPOINT.") from e


def estimate_tokens(text: str) -> int:
    """~4 chars/token fallback when the backend reports no usage (same heuristic Bedrock's own console uses)."""
    return max(1, math.ceil(len(text or "") / 4)) if text else 0


def status(probe: bool = True) -> dict:
    st = {"available": False, "backend": None, "model": model_name(), "endpoint": None, "honest_limit": HONEST_LIMIT}
    if _state["fn"]:
        st.update(available=True, backend="registered", endpoint="in-process")
        return st
    ep = _endpoint()
    st["endpoint"] = ep
    if ep:
        st["backend"] = "openai-compatible"
        if probe:
            try:
                _http("/v1/models", None, timeout=2.0)
                st["available"] = True
            except LlmUnavailable:
                pass
    return st


def _norm_messages(messages, system):
    out = []
    if system:
        out.append({"role": "system", "content": str(system)})
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        out.append({"role": "assistant" if role in ("assistant", "model") else ("system" if role == "system" else "user"),
                    "content": str(content)})
    return out


def chat(messages, system=None, max_tokens=256, temperature=0.7, stop=None, model=None) -> dict:
    msgs = _norm_messages(messages, system)
    if not any(m["role"] == "user" for m in msgs):
        raise ValueError("at least one user message is required")
    max_tokens = max(1, int(max_tokens or 256))
    prompt_text = "\n".join(m["content"] for m in msgs)
    if _state["fn"]:
        r = _state["fn"](msgs, system, max_tokens, temperature, stop)
        info = r if isinstance(r, dict) else {"text": str(r)}
        text = info.get("text", "")
        return {"text": text, "input_tokens": info.get("input_tokens") or estimate_tokens(prompt_text),
                "output_tokens": info.get("output_tokens") or estimate_tokens(text),
                "finish_reason": info.get("finish_reason") or "stop", "backend": "registered", "model": model_name()}
    body = {"model": model or model_name(), "messages": msgs, "max_tokens": max_tokens, "temperature": float(temperature),
            "stream": False}
    if stop:
        body["stop"] = list(stop)[:4]
    r = _http("/v1/chat/completions", body)
    try:
        ch = r["choices"][0]
        text = (ch.get("message") or {}).get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LlmUnavailable("Local LLM endpoint returned an unexpected response.") from e
    u = r.get("usage") or {}
    return {"text": text, "input_tokens": u.get("prompt_tokens") or estimate_tokens(prompt_text),
            "output_tokens": u.get("completion_tokens") or estimate_tokens(text),
            "finish_reason": ch.get("finish_reason") or "stop", "backend": "llama.cpp", "model": r.get("model") or model_name()}


def hash_embed(text: str, dim: int = HASH_DIM) -> list[float]:
    """Deterministic feature-hash bag-of-words(+bigram) embedding, L2-normalised."""
    v = [0.0] * dim
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    for feat in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
        h = int(hashlib.md5(feat.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [round(x / n, 6) for x in v]


def embed(texts, dimensions: int | None = None) -> dict:
    texts = [texts] if isinstance(texts, str) else list(texts)
    toks = sum(estimate_tokens(t) for t in texts)
    vecs = backend = None
    try:
        if _state["embed_fn"]:
            vecs, backend = _state["embed_fn"](texts), "registered"
        elif not _state["fn"] and _endpoint():
            r = _http("/v1/embeddings", {"model": model_name(), "input": texts}, timeout=30.0)
            vecs, backend = [d["embedding"] for d in r["data"]], "llama.cpp"
    except (LlmUnavailable, KeyError, TypeError):
        vecs = None
    if vecs is None:
        vecs, backend = [hash_embed(t) for t in texts], "vyomi-hash-embed"
    if dimensions and vecs and dimensions < len(vecs[0]):
        vecs = [_renorm(v[:dimensions]) for v in vecs]
    return {"vectors": vecs, "dimensions": len(vecs[0]) if vecs else 0, "input_tokens": toks, "backend": backend,
            "model": model_name() if backend != "vyomi-hash-embed" else "vyomi-hash-embed"}


def _renorm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) or 1) * (math.sqrt(sum(y * y for y in b)) or 1))
