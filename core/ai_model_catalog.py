"""The ONE AI model catalogue every AI console / API lane shows: the ten booster LLM-mesh models.

Single source for: Bedrock ListFoundationModels/GetFoundationModel, Vertex Model Garden (publisher models), Azure OpenAI /
AI Foundry model catalogue + deployments, the Agent Spec / AgentCore / Agent Engine / Guardrails model pickers (they read the
backend lists), on BOTH substrates (offline appliance + Nano/Pyodide: this module is pure stdlib and ships as a Nano core).

Runner side (docker/booster-runner-llm/models.json) owns ollama tags / RAM / runner placement and the per-cloud alias map;
tests/conformance/test_ai_model_catalog.py fails if the ids or the alias map here drift from it. Display names / blurbs mirror
the portal /models page.

Legacy real-vendor ids (anthropic.claude*, gemini-*, gpt-4o ...) are NOT listed anywhere. They still RESOLVE through ALIASES so SDK
code written against the real clouds keeps working; any other id is the cloud's own not-found / validation error.
"""
from __future__ import annotations

import fnmatch

# id, display name, vendor (provider), vertex publisher, kind, size class, role, best-for blurb, ollama tag
_ROWS = [
    ("qwen2.5-3b", "Qwen2.5 3B", "Alibaba", "qwen", "chat", "Small (3B)", "Fast chat", "Quick turns, cheap routing and classification steps", "qwen2.5:3b"),
    ("nomic-embed-text", "Nomic Embed Text", "Nomic AI", "nomic-ai", "embed", "Embedding", "Embeddings", "Vector search and retrieval (RAG) pipelines", "nomic-embed-text"),
    ("qwen2.5-7b", "Qwen2.5 7B", "Alibaba", "qwen", "chat", "Medium (7B)", "General", "General question answering and summaries", "qwen2.5:7b"),
    ("qwen2.5-coder-7b", "Qwen2.5 Coder 7B", "Alibaba", "qwen", "chat", "Medium (7B)", "Code", "Code generation, review and refactoring agents", "qwen2.5-coder:7b"),
    ("llama3.1-8b", "Llama 3.1 8B", "Meta", "meta", "chat", "Medium (8B)", "Tool use / agents", "Function calling and multi-step agent loops", "llama3.1:8b"),
    ("gemma2-9b", "Gemma 2 9B", "Google", "google", "chat", "Medium (9B)", "Second family", "Cross-checking answers against a different model family", "gemma2:9b"),
    ("qwen3-8b", "Qwen3 8B", "Alibaba", "qwen", "chat", "Medium (8B)", "Newer general", "Newer-generation general tasks", "qwen3:8b"),
    ("deepseek-r1-8b", "DeepSeek R1 8B", "DeepSeek", "deepseek-ai", "chat", "Medium (8B)", "Reasoning", "Step-by-step reasoning and problem solving", "deepseek-r1:8b"),
    ("mistral-7b", "Mistral 7B", "Mistral AI", "mistralai", "chat", "Medium (7B)", "Another family", "A third family for agreement and disagreement checks", "mistral:7b"),
    ("qwen3-30b", "Qwen3 30B (MoE)", "Alibaba", "qwen", "chat", "Large (30B MoE)", "Pooled across 2 machines", "The strongest answer in the pool, split over two machines on the private mesh", "qwen3:30b"),
]
MODELS = [dict(id=r[0], name=r[1], vendor=r[2], publisher=r[3], kind=r[4], size=r[5], role=r[6], blurb=r[7], tag=r[8],
               pooled=r[0] == "qwen3-30b") for r in _ROWS]
IDS = [m["id"] for m in MODELS]
BY_ID = {m["id"]: m for m in MODELS}
LOCAL_ID = "qwen2.5-3b"              # the only model that runs without a booster (the in-appliance small model)
DEFAULT_CHAT, DEFAULT_EMBED = "qwen2.5-3b", "nomic-embed-text"
NEEDS_BOOSTER = "Needs Booster (Pro/Max)"

# Hidden compatibility map: cloud API id (or fnmatch pattern) -> catalogue id. Exact match first, then the longest pattern.
# Mirrors docker/booster-runner-llm/models.json "aliases" (drift-tested). Never listed by any console or list API.
ALIASES = {
    "aws": {
        "meta.llama*": "llama3.1-8b", "mistral.*": "mistral-7b", "mistral.mistral-large*": "qwen2.5-7b", "google.gemma*": "gemma2-9b",
        "deepseek.r1*": "deepseek-r1-8b", "qwen.qwen3-30b*": "qwen3-30b", "qwen.qwen3*": "qwen3-8b",
        "amazon.nova-micro*": "qwen2.5-3b", "amazon.nova-lite*": "qwen2.5-3b", "amazon.nova-pro*": "qwen2.5-7b",
        "anthropic.claude*": "qwen2.5-7b", "amazon.titan-embed*": "nomic-embed-text", "cohere.embed*": "nomic-embed-text",
    },
    "gcp": {
        "gemini-*-flash*": "qwen2.5-3b", "gemini-*-pro*": "qwen2.5-7b", "gemma-2*": "gemma2-9b", "gemma*": "gemma2-9b",
        "codestral*": "qwen2.5-coder-7b", "gemini-*-code*": "qwen2.5-coder-7b", "deepseek-r1*": "deepseek-r1-8b",
        "qwen3-235b*": "qwen3-30b", "mistral-*": "mistral-7b", "llama-3*": "llama3.1-8b",
        "text-embedding-*": "nomic-embed-text", "gemini-embedding*": "nomic-embed-text",
    },
    "azure": {
        "gpt-4o-mini*": "qwen2.5-3b", "gpt-4o*": "qwen2.5-7b", "gpt-4*": "qwen2.5-7b", "gpt-35*": "qwen2.5-3b",
        "o1*": "deepseek-r1-8b", "o3*": "qwen3-8b", "DeepSeek-R1*": "deepseek-r1-8b", "Mistral*": "mistral-7b",
        "Meta-Llama*": "llama3.1-8b", "Phi-*": "gemma2-9b", "gpt-oss*": "qwen3-30b", "text-embedding-*": "nomic-embed-text",
    },
}


def _generated(mid):
    tag = BY_ID[mid]["tag"]
    return {f"ollama.{tag}", tag, f"vyomi.{mid}", mid}


_BYNAME = {k: m for m in IDS for k in _generated(m)}


def resolve(cloud, api_id):
    """Cloud API model id / deployment name -> catalogue id, or None (the cloud then answers with its own not-found error)."""
    if not api_id:
        return None
    api_id = str(api_id)
    if api_id in _BYNAME:
        return _BYNAME[api_id]
    al = ALIASES.get(cloud, {})
    if api_id in al:
        return al[api_id]
    hits = [k for k in al if "*" in k and fnmatch.fnmatchcase(api_id, k)]
    return al[max(hits, key=len)] if hits else None


def is_listed_id(cloud, api_id):
    """True when api_id is one of the ten catalogue ids as the cloud lists them (not a hidden compat alias)."""
    return api_id == cloud_id(cloud, BY_ID[resolve(cloud, api_id)]["id"]) if resolve(cloud, api_id) else False


def cloud_id(cloud, mid):
    """How the cloud lists a catalogue model: Bedrock modelId 'vyomi.<id>'; Vertex/Azure use the bare catalogue id."""
    return f"vyomi.{mid}" if cloud == "aws" else mid


def availability(mid):
    """{'state': available | needs_booster | starting | ready | stopped, 'label', 'available': bool}.
    No booster: only the local small model is available. With the booster LLM mesh attached the pool reports each model."""
    st = None
    try:
        try:
            from core import booster_remote_llm as R
        except ImportError:
            R = None
        pool = R.pool() if R is not None and R.active() else None
        if pool is not None:
            st = pool.state(mid)
    except Exception:
        st = None
    if st in ("ready", "rotating"):
        return {"state": "ready", "label": "Ready" if st == "ready" else "Rotating", "available": True}
    if st == "starting":
        return {"state": "starting", "label": "Starting", "available": False}
    if st in ("draining", "stopped"):
        return {"state": "stopped", "label": "Stopped", "available": False}
    if mid == LOCAL_ID:
        return {"state": "available", "label": "Available", "available": True}
    return {"state": "needs_booster", "label": NEEDS_BOOSTER, "available": False}


def listing(cloud):
    """The ten models as one cloud lists them, each with availability: [{id, cloud_id, name, vendor, ..., availability}]."""
    return [dict(m, cloud_id=cloud_id(cloud, m["id"]), availability=availability(m["id"])) for m in MODELS]
