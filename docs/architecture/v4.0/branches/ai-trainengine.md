# ai-trainengine: real head training behind Bedrock / Vertex / Azure OpenAI customization

- Owner: lane `trainengine` (2026-11-15). Branch `v4/ai-trainengine`, base local `v4/ai-integration` (4e71e1d6f). Console pages are lane `trainui` (not touched here).
- Spec: `ai-nano-training-scope.md` section 9 (T1 heads) and the ROUND 4 shared contract (job record key `vyomiTraining`, caps, invocation shapes).

## What exists
`core/training_core.py` is the one job runner. The three cloud cores are thin adapters:
- Bedrock (`core/bedrock_ctl_core.py`): CreateModelCustomizationJob on a trainable base runs a real job; Get/List/Stop mirror it; the custom model is invocable
  through InvokeModel / Converse on the custom-model ARN (`core/ai_models_core.py::_invoke_trained`). Non-trainable bases keep the metadata-only 2 s completion and say so.
- Vertex (`core/gcp_vertex_core.py`): `tuningJobs` create/get/list/cancel; on success a tuned Model + Endpoint exist and `endpoints/{id}:predict` answers from the head.
- Azure OpenAI (`core/ai_models_core.py`, `/openai/files` multipart upload + `/openai/fine_tuning/jobs` create/list/get/cancel/events, also under `/openai/v1`):
  the fine-tuned model `ft:<base>:<suffix>:<id>` can be deployed through ARM (`azure_cognitiveservices_core._find_model` accepts `ft:`) and `chat/completions` on that
  deployment returns the label as assistant content (Vyomi extension, `vyomiTrained: true`, `vyomiScores`).

Trainable base = `all-minilm-l6-v2`, `nomic-embed-text`, or any `vyomi.head.*` id. Rows: `{"text","label"}` (classifier; `taskType=router` gives the 384->64->K MLP) or
`{"query","positive","negative"}` (pairwise reranker on `[q*d, |q-d|]`). Caps (all three clouds, modeled validation errors, no job created): 2000 rows, 5 MB, 20 labels,
min 10 rows and 2 labels, epochs 1..50. 20 % seeded held-out split; baseline = majority class (classifier/router) or zero-shot cosine (reranker). Per-epoch metrics
`{epoch, loss, accuracy, valAccuracy}`; status Queued, Embedding, Training, Evaluating, Completed|Failed|Stopped; Stop cancels within one mini-batch.
Artifact `head.json` (float32 base64, embedder id recorded) is written to `s3://vyomi-models/models/<id>/head.json` (+ `meta.json`, and `<outputDataConfig>/<id>/head.json` for
Bedrock). Reload: heads and Bedrock custom-model records are rebuilt from that bucket; invocation refuses a head whose embedder differs from the running one.

## Substrates
| | Offline / Mesh | Nano (browser) |
|---|---|---|
| runner | `head-py`: background thread inside the request's contextvars (so the head lands in that cloud space's store) | `nano-head-js`: `wasm/train-bridge.js` embeds in the tab (MiniLM via `vyomiEmbed`), `wasm/train-worker.js` trains typed-array Adam in a Web Worker, events flow back to `training_core.on_event` |
| embedder | `llm_core.embed` (nomic-embed-text via llama.cpp; labelled `vyomi-hash-embed` fallback when no model is up, recorded in the head and the job note) | all-MiniLM-L6-v2 (already in Nano) |
| invoke | Python forward pass | same Python forward pass, query embedded through the async `arun` seam |

## OSS choices (thumb rule)
| Need | Choice | Why / limits |
|---|---|---|
| Embeddings | existing `llm_core` seam (nomic-embed-text / transformers.js MiniLM, both Apache-2.0) | nothing new to ship |
| Head training Nano | plain typed-array JS Adam (spike winner: 0.96 s for 3 heads, 76 MB, 0 download) | hand-written (about 90 lines) because TF.js costs +40 % RAM and 0.4 MB for no capability a head needs; TF.js wasm is the documented fallback |
| Head training offline | pure-Python Adam, no numpy (numpy is not in `requirements.txt`) | fine up to the caps; an MLP epoch on 1600 rows x 64 hidden is a few seconds in CPython. numpy/sklearn would be faster but add a dependency to the Mesh image |
| Object store / jobs / SDK shapes | existing simulated S3, adapters only | no new backend |

## Tests
- `tests/conformance/test_training_jobs.py` (43 checks): boto3 (Bedrock create/get/list/stop, invoke_model, converse, S3), plain REST for Vertex (as the aiplatform client sends it;
  `google-cloud-aiplatform` itself is not installed in the probe venv), the real `openai` SDK (`AzureOpenAI`: files.create, fine_tuning.jobs create/retrieve/list/list_events/cancel, chat.completions).
  Happy path (held-out accuracy beats baseline by >0.3, loss changes every epoch), cancel, caps rejection (6 Bedrock cases, Vertex, Azure), reload persistence on all three, reranker, metadata-only fallback.
  Run: `PYTHONPATH=.:<dir with: pip install --target openai> python tests/conformance/test_training_jobs.py`.
- `wasm/ui-tests/train-e2e.mjs` (10 checks): REAL Nano console in headless Chromium: S3 upload, CreateModelCustomizationJob (engine `nano-head-js`), 8 epochs, held-out 1.0 vs baseline 0.25,
  InvokeModel -> shipping, Stop, missing-data 400, tab reload then invoke again. Needs internet for MiniLM weights. Run with `NANO_DIR=wasm NODE_PATH=<portal-OLD>/node_modules node wasm/ui-tests/train-e2e.mjs`.
- Existing suites still green: test_bedrock_ctl 24, test_bedrock_models_alias 28, test_agentcore_facilities 25, test_gcp_vertex_core 53, test_azure_openai_inference 15, test_azure_cognitiveservices_core 28; Facilities e2e `--llm-stub` 13/13.

## Declared limits
- A head separates only what the frozen embedder separates; held-out numbers are on the customer's own rows (test data is synthetic and easy). Not an LLM fine-tune; every response says `vyomiTrained`.
- Nano: only contexts that own the embedder install the bridge (the console tab). SDK/CLI jobs arriving through the relay shared worker / relay tab fail fast ("no thread support and no Nano training worker") instead of silently doing nothing. The tab must stay open while embedding (~12 ms/text).
- boto3 drops unmodeled response keys, so `vyomiTraining` is visible to REST callers and the console, not to boto3 (boto3 still gets `trainingMetrics.trainingLoss`). openai SDK keeps it via `model_extra`.
- Vertex dataset `gs://` is read from fake-gcs when `CLOUDLEARN_GCS_URL` is set, otherwise from the shared simulated object store (same bucket name). Job records for Bedrock/Azure are process-local like before; heads persist in the object store.
- Offline pure-Python training has not been timed on a large 2000-row MLP in this lane; the thread cannot be hard-killed, only cancelled between mini-batches.
- Bedrock `hyperParameters` accepted: epochCount, taskType (`classifier|router`), learningRate, learningRateMultiplier, batchSize.

## Shared-file edits (kept small, additive)
`core/aws_wire_router.py` (bind object store to the engine in `__init__`; `/openai/(files|fine_tuning)` routed to az-openai), `core/azure_cognitiveservices_core.py` (`ft:` models deployable),
`wasm/nano-boot.js` (+ relay lists) register `training_core.py` and load `train-bridge.js`; `wasm/core/*` regenerated by `build_cores.py`.

## Open
Mesh: not exercised on a real Codespace here (offline runner = the same code run in-process). Non-embedder bases (chat LoRA) stay metadata-only; chat-LoRA on Mesh is a later lane.
