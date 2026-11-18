# Branch: v4/endurance-proof (vyomi-endurance, SDK / CLI / UI proof layers)

## Why
Terraform proves the control plane (the provider reads back via Describe/List/Get). It does not prove that the same resources are visible and usable through the other three
surfaces. This branch adds independent SDK, CLI and Nano-console-UI proof for every AWS capability the estate (stages 1-4, 6) already covers, plus Bedrock data-plane proof.

## What
- `tests/endurance/proof/checks.py`: one check per Terraform-created resource, run through a backend (boto3 `Sdk` or the real `aws` CLI `Cli`, driven with
  `--cli-input-json`, so both backends execute the same assertions). Each reads the resource Terraform created (from `terraform.tfstate`) and asserts names, ARNs,
  tags, state and key attributes; SQS/DynamoDB/Bedrock also exercise the data plane (SendMessage/Receive/Delete on the FIFO queue, Put/Get/Query(GSI)/Delete item,
  `bedrock-runtime Converse`).
- `tests/endurance/proof/ui/run_ui.mjs`: Playwright on the real Nano v4 AWS console bundle (`wasm/v4/aws`). It pairs the tab with the server, creates a **mesh-homed
  space** (so every `/_wire` call goes to the server the estate was applied to) and opens a list (+ detail) page per service, asserting the Terraform resources render.
  Reuses `wasm/ui-tests/lib.mjs` (static server), no new framework. 40 pages / 24 checks, ~2 minutes.
- `tests/endurance/proof/run_proof.sh <endpoint> [tfstate] [out]`: runs the three layers and `aggregate.py`, emitting `proof.json`
  `{capability_id: {sdk, cli, ui}}` (pass|fail|n/a), `proof-detail.json`, and `estate/coverage-map.proof.json` (only what passed).
- `tests/endurance/coverage.py`: additive `merge_proofs()`; `--require-verified` now counts `proof.sdk/cli/ui` from `coverage-map.proof.json` and `proof/proof.json`
  (only `"pass"` counts). Existing behaviour is unchanged when neither file exists.
- `tests/endurance/proof/run_mesh_server.py`: starts the simulator in Mesh mode with the Pro-trial licence claims the pairing handshake needs (same as
  `tests/mesh/run_real_mesh.py`), on the state file the estate was applied to.
- `tests/endurance/proof/fake_llm_server.py`: OpenAI-compatible echo stand-in for llama-server (see honesty note).

## How to run (own port 19105)
1. `~/.vyomi-endurance-proof/fresh.sh` (clean server) then restart it with `VYOMI_LLM_ENDPOINT=http://127.0.0.1:19205` via `run_mesh_server.py 19105`;
   start `fake_llm_server.py 19205`.
2. Apply: `tests/endurance/estate/aws/run.sh apply -auto-approve -backup=- -var=endpoint=http://host.docker.internal:19105` (keep the state).
3. `NODE_PATH=<node_modules with playwright> tests/endurance/proof/run_proof.sh http://127.0.0.1:19105`; then destroy.
4. The v4 AWS console is built with `node consoles/build.mjs --cloud aws` (needs `consoles/node_modules`; `CONSOLES_NODE_MODULES` symlinks one).

## Simulator defects found by reading Terraform's resources through the other clients
| F | defect | fix |
|---|---|---|
| F500 | `DescribeLaunchTemplateVersions` ignored the symbolic versions `$Latest` / `$Default` (CLI and SDKs use them) and returned an empty list | `core/vpc_core.py` resolves them |
| F501 | bedrock-agent `List*` operations are `POST /agents/` (trailing slash, maxResults/nextToken in the body); only GET was handled, so `ListAgents` (SDK/CLI) failed with UnknownOperation | `core/bedrock_agents_core.py` maps body-less POST on a trailing-slash collection to the list handler |
| F502 | Mesh CORS preflight allowed only `authorization, content-type, x-vyomi-mesh-token` and GET/POST: a real browser console on a mesh-homed space could not send `x-amz-date`/`x-amz-target` or PUT/DELETE, so every call died as "HTTP 503" | `core/mesh.py` reflects the requested header names (sanitised), allows PUT/DELETE/PATCH/HEAD, exposes response headers |
Regression tests: `tests/conformance/test_endurance_proof_core.py` (F500-F502). Nano vendored cores rebuilt with `wasm/build_cores.py`.

## Results (against the estate applied once on :19105, 73 of 74 resources; stack destroyed afterwards)
- SDK 26/26 checks, CLI 26/26 checks, UI 24/24 checks (40 pages; 1 check n/a).
- `proof.json`: 75 mapped capabilities, SDK pass 72, CLI pass 72, UI pass 71, fail 0. `coverage.py`: tf=75 sdk=72 cli=72 ui=71, VERIFIED (tf+sdk+cli+ui) = 71.
- Bedrock data plane: `Converse` through the AWS CLI and boto3, guardrail + agent + alias Describe/Get/List round-trips, guardrail version 1, tags.

## Honest limits / open gaps
- **Model backend is a fake echo**, not a real model: no llama.cpp/Ollama model is present and the disk guard (~4 GiB free) forbids downloading one. The proof covers the real
  Bedrock wire path -> `core/llm_core` HTTP backend -> an OpenAI-compatible server -> Converse response shape and token usage; the answer text (`ECHO: ...`) is not model output.
  `InvokeModel` with a model-specific body is not asserted (Converse only).
- **EC2 instance, its volume attachment and the EBS snapshot were not created**: `RunInstances` is refused by the simulator's own disk guard (`disk_freeze`, host disk 98 percent
  used), so `ec2.instances.details`, `ec2.instances.lifecycle`, `ec2.snapshots` are `n/a` in all three layers (never reported as pass). The key pair, launch template and standalone volume are proven.
- `ec2.iam-instance-profiles`: SDK and CLI pass; UI `n/a` because the v4 AWS console has no IAM instance-profile page.
- Java/Go SDK smoke not added (boto3 + AWS CLI only).
- UI runner retries a page once when the mesh link shows its own "HTTP 503" refusal (the 2.5 s `/mesh/status` health probe of the single-process server flickers under load, which
  flips the tab to "unreachable"); pages that render without the resource still fail. Worth a follow-up: the probe timeout or per-request refusal is too eager.
- The UI proof needs Mesh mode (`VYOMI_MESH_MODE=1`); with it the server serves no legacy UI (404 pointing at Nano), by design.
- Only AWS stages 1-4 and 6 (the capabilities the AWS estate covers) are proven; other stages/clouds belong to other agents.
