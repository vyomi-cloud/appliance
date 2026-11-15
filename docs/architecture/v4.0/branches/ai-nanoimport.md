# ai-nanoimport: import a LoRA chat model (trained on Mesh / your machine) and serve it in the Nano tab with wllama

- Owner: lane `nanoimport` (2026-11-15/16). Branch `v4/ai-nanoimport`, base local `v4/ai-integration` (50b84446c). No `consoles/` changes (the UI import page comes later).
- Spec: `ai-nano-training-scope.md` section 10 (no in-tab chat training; chat LoRA is trained elsewhere and IMPORTED as GGUF) and the spike `spikes/nano-training-trainlora/`.

## What exists
`core/import_core.py` (new, pure Python, vendored to `wasm/core/`) is the shared engine; the clouds are thin adapters:

| Cloud | Wire | Notes |
|---|---|---|
| Bedrock | Custom Model Import, real shapes: `CreateModelImportJob`, `GetModelImportJob`, `ListModelImportJobs`, `ListImportedModels`, `GetImportedModel`, `DeleteImportedModel` (`core/bedrock_ctl_core.py`); `InvokeModel` (Llama-style `{"prompt"}` or `{"messages"}`), `Converse`, `ConverseStream` on `arn:...:imported-model/<id>` (`core/ai_models_core.py`) | `modelDataSource.s3DataSource.s3Uri` = a prefix holding `adapter.gguf` + `adapter_meta.json` (VYOMI EXTENSION: real Bedrock wants Hugging Face weights). Artifact problems fail the job (`status Failed` + `failureMessage`), like the async API |
| Vertex | `models:upload` with `model.artifactUri=gs://.../` (adapter dir) -> Model labelled `vyomi-imported`; `deployModel` to an endpoint; endpoint `:generateContent` / `:streamGenerateContent` (buffered) / `:predict` (instances `prompt`/`messages`) (`core/gcp_vertex_core.py`, `ai_models_core.vertex_imported_call`) | an upload whose artifactUri has no adapter stays the old metadata-only upload; label `vyomi-import: chat-lora` forces import (404 if no adapter). Bad adapter -> 400 INVALID_ARGUMENT |
| Azure | **Vyomi extension** `POST /openai/vyomi/custom-models` (multipart `name`,`adapter`,`meta`, or JSON `{name, adapter_file, meta_file}` with ids from `/openai/files`), GET list/one, DELETE; deploy through the normal ARM deployment (`model.format=Vyomi`, `model.name=<id>`), then `chat/completions` | no real Azure API registers a custom LoRA this way; labelled in `vyomiNote`. Reading `modelUri` from the S3 store was dropped: under the Azure provider context the S3 store is a different space |

Records and answers carry `vyomiImported: true` and `vyomiTrained: true`. Model ids are `vyomi.import.<8 hex>`.

Validation (`import_core.validate_artifacts`, all with a user-facing reason): GGUF magic + version, header parsed (truncation, implausible sizes), must be `general.type=adapter` / `adapter.type=lora`
(a merged model is rejected), architecture, uniform rank, rank/alpha in `adapter_meta.json` must equal the GGUF's, hidden size must match the base (a 360M adapter cannot be loaded on 135M), 50 MB cap,
`base_model` must be one Nano can serve (`smollm2-135m-instruct`, `smollm2-360m-instruct`; aliases accepted), optional `base_quant`.

Persistence: adapter + meta live in the simulated object store at `s3://vyomi-models/imports/<id>/` (deliberately not under `models/`, which holds heads and has its own rehydration); the registry,
the Bedrock records and jobs are rebuilt from there after a reload. The adapter is also cached in OPFS (content-addressed `adapter-<sha256>.gguf`), the base GGUF in OPFS (`<file>` + `.ok` marker).

## Serving on Nano
`llm_core` seam: `set_custom_backend(is_fn, afn)`. A request whose `model` is an imported id is answered ONLY by that engine through the same async replay as WebLLM (`NeedAsync(kind="custom")`); without an engine
it fails as unavailable (Bedrock 429 ModelNotReady, Vertex 503, Azure 503). The default model is never a fallback, on any runtime. Base models keep using WebLLM untouched. Tools/structured output on imported models are
prompt-translated (never native).
`wasm/wllama-bridge.js` (installed from `nano-boot.js`, Python glue is `_import_chat`): pinned `@wllama/wllama@3.13.0` from jsDelivr (override `globalThis.VYOMI_WLLAMA_CDN`), base GGUF fetched from Hugging Face on first use with
progress (`vyomiWllamaStatus()` + `vyomi-wllama` event) and cached in OPFS, adapter loaded as the second shard (`lora_adapters:[{path:'models/model-00002-of-00002.gguf'}]`, an undocumented trick that works in 3.13.0),
one model resident at a time, generations queue.

Bases (bartowski GGUF repos, Apache-2.0 SmolLM2): 135M default **Q8_0 145 MB**, optional Q4_K_M 105 MB; 360M default Q4_K_M 271 MB, optional Q8_0 386 MB. Default for 135M is Q8_0 because the adapter was trained on f16 weights.

## Measured (SmolLM2-135M, r=8 adapter 1.86 MB f16 GGUF, spike ticket-triage task, 30 held-out, exact match, temperature 0; headless Chromium on a memory-pressured 16 GB Mac)
| Setup | Exact match | Notes |
|---|---|---|
| spike f16 base + adapter (4 threads) | 30/30 (spike) | reference |
| Q8_0 base + adapter (4 threads, isolated page) | **30/30** | 35.6 tok/s incl. prefill, load 0.9 s |
| Q4_K_M base + adapter (4 threads) | 28/30 | quantisation noise; load 0.8 s, 21.8 tok/s |
| Q4_K_M base + adapter, 1 thread | 28/30 | 8 tok/s |
| same Q4_K_M base, no adapter | 0/30 | |
E2E through the Nano console wire (`wasm/ui-tests/import-e2e.mjs`): see the results block at the bottom.

## Threads / cross-origin isolation
wllama multi-thread needs `SharedArrayBuffer` = COOP `same-origin` + COEP. Nothing in the portal or the Nano bundle sends these headers for `/nano` (grepped both repos), so in the tab `crossOriginIsolated` is false and wllama
runs **single-thread** (it falls back by itself; `vyomiWllamaStatus().multiThread` reports it). Getting 3-4x needs the portal to serve `/nano` with COOP/COEP (and every cross-origin subresource, e.g. the jsDelivr
module and Hugging Face, CORS/CORP compatible); that is a portal change, not done here.

## OSS choices (thumb rule)
| Need | Choice | Why / limits |
|---|---|---|
| CPU LLM + LoRA in the tab | wllama 3.13.0 (llama.cpp WASM, MIT; 10 MB wasm) | measured in the spike; WebLLM cannot apply a GGUF LoRA |
| Base models | SmolLM2 135M/360M Instruct GGUF (Apache-2.0) | small enough for CPU WASM; same family trained in the spike |
| Adapter format | llama.cpp `convert_lora_to_gguf.py` output | produced by the Mesh trainer / user machine |
| Hand-written | GGUF header parser (about 60 lines) + wire adapters + bridge | no Python GGUF lib is available under Pyodide (`gguf` needs numpy); only the header is read |

## Tests
- `tests/conformance/test_model_import.py` (56 checks; real boto3 for Bedrock + S3, REST for Vertex, the real `openai` SDK + REST for Azure): validation matrix, jobs Failed/Completed, list/get/delete, conflicts, Converse/InvokeModel/ConverseStream
  routed to the custom engine, base models never reach it, no-engine honest errors on all three clouds, reload rebuilds from the object store, Vertex upload/deploy/generateContent/predict, Azure register/deploy/chat. The serving engine in this test is a labelled stub
  (`llm_core.set_custom_backend`); real serving is the browser test.
- `wasm/ui-tests/import-e2e.mjs`: headless Chromium, real Nano console, real wllama + Hugging Face base, 30 held-out tickets through Bedrock Converse, base-only comparison, reload persistence, delete.
  Run: `NANO_DIR=$PWD/wasm NODE_PATH=<portal-OLD>/node_modules node wasm/ui-tests/import-e2e.mjs` (needs internet; first run downloads 145 MB into OPFS).
- Fixtures: `tests/conformance/fixtures/nanoimport/` (adapter.gguf 1.8 MB, adapter_meta.json, heldout.json).
- Shared-file edits (small, additive): `core/aws_wire_router.py` (route `/openai/vyomi/custom-models`; `gcp-vertex` goes through `llm_core.arun`; `training_core.bind_gcs` call), `core/training_core.py` (`bind_gcs`; `gs://` reads the GCS store first),
  `core/llm_core.py` (custom backend hook), CORES lists (`nano-boot.js`, `relay/*`, `build_cores.py`).

## Declared limits
- Serving is Nano-only (the tab must stay open and own the engine; relay shared-worker callers get an honest error). Mesh/offline accept imports and keep the records but cannot serve them (llama-server `--lora` is not wired).
- Single-thread today (no COOP/COEP): about 8 tok/s Q4 on this machine vs about 22-36 with threads. First use downloads 105-386 MB (no resume); needs OPFS `createWritable` (Chromium, Firefox 111+, not older Safari).
- Memory: base is held in the tab twice while loading (about 2x the GGUF); 360M Q8 is not recommended on low-RAM devices. One imported model resident at a time. Context 2048. No streaming tokens (answers are returned whole; stream APIs replay).
- Q4 bases cost accuracy relative to f16 training (28/30 vs 30/30 here); quality claims only come from your own held-out check.
- Only SmolLM2 135M/360M (llama architecture) bases; Azure/Vertex Nano `gs://` reads fall back to the S3 store when the GCS store has no object.
- wllama LoRA via the second-shard trick is not a documented API: version is pinned; re-verify on upgrade.

## Results
`import-e2e.mjs`, real Nano console in headless Chromium, real wllama 3.13.0 + Hugging Face Q8_0 base, single-thread (page not cross-origin isolated): 17/17 checks.
- Tuned model through Bedrock Converse on the imported ARN: **30/30** held-out exact match; same base GGUF without the adapter: **0/30**.
- First call (download 145 MB + load): 18.4 s on this network; model load 1.1 s; steady state 5.5 tok/s end to end through the console wire (single thread).
- After a tab reload: adapter from the object store/OPFS, base from OPFS (no download): first answer 9.7 s (Nano re-boot included).
- The SW's 15 s backend timeout is extended by a `{keepalive:true}` heartbeat from the page while wllama downloads/loads/generates (`sw.js`, `nano-boot.js`).
- `test_model_import.py`: 56/56. Regression: `test_training_jobs.py` re-run (see report).
- Not measured: WebGPU, multi-thread inside the Nano page, 360M, Safari/Firefox.
