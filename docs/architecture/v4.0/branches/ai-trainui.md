# Branch: v4/ai-trainui

Owner: AI session (lane `trainui`). Base: `v4/ai-integration` (4e71e1d6f). Not merged; the orchestrator merges and rebuilds the wasm/v4 bundles (none are committed here).

## Purpose
Console UI for REAL (small head) training jobs on all three clouds, against the shared Round 4 contract (job record extension `vyomiTraining`).
Backend is built in parallel by lane `trainengine`; this lane only touches `consoles/` and uses each console's existing wire client, so it works the moment the backend lands.

## Pages
| Cloud | Where | What |
|---|---|---|
| AWS (Cloudscape) | Bedrock > Custom models, job detail route `#/bedrock/custom-models/jobs/:id` | Create fine-tuning job: trainable base group (all-MiniLM-L6-v2, nomic-embed-text), task type, bucket + `.jsonl` object picker from the simulated S3 with client-side cap validation; detail page: status, progress, per-epoch chart, held-out vs baseline, Stop, artifact, Try it (InvokeModel) |
| GCP (MUI) | Agent Platform > Models > Tuning `#/vertex-ai/tuning` (+ `/tuning/:location/:id`) | list, Create tuned model dialog (GCS picker + validation), detail, cancel, Try it (`:predict`) |
| Azure (Fluent) | Foundry > All models > Fine-tuning `#/foundry/finetuning` (+ `/finetuning/:jobId`) | list, create (uploaded file or local upload with validation), detail, cancel, Try it (chat/completions, Vyomi extension) |

Shared code: `consoles/src/common/training.js` (caps, trainable-base test, JSONL validator, `trainingOf(job)`), `consoles/src/common/TrainingViz.jsx` (SVG loss/accuracy chart, progress bar, held-out bars, score bars; theme-neutral, used by all three).

## Contract assumptions the engine lane must match
- Trainable base = `all-minilm-l6-v2`, `nomic-embed-text` or `vyomi.head.*` (bare id or ARN tail). Task type is sent as `hyperParameters.taskType` (Bedrock), `supervisedTuningSpec.hyperParameters.taskType` (Vertex), `hyperparameters.taskType` (Azure), values `classifier|router|reranker`. Epochs: `epochCount` / `epochCount` / `n_epochs`.
- Detail pages poll GET job every 1.5 s while `vyomiTraining.status` is Queued/Embedding/Training/Evaluating and render `vyomiTraining` as specified. Get-job must carry it (list summaries may too: used for the progress column).
- Try it: Bedrock `POST /model/{outputModelArn}/invoke` `{task:classify,text}` / `{task:score,query,document}`; Vertex `POST /v1/{tunedModel.endpoint}:predict` `{instances:[{text}|{query,document}]}` (falls back to `tunedModel.model`); Azure `POST /openai/deployments/{fine_tuned_model}/chat/completions` (reranker sends the user message as JSON `{"query","document"}`, scores read from `vyomi.scores` or `scores`).
- Azure files: `GET /openai/files`, `GET /openai/files/{id}/content`, multipart `POST /openai/files`.
- Stop: Bedrock `POST /model-customization-jobs/{id}/stop`, Vertex `:cancel`, Azure `/fine_tuning/jobs/{id}/cancel`.

## Honest labelling
Every trainable create/detail page shows "Trained in this simulator on the embedding model: a small classifier/reranker head, not a language model. It cannot generate text." Non-trainable bases show "not trainable here... metadata only" and keep the old behaviour. On Nano a "keep this tab open" warning shows while training. Results carry the `vyomiTrained: true` note.

## Tests
`consoles/tests/smoke-training-ui.mjs` (Playwright, 51 checks, ALL PASSED x3) runs the real built consoles under `nano_preview.mjs` with service workers blocked and `consoles/tests/training-fake.mjs` answering `/_wire` per the contract (time-driven 7 s job, caps rejection, stop). Covers create validation (rows / labels / bad rows / size), progress, chart points, held-out, artifact, Try it, Stop, lists. Screenshots reviewed by eye.

    node consoles/build.mjs && node consoles/nano_preview.mjs --port 8771 --tier pro &
    BASE=http://127.0.0.1:8771 SHOTS=/tmp/shots node consoles/tests/smoke-training-ui.mjs

## Declared limits / open
- Verified against the fake only; real-backend wiring (paths above) is unverified until `trainengine` merges.
- The fake build needed `@xyflow/react` + `umap-js` which are imported by RAG Studio but missing from `consoles/package.json` on the integration branch (installed outside the repo for this run; someone should add them).
- Bedrock Models tab now also has a Create button (it was only on the empty state / Jobs tab).
- Vertex "Training > Model tuning" tab (metadata list) is left as is; the Tuning nav and Overview card now point at the new page.
- Reranker Try it has not been exercised in the browser test (classifier path only).
