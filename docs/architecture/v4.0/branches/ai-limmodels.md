# Branch v4/ai-limmodels

- **Owner:** AI session, round 8 lane `limmodels` (overcome declared model-capability limits on Mesh)
- **Base:** `v4/ai-integration` @ 5feeae0e6 (local; not pushed to trunk)
- **Purpose:** the Bedrock/Vertex/Azure surfaces rejected `image` blocks and reasoning because "no served model" had vision or reasoning, and
  Bedrock Data Automation was a "Not in scope" panel. This lane adds two small open role models on Mesh and builds on the vision one.

## What now works (all through the real SDK, tests below)
| Limit | State |
|---|---|
| Image blocks (Bedrock Converse / ConverseStream / Claude InvokeModel, Vertex `inlineData`, Azure `image_url` data URLs) | **closed on Mesh**: answered by SmolVLM-500M via llama.cpp (`--mmproj`) when the vision server is up; ValidationException naming vision otherwise; Nano never serves it; remote image URLs are never fetched |
| Reasoning (`reasoningContent`, `thinking`, `reasoning_config`) | **closed on Mesh**: DeepSeek-R1-Distill-Qwen-1.5B (`--reasoning-format deepseek`) returns real `reasoningContent` / `thinking` blocks (non-stream and streamed first), Vertex `thinkingConfig.includeThoughts` thought parts, Azure `message.reasoning_content` (+ `reasoning_effort`) |
| Bedrock Data Automation | **built, limited**: blueprints, projects, `InvokeDataAutomationAsync`, `GetDataAutomationStatus`, `InvokeDataAutomation`, tags; S3 in/out with the real layout |
| Catalogue | role models are listed (Bedrock `IMAGE` input, Vertex Model Garden, Azure account models, console pickers via `markServed`) **only while their server answers /health** |

## OSS choices (thumb rule)
| Piece | Choice | Licence | Size | Substrate | Why / limit |
|---|---|---|---|---|---|
| Vision | SmolVLM-500M-Instruct Q8_0 + mmproj Q8_0 (`ggml-org/SmolVLM-500M-Instruct-GGUF`) in llama.cpp `llama-server` | Apache-2.0 | 437 MB + 109 MB | Mesh container | Qwen2.5-VL-3B is under the Qwen Research licence for the 3B size (not for a paid product) and is ~2 GB+; Moondream has weak llama.cpp support. `VYOMI_LLM_VISION_HF=ggml-org/SmolVLM2-2.2B-Instruct-GGUF:Q4_K_M` swaps in the 2.2B (Apache-2.0, 1.1 GB + 0.6 GB mmproj): **not run here** |
| Reasoning | DeepSeek-R1-Distill-Qwen-1.5B Q4_K_M (`bartowski/...-GGUF`) | MIT | 1117 MB | Mesh container | smallest open reasoning model that emits a separate thought stream; llama.cpp splits it (`reasoning_content`) |
| Documents | `core/knowledge_core.parse_document` (existing) | n/a | n/a | both | text-layer files need no model |
| Field extraction | llama.cpp grammar from the blueprint as `response_format: json_schema` (existing seam) | MIT | n/a | Mesh (vision), Mesh/appliance (text) | typed JSON or null |
| BDA control plane + jobs | thin records in the account bag (`core/bedrock_bda_core.py`) | n/a | n/a | both | no OSS implements BDA; behaviour is all on engines above. Hand-built only for the wire shape |

## Code map
`core/llm_core.py` role endpoints (`VYOMI_LLM_VISION_ENDPOINT`, `VYOMI_LLM_REASONING_ENDPOINT`, `set_role_endpoint`, `role_available` cached /health probe),
`chat(role=, reasoning=)`, `reasoning` result field and `reasoning` stream events; `core/ai_models_core.py` request/response plumbing (Converse, Claude, Gemini, Azure);
`core/ai_model_catalog.py` `SPECIAL` role models (the ten pool models are unchanged); `core/llm_runtime.py` role containers + RAM plan; `core/bedrock_bda_core.py`;
router: one additive branch in the `bedrock` section of `core/aws_wire_router.py`; one additive pass-through in `bedrock_guardrails_core.guard_events`;
`wasm/build_cores.py` + `wasm/nano-boot.js` list the new core; console `DataAutomation.jsx`, `aiModels.markServed`.

## Measured (real llama.cpp b12438, macOS arm64 M-series, **CPU only, 2 threads, ctx 4096, no mmap**, machine under heavy load from parallel lanes, load average 15-23)
Numbers are upper bounds on a loaded laptop, **not** a Codespace measurement.
- SmolVLM-500M: RAM (`footprint`, phys_footprint) 850 MB; Converse with a 560x260 invoice PNG, 44 output tokens: 6.9 s. Transcription returned all four lines correctly; blueprint extraction (4 fields, constrained JSON) returned all four fields correct, `total_due` typed as number.
- R1-Distill-1.5B: RAM 1265 MB; 255 output tokens in 49.5 s (5.2 tok/s); the thought stream and answer were separated; the answer was a correct breakdown of 17x23.
- Both together: about 2.1 GB, before the default Qwen2.5-3B chat model (about 2.5 GB, estimate). **They do not all fit the 2.8 GB AI bucket of an 8 GB Codespace**: `llm_runtime.plan_role_start` stops the chat model (and the other role) before starting a role model; `VYOMI_LLM_AI_BUDGET_MB` raises it. Same machine with Metal (earlier, also under load): vision 2.4 s, reasoning about 15 tok/s.
- Not measured: any Codespace, Docker `-hf` auto-download of the mmproj, SmolVLM2-2.2B, multi-page documents, dense/handwritten input.

## Tests
- `tests/conformance/test_bedrock_limmodels.py` (57 checks, real boto3/HTTP + in-process Azure dispatcher, **fake** role servers from `tests/conformance/llm_fakes.py`): routing, wire shapes, errors, listing-only-when-served, BDA CRUD/versions/jobs/S3 outputs/errors, role plan. Proves plumbing, not quality.
- `tools/llm_roles/live_check.py` runs the same wire against REAL llama-servers and prints measured numbers (used for the section above).
- `consoles/tests/smoke-limmodels.mjs` (Nano preview): Data Automation page CRUD + Run reaching the runtime target; screenshots viewed. Image runs are not exercised in the browser (Nano has no vision model).
- Updated: `test_bedrock_kb_runtime_caps.py` (a `reasoningContent` block is now accepted in assistant turns; rejected in user turns). Re-run green: catalogue, alias, KB runtime, agents, seam v2, async bridge, SDK tools, guardrails, ctl, Vertex, Azure OpenAI/cognitive suites. Pre-existing failures identical on the base: `test_local_llm_seam` (titan-text), `test_bedrock_build` (list_prompts), `test_ai_agent_lanes` (timing flake).

## Declared limits (still true)
- Quality is that of 0.5B vision / 1.5B reasoning models: no confidence scores, bounding boxes, layout elements, tables; dense layouts and handwriting unreliable; scanned PDFs have no OCR (no rasteriser); audio/video rejected.
- `budget_tokens` is validated (>=1024) but advisory; no thinking signature / redacted content; non-Claude InvokeModelWithResponseStream drops the thought.
- Nano serves neither model; Nano BDA custom output is unsupported (WebLLM cannot run in a background job), text-document standard output works.
- BDA libraries, blueprint optimisation, CopyBlueprintStage, EventBridge notifications, KMS, PII settings are not executed.
- Sync `InvokeDataAutomation` on CPU can exceed an SDK's 60 s read timeout: use the async call for real work.
- `wasm/docs/aws/bedrock.json` (generated by `scripts/gen_nano_docs.py`, needs googleapiclient) was not regenerated; `wasm/v4` bundles are not committed.
