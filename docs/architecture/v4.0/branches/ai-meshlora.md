# ai-meshlora: real chat-model LoRA fine-tuning on Mesh / offline behind the three customization APIs

- Owner: lane `meshlora` (2026-11-15/16). Branch `v4/ai-meshlora`, base local `v4/ai-integration` (50b84446c). No console work (another lane owns the import page).
- Spec: `ai-nano-training-scope.md` section 10 (chat LoRA is trained on Mesh and imported to Nano as GGUF) + `ai-trainengine.md` (job runner contract).

## What exists
When a customization / tuning / fine-tuning job's base is a chat model of the Mesh open-source pool, `core/training_core.py` runs a REAL LoRA job (engine `lora-peft`):
JSONL rows `{"messages":[...]}` or `{"prompt","completion"}` from the simulated object store (caps: 2000 rows, 5 MB, min 10 rows, `maxSequenceLength` 32..1024, rank 1..64,
epochs 1..10) -> `trainer/lora_train.py` (PEFT/PyTorch CPU) in a separate process -> adapter converted to an **f16 GGUF LoRA** with the pinned llama.cpp `convert_lora_to_gguf.py` ->
`s3://vyomi-models/models/<id>/adapter.gguf` + `meta.json` (base id, HF repo, rank, alpha, rows, steps, held-out, adapter bytes). The three cloud adapters stay thin:
- Bedrock `CreateModelCustomizationJob` (FINE_TUNING, hyperParameters `epochCount, batchSize, learningRate, loraRank, loraAlpha, maxSequenceLength`), Get/List/Stop mirror it; custom ARN invocable via
  InvokeModel (Nova-style `messages` or Llama-style `prompt`) and Converse.
- Vertex `tuningJobs` (`supervisedTuningSpec.trainingDatasetUri` s3:// or gs://); tuned endpoint `:predict` (instances `{"prompt"}|{"messages"}`) and `:generateContent` (Gemini body).
- Azure OpenAI `/openai/fine_tuning/jobs` (events are per optimiser step, `type: metrics`, `train_loss`); `ft:<base>:<suffix>:<id>` deployable via ARM; `chat/completions` on it.
Job record `vyomiTraining`: `engine lora-peft, taskType chat-lora, status Queued|Embedding(loading+tokenising)|Training|Evaluating|Completed|Failed|Stopped, progress, epoch(s),
steps[{step,epoch,loss}] (per step, last 1000), metrics[{epoch,loss,accuracy(token),valLoss}], heldOut{exactMatch,baselineExactMatch,perplexity,baselinePerplexity,n, accuracy/baseline = exact match},
rows, artifact, adapterId, baseModel, note`. Stop kills the trainer (cancel file, then `docker kill`/`terminate`) within a step; nothing is published.
Every served response carries `vyomiTrained: true` + the adapter id + base model (Bedrock: `additionalModelResponseFields` and `x-vyomi-trained`/`x-vyomi-adapter` headers; Vertex/Azure top-level `vyomi*` keys).

### Trainable bases (4 vCPU / 16 GB Codespace)
`smollm2-135m-instruct, smollm2-360m-instruct, qwen2.5-0.5b, qwen2.5-1.5b, qwen2.5-3b` (3B in bf16). Ids accepted as `<id>`, `vyomi.<id>`, `ollama.<id>`, `qwen2.5:3b-instruct-...`.
Recognised but rejected with the cloud's validation error ("too large to LoRA-train on 16 GB CPU"): llama3.1-8b, qwen2.5-7b, qwen2.5-coder-7b, mistral-7b, gemma2-9b, qwen3-8b, deepseek-r1-8b, qwen3-30b.
Vendor ids (`amazon.nova-*`, titan, gemini, gpt-*) keep the metadata-only behaviour on purpose (existing tests and honesty: a Nova job must not silently become a Qwen fine-tune).

## Trainer: separate script + container recipe (NOT in the Mesh image)
`trainer/` = `lora_train.py` (standalone; emits JSON-line events; cancel file), `requirements.txt` (pinned: torch 2.15.0, transformers 5.23.0, peft 0.21.3, gguf 0.19.0, ...),
`Dockerfile` (python:3.13-slim + CPU-only torch index + pinned llama.cpp converter), `fetch_llamacpp.sh` (sparse, pinned tag b8996 = c3c15053, 3 MB, no build), `sample_data.py`.
`training_core.trainer_mode()` picks, in order (override `VYOMI_TRAINER=docker|venv`):
1. **Docker** (the same Docker CLI seam as `core/llm_runtime`): image `vyomi-trainer:lora1` (`VYOMI_TRAINER_IMAGE`), `docker run --rm --memory 12g -v <work>:/work -v vyomi-trainer-hf:/root/.cache/huggingface`. Base weights download into the named volume on first use.
2. **venv subprocess fallback**: `VYOMI_TRAINER_PYTHON` (or `trainer/.venv/bin/python`) + `VYOMI_LLAMACPP_DIR` (or `trainer/llama.cpp`). `python -m venv trainer/.venv && trainer/.venv/bin/pip install -r trainer/requirements.txt && trainer/fetch_llamacpp.sh`.
Neither available -> validation error with the build instructions (no job created). Nano (bridge registered) -> validation error "Mesh-only: train there, import the GGUF adapter".

## Serving seam (thin change)
- `core/llm_core.chat(..., lora={"name","path","scale"})`: the HTTP path adds `"lora":[{"id":<index>,"scale":s}]` to `/v1/chat/completions`, the id resolved by adapter file name from `GET /lora-adapters`
  (llama-server loads adapters at START; per-request only sets scale). A registered backend fn that declares `lora`/`**kw` receives it (deterministic stub seam). Adapter not loaded -> `LlmUnavailable` with the restart hint (cloud-modeled 503, not a 500).
- `training_core.invoke_chat` fetches `adapter.gguf` from the object store, `llm_core.lora_prepare` writes it to `VYOMI_LLM_ADAPTER_DIR` (default `$CLOUDLEARN_DATA_DIR/llm-adapters`), and calls chat with `model=<base pool id>` so the gateway/pool routes to the base model.
- `core/llm_runtime.lora_args()` + `start()`: when adapters exist, the local `vyomi-llm` container mounts the dir read-only at `/adapters` and starts with `--lora-init-without-apply --lora /adapters/<id>.gguf ...`.
  The Mesh compose (`codespace/.devcontainer/mesh/docker-compose.mesh.yml`, `llm-chat`) is NOT edited here: it needs the same volume + flags and a restart of `llm-chat` after a new adapter lands (open item below).
- Streaming on a LoRA model is refused with a modeled 400 (Azure/Bedrock); the mesh_llm_gateway forwards the `lora` field untouched (body passthrough, read, not run).

## OSS choices (thumb rule)
| Need | Choice | License / size | Substrate | Why / note |
|---|---|---|---|---|
| LoRA training | HF PEFT + PyTorch CPU | Apache-2.0 / BSD; torch CPU wheel about 200 MB (macOS wheel pulled larger), whole venv 983 MB | Mesh / offline only (container or venv) | the proven path from the T2 spike; no hand-written trainer, only 150 lines of loop/eval glue |
| Adapter -> GGUF | llama.cpp `convert_lora_to_gguf.py` + `gguf-py` (pinned b8996) | MIT, 3 MB sparse | trainer image | the converter llama-server's `--lora` expects |
| Serving | llama-server `--lora` + per-request `lora` (existing Mesh AI pack) | MIT | Mesh | Nano serving = wllama adapter-as-second-shard trick (spike section 10), import page is another lane |
| Job runner, object store, 3 cloud shapes | existing `training_core` + cloud adapters | n/a | both | extended, not rewritten |

## Measured (Apple-silicon macOS CPU, 4 threads, torch 2.15.0; NOT a 4 vCPU Codespace; synthetic templated triage rows, rank 8, all attention + MLP projections)
| Base | rows / steps | s/step | total | peak RSS | adapter (f16 GGUF) | held-out ppl base -> tuned | exact match base -> tuned |
|---|---|---|---|---|---|---|---|
| SmolLM2-135M | 110 / 100 (4 ep, bs 4) | 0.47 | 57 s | 1.49 GB | 4.9 MB | 271.5 -> 1.06 | 0/11 -> 8/11 |
| SmolLM2-360M | 110 / 75 (3 ep) | 1.05 | 100 s | 2.63 GB | 8.7 MB | 151.8 -> 1.06 | 0/11 -> 11/11 |
| Qwen2.5-0.5B | 110 / 75 (3 ep) | 1.73 | 151 s | 3.48 GB | 8.8 MB | 194.2 -> 1.08 | 0/11 -> 10/11 |
Qwen2.5-1.5B / 3B: **not measured** (download budget); rough scaling suggests several s/step and 8-12 GB RSS for 1.5B fp32, 3B only fits in bf16; treat as unverified. A 4 vCPU Codespace will be slower than these numbers (not measured).
Held-out = 10 % of rows (min 2), so n=11: coarse; the task is easy and templated: this proves the mechanism, not general quality. The adapter size is bigger than the T2 spike (1.86 MB) because this lane targets MLP projections too and r=8 on bigger models; the 5 MB cap applies to training DATA, adapters are about 5-9 MB.
GGUF validity was checked by reading it with `gguf.GGUFReader` (type adapter/lora, 420 tensors, f16) and by the stored bytes equalling what the seam writes; it was NOT loaded by a real llama-server.

## Tests
`tests/conformance/test_chat_lora_jobs.py` (40 checks, about 2.5 min): real boto3 (bedrock + bedrock-runtime + s3), plain REST for Vertex, the real `openai` SDK (AzureOpenAI). Trains SmolLM2-135M for real on all three clouds,
checks per-step loss growth while running, falling loss, held-out ppl improvement vs adapter-off baseline, adapter.gguf in the store with metadata, stop kills the trainer process, reload persistence, caps/validation/unavailable/Nano errors,
serving through a deterministic registered backend (adapter selection, base model id, exact adapter bytes, vyomiTrained) and through a fake llama-server over real HTTP (the `lora:[{id,scale}]` wire contract).
Run: `PYTHONPATH=.:<openai-pkgs> VYOMI_TRAINER_PYTHON=<venv python> VYOMI_LLAMACPP_DIR=<llama.cpp dir> python tests/conformance/test_chat_lora_jobs.py` (validation + seam parts run without the trainer; training parts SKIP).
Existing suites unchanged and green: test_training_jobs 43, test_bedrock_ctl 24, test_gcp_vertex_core 53, test_azure_openai_inference 15, test_bedrock_models_alias 28. `wasm/core/*` regenerated with `wasm/build_cores.py`.

## NOT run / declared limits
- **No real llama-server, no Codespace, no Docker build was run.** The `--lora` flags, `GET /lora-adapters` shape, per-request `lora` field and base/adapter compatibility follow llama.cpp docs/knowledge at tag b8996 but were verified only against a fake server. A mismatched base GGUF (e.g. Q4 `qwen2.5-3b` served while the adapter was trained on the HF fp weights) is expected to work (llama.cpp applies LoRA on quantised bases) with some quality loss: unmeasured.
- The Dockerfile and the CPU-torch-index install were not built here (no Docker pulls); the venv path is what ran.
- llama-server loads adapters only at start: a newly trained adapter needs the `llm-chat` container restarted with the new `--lora` list (Mesh compose + restart hook are an open item; `llm_runtime.start()` handles the single-container offline case).
- Held-out check is small and from the user's own rows; a tuned model is a small open model + LoRA, not a vendor model. Job records are process-local like the head jobs; adapters persist in the object store and are rebuilt for Bedrock on reload (Vertex/Azure records are not rebuilt, as for heads).
- Training stays on loss over the last assistant turn only; multi-turn history is context. `max_seq` truncates (rows whose prompt fills the window are dropped and counted). Tool-calling training data is not supported.
- Not measured: 1.5B/3B training, Codespace timing, long-run (2000-row) time, Linux CPU-torch wheel size.

## Shared-file edits (small, additive)
`core/llm_core.py` (`lora` kwarg + helpers), `core/llm_runtime.py` (`lora_args`, mount), `core/ai_models_core.py` (Bedrock chat-LoRA invoke, Azure lora chat + per-step events, Azure hyperparameter default no longer forced to 10),
`core/bedrock_ctl_core.py` (note text, rehydrate engine/artifact), `core/gcp_vertex_core.py` (`generateContent` endpoint verb, chat predict), `wasm/core/*` regenerated. Nothing in `consoles/`.
