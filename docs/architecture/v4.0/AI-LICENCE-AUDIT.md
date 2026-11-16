# AI model and OSS licence audit (paid hosted Mesh)

Date: 2026-11-16. Branch: `v4/ai-licences`. Scope: every model Vyomi serves or bundles, plus the other OSS we vendor or ship.

**This is an engineering audit, not legal advice.** It reads primary sources (model cards and licence texts, fetched 2026-11-16) and reports what they say. Counsel must confirm the items in section 6 before the owner charges for hosted Mesh.

Sources of the model list: `core/ai_model_catalog.py` (Mesh pool of 10, Nano web pool of 5, two special role models), `docker/mesh-runner-llm/models.json` (exact Ollama tags), `trainer/lora_train.py` (SmolLM2-135M base). "Paid hosting" means: Vyomi runs the weights on its infrastructure (Mesh Codespace / runner) and customers pay Vyomi, or Vyomi ships the weights to the customer's browser or machine inside a paid product.

## 1. Headline: one model is NOT cleared for paid use

> **RESOLVED 2026-11-16 (branch `v4/ai-qwen3swap`, engineering draft, not legal advice):** the Mesh default chat model, the "fast" runner, the in-Codespace AI pack and the `amazon.nova-micro/lite`, `gemini-*-flash`, `gpt-4o-mini`, `gpt-35` aliases now point at **Qwen3-4B-Instruct-2507, Apache-2.0** (HF model card metadata `apache-2.0`; LICENSE file = Apache License 2.0, Copyright 2024 Alibaba Cloud), served from the Q4_K_M GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF`. `qwen2.5-3b` stays in the catalogue flagged non-commercial, is on no runner, is never a default and is refused on a paid tier. The default no longer depends on `VYOMI_PAID_TIER`. The section below is kept as the original finding. See `branches/ai-qwen3swap.md`.

**Qwen2.5-3B-Instruct (`qwen2.5-3b`) is under the "Qwen RESEARCH LICENSE AGREEMENT" (Release Date: September 19, 2024), non-commercial only.**
It is the Mesh default chat model (`DEFAULT_CHAT`, `LOCAL_ID`), the "fast" runner model, the in-Codespace AI pack model, the target of the `amazon.nova-micro*` and `amazon.nova-lite*` aliases, and the default LoRA training target in the Mesh docs.

- HF metadata for `Qwen/Qwen2.5-3B-Instruct`: "License: qwen-research". The Ollama page `qwen2.5:3b` also shows "Qwen RESEARCH LICENSE AGREEMENT" and notes the 3B is under the Qwen licence rather than Apache 2.0.
- Clause 2(a): grant is "FOR NON-COMMERCIAL PURPOSES ONLY"; 1(i) defines Non-Commercial as "for research or evaluation purposes only"; 2(b): "If you are commercially using the Materials, you shall request a license from us."
- Source: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/LICENSE and https://ollama.com/library/qwen2.5:3b
- The same clause also covers any LoRA or fine-tune derived from the 3B weights.

**Action required before charging:** stop serving `qwen2.5-3b` in any paid tier, or obtain a commercial licence from Alibaba Cloud (the licence says to request one).

**Proposed replacement.** The brief asks for a catalog replacement. Nothing in today's catalog is both Apache-2.0 and 3B-sized, so there are two options:
1. In catalog, no new weights: point the fast/default slot at `qwen2.5-7b` (Apache-2.0, ~6.2 GB RAM per models.json; heavier than the 3B's 2.8 GB, so it will not fit alongside the embedder on an 8 GB Codespace) or `qwen3-8b` (Apache-2.0).
2. Recommended: add `Qwen/Qwen3-4B-Instruct-2507` (Apache-2.0 per its HF metadata, 4.0B params, non-thinking, Q4 about 2.5 GB, comparable footprint to the 3B). Needs a catalog entry, an Ollama or GGUF tag, and a quality/RAM check on the Mesh. Not done in this lane (engines and catalog untouched, per the brief).
For the trainer/LoRA docs that name the 3B as a target, use `qwen2.5-1.5b` or `smollm2-*` (both Apache-2.0) or the replacement above.

Everything else in the catalog is usable commercially, with the conditions below.

## 2. Model table

Paid-hosting key: YES = permitted; YES+ = permitted with conditions that Vyomi must implement; NO = not cleared.

| Model (catalog id) | Where | Licence (version) and primary source | Commercial / paid hosting | Conditions | Action required |
|---|---|---|---|---|---|
| Qwen2.5 3B (`qwen2.5-3b`) | Mesh default, fast runner, AI pack | Qwen Research License, 2024-09-19. https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/LICENSE | **NO** (non-commercial only) | Commercial use needs a licence from Alibaba Cloud. If kept for research tiers: ship the licence copy and the Notice "Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) Alibaba Cloud. All Rights Reserved." | **Remove from paid tiers; replace (section 1).** |
| Qwen2.5 7B (`qwen2.5-7b`) | Mesh | Apache-2.0. https://huggingface.co/Qwen/Qwen2.5-7B-Instruct | YES | Keep licence text and NOTICE; state changes if modified. | Notices page entry. |
| Qwen2.5 Coder 7B (`qwen2.5-coder-7b`) | Mesh | Apache-2.0. https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct | YES | As above. | Notices page entry. |
| Qwen3 8B (`qwen3-8b`) | Mesh | Apache-2.0. https://huggingface.co/Qwen/Qwen3-8B | YES | As above. | Notices page entry. |
| Qwen3 30B-A3B (`qwen3-30b`) | Mesh pooled | Apache-2.0. https://huggingface.co/Qwen/Qwen3-30B-A3B | YES | As above. | Notices page entry. |
| Qwen2.5 0.5B / 1.5B (`qwen2.5-0.5b`, `qwen2.5-1.5b`) | Nano WebLLM | Apache-2.0 (base cards https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct, https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct). The MLC repos (https://huggingface.co/mlc-ai/Qwen2.5-1.5B-Instruct-q4f16_1-MLC) state the licence is inherited from the base model. | YES | As Apache-2.0. Note: only the 0.5B, 1.5B, 7B, 14B, 32B are Apache; 3B (and 72B) are not. Never swap a 3B into the Nano list. | Notices entry. Add a test that fails if a `qwen2.5-3b` tag appears in a paid catalog. |
| Llama 3.2 1B (`llama3.2-1b`) | Nano WebLLM | Llama 3.2 Community License. https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_2/LICENSE (the MLC repo https://huggingface.co/mlc-ai/Llama-3.2-1B-Instruct-q4f16_1-MLC names meta-llama/Llama-3.2-1B-Instruct as base and gives no licence of its own) | YES+ | 1.b.i: "provide a copy of this Agreement with any such Llama Materials"; "prominently display 'Built with Llama' on a related website"; any distributed AI model created/fine-tuned from it must include "Llama" at the start of its name. 1.b.iii Notice: "Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved." 1.b.iv must follow the Acceptable Use Policy. 2: licensee with "greater than 700 million monthly active users in the preceding calendar month" must request a licence from Meta. 6: Meta may terminate on breach. | Show "Built with Llama" + notice + licence link + AUP link; flow AUP into customer terms; name any Llama-derived tuned model "Llama ...". The 700M MAU clause does not bite Vyomi today (counsel to confirm how it applies to customers who embed Vyomi). |
| Llama 3.1 8B (`llama3.1-8b`) | Mesh | Llama 3.1 Community License (Release Date July 23, 2024). https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_1/LICENSE | YES+ | Same structure as 3.2. Notice text: "Llama 3.1 is licensed under the Llama 3.1 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved." AUP at https://llama.meta.com/llama3_1/use-policy. | Same as 3.2; keep 3.1 and 3.2 notices separate (different licence texts). |
| Gemma 2 9B (`gemma2-9b`) | Mesh | Gemma Terms of Use (Ollama/HF copy shows "Last modified: February 21, 2024"; ai.google.dev now shows "Last modified: April 1, 2026") + Gemma Prohibited Use Policy (last modified Feb 21, 2024). https://ai.google.dev/gemma/terms , https://ai.google.dev/gemma/prohibited_use_policy , https://ollama.com/library/gemma2:9b | YES+ | 2.2 use only per the Agreement. 3.1(1): must include the Section 3.2 use restrictions "as an enforceable provision in any agreement" with recipients. 3.1(2): "provide all third party recipients of Gemma or Model Derivatives a copy of this Agreement." 3.1(4) notice: "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms". 3.2: "Google reserves the right to restrict (remotely or otherwise) usage of any of the Gemma Services". 3.3: "Google claims no rights in Outputs." Prohibited uses include sexual chatbots, automated decisions affecting rights, safety-filter circumvention, and "You may not use nor allow others to use". | Customer terms must flow down the PUP. Show the notice and link. Counsel: which Terms version governs the weights we pull (Feb 2024 vs the April 2026 page), and how the remote-restriction right interacts with our SLA. This is the most restrictive model that remains in the catalog; consider dropping it if flow-down is unwanted. |
| Mistral 7B (`mistral-7b`) | Mesh | Apache-2.0 (Mistral-7B-Instruct-v0.3 card https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3; Ollama tag page shows "Apache License Version 2.0") | YES | Apache-2.0 notice. Ollama tag `mistral:7b-instruct-q4_K_M` is an older upload (page says "Updated 2 years ago"; could be v0.1/0.2); v0.1, v0.2 and v0.3 are all Apache-2.0 but confirm the exact blob's licence file at pull time. | Notices entry; pin and record the pulled digest. |
| DeepSeek R1 8B (`deepseek-r1-8b`) | Mesh | MIT. Ollama `deepseek-r1:8b` is "DeepSeek-R1-0528-Qwen3-8B" (arch qwen3), licence shown "MIT License Copyright (c) 2023 DeepSeek"; derived from Qwen3 (Apache-2.0). https://ollama.com/library/deepseek-r1:8b | YES | MIT notice plus Apache-2.0 notice for the Qwen3 base. Trap: the older DeepSeek-R1-Distill-Llama-8B is Llama-3.1-derived and would carry the Llama licence; the pinned tag must stay the Qwen3 one. | Pin the tag (`deepseek-r1:8b` alias can move); test that the architecture is qwen3. |
| DeepSeek-R1-Distill-Qwen-1.5B (`deepseek-r1-1.5b`) | Mesh reasoning role | MIT. https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B ("This code repository and the model weights are licensed under the MIT License."; "DeepSeek-R1 series support commercial use, allow for any modifications and derivative works"; derived from Qwen2.5 series, Apache-2.0; HF base: Qwen2.5-Math-1.5B) | YES | MIT + Apache-2.0 notices. | Notices entry. |
| SmolVLM-500M-Instruct (`smolvlm-500m`) | Mesh vision role | Apache-2.0. https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct ("We release the SmolVLM checkpoints under the Apache 2.0 license.") Components: SigLIP encoder (google/siglip-base-patch16-512) and SmolLM2 decoder; their licences are not stated on the card (SigLIP is Apache-2.0 per its own card; not re-verified here). | YES | Apache notice. | Counsel/ops: confirm SigLIP card. |
| SmolLM2 360M (`smollm2-360m`) | Nano WebLLM default | Apache-2.0. https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct (card lists FineWeb-Edu, DCLM, The Stack, smol-smoltalk, UltraFeedback and other datasets without per-dataset licences) | YES | Apache notice. Training-data provenance is the publisher's. | Notices entry. |
| SmolLM2 135M | Trainer base (LoRA) | Apache-2.0 (same family). https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct | YES | A LoRA adapter is a derivative: Apache notice; no naming rule. | Notices entry. |
| nomic-embed-text v1.5 (`nomic-embed-text`) | Mesh embedder | Apache-2.0. https://huggingface.co/nomic-ai/nomic-embed-text-v1.5 (training data released; per-dataset licences not stated on the card) | YES | Apache notice. Ollama's `nomic-embed-text:latest` is v1.5. | Notices entry. |
| all-MiniLM-L6-v2 (`all-minilm-l6-v2`) | Nano embedder (transformers.js, ONNX via Xenova) | Apache-2.0. https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 (fine-tuned on 1B+ sentence pairs incl. Reddit comments, S2ORC, MS MARCO, Yahoo Answers; dataset licences not stated) | YES (model licence) | Apache notice. Training-data provenance is a publisher-level risk common to the whole ecosystem. | Notices entry; counsel to accept the residual data-provenance risk. |

Notes that apply to all rows:
- Outputs: Qwen, Apache and MIT texts impose no output restriction. Gemma 3.3 says Google claims no rights in outputs; Llama licences do not claim outputs but the AUP applies.
- "Powered by"/endorsement: showing model names (Llama, Gemma, Qwen, Mistral, DeepSeek) is nominative use. Do not imply Meta, Google, AWS, Alibaba or Mistral endorse Vyomi. The Bedrock alias `meta.llama*` -> `llama3.1-8b` is an API-compatibility map: the response must not claim the model is AWS-hosted Meta.
- Distribution path: Nano pulls weights from Hugging Face / MLC CDNs directly in the user's browser; Mesh pulls from Ollama / Hugging Face into the customer's Codespace. If Vyomi ever mirrors weights on its own storage or an image, it becomes a redistributor and the "copy of the Agreement" and Notice-file duties apply to the artifact itself (Llama 1.b.i/iii, Gemma 3.1, Apache 4). Counsel to confirm whether the current pull-from-upstream design leaves Vyomi only as a user of the models for each licence.
- LoRA / tuned models: Llama-derived tuned models must be named "Llama ..." (1.b.i). Gemma-derived are "Model Derivatives" (flow-down + notice). Qwen2.5-3B derivatives inherit the research-only restriction.

## 3. Required attribution text (verbatim from the sources)

Include these in the product Notices (section 5) and in every distributed Notice file:

- Llama 3.2: "Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved."
- Llama 3.1: "Llama 3.1 is licensed under the Llama 3.1 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved."
- Visible label near any Llama-powered UI/docs: "Built with Llama"
- Gemma: "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms"
- Qwen (only if the 3B research model is kept for a non-commercial tier): "Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) Alibaba Cloud. All Rights Reserved."
- Apache-2.0 models (Qwen2.5 0.5B/1.5B/7B/Coder, Qwen3, Mistral, SmolLM2, SmolVLM, nomic-embed, MiniLM): keep the licence text and any upstream NOTICE; name the licence, copyright holder and source link.
- MIT (DeepSeek-R1 distills): "MIT License, Copyright (c) 2023 DeepSeek" plus the full MIT text.

## 4. Other OSS we vendor or ship (lighter pass)

Verified by fetch unless marked "from knowledge, confirm".

| Component | Licence | Risk | Note |
|---|---|---|---|
| llama.cpp (`ghcr.io/ggml-org/llama.cpp:server`, Mesh) | MIT (from knowledge; confirm) | Low | Attribution in Notices. |
| wllama 3.13.0 (Nano chat import) | MIT (https://github.com/ngxson/wllama) | Low | |
| WebLLM (Nano) | Apache-2.0 (https://github.com/mlc-ai/web-llm) | Low | |
| transformers.js (Nano embedder) | Apache-2.0 (https://github.com/huggingface/transformers.js) | Low | ONNX runtime: MIT (from knowledge). |
| @xyflow/react 12.3.5 | MIT (from knowledge, confirm) | Low | Attribution/licence text. |
| Cloudscape, MUI, Fluent UI, React, umap-js, esbuild | Apache-2.0 / MIT (from knowledge) | Low | Collect with a licence-checker over `consoles/package.json`. |
| cedarpy / cedar-wasm | Apache-2.0 (from knowledge) | Low | |
| pypdf | BSD-3-Clause (from knowledge) | Low | |
| moto, hvac, nats-py, boto3, docker-py, pyarrow, cryptography, PyJWT, httpx, fastapi, uvicorn | Apache-2.0 / MIT / BSD (from knowledge) | Low | Run `pip-licenses` in the release pipeline. |
| psycopg2-binary | LGPL-3.0 with exceptions (from knowledge) | Low-medium | Dynamic linking and unmodified use is normal; keep the LGPL notice and let users replace it. |
| **MinIO** (`vyomi/minio`, built from source) | **GNU AGPL v3.0.** https://github.com/minio/minio : "MinIO source is licensed under the GNU AGPLv3"; "THIS REPOSITORY IS NO LONGER MAINTAINED"; archived 2026-04-25; "distributed as source code only" | **Highest of the infra pieces** | Running an UNMODIFIED build as a separate service is generally fine, but we redistribute images, so we must offer the corresponding source (pinned tag `RELEASE.2025-09-07T16-13-09Z` + our Dockerfile) with the image/notice. Any patch to MinIO we host to network users triggers AGPL s.13 source offer to those users. Upstream is unmaintained (no security fixes). Recommendation: plan a swap to an Apache-2.0 S3 backend (for example SeaweedFS, not evaluated here) before charging; counsel to review AGPL posture meanwhile. |
| FRRouting (planned hybrid-edge, `V4-WAVES-5-8-PLAN`) | GPL-2.0-or-later (from knowledge, confirm) | Medium if redistributed | Separate container/process, unmodified: fine, but shipping the image obliges a GPL source offer and licence text. Not in compose yet. |
| MySQL 8.0 image | GPL-2.0 (from knowledge) | Low-medium | Unmodified upstream image pulled by the user; separate process. |
| Postgres + pgvector (`vyomi/postgres:16-alpine-pgvector`) | PostgreSQL Licence (permissive) (from knowledge) | Low | We rebuild the image: keep notices. PGlite (Nano): Apache-2.0 / PostgreSQL (from knowledge). |
| HashiCorp Vault 1.15 | MPL-2.0 for 1.15 (HashiCorp moved later releases to BUSL-1.1; page fetch did not state the cutoff, from knowledge) | Medium on upgrade | Pin to 1.15.x. BUSL forbids competing hosted offerings, so do NOT upgrade past the MPL line without counsel. Consider OpenBao (MPL-2.0 fork). |
| `amazon/dynamodb-local:latest` | Amazon proprietary terms, not an OSS licence (from knowledge) | **Needs review** | Pulled at runtime by the user's Docker, but a paid hosted product that runs it for customers is a use of Amazon software under its terms. Counsel to read the DynamoDB Local terms; the alternative is the existing moto/own DynamoDB engine. |
| Google Cloud SDK emulators image | Google Cloud SDK terms / Apache-2.0 (from knowledge) | Medium | Same question as DynamoDB Local. |
| Azurite (MIT), fake-gcs-server (BSD/MIT), elasticmq (Apache-2.0), NATS (Apache-2.0), Caddy (Apache-2.0), Valkey (BSD-3), VictoriaMetrics (Apache-2.0), registry (Apache-2.0) | permissive (from knowledge) | Low | |
| Vyomi's own `LICENSE` | Source-available licence with Additional Use Grant forbidding hosted or managed offerings of the Licensed Work by others | n/a | Consistent with the owner running the hosted Mesh; make sure Notices states third-party components keep their own licences. |

Not found in this checkout: a THIRD-PARTY-NOTICES file, a NOTICE file, or an SBOM. Generate one in CI.

## 5. Recommended in-product "Notices and model licences" page text

> **Notices and model licences**
>
> Vyomi runs open models and open-source software. Each keeps its own licence. Nothing here implies that the model makers or any cloud vendor endorse Vyomi.
>
> **Models**
> - Llama 3.1 8B (Mesh) and Llama 3.2 1B (Nano). **Built with Llama.** Llama 3.1 is licensed under the Llama 3.1 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved. Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved. Use of these models is subject to Meta's Acceptable Use Policy. [links to both licences and the AUP]
> - Gemma 2 9B. Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms. Use of Gemma is subject to the Gemma Prohibited Use Policy, which also applies to your use of Vyomi. Google may restrict use of Gemma as set out in those terms.
> - Qwen2.5 0.5B / 1.5B / 7B / Coder 7B and Qwen3 8B / 30B (Alibaba Cloud / Qwen team), Mistral 7B (Mistral AI), SmolLM2 and SmolVLM (Hugging Face), nomic-embed-text (Nomic AI), all-MiniLM-L6-v2 (Sentence Transformers): Apache License 2.0. [links to the licence text and each model card]
> - DeepSeek-R1 distilled models (DeepSeek-AI): MIT License, Copyright (c) 2023 DeepSeek; derived from Qwen (Apache-2.0).
> - Models are third-party open-weight models running on Vyomi infrastructure or in your browser. They are not the vendor's hosted API models. Outputs can be wrong; review them before relying on them.
>
> **Software**
> llama.cpp, wllama, WebLLM, transformers.js, ONNX Runtime, moto, Cedar, pypdf, xyflow, React and the other packages listed in the full third-party list are used under their MIT, BSD or Apache-2.0 licences. MinIO is used under AGPL v3; the corresponding source and our build recipe are at [link]. [FRR / GPL components: source link, when shipped.]
>
> Full licence texts and the complete third-party list: [link to THIRD-PARTY-NOTICES]. Customer terms must also pass on the Llama Acceptable Use Policy and the Gemma Prohibited Use Policy.

If the 3B research model is kept for a free or non-commercial tier, add the Qwen Notice from section 3 and label the tier "non-commercial use only".

## 6. What counsel must confirm

1. Whether serving `qwen2.5-3b` anywhere customers pay (including as the free tier of a paid product) is outside "non-commercial", and whether to buy a licence from Alibaba Cloud instead of replacing it.
2. Llama 3.1 and 3.2: that a hosted API/console meets "Built with Llama" ("on a related website"), that the AUP flow-down in customer terms is sufficient, how the 700M MAU test applies to Vyomi and to customers, and the naming rule for tuned derivatives. Also that Llama 3.2's regional (EU) restriction applies only to the multimodal 3.2 models and not the text-only 1B (not verified here; the fetched text did not show it).
3. Gemma: which Terms version governs the weights we pull (Feb 2024 vs the April 2026 page), the enforceable flow-down of the Prohibited Use Policy, and Google's right to restrict use remotely. Decide whether Gemma is worth keeping.
4. Whether pull-from-upstream (HF/Ollama into the user's browser or Codespace) keeps Vyomi from being a "distributor" of weights, or whether notice/copy duties already attach.
5. Training-data provenance of MiniLM, nomic-embed, SmolLM2 and the distilled models (publishers state Apache/MIT; datasets are not individually licensed on the cards).
6. MinIO AGPL: source-offer mechanics for `vyomi/minio` and the replacement plan; FRR GPL if shipped; Vault version pin (BUSL); DynamoDB Local and Google emulator terms for a paid hosted use.
7. Trademarks: use of Llama, Gemma, Qwen, Mistral, DeepSeek, Bedrock-style ids (`meta.llama*`, `google.gemma*`) in model ids and marketing.

## 7. Engineering follow-ups (not done in this lane)

- Add a catalog test failing on any model whose licence is not in {Apache-2.0, MIT, Llama-community, Gemma} for paid tiers; record a `licence` field per model (SPECIAL rows already carry one).
- Pin Ollama digests so a tag cannot silently change base model or licence (`deepseek-r1:8b`, `mistral:7b-instruct-q4_K_M`).
- Generate THIRD-PARTY-NOTICES in CI (pip-licenses, license-checker over `consoles/`, and the image list).
- Add the Notices page to the portal and Nano console footer, and a link in the Mesh Models page.
