# Vyomi Labs: enterprise content changes

Branch `v4/labs-enterprise-content`. Content only; the runtime (wasm/labs/*.js) is untouched.

## Data files and schema (for the runtime)
- `wasm/labs/data/<cloud>.json`: Mesh edition, every block. `<cloud>-nano.json`: Nano subset. Both `schema: 2`, `edition` at the top.
- Block fields added: `edition` (["nano","mesh"] or ["mesh"]), `nano_note`, `kind` (build|harden|iam|failure|ship), `needs_appliance`.
- Layer fields added: `blocks_total`, `blocks_nano`, `blocks_mesh_only`, `mesh_only_titles`; `minutes` grows 4 per Mesh-only block.
- Counts: AWS 85 mesh / 63 nano; GCP 89 / 83; Azure 95 / 89 (includes chapter 14 Design the RAG, 3 blocks, both editions). Existing blocks default to both editions; every new enterprise block is Mesh-only.

## AWS (verified: all 13 chapters pass in-process; IAM blocks pass on a local full server)
- Ch10: retry/backoff, `ModelUnavailable`, notional cost `Budget` in `vymodels.py` (renamed from models.py, which collided with core). Blocks: chaos.py + fail_models.py (throttling, both editions), iamkit.py, iam_models.py (least-privilege + audit "what is missing").
- Ch3: step budget guard (runaway.py), iam_runtime.py. Ch7: validated handlers, ConditionExpression idempotency, tool_contract.py (failure), iam_tools.py.
- Ch5: expiry (state machine Timeout to an expire Lambda), risk levels (P4 auto-approves), iam_approval.py, real approver identity from the IAM audit log.
- Ch12 reingest.py, dlq_ingest.py. Ch11 screen.py, refusal.py, poisoned_doc.py. Ch9 memory_guard.py. Ch4 cedar_enforce.py (action name fixed). Ch1 token_attacks.py. Ch2 guardrail_bypass.py. Ch8 cost_meter.py.
- Ch13 key_rotation.py, audit_chain.py (hash chain), audit_who.py, ship_it.py (Terraform export via /api/terraform/export/bundle, plan, warnings, re-import).
- Vacuous checks replaced by asserts: search, rerank, grounded_answer, retrieve_and_generate, memory, cedar, guardrail, token, trace, evaluators, inbox, invoke, kms, audit.

## Azure (verified in-process, full course; only call_container_app.py fails, see below)
- Ch5 expiry.py (ETag-conditioned sweeper). Ch7 tool_contract.py (failure lab). Ch8 cost_meter.py. Ch13 key_rotation.py, audit_chain.py, ship_it.py (ARM export template, 35 resources).
## GCP (verified in-process, full course, all pass)
- Ch5 expiry.py (Firestore transaction). Ch7 tool_contract.py. Ch8 cost_meter.py. Ch13 key_rotation.py (KMS version + primary), audit_chain.py, ship_it.py (Infrastructure Manager deployment, 2 resources).

## Wrong-cloud copy fixed (explain.py, narrative.py)
"Create the trail" -> "open the cloud's audit log"; "server-side encryption" -> "encrypted with your key"; "callback token" made cloud-neutral; `request-approval` tool prose made neutral; the Risk level concept now states what each course actually implements.

## Not done / not verifiable (candid)
- Azure and GCP have no IAM Enforce lab: the enforcement gate was not probed for them. Only AWS has least-privilege-per-layer plus the audit "find what is missing" step.
- Azure and GCP approver identity is still the self-declared `@example.com` allow-list; only AWS derives it from the IAM audit log. No Azure/GCP risk-level, DLQ or poisoned-document/guardrail-bypass labs.
- Azure `call_container_app.py` fails in-process (503 from the container app sandbox); the same block was not changed by this work.
- AWS IAM blocks need the full appliance (`needs_appliance`, run with `--endpoint`); Lambda/agent-runtime blocks hang on a single-worker uvicorn server, so they were verified in-process only.
- No new block is Nano-verified; that is why they are Mesh-only.
- Simulator gaps found: Converse needs bedrock:ApplyGuardrail under Enforce; STS GetCallerIdentity returns root; per-request SSE-KMS header reported as AES256; KB scores are relative so cannot signal "no answer"; re-ingest stats overcount; Terraform real-mode export leaves the simulator account id in IAM/KMS policy ARNs; Cedar ENFORCE hides non-permitted tools from tools/list.
