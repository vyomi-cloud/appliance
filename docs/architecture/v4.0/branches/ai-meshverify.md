# ai-meshverify: real-model verification of the Mesh AI stack

Owner: AI session, lane `meshverify`. Base: `v4/ai-integration` 8d4c642fd. Branch `v4/ai-meshverify`. Scripts + raw results: `tools/mesh_verify/` (`results/*.json`).

## WHERE THIS RAN (read first)
**NOT on a Codespace.** Creating the Codespace was attempted and refused by GitHub:
`gh codespace create -R vyomi-cloud/appliance -b v4/ai-integration -m standardLinux32gb` -> `HTTP 402: Usage not allowed: vyomi-admin, you are out of monthly free usage or have exceeded your budget for Codespaces.`
(vyomi-admin also holds 10 old Shutdown `vyomi-booster-*` Codespaces; none were touched; no Codespace was created, `gh codespace list` shows nothing from this lane.) Per the brief, every measurement below ran on a **Mac (Apple M1, 8 cores, 16 GB RAM)**, real `llama-server` b12441 (macOS arm64 release), CPU only (`-ngl 0`, `-t 4`, `--no-mmproj-offload`) to approximate the 4 vCPU Mesh. Models: Qwen2.5-3B-Instruct Q4_K_M, nomic-embed-text-v1.5 Q4_K_M, SmolVLM-500M-Instruct Q8_0 (+mmproj), DeepSeek-R1-Distill-Qwen-1.5B Q4_K_M, SmolLM2-135M-Instruct. M1 is faster per core than a Codespace vCPU and the machine was shared with other sessions: **tokens/s here is an upper-ish, noisy bound, not a Codespace number; macOS RSS is unreliable after memory compression.** The appliance code ran from source (this worktree) in-process with real boto3; no image/release was published.
Re-run on a Codespace once quota is available: start llama-server (chat :28080, embed :28083) + `python -m core.mesh_llm_gateway` (:28090) and `PY=<venv> sh tools/mesh_verify/run_all.sh`; `bench.py` needs `MV_LLAMA/MV_MODELS/MV_CHAT_PID`.

## Results
| # | Check | Result (Mac, real models) |
|---|---|---|
| 1 | Chat alone, Qwen2.5-3B Q4, 3 x ~100-token generations | decode 12.9 / 7.7 / 9.4 tok/s (noisy, shared machine); prefill 12-41 tok/s on a 49-token prompt, 33 tok/s on a 667-token prompt; RSS 3.2 GB idle-after-load, 2.5 GB later |
| 1 | + SmolVLM-500M vision (real red-square PNG) | started in 3.5 s; answered "Red."; RSS 461 MB; chat still served at the same time (an 8-token reply ran at 2.6 tok/s while the vision model was loading: contention) |
| 1 | + R1-1.5B reasoning | started in 11.7 s; 295-token answer at 10.4 tok/s with `reasoning_content` separated; RSS 1721 MB |
| 1 | `plan_role_start` swap | **Correct as designed, but the 2800 MB default stopped the chat model for any role start** (2500 + 900 > 2800). Real `role_start` was driven with an injected `run` mapped onto native processes: with a 9000 MB budget chat+vision+reasoning ran together (plan `stop: []`); with 2800 it stopped `vyomi-llm`, started vision from the exited container (`docker start` path), vision answered "Red." Not run: the real Docker container path (no image pulls). |
| 2 | Facilities e2e with the real model (Qwen2.5-3B via gateway) | **11 PASS, 0 BLOCKED, 2 FAIL of 13.** Component 10 (foundation models) PASS 5/5. Component 11 (grounded answer) **FAIL 3/4**: "the agent returned no citations": the real model routed the question only to `maintenance`, so no knowledge-base search ran and the answer said the context lacked the SOP (the stub routes to several agents). Component 3 **FAIL 3/4**: `InvokeAgentRuntime` hit the e2e client's 60 s `read_timeout` (three sub-agents x CPU model latency). Both are real-model effects, not code bugs; log in `results/e2e-run.log`. |
| 3 | 20 tool-calling prompts through `InvokeAgent` + action groups (5 functions, 16 tool prompts, 4 no-tool prompts) | **20/20 correct** (right function and right argument on 16/16; no tool called on 4/4). 0 retries (every prompt: 2 model invocations), 0 failure traces, 0 errors. Median 9.6 s per prompt (mean 11.5 s). One earlier attempt scored 9/20 only because the embed/chat servers were killed mid-run (harness fault, discarded; the scored run is `results/agent_tools.json`). |
| 4 | Guardrail semantic classifier, 6 categories x 30 prompts (15 harmful, 15 benign incl. hard negatives such as "kill the process") | see calibration below |
| 5 | LLM-as-judge (`agentcore_eval_core._judge`), 20 QA pairs | 18/20 = **0.90** (precision 1.00, recall 0.80; 2 correct paraphrases judged Incorrect; 20/20 verdicts parsed). Token-F1/embedding similarity baseline: 0.75 at its best threshold chosen on the same data (optimistic). Small sample. |
| 6 | llama-server `--lora` with a trainer-produced adapter | trainer (PEFT, SmolLM2-135M, 110 rows, 4 epochs): 129 s, peak 2.1 GB, 4.9 MB adapter, held-out exact match 0.0 -> 0.73 (n=11). `llama-server` loaded the GGUF adapter; `GET /lora-adapters` returns `{id,path,scale,...}`; per-request `lora:[{id,scale}]` works: on 12 fresh tickets scale 0 = 0/12 exact, scale 1 = 9/12. **Finding fixed in code:** with the seam's flag `--lora-init-without-apply` a request WITHOUT `lora` still got the adapter (9/12): the base model was silently tuned. `--lora-scaled <file>:0` gives true opt-in (verified: no field = base, scale 1 = tuned, 2 adapters listed). `core/llm_runtime.lora_args` now emits that. **The `llm-chat` restart hook does not exist**: `docker-compose.mesh.yml` has no adapter volume and no `--lora` flags, nothing restarts `llm-chat` when an adapter lands, and a new adapter can't be hot-loaded (`POST /lora-adapters` only sets scales; an unknown id returned `{success:true}`). Not built here (needs an entrypoint that globs `/adapters/*.gguf` + a restart path; the appliance container has no docker socket). Not measured: LoRA on the 3B Q4 model. |
| 7 | KB retrieval, 24 passages, 30 paraphrased queries, through bedrock-agent + bedrock-agent-runtime (real boto3) | nomic-embed (via llama.cpp): recall@1 **0.83**, recall@3 0.83, recall@5 0.87, MRR 0.84. Hash fallback: recall@1 0.40, recall@3 0.57, recall@5 0.67, MRR 0.49. Cosmetic issue: the embed result's `model` field says the chat model name (`qwen2.5-3b`), not nomic. |

## Guardrail calibration (check 4), measured change applied
Default cut-offs (LOW, MEDIUM, HIGH) = (0.58, 0.68, 0.78) on the nomic scale, end-to-end `evaluate()` with one filter per category, all 180 prompts:
| strength (blocks at) | precision | recall |
|---|---|---|
| HIGH (>= 0.58) | 0.80 | 0.91 |
| MEDIUM (>= 0.68) | 0.97 | 0.40 |
| LOW (>= 0.78) | 1.00 | 0.10 |
Per category at HIGH: HATE P .88 R 1.0; INSULTS .92/.80; SEXUAL .79/1.0; VIOLENCE .79/1.0; MISCONDUCT .65/.87 (weakest: 7 false positives); PROMPT_ATTACK .86/.80.
Calibration: scanned on the even-indexed half (90 prompts), scored on the odd half. Proposed (0.58, 0.61, 0.67). Held-out (odd) at MEDIUM: recall 0.36 -> 0.76, precision 0.94 -> 0.89; at HIGH: recall 0.14 -> 0.40, precision 1.00 -> 0.94; LOW cut-off unchanged. **Applied** in `core/bedrock_guardrails_core.py` as `SEM_THRESHOLDS_BY_BACKEND["llama.cpp"]`; other embedders (Nano MiniLM) keep the old defaults because they were not measured. End-to-end after the change (all 180, in-sample): MEDIUM P 0.90 R 0.77, LOW(HIGH conf) P 0.98 R 0.46, HIGH unchanged. Caveats: prompts were written by this lane (not an external benchmark), 15+15 per category, so per-category numbers are +/- 0.1.

## Other measured changes in this branch
- `core/llm_runtime.py`: AI budget default was a fixed 2800 MB (35 % of the old 8 GB Codespace). Now `max(2800, 35 % of physical RAM)` (5734 MB here; 5600 on a 16 GB Mesh), env `VYOMI_LLM_AI_BUDGET_MB` still wins; reasoning estimate 1500 -> 1800 MB (measured RSS 1721 MB). Vision estimate (900) kept although measured RSS was 461 MB (KV/context not measured). Tests updated: `test_bedrock_limmodels` 59/59.
- `core/llm_runtime.lora_args`: `--lora-scaled <file>:0` instead of `--lora-init-without-apply --lora` (see 6). `test_chat_lora_jobs` 14/14 (training sections skipped, no trainer env set).
- `wasm/core` re-mirrored (`wasm/build_cores.py`). `test_bedrock_guardrails_caps` 29/29.

## Not done / declared limits
- No Codespace numbers (402). 3B-LoRA, Codespace tokens/s and RSS, and the real Docker `role_start` path remain unmeasured.
- llama.cpp b8996 (the trainer's pinned converter tag) could NOT serve SmolVLM images (`number of bitmaps (1) does not match number of markers (0)`); b12441 can. Pin the converter and the server separately.
- Mesh e2e would need a longer `read_timeout` in `examples/enterprise-facilities-agent/facilities/runtime.py` (60 s) and the supervisor/knowledge routing tightened for the 3B model; left as is.
