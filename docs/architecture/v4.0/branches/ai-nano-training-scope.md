# Nano: train lightweight custom models in the browser (SCOPE, not built)

Owner ask (2026-11-15): Nano should let users train lightweight models, in the same spirit as the WebLLM chat models, so that
custom models are real on Nano and not the metadata-only lifecycle shipped by lane `bedrockui-b`.

Status: scope only. Every library/size/speed claim below marked (verify) is from general knowledge and MUST be confirmed by the
Phase 0 spike before it is promised in a console or a doc. No code is written by this document.

## 1. Where we are

- `core/bedrock_ctl_core.py`: `CreateModelCustomizationJob` completes in about 2 s with a custom-model record. It trains nothing; an
  invocation of the custom model resolves to the base model's local alias. It is labelled "metadata only" in the job description.
- GCP (Vertex tuning jobs) and Azure (OpenAI fine-tuning jobs) have no equivalent lifecycle at all on this build.
- Nano serves chat through WebLLM (smollm2-360m, qwen2.5-0.5b, llama3.2-1b, qwen2.5-1.5b) and embeddings through
  transformers.js (`all-minilm-l6-v2`, lane `nanoembed`). WebLLM and transformers.js are inference-only.

## 2. What "train" can honestly mean in a browser tab

| Tier | What the user trains | Real training? | Fits a tab? | Result that is invoked |
|---|---|---|---|---|
| T1 | A task head on frozen embeddings: classifier, intent router, reranker, anomaly scorer | Yes (gradient descent on a small head) | Yes, seconds to minutes, any laptop | A model that answers `classify`/`score` calls; an embedding+head pipeline |
| T2 | A LoRA adapter on a very small chat model (about 100M-360M parameters) | Yes, if a trainable WebGPU/WASM engine works (verify) | Maybe, WebGPU and memory dependent, tab must stay open | The base model plus the adapter, answering chat |
| T3 | Nothing: user brings weights (GGUF or MLC) | No, import only | Download size dependent | The imported model |
| T0 | Nothing: retrieval or prompt shaping | No | Yes | Existing RAG / prompt tooling, not a custom model |

Recommendation: ship T1 first because it is real and reliable, run a time-boxed spike for T2, offer T3 as the fallback for "my own
model", and never present T0 as training.

## 3. Cross-cloud API surface (what the console/SDK call)

- AWS Bedrock: `CreateModelCustomizationJob` (FINE_TUNING, CONTINUED_PRE_TRAINING, DISTILLATION), `GetModelCustomizationJob`,
  `ListCustomModels`, `GetCustomModel`, `DeleteCustomModel`, Custom Model Import for T3.
- GCP Vertex: `tuningJobs` (supervised tuning spec), tuned model resources under Model Registry / Garden.
- Azure OpenAI/Foundry: `/openai/fine_tuning/jobs`, `/openai/files`, then a deployment of the fine-tuned model.
- Data in: JSONL from the simulated object store (S3 / GCS / Blob, persisted in OPFS on Nano).
- Data out: a custom-model record plus an artifact (head weights, or LoRA adapter) stored in the same object store and OPFS.

The three clouds share one job runner behind thin per-cloud adapters (thumb rule: wire adapters only, one engine).

## 4. Open-source building blocks (all to verify in the spike)

| Need | Candidate | Licence | Why / concern |
|---|---|---|---|
| Embeddings (frozen) | transformers.js `all-minilm-l6-v2` (already shipped) | Apache-2.0 | Already in Nano. |
| Train a small head | TensorFlow.js (WebGL/WebGPU/WASM backends), or onnxruntime-web training (verify maturity), or hand-rolled logistic/MLP in typed arrays | Apache-2.0 / MIT | A head is tiny; the lightest option may be plain JS. Prefer an existing library if it covers dense layers, Adam and checkpointing. |
| Classical ML in Python on Nano | scikit-learn from Pyodide (already the Pyodide distribution) | BSD | Logistic regression, linear models, TF-IDF without a new dependency. Good for the tabular and text classifier case. |
| LoRA on a tiny LM | A WebGPU training engine: Burn (Rust, wgpu), candle (Rust, WASM), or a custom onnxruntime-web training graph | MIT / Apache-2.0 | None is a drop-in. Needs a spike to see whether any trains a 135M-360M model within a tab's memory. Highest risk item. |
| Serving a LoRA adapter | wllama (llama.cpp compiled to WASM, supports GGUF LoRA adapters; CPU only) | MIT | WebLLM cannot hot-load arbitrary adapters (verify), so a tuned chat model may need to be served by wllama, not WebLLM. That is slower than WebGPU WebLLM. |
| Persist artifacts | OPFS + IndexedDB | n/a | Already used for Nano state. |

We will not build a training framework. If the spike finds no engine that fits, T2 is declared unsupported on Nano and T3 import plus T1 cover the ask.

## 5. Phases

Phase 0: spike (2-3 days, no console work)
- T1: train a classifier head on MiniLM embeddings inside a worker; measure time, memory, accuracy on a 1k-row JSONL.
- T2: try to LoRA-train SmolLM2-135M / 360M on a small instruction set with each candidate engine; record whether it fits, the
  tokens/s, peak memory, and whether the adapter can be served (wllama).
- Output: a go/no-go note per tier with measured numbers, written into this doc.

Phase 1: job engine + T1 (about 1 week after a go)
- One `training_core.py` job runner behind the three cloud adapters; jobs run in a dedicated worker, report real progress/metrics
  (loss, accuracy), are cancellable, and survive tab reload where the engine allows (checkpoints in OPFS).
- Replace the Bedrock metadata-only completion for jobs whose base model is trainable; keep metadata-only for everything else and say so.
- Invocation of a trained T1 model returns real predictions.
- Console: real job page (progress, metrics chart, logs), training-data validation (JSONL schema, size caps), custom-model page
  showing the artifact, base model and measured eval.

Phase 2: T2 (only if the spike says go; 1-2 weeks)
- LoRA on the chosen tiny base model, adapter saved to OPFS, served through wllama; chat playground selects it.

Phase 3: T3 import and Mesh parity (about 1 week)
- Bring-your-own GGUF/MLC import on Nano; same job API on Mesh with a heavier backend (LoRA over llama.cpp on the Codespace).

## 6. Limits to state in the product

- The tab must stay open and awake; mobile and low-memory machines may not support T2.
- Only small models and small datasets; row/size caps enforced and shown before the job starts.
- WebGPU is required for any GPU speed-up; without it the job falls back to CPU or is refused with a clear message.
- A tuned model is a Vyomi artifact: it is not a real cloud vendor model and does not match vendor quality or behaviour.
- Mesh is the place for anything bigger than a head or a tiny LoRA.

## 7. Acceptance for "real" custom models on Nano

1. Submit a fine-tuning job through the real SDK (Bedrock/Vertex/Azure shapes) with JSONL from the simulated object store.
2. The job shows real metrics that change run to run, and can be cancelled.
3. The custom model, when invoked, behaves measurably differently from its base on a held-out set (shown in the evaluation).
4. Reload the tab: the model is still there and still invokable.
5. Nothing is labelled "trained" unless training actually ran.

## 8. Decisions needed from the owner

1. Is T1 (heads on frozen embeddings: classifier / router / reranker) acceptable as the first real "custom model", given a chat LoRA is uncertain?
2. Approve the Phase 0 spike (2-3 days) before any console work?
3. May a tuned chat model be served by wllama (CPU, slower) if WebLLM cannot load adapters, or should T2 be dropped in that case?
4. Dataset and size caps: is "about 1k rows, a few MB" the right order of magnitude for Nano?
