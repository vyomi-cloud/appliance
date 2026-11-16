# ai-qwen3swap: Mesh default chat model Qwen2.5-3B -> Qwen3-4B-Instruct-2507

Owner: AI session, lane `qwen3swap`. Base: `v4/ai-integration` 0fecc2c36. Branch `v4/ai-qwen3swap`. Engineering draft, not legal advice.

## WHERE THIS RAN (read first)
Every measurement below ran on a **Mac (Apple M1, 8 cores, 16 GB), NOT a Codespace**, real `llama-server` b12441 (macOS arm64), CPU only (`-ngl 0 -t 4`, same flags as the earlier ai-meshverify run). The machine was shared: load average was 10-12 on 8 cores during the A/B, so tokens/s are noisy and macOS RSS is unreliable (mmap + compression). Where a number is a llama.cpp memory accounting figure rather than an RSS, it says so. Nothing was run on a Codespace and no image/release was published. All temporary downloads (llama-server, the three GGUFs) were deleted afterwards.

## 1. Licence verification (primary sources, 2026-11-16)
| Item | Evidence |
|---|---|
| Base model | `Qwen/Qwen3-4B-Instruct-2507`: HF API `cardData.license = apache-2.0`; the repo `LICENSE` file is the Apache License 2.0 text, "Copyright 2024 Alibaba Cloud". No NOTICE file in the repo listing. |
| GGUF chosen | `unsloth/Qwen3-4B-Instruct-2507-GGUF`, file `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`. Card `license: apache-2.0`, `base_model: Qwen/Qwen3-4B-Instruct-2507`, 869k downloads at the time. URL: https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf |
| Size | 2,497,281,120 bytes (2381.6 MiB), downloaded and checked |
| sha256 | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` (matches the HF LFS oid; recomputed locally with `shasum -a 256`) |
| Why not `Qwen/Qwen3-4B-Instruct-2507-GGUF` | that repo does not exist (HF API: not found); `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` exists but its card carries no licence metadata, so the unsloth repack (explicit apache-2.0) was chosen. The chat template ships inside the GGUF. |
| Architecture | `Qwen3ForCausalLM`, 36 layers, hidden 2560, 32 heads, 8 KV heads, head_dim 128, tied embeddings, 262144 max positions. |

Limits of this check: the licence of a third-party repack is the publisher's statement; the weights are a conversion of the Apache-2.0 base. Counsel should still review attribution (recorded in `tools/notices/notices.json`).

## 2. What changed
- **Default**: `core/ai_model_catalog.py` `DEFAULT_CHAT` / `LOCAL_ID` / `default_chat()` = `qwen3-4b`; `core/mesh_ai.py` `DEFAULT_CHAT` = `qwen3-4b`; `docker/mesh-runner-llm/models.json` `default_chat` and the `fast` runner; compose (`codespace/.devcontainer/mesh/docker-compose.mesh.yml`) and `docker/mesh-runner-llm/entrypoint.sh` default GGUF; `core/agent_spec_core.py`, `core/ai_models_core.py` (`amazon.titan-text` alias), Nano `wasm/nano-connect.js` model list, console fixtures, scripts and tests. `boot-mesh.sh` needed no edit: it reads the HF spec and context from `core/mesh_ai.MODELS`.
- **Aliases re-pointed to `qwen3-4b`** (catalogue + `models.json`, drift-tested): `amazon.nova-micro*`, `amazon.nova-lite*`, `gemini-*-flash*`, `gpt-4o-mini*`, `gpt-35*`, `amazon.titan-text`.
- **`qwen2.5-3b` kept, flagged, inert**: still in the catalogue (11 ids now) with `commercialUse: false`; it is on no runner, `load_catalogue()` drops `"unhosted"` models so the runner pool never routes, resolves or lists it; availability says "Not served (non-commercial licence)"; `mesh_ai.admit` refuses it when `VYOMI_PAID_TIER=1`; `resolve()` still redirects it to the default on a paid tier.
- **The default no longer depends on `VYOMI_PAID_TIER`.** The default is itself Apache-2.0. New assertions (`test_ai_notices.py`): default chat is commercial with the env unset; every small-model alias resolves to a commercial model with the env unset; the runner catalogue's `default_chat` is commercial and `qwen2.5-3b` is on no runner; the compose default is the Qwen3 GGUF; no trainable LoRA base is non-commercial or Llama-derived.
- **Licence traps fixed**: `core/training_core.py` `CHAT_BASES`: `qwen3-4b` added as a LoRA base; `qwen2.5-3b` removed (non-commercial, a LoRA inherits it); `deepseek-r1-8b` removed (it pointed at `DeepSeek-R1-Distill-Llama-8B`, a Llama-3.1 derivative, while the catalogue claims MIT). Both are now metadata-only bases like any non-trainable id. Redis image pinned `redis:7.2.5-alpine` in `core/backend_provisioner.py` (the only place a Redis image is named; no compose file references one) and `docs/specs/redis-siftly-spec.md`, noted in `tools/notices/notices.json` (BSD-3-Clause line ends at 7.2; 7.4+ is RSALv2/SSPLv1, 8.x AGPLv3); tag existence checked on Docker Hub. A test asserts the pin.
- Regenerated: `tools/notices/gen_notices.py` (THIRD-PARTY-NOTICES.md, sbom, console notices JSON), `scripts/gen_ai_model_catalog_json.py`, `wasm/build_cores.py`; capability text in `core/capabilities/aws/bedrock.json` ("3B" -> "4B"); `consoles/src/common/scopeHelp.js`; docs naming the old default (go-live checklist, runner doc, packaging recommendation, customer-terms addendum, licence audit marked RESOLVED, pack audit marked SUPERSEDED, agent-workflow example).

## 3. LoRA on Qwen3 (converter check)
`llama.cpp` tag **b8996** (the trainer's pinned converter): `convert_hf_to_gguf.py` registers `Qwen3ForCausalLM` (class `Qwen3Model(Qwen2Model)`) and `convert_lora_to_gguf.py` is architecture-generic. Verified by running it: a synthetic PEFT-layout adapter (rank 8, q/k/v/o/gate/up/down on all 36 layers, real Qwen3-4B-2507 `config.json`, real dimensions, 33 MB f16 GGUF) converted without error, and **`llama-server` b12441 loaded that adapter against the real Qwen3-4B Q4_K_M** (`GET /lora-adapters` listed it; scale 0 request answered). Caveats, all unmeasured: the adapter was synthetic (B = 0), so this proves the tensor names/shapes and serve path, not tuned quality; **no real Qwen3-4B training run was done** (bf16 weights are ~8 GB, `fits: True` in `CHAT_BASES` is an estimate for a 16 GB host); b8996 specifically was only exercised for the converter, the server used b12441.

## 4. Memory plan (measured on the Mac, derived for the Mesh)
llama.cpp memory accounting (deterministic, platform independent, from the server log) and measured peak footprint:
| Context | Weights (repacked + embeddings) | KV (f16) | Compute | llama.cpp total | Measured peak footprint (macOS, long prompt) |
|---|---|---|---|---|---|
| 4096 | 2375 + 305 MiB | 576 MiB | 86-172 MiB | 3342-3428 MiB | 3.27 GB (3,270,505,536 B, 3,096-token prompt) |
| 8192 | 2375 + 305 MiB | 1152 MiB | 90-180 MiB | 4012-4112 MiB | 3.87 GB (3,873,831,360 B, 6,616-token prompt) |
(Max RSS on macOS was 5.36 / 4.89 GB: it counts mapped file pages and is not a Linux RSS; not used for planning.)

Decisions (`core/mesh_ai.py`, `core/llm_runtime.py`):
- Mesh pack default context **4096**, `ram_mb` **3500** (was 2500 for the 3B). The hosted-runner entry in `models.json` is 8192 / 4100.
- **8 GB Codespace: not supported for this default.** The AI bucket is 2800 MB (70 % x 50 % of 8 GB); 3500 + embedder does not fit even at 2k context. Admission refuses it with a readable message and suggests `qwen2.5-1.5b` (the hint now skips non-commercial models and anything bigger than the free bucket). `tests/conformance/test_mesh_ai.py` now asserts this honestly.
- **4 vCPU / 16 GB Mesh (production default)**: bucket 5600 MB (`mesh.py`) / 5734 MB (`llm_runtime`). Chat 3500 + nomic 250 = 3750 fits. Role swap (`CHAT_EST_MB` = 3500): chat + vision = 4400, chat + reasoning = 5300 both fit without stopping chat; starting reasoning while vision runs stops **vision** (not chat). **Regression vs the 3B:** chat + vision + reasoning together (6200) no longer fit; before they did (5200). Raising the AI share is a compute trade-off and was not done silently.
- Long context is slow on CPU: decode 2.2-2.3 tok/s with a 3-6.6k-token prompt (Mac).

## 5. Measured behaviour vs the Qwen2.5-3B numbers in `ai-meshverify.md` (all Mac, not Codespace)
| Check | Qwen2.5-3B (ai-meshverify, b12441, shared Mac) | Qwen3-4B-Instruct-2507 (this lane) |
|---|---|---|
| Decode tok/s, 3 x 100 tokens | 12.9 / 7.7 / 9.4 | first run, ctx 8192, load not recorded: 17.0 / 18.3 / 17.6. Loaded machine (load 10-12), back-to-back with Qwen2.5-3B in the SAME session, ctx 4096: Qwen2.5-3B 17.6 / 10.5 / 7.2 vs Qwen3-4B 8.2 / 8.2 / 6.6. So Qwen3-4B is roughly 25 % slower per token on equal terms; the quiet-vs-old comparison is not like-for-like. |
| Long prefill (~680 tokens) | 33 tok/s (667 tokens) | 50.7 (first run); 30.5 vs 32.7 (loaded A/B, Qwen3 vs 2.5-3B) |
| 20 InvokeAgent tool prompts | 20/20, median 9.6 s, mean 11.5 s | **20/20** (16/16 right function and argument, 4/4 no tool), 0 retries, 0 errors; mean 7.6 s (ctx 8192, load not recorded), 8.8 s (ctx 4096, load about 8-11). `results/qwen3-4b/agent_tools_ctx*.json` |
| LLM-as-judge, 20 QA pairs | 18/20 = 0.90 (P 1.00, R 0.80) | **20/20 = 1.00** (tp 10, fp 0, fn 0, tn 10, 20/20 verdicts parsed), ctx 8192. A re-run at ctx 4096 was abandoned (machine saturated); prompts are far below 4k, so context should not matter, but that is not measured. Same small sample, +/- large. |
| Guardrail classifier (180 prompts) | HIGH P .80 R .91; MEDIUM P .90 R .77; LOW P .98 R .46 | **Identical to the digit** (embedder is nomic via llama.cpp, unchanged; the classifier never calls the chat model). Thresholds `SEM_THRESHOLDS_BY_BACKEND["llama.cpp"]` stay as calibrated. |
| Facilities e2e, real model via gateway | 11 PASS, 0 BLOCKED, 2 FAIL: comp 3 (InvokeAgentRuntime 60 s timeout), comp 11 (no citations) | **11 PASS, 0 BLOCKED, 2 FAIL** at ctx 8192 (92 s) and ctx 4096 (134 s). Same two components, **different cause for 3**: no timeout now; the supervisor's router prompt returns `["maintenance"]` only (verified by calling the model with the exact router prompt), so the Facilities agent is never invoked and no knowledge-base search runs: comp 3 "agent:facilities did not run", comp 11 "no citations". It is the example app's under-specified routing prompt (it never defines what each agent does), not a Qwen3 template or tool-call defect; Qwen2.5-3B had the same routing outcome for comp 11. Not changed: the example app is outside this lane; a stub-free fix is to describe the agents in the router prompt. |
| Chat template / stop / tool / schema path (llama-server `--jinja`) | n/a | Embedded Qwen3 ChatML template loads; `eos = <|im_end|>`; `chat_template_caps` shows tools + parallel tool calls; non-streaming tool call returns `finish_reason: tool_calls` with parsed JSON arguments; `response_format: json_schema` returns schema-valid JSON; `stop` strings work; **no `<think>` and no `reasoning_content`** (the 2507 instruct build is non-thinking, so the seam's reasoning handling is untouched). Gateway path (`core/mesh_llm_gateway`) used by every run above. |
| KB retrieval (nomic) | recall@1 0.83 | not re-run: embedder unchanged |

Not measured: any Codespace number, Qwen3-4B tokens/s on 2 or 4 Codespace vCPUs, RSS on Linux, real LoRA training on Qwen3-4B, streaming tool calls, thinking-mode requests (this model has none), the real Docker `role_start` path.

## 6. Tests (all run here, `/private/tmp/ai-probe-venv13`)
`test_ai_notices` 190/0 (new default/paid/Redis/compose/training assertions), `test_ai_model_catalog` 26/0, `test_local_llm_seam` 43/0, `test_chat_lora_jobs` 14/0 (training sections skipped: no trainer env), `test_bedrock_limmodels` 60/0 (role plan cases rewritten for the 3500 MB chat), `test_ai_agent_lanes` 47/0; also updated and passing: `test_mesh_ai` 44/0, `test_mesh_remote_llm` 41/0 (host now 16 GB), `test_mesh_runner_pool` 56/0, `test_gcp_vertex_core`, `test_llm_seam_v2`. `test_capabilities` and the Playwright/UI smokes were not re-run here.

## 7. Open items
- Real Codespace run (tokens/s, Linux RSS, `llm-chat` start with `-hf unsloth/...:Q4_K_M`, first-download time for 2.4 GB) once Codespace quota allows.
- Decide whether to give the AI bucket more than 35 % of RAM so vision + reasoning + chat can again run together on 16 GB.
- Router prompt in `examples/enterprise-facilities-agent/facilities/agents.py` (comps 3 and 11).
- `bge-small` (compose default embedder, 130 MB) and `nomic-embed-text` (84,106,624 bytes measured; `core/mesh_ai.py` says 274 MB) sizes in the catalogue are stale estimates; not changed here.
- Counsel review of the unsloth repack attribution.
