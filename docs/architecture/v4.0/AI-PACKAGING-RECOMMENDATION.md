# AI packaging and pricing recommendation: Nano Free vs Mesh paid

Status: recommendation for the owner, 2026-11-16. Source of truth for what may be claimed is the generated
[AI-SELLABLE-CLAIMS.md](AI-SELLABLE-CLAIMS.md) (45 features, 33 referenced tests run in isolation at `8d4c642fd`; 29 pass, 4 fail today).
No price numbers appear here on purpose: none have been measured or decided. Items marked **unmeasured** have no data yet.

## 1. What goes where

| Tier | Substrate | Contents (all with the Bedrock-compatible, Vertex-compatible and Azure OpenAI-compatible APIs) |
|---|---|---|
| **Free** | Nano (browser) | WebLLM chat models, 4 of them: SmolLM2 360M, Qwen2.5 0.5B, Llama 3.2 1B, Qwen2.5 1.5B (needs WebGPU; model downloaded into the user's own browser). In-browser embeddings (all-MiniLM-L6-v2). Control planes and the tested AI surfaces that run in pure Python: knowledge bases, agents, AgentCore gateway and runtime records, guardrails, flows, evaluations, trained heads (classifier / router / reranker), imported small models. Claim wording per row of the register (mostly `dev-simplified`). |
| **Mesh paid** | Mesh (Codespace appliance, llama.cpp) | The 10-model open pool (Qwen3 4B Instruct 2507 default, Qwen2.5 7B/Coder 7B, Qwen3 8B and 30B MoE, plus the non-commercial Qwen2.5 3B kept in the catalogue but never served, Llama 3.1 8B, Gemma 2 9B, DeepSeek R1 8B, Mistral 7B, Nomic embed), plus: vision (SmolVLM-500M), reasoning (DeepSeek-R1-Distill 1.5B, real `reasoningContent`), Data Automation with vision extraction, code interpreter and file search for the Azure Assistants/Responses path, full agents, flows, evals and RAG against a real model, LoRA training on Mesh with import to Nano. |

Rationale: Free shows that the API surface and console are real and lets a developer build against it with nothing installed. Paid is
exactly what Nano physically cannot do (large models, vision, reasoning, background jobs, larger RAM). That makes the upgrade honest:
the register's `Mesh only` and `Both (parts Mesh-only)` rows are the upsell list.

Caveats to state to customers: the 10 pool models do not all fit an 8 GB Codespace at once; `llm_runtime.plan_role_start` swaps role models
(vision, reasoning) in and out, so a user gets one role model at a time beside the default chat model (documented in `ai-limmodels.md`).

## 2. Cost to Vyomi

- **Zero marginal compute for BYO-PAT users**: the Codespace runs on the user's own GitHub quota (120 core-hours/month on a free personal
  account; resets on the 1st, 00:00 UTC). Models are pulled from public hubs into that Codespace. Nano inference runs on the user's own device.
- **Wallet model** (memory `personal-sandbox-byo-pat-wallet`, portal branch `feat/personal-sandbox-byo-pat`, local only, not deployed): a flat
  platform fee per sandbox is debited from a two-bucket wallet. The `gift` bucket pays only fees; the `loaded` (real money) bucket pays fees
  and any Vyomi-PAT compute. Fee and gift amounts exist only as portal config defaults (`VYOMI_PERSONAL_FEE_CENTS`,
  `VYOMI_SIGNUP_GIFT_CENTS`); **they are not a decision and are not quoted here**.
- **Where Vyomi does pay**: (a) the Vyomi-PAT path (compute from loaded funds, so priced to cover itself); (b) payment-processor fees;
  (c) the existing portal hosting and any model-download bandwidth if Vyomi hosts model files itself (**unmeasured**; today models
  come from public hubs); (d) support load. None of these has a measured per-user figure.
- **Quota exhaustion is a product risk, not a cost**: when the user's free hours run out the sandbox stops (create 403 / start 402);
  the user then waits for the reset or switches to the Vyomi-PAT path.

## 3. Legal-safe wording

Use: "Bedrock-compatible API", "works with the AWS SDK/CLI", "OpenAI-compatible", "Vertex-compatible". Say what actually answers:
"open-source models (Qwen, Llama, Gemma, Mistral, DeepSeek, SmolLM2) running locally".

Do not use:
- Vendor model names (Claude, Nova, Titan, Gemini, GPT) as models Vyomi serves, in UI, docs or marketing.
- Any claim of equivalence, parity or "same quality as" Bedrock or any vendor model. Tests prove wire shapes and behaviour through the
  real SDK, not answer quality. The registry itself says the models are small and toy-grade for some tasks; keep that wording.
- "Bedrock" as a product name for what we sell: say "a Bedrock-compatible API on open models".
- Third-party trademarks as endorsement. Model vendor names are fine only as factual attribution ("Qwen2.5 7B by Alibaba").

Open item in the code (do not ship until decided): legacy ids such as `anthropic.claude*` and `amazon.nova*` still RESOLVE to a local open
model so existing SDK code runs (`core/ai_models_core.py`, `BEDROCK_ALIASES`). Listing them is off by default
(`VYOMI_LIST_BEDROCK_ALIASES`), and responses carry `x-vyomi-local-model` plus `vyomiBackedBy`. Counsel should decide whether silent
resolution of vendor ids to a different model is acceptable for a paid product; the conservative option is an explicit, documented
"compatibility alias" notice at first use, or removing the alias resolution from the paid build.

## 4. Risks

1. **Four referenced tests fail today** (register, "Failing or missing tests"): `test_ai_agent_lanes.py` and `test_bedrock_agents_limits.py`
   die with `KeyError: '_items'` in `core/azure_openai_agents_core.py::_run_view` (an Assistants run view; a real engine bug reproduced
   in isolation); `test_azure_netenforce_sdk.py` needs the `azure.mgmt` SDK that the interpreter does not have; the `az` CLI smoke
   needs a configured `az` (environment, not proven a product bug). The affected features are automatically demoted to
   "not supported (test failing or not run)" and must not be advertised until fixed.
2. **Model licences are not audited**. Each served model carries its own licence (Apache-2.0, MIT, Llama community licence, Gemma terms,
   Qwen licences). At least the Llama and Gemma terms impose attribution or use conditions, and the Qwen2.5 3B default is, per our
   recollection, not under Apache-2.0 (a prior lane already avoided Qwen2.5-VL-3B for this reason). **Verify each licence on its model card
   before charging** (not verified in this lane).
3. **Quality**: 0.5B vision and 1.5B reasoning models; no OCR for scanned PDFs; Nano cannot serve vision, reasoning or background jobs.
   A paying customer comparing against real Bedrock will see the gap; position as a cheap, offline, deterministic-wire dev and test
   environment, not as a production model host.
4. **Latency and sizing are unmeasured on a Codespace**: published speeds are from a loaded M-series laptop (`ai-limmodels.md`), a 2-core Codespace
   will be slower, and the 8 GB limit forces model swapping. Do not publish tokens/second.
5. **Platform dependence**: the free-compute model depends on GitHub Codespaces terms, quota and pricing, and on users supplying a PAT.
6. **Billing is not live**: the wallet and top-up flow are verified locally only; live Razorpay and live Codespaces paths are untested.
7. **Nano needs WebGPU** for the 4 chat models; browsers without it get `ModelNotReadyException` (no canned answers, by design).
8. **Honest labelling rule**: tuned or imported chat models are small open models with a LoRA adapter, not vendor models; quality claims only
   from held-out measurements, of which none are published yet.

## 5. Keeping claims true

Regenerate the register after any capability change: `python3 tools/ai_claims/gen_claims.py --run`, then commit. The drift check
`tests/conformance/test_ai_claims_register.py` fails if the capability JSONs changed, a claimed test file is missing, the recorded
results omit a test, or the register differs from a regeneration. It does not re-run the tests (that takes minutes and needs the venv); the
recorded results carry the commit and timestamp, and a pre-release run of `--run` is the gate.
