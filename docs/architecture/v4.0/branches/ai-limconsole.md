# ai-limconsole: console gaps (import pages, Foundry agent tools, capability badges, build hygiene)

Branch `v4/ai-limconsole`. UI over existing engines; no new engine except one bug fix (below).

## Delivered
| Item | What |
|---|---|
| Import model, AWS | Bedrock > Tune > Imported models: Models and Jobs tabs, 3-step wizard (uploads the adapter to `s3://vyomi-models/uploads/...`, `CreateModelImportJob`), job and model detail, Playground lists imported models. |
| Import model, GCP | Vertex Model Registry: import dialog (uploads to `<project>-vyomi-imports`, `models:upload` with label `vyomi-import=chat-lora`), Type column "Chat (LoRA adapter)", "Chat with model" (deploys to an endpoint on demand), Studio lists imported endpoints. |
| Import model, Azure | Foundry > Custom models (Vyomi extension `POST /openai/vyomi/custom-models`), deploy as ARM deployment format `Vyomi`, chat. |
| Shared | `consoles/src/common/importModel.js`: GGUF magic pre-check, meta builder, wllama progress hook (`vyomiWllamaStatus`, `vyomi-wllama`). |
| Foundry agent tools | `AgentTools.jsx`: code_interpreter and file_search toggles, vector stores tab (create, files, delete), file upload, citations `[n]` with Sources, output files with View, run steps (code and logs). |
| Capability registry | GCP vertex-ai.json: sessions, memory-bank, app-builder, evaluation, metadata, monitoring, agent-registry, topology, adk, mcp-servers (existing: rag-engine, search, agent-gateway, agent-policies, model-armor, provisioned-throughput); models and endpoints text updated for imports. Azure: new `foundry.json` (agents, content-filters, evaluations, promptflow, finetuning, custom-models), AI Search panels wired to `aisearch.json`. AWS `bedrock.imported-models`. Badges only render where the level is limited. |
| `@xyflow/react` | In `consoles/package.json` (12.3.5, plus `umap-js`, and `scheduler` which `--omit=peer` would otherwise skip). `rag-overlay` removed. |
| Smokes | `consoles/tests/run-ai-smokes.sh` runs all AI smokes against the Nano preview (default port 8841, `--tier max`). |

## Bug fixes found on the way
- `core/training_core.read_uri` could not read `gs://` objects written through the GCS console path (404 from the S3 reader). Added `_gcs_get`; regression checks in `test_model_import.py` (58/58).
- `core/azure_openai_agents_core.py` defined `_run_view` twice (Assistants and Evals); the Evals one shadowed it and broke every assistant run. Renamed to `_eval_run_view`.
- `test_model_import.py` used a fixed state file and failed on re-run (`BucketAlreadyOwnedByYou`); now per-process.
- `smoke-azure-aoai.mjs` seeded `qwen2.5-3b` format Alibaba (rejected 400); now `OpenAI/gpt-4o`.

## One React
`npm install --omit=peer` in `consoles/`. Checked per bundle: `ReactCurrentDispatcher` count unchanged from baseline and a single `version:"18.3.1"` pair; Azure's four `scheduler.production` matches equal the baseline. Build: `node consoles/build.mjs --cloud <aws|gcp|azure>`.

## Capability test, per entry
`CAP_ONLY=<id substring> PYTHONPATH=. python tests/conformance/test_capabilities.py` checks only matching claims (new additive filter; no filter = full sweep as before). Every new id above passes in isolation.

## Honest limits
- Serving an imported model needs the Nano tab and internet (base GGUF from Hugging Face, 105 to 386 MB, cached in OPFS). Mesh and offline store imports but cannot serve them yet.
- Headless Playwright has no local model: agent runs end with the native "No local LLM backend" failure, shown as such; citations and run steps render only when a model answers. Retrieval and file parsing (vector store file status completed) are verified.
- Bundles under `wasm/v4` are not committed.
