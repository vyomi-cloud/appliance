# Customer terms: AI model addendum (DRAFT FOR COUNSEL)

**DRAFT. Engineering text only, not legal advice, not reviewed by counsel. Do not publish or rely on it until counsel has reviewed and edited it.**
Source of facts: `docs/architecture/v4.0/AI-LICENCE-AUDIT.md` and `THIRD-PARTY-NOTICES.md` (generated). Clause numbers below are placeholders.

## A1. Open models, no vendor affiliation
Models available through Vyomi are open-weight models from their publishers (for example Meta, Google, Alibaba Cloud/Qwen, Mistral AI, DeepSeek, Hugging Face, Nomic AI). Vyomi is not affiliated with AWS, Google, Microsoft, Meta, Anthropic or OpenAI. Names of third-party products and model ids are used only to describe API compatibility. A model reached through a compatibility alias (for example a `meta.llama*` or `amazon.nova*` id) is the open model shown in the Notices page, not the vendor's hosted model. It is not equivalent to, and does not carry the guarantees of, any AWS, Google or Microsoft service.

## A2. Model licences apply to you
Each model remains under its own licence, listed on the Notices and licences page and in THIRD-PARTY-NOTICES.md. You agree to comply with them when you use a model through Vyomi, including the clauses below. If a model licence conflicts with these terms for that model, the model licence controls for that model.

## A3. Llama models (Llama 3.1 and 3.2)
- You will comply with Meta's Acceptable Use Policy for the Llama version used (links on the Notices page); it is incorporated into these terms.
- "Built with Llama" is shown where Llama models are used or served; keep it if you redistribute outputs or applications as the Llama licence requires.
- Any AI model you create, train or fine-tune using Llama materials through Vyomi and distribute must include "Llama" at the beginning of its name. Vyomi prefixes the displayed name of tuned Llama derivatives.
- Llama licence section 2 (more than 700 million monthly active users) applies to you directly. *Counsel: how it applies to customers embedding Vyomi.*
- Meta may terminate the licence on breach; Vyomi may suspend access to Llama models if you breach it.

## A4. Gemma
- You will not use Gemma, or allow others to use it through your account, in any way prohibited by the Gemma Prohibited Use Policy (link on the Notices page). This restriction is an enforceable provision of these terms and binds your own recipients and end users (Gemma Terms section 3.1(1)).
- You are given a copy of the Gemma Terms of Use (Notices page). "Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms."
- Google reserves the right to restrict use of Gemma remotely or otherwise; Vyomi may withdraw Gemma access accordingly without liability. *Counsel: interaction with any SLA; which Terms version governs.*

## A5. Qwen and other Apache-2.0 / MIT models
- Apache-2.0 models (for example Qwen2.5 0.5B/1.5B/7B, Qwen3, Mistral 7B, SmolLM2, nomic-embed-text): if you redistribute the weights or a derivative, you keep the licence text, the NOTICE file and state your changes.
- MIT models (DeepSeek R1): keep the notice "MIT License, Copyright (c) 2023 DeepSeek" and the licence text.
- Qwen3-4B-Instruct-2507 (the default chat model since 2026-11-16) is Apache-2.0. Qwen2.5-3B is under the Qwen Research Licence: non-commercial research or evaluation use only. It is flagged in the catalogue, is on no runner, is never a default and is not offered in paid tiers. If you use it, you represent that your use is non-commercial; commercial use needs a licence from Alibaba Cloud. Derivatives (LoRA, fine-tunes) inherit the restriction.

## A6. No warranty on model output
Model output may be inaccurate, offensive or infringing. Models are provided as is, without warranty of any kind. You are responsible for reviewing output before relying on it and for your use of it, including in decisions that affect people. Do not use models for uses prohibited by the policies above. *Counsel: output ownership, indemnity limits.*

## A7. Third-party software
Open-source components keep their own licences (THIRD-PARTY-NOTICES.md, sbom.cdx.json). Nothing in these terms limits rights you have under those licences. Source for AGPL/GPL components we redistribute is available on request and as described in the Notices.

## A8. Open points for counsel
1. Whether serving any non-commercial model anywhere customers pay (including a free tier of a paid product) is permitted.
2. Enforceable flow-down mechanics for the Llama AUP and the Gemma Prohibited Use Policy.
3. Whether pull-from-upstream makes Vyomi a distributor of weights.
4. Trademark use of Llama, Gemma, Qwen, Mistral, DeepSeek and Bedrock-style ids.
