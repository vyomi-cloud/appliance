# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""The ONE AI model catalogue every AI console / API lane shows: the ten mesh LLM-mesh models.

Single source for: Bedrock ListFoundationModels/GetFoundationModel, Vertex Model Garden (publisher models), Azure OpenAI /
AI Foundry model catalogue + deployments, the Agent Spec / AgentCore / Agent Engine / Guardrails model pickers (they read the
backend lists), on BOTH substrates (offline appliance + Nano/Pyodide: this module is pure stdlib and ships as a Nano core).

Runner side (docker/mesh-runner-llm/models.json) owns ollama tags / RAM / runner placement and the per-cloud alias map;
tests/conformance/test_ai_model_catalog.py fails if the ids or the alias map here drift from it. Display names / blurbs mirror
the portal /models page.

Legacy real-vendor ids (anthropic.claude*, gemini-*, gpt-4o ...) are NOT listed anywhere. They still RESOLVE through ALIASES so SDK
code written against the real clouds keeps working; any other id is the cloud's own not-found / validation error.
"""
from __future__ import annotations

import fnmatch
import os
import sys

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
# Nano (Pyodide, no Mesh): the only models are in-browser web LLMs (WebLLM). The ten-model pool exists only on a Mesh appliance.
WEB = sys.platform == "emscripten" or os.environ.get("VYOMI_CATALOG") == "web"
if WEB:
    _ROWS = [
        ("smollm2-360m", "SmolLM2 360M", "Hugging Face", "huggingface", "chat", "Tiny (360M)", "Fast chat", "Runs in your browser, nothing to install", "SmolLM2-360M-Instruct-q4f16_1-MLC"),
        ("qwen2.5-0.5b", "Qwen2.5 0.5B", "Alibaba", "qwen", "chat", "Tiny (0.5B)", "General", "Small general assistant in your browser", "Qwen2.5-0.5B-Instruct-q4f16_1-MLC"),
        ("llama3.2-1b", "Llama 3.2 1B", "Meta", "meta", "chat", "Small (1B)", "Tool use / agents", "Compact instruction model in your browser", "Llama-3.2-1B-Instruct-q4f16_1-MLC"),
        ("qwen2.5-1.5b", "Qwen2.5 1.5B", "Alibaba", "qwen", "chat", "Small (1.5B)", "Better answers", "Largest web LLM; needs a WebGPU laptop", "Qwen2.5-1.5B-Instruct-q4f16_1-MLC"),
        # In-browser embedding model (transformers.js + ONNX, Apache-2.0, ~23 MB q8, 384-d, WASM so no WebGPU needed).
        ("all-minilm-l6-v2", "all-MiniLM-L6-v2", "Sentence Transformers", "sentence-transformers", "embed", "Embedding (23 MB)", "Embeddings",
         "Vector search and retrieval (RAG) in your browser", "Xenova/all-MiniLM-L6-v2"),
    ]
MODELS = [dict(id=r[0], name=r[1], vendor=r[2], publisher=r[3], kind=r[4], size=r[5], role=r[6], blurb=r[7], tag=r[8],
               pooled=r[0] == "qwen3-30b") for r in _ROWS]
IDS = [m["id"] for m in MODELS]
BY_ID = {m["id"]: m for m in MODELS}

# Role models (Mesh only): a small open VISION model and a small open REASONING model, each served by its OWN llama-server
# (core/llm_runtime roles; one role model beside the default chat model so an 8 GB Codespace never holds more). They are NOT part of the
# ten-model pool and are listed ONLY where a server for the role answers (served_special()); anywhere else the id is the cloud's not-found
# error. Nano never serves them (WebLLM has no multimodal/reasoning model registered).
#   id, name, vendor, publisher, role, size class, role label, blurb, local GGUF repo, licence, capabilities
SPECIAL = [
    dict(id="smolvlm-500m", name="SmolVLM 500M (vision)", vendor="Hugging Face", publisher="huggingface", kind="chat", size="Small (0.5B vision)",
         role="Vision", blurb="Reads images and scanned pages: OCR-style text, simple charts, short descriptions. Small model, expect mistakes on dense layouts",
         tag="ggml-org/SmolVLM-500M-Instruct-GGUF:Q8_0", pooled=False, licence="Apache-2.0", caps=["vision"], serve="vision"),
    dict(id="deepseek-r1-1.5b", name="DeepSeek R1 Distill Qwen 1.5B (reasoning)", vendor="DeepSeek", publisher="deepseek-ai", kind="chat", size="Small (1.5B reasoning)",
         role="Reasoning", blurb="Shows its step-by-step reasoning before the answer. A distilled 1.5B model: fine for arithmetic and short logic, weak on long chains",
         tag="bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF:Q4_K_M", pooled=False, licence="MIT", caps=["reasoning"], serve="reasoning"),
]
SPECIAL_IDS = [m["id"] for m in SPECIAL]
ROLE_OF = {m["id"]: m["serve"] for m in SPECIAL}
for _m in SPECIAL:
    BY_ID[_m["id"]] = _m

# Licence + attribution per model (ENGINEERING DRAFT, not legal advice; docs/architecture/v4.0/AI-LICENCE-AUDIT.md). The block between the
# markers is GENERATED from tools/notices/notices.json by tools/notices/gen_notices.py: edit the JSON, not this block.
# BEGIN GENERATED LICENCES
_LICENSE_DATA = {'all-minilm-l6-v2': {'attribution': 'all-MiniLM-L6-v2: Apache License 2.0. Copyright holder: Sentence Transformers.',
                      'aupUrl': '',
                      'builtWithLlama': False,
                      'commercialUse': True,
                      'copyright': 'Sentence Transformers',
                      'license': 'Apache License 2.0',
                      'licenseFlag': '',
                      'licenseId': 'Apache-2.0',
                      'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                      'requiredNotice': '',
                      'upstream': 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2'},
 'deepseek-r1-1.5b': {'attribution': 'DeepSeek R1 Distill Qwen 1.5B (reasoning): MIT License. Copyright (c) 2023 DeepSeek',
                      'aupUrl': '',
                      'builtWithLlama': False,
                      'commercialUse': True,
                      'copyright': 'Copyright (c) 2023 DeepSeek',
                      'license': 'MIT License',
                      'licenseFlag': '',
                      'licenseId': 'MIT',
                      'licenseUrl': 'https://opensource.org/license/mit',
                      'requiredNotice': 'MIT License, Copyright (c) 2023 DeepSeek',
                      'upstream': 'https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B'},
 'deepseek-r1-8b': {'attribution': 'DeepSeek R1 8B: MIT License. Copyright (c) 2023 DeepSeek',
                    'aupUrl': '',
                    'builtWithLlama': False,
                    'commercialUse': True,
                    'copyright': 'Copyright (c) 2023 DeepSeek',
                    'license': 'MIT License',
                    'licenseFlag': '',
                    'licenseId': 'MIT',
                    'licenseUrl': 'https://opensource.org/license/mit',
                    'requiredNotice': 'MIT License, Copyright (c) 2023 DeepSeek',
                    'upstream': 'https://ollama.com/library/deepseek-r1:8b'},
 'gemma2-9b': {'attribution': 'Gemma 2 9B: Gemma Terms of Use. Copyright holder: Google LLC.',
               'aupUrl': 'https://ai.google.dev/gemma/prohibited_use_policy',
               'builtWithLlama': False,
               'commercialUse': True,
               'copyright': 'Google LLC',
               'license': 'Gemma Terms of Use',
               'licenseFlag': '',
               'licenseId': 'LicenseRef-Gemma-Terms',
               'licenseUrl': 'https://ai.google.dev/gemma/terms',
               'requiredNotice': 'Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms',
               'upstream': 'https://ollama.com/library/gemma2:9b'},
 'llama3.1-8b': {'attribution': 'Built with Llama. Llama 3.1 8B, Llama 3.1 Community License.',
                 'aupUrl': 'https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/USE_POLICY.md',
                 'builtWithLlama': True,
                 'commercialUse': True,
                 'copyright': 'Meta Platforms, Inc.',
                 'license': 'Llama 3.1 Community License',
                 'licenseFlag': '',
                 'licenseId': 'LicenseRef-Llama-3.1-Community',
                 'licenseUrl': 'https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE',
                 'requiredNotice': 'Llama 3.1 is licensed under the Llama 3.1 Community License, Copyright (c) Meta Platforms, Inc. All Rights '
                                   'Reserved.',
                 'upstream': 'https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct'},
 'llama3.2-1b': {'attribution': 'Built with Llama. Llama 3.2 1B, Llama 3.2 Community License.',
                 'aupUrl': 'https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/USE_POLICY.md',
                 'builtWithLlama': True,
                 'commercialUse': True,
                 'copyright': 'Meta Platforms, Inc.',
                 'license': 'Llama 3.2 Community License',
                 'licenseFlag': '',
                 'licenseId': 'LicenseRef-Llama-3.2-Community',
                 'licenseUrl': 'https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE',
                 'requiredNotice': 'Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights '
                                   'Reserved.',
                 'upstream': 'https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct'},
 'mistral-7b': {'attribution': 'Mistral 7B: Apache License 2.0. Copyright holder: Mistral AI.',
                'aupUrl': '',
                'builtWithLlama': False,
                'commercialUse': True,
                'copyright': 'Mistral AI',
                'license': 'Apache License 2.0',
                'licenseFlag': '',
                'licenseId': 'Apache-2.0',
                'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                'requiredNotice': '',
                'upstream': 'https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3'},
 'nomic-embed-text': {'attribution': 'Nomic Embed Text v1.5: Apache License 2.0. Copyright holder: Nomic AI.',
                      'aupUrl': '',
                      'builtWithLlama': False,
                      'commercialUse': True,
                      'copyright': 'Nomic AI',
                      'license': 'Apache License 2.0',
                      'licenseFlag': '',
                      'licenseId': 'Apache-2.0',
                      'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                      'requiredNotice': '',
                      'upstream': 'https://huggingface.co/nomic-ai/nomic-embed-text-v1.5'},
 'qwen2.5-0.5b': {'attribution': 'Qwen2.5 0.5B: Apache License 2.0. Copyright holder: Alibaba Cloud (Qwen team).',
                  'aupUrl': '',
                  'builtWithLlama': False,
                  'commercialUse': True,
                  'copyright': 'Alibaba Cloud (Qwen team)',
                  'license': 'Apache License 2.0',
                  'licenseFlag': '',
                  'licenseId': 'Apache-2.0',
                  'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                  'requiredNotice': '',
                  'upstream': 'https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct'},
 'qwen2.5-1.5b': {'attribution': 'Qwen2.5 1.5B: Apache License 2.0. Copyright holder: Alibaba Cloud (Qwen team).',
                  'aupUrl': '',
                  'builtWithLlama': False,
                  'commercialUse': True,
                  'copyright': 'Alibaba Cloud (Qwen team)',
                  'license': 'Apache License 2.0',
                  'licenseFlag': '',
                  'licenseId': 'Apache-2.0',
                  'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                  'requiredNotice': '',
                  'upstream': 'https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct'},
 'qwen2.5-3b': {'attribution': 'Qwen2.5 3B: Qwen RESEARCH LICENSE AGREEMENT (Release Date: September 19, 2024). Copyright holder: Alibaba Cloud.',
                'aupUrl': '',
                'builtWithLlama': False,
                'commercialUse': False,
                'copyright': 'Alibaba Cloud',
                'license': 'Qwen RESEARCH LICENSE AGREEMENT (Release Date: September 19, 2024)',
                'licenseFlag': 'Non-commercial research licence: not for paid use',
                'licenseId': 'LicenseRef-Qwen-Research',
                'licenseUrl': 'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/LICENSE',
                'requiredNotice': 'Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) Alibaba Cloud. All Rights Reserved.',
                'upstream': 'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct'},
 'qwen2.5-7b': {'attribution': 'Qwen2.5 7B: Apache License 2.0. Copyright holder: Alibaba Cloud (Qwen team).',
                'aupUrl': '',
                'builtWithLlama': False,
                'commercialUse': True,
                'copyright': 'Alibaba Cloud (Qwen team)',
                'license': 'Apache License 2.0',
                'licenseFlag': '',
                'licenseId': 'Apache-2.0',
                'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                'requiredNotice': '',
                'upstream': 'https://huggingface.co/Qwen/Qwen2.5-7B-Instruct'},
 'qwen2.5-coder-7b': {'attribution': 'Qwen2.5 Coder 7B: Apache License 2.0. Copyright holder: Alibaba Cloud (Qwen team).',
                      'aupUrl': '',
                      'builtWithLlama': False,
                      'commercialUse': True,
                      'copyright': 'Alibaba Cloud (Qwen team)',
                      'license': 'Apache License 2.0',
                      'licenseFlag': '',
                      'licenseId': 'Apache-2.0',
                      'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                      'requiredNotice': '',
                      'upstream': 'https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct'},
 'qwen3-30b': {'attribution': 'Qwen3 30B (MoE): Apache License 2.0. Copyright holder: Alibaba Cloud (Qwen team).',
               'aupUrl': '',
               'builtWithLlama': False,
               'commercialUse': True,
               'copyright': 'Alibaba Cloud (Qwen team)',
               'license': 'Apache License 2.0',
               'licenseFlag': '',
               'licenseId': 'Apache-2.0',
               'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
               'requiredNotice': '',
               'upstream': 'https://huggingface.co/Qwen/Qwen3-30B-A3B'},
 'qwen3-8b': {'attribution': 'Qwen3 8B: Apache License 2.0. Copyright holder: Alibaba Cloud (Qwen team).',
              'aupUrl': '',
              'builtWithLlama': False,
              'commercialUse': True,
              'copyright': 'Alibaba Cloud (Qwen team)',
              'license': 'Apache License 2.0',
              'licenseFlag': '',
              'licenseId': 'Apache-2.0',
              'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
              'requiredNotice': '',
              'upstream': 'https://huggingface.co/Qwen/Qwen3-8B'},
 'smollm2-135m-instruct': {'attribution': 'SmolLM2 135M Instruct: Apache License 2.0. Copyright holder: Hugging Face.',
                           'aupUrl': '',
                           'builtWithLlama': False,
                           'commercialUse': True,
                           'copyright': 'Hugging Face',
                           'license': 'Apache License 2.0',
                           'licenseFlag': '',
                           'licenseId': 'Apache-2.0',
                           'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                           'requiredNotice': '',
                           'upstream': 'https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct'},
 'smollm2-360m': {'attribution': 'SmolLM2 360M: Apache License 2.0. Copyright holder: Hugging Face.',
                  'aupUrl': '',
                  'builtWithLlama': False,
                  'commercialUse': True,
                  'copyright': 'Hugging Face',
                  'license': 'Apache License 2.0',
                  'licenseFlag': '',
                  'licenseId': 'Apache-2.0',
                  'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                  'requiredNotice': '',
                  'upstream': 'https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct'},
 'smolvlm-500m': {'attribution': 'SmolVLM 500M (vision): Apache License 2.0. Copyright holder: Hugging Face.',
                  'aupUrl': '',
                  'builtWithLlama': False,
                  'commercialUse': True,
                  'copyright': 'Hugging Face',
                  'license': 'Apache License 2.0',
                  'licenseFlag': '',
                  'licenseId': 'Apache-2.0',
                  'licenseUrl': 'https://www.apache.org/licenses/LICENSE-2.0',
                  'requiredNotice': '',
                  'upstream': 'https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct'}}
# END GENERATED LICENCES
for _m in list(MODELS) + SPECIAL:
    _m.update(_LICENSE_DATA.get(_m["id"], {}))
LICENSE_FIELDS = ("license", "licenseId", "licenseUrl", "attribution", "requiredNotice", "commercialUse", "builtWithLlama", "licenseFlag", "aupUrl", "copyright", "upstream")


def paid_tier() -> bool:
    """True when this process serves a paid tier (VYOMI_PAID_TIER=1): models flagged non-commercial are then never selected."""
    return os.environ.get("VYOMI_PAID_TIER", "").strip().lower() in ("1", "true", "yes")


def commercial(mid) -> bool:
    """False for a model whose licence forbids commercial use (qwen2.5-3b: Qwen Research Licence)."""
    return bool(BY_ID.get(mid, {}).get("commercialUse", True))


def default_chat(paid=None):
    """The default chat model. For a paid tier the first commercially usable chat model in catalogue order when the plain default is flagged non-commercial."""
    paid = paid_tier() if paid is None else paid
    d = DEFAULT_CHAT
    if paid and not commercial(d):
        return next((m["id"] for m in MODELS if m["kind"] == "chat" and commercial(m["id"])), d)
    return d


def license_of(mid):
    """The licence/attribution fields of a catalogue model ({} if unknown). Additive vyomi extension for API responses."""
    m = BY_ID.get(mid) or {}
    return {k: m[k] for k in LICENSE_FIELDS if k in m}


def derived_name(name, base_id):
    """Llama naming rule (Llama Community Licence 1.b.i): a model created from Llama Materials carries "Llama" at the start of its name."""
    b = BY_ID.get(str(base_id or "").replace("vyomi.", ""))
    if b and b.get("builtWithLlama") and name and not str(name).lower().startswith("llama"):
        return "Llama-" + str(name)
    return name


def special_served(mid) -> bool:
    """True when this role model is served right now (its llama-server role answers /health). Never on Nano."""
    if WEB or mid not in ROLE_OF:
        return False
    try:
        try:
            from core import llm_core as _llm
        except ImportError:
            import llm_core as _llm  # type: ignore
        return _llm.role_available(ROLE_OF[mid])
    except Exception:  # noqa: BLE001
        return False


def served_special():
    """The role models that are served now (empty when no vision/reasoning pack is running)."""
    return [m for m in SPECIAL if special_served(m["id"])]


def all_models():
    return MODELS + served_special()
WEB_EMBED = "all-minilm-l6-v2"
LOCAL_ID = IDS[0] if WEB else "qwen2.5-3b"   # the model that runs without a mesh (web LLM on Nano, small model on the appliance)
DEFAULT_CHAT, DEFAULT_EMBED = (IDS[0], WEB_EMBED) if WEB else ("qwen2.5-3b", "nomic-embed-text")
NEEDS_MESH = "Needs Mesh (Pro/Max)"

# Hidden compatibility map: cloud API id (or fnmatch pattern) -> catalogue id. Exact match first, then the longest pattern.
# Mirrors docker/mesh-runner-llm/models.json "aliases" (drift-tested). Never listed by any console or list API.
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


if WEB:  # hidden compat aliases may only point at models that exist here
    ALIASES = {c: {k: (v if v in BY_ID else (WEB_EMBED if v == "nomic-embed-text" else IDS[1] if v.startswith("qwen2.5-7b") or "7b" in v or "8b" in v or "9b" in v or "30b" in v else IDS[0]))
                   for k, v in m.items()} for c, m in ALIASES.items()}


def _generated(mid):
    tag = BY_ID[mid]["tag"]
    return {f"ollama.{tag}", tag, f"vyomi.{mid}", mid}


_BYNAME = {k: m for m in IDS for k in _generated(m)}
_SPECIAL_BYNAME = {k: m for m in SPECIAL_IDS for k in _generated(m)}


def resolve(cloud, api_id):
    """Cloud API model id / deployment name -> catalogue id, or None (the cloud then answers with its own not-found error).
    On a paid tier (VYOMI_PAID_TIER=1) a model flagged non-commercial is replaced by the first commercially usable chat model."""
    mid = _resolve(cloud, api_id)
    if mid and paid_tier() and BY_ID.get(mid, {}).get("kind") == "chat" and not commercial(mid):
        return default_chat(True)
    return mid


def _resolve(cloud, api_id):
    if not api_id:
        return None
    api_id = str(api_id)
    if api_id in _SPECIAL_BYNAME:        # role models resolve only while their server is up (otherwise the cloud's not-found error)
        return _SPECIAL_BYNAME[api_id] if special_served(_SPECIAL_BYNAME[api_id]) else None
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
    """{'state': available | needs_mesh | starting | ready | stopped, 'label', 'available': bool}.
    No mesh: only the local small model is available. With the mesh LLM mesh attached the pool reports each model."""
    st = None
    try:
        try:
            from core import mesh_remote_llm as R
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
    if mid in ROLE_OF:
        ok = special_served(mid)
        return {"state": "ready" if ok else "stopped", "label": "Ready (Mesh " + ROLE_OF[mid] + " pack)" if ok else "Not running", "available": ok}
    if WEB:
        return {"state": "available", "label": "Web LLM (in browser)", "available": True}
    if mid == LOCAL_ID:
        return {"state": "available", "label": "Available", "available": True}
    return {"state": "needs_mesh", "label": NEEDS_MESH, "available": False}


def listing(cloud):
    """The ten models as one cloud lists them, each with availability: [{id, cloud_id, name, vendor, ..., availability}]."""
    return [dict(m, cloud_id=cloud_id(cloud, m["id"]), availability=availability(m["id"])) for m in all_models()]
