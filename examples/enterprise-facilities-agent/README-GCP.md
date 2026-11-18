# Enterprise Facilities agent on GCP: reference application and end-to-end test

The same facilities-management agent as the [AWS app](README.md), written the way a customer would write it against the **real Google client libraries**
(`google-cloud-*`, `google-genai`, `vertexai`). The code runs on real Google Cloud by dropping the endpoint overrides; here it runs on a Vyomi simulator
(Mesh appliance, or the in-process server used by the harness). It exercises all 13 components of the "Agentic AI" reference architecture on GCP services.

```
user -> Identity Platform sign-in (ID token) -> API Gateway (JWT validation) + Cloud Armor policy -> Vertex AI Agent Engine
        supervisor + Facilities / Maintenance / Analytics sub-agents (LangGraph) + Agent Platform Sessions + Memory Bank
     -> agent gateway (Agent Platform agentGateways, MCP tool registry, Cedar agent policy) -> Cloud Run function tools
          read-only: kb-search (Vertex RAG Engine retrieveContexts), asset-status (Firestore)
          write: create-work-order behind a human approval:
                 Pub/Sub request topic -> approver-inbox subscription -> approval-decision Cloud Run function -> Firestore ledger -> caller polls APPROVED
     -> Model Armor in/out + grounded, cited answer (Gemini on Vertex) -> Cloud Trace / Logging / Monitoring -> Cloud KMS + Cloud Audit Logs
     pipeline: GCS upload -> notification / Eventarc -> Cloud Run function -> RAG Engine import (re-ingest on upload)
```

## Run it

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-gcp.txt
# in-process simulator (needs the repo checkout; clean state every run):
.venv/bin/python examples/enterprise-facilities-agent/run_e2e.py --cloud gcp
# Pub/Sub and Firestore on the REAL Google emulators (local Docker image google-cloud-cli:emulators, never pulled by this tool):
.venv/bin/python examples/enterprise-facilities-agent/run_e2e.py --cloud gcp --start-emulators
# or against a running simulator / Mesh (set VYOMI_GCP_REAL_BACKENDS=1 on the simulator and point the app at the emulators):
PUBSUB_EMULATOR_HOST=127.0.0.1:8085 FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 \
  .venv/bin/python examples/enterprise-facilities-agent/run_e2e.py --cloud gcp --endpoint http://localhost:8099
# against another checkout of the simulator code (e.g. an integration branch):
VYOMI_REPO=/path/to/checkout .venv/bin/python examples/enterprise-facilities-agent/run_e2e.py --cloud gcp --start-emulators
```

Outputs `results/gcp-e2e-result.json` and `results/gcp-report.html` (static, no build step). Exit code 0 only if all 13 components PASS.
`--only 5,6` runs a subset (dependencies are not re-run). Statuses: **PASS**; **BLOCKED** (the simulator lacks a capability another lane is building, or
a model is needed; the owner is named); **FAIL** (the app or the simulator is wrong; includes gaps nobody owns yet).
Nothing is mocked and nothing blocked is reported as a pass. `--dev-local-functions` is a developer aid (runs the function handlers in the harness
process, bypassing the simulator's function sandbox) and forces a non-zero exit: it is never a conformance result.

## The 13 components

| # | Component | GCP service (SDK) | Notes |
|---|---|---|---|
| 1 | Access and perimeter | Identity Platform REST sign-in, `google-auth` token verify, `google-cloud-api-gateway`, `google-cloud-compute` Cloud Armor | JWT validated at the gateway; Cloud Armor policy is created, not enforced by the simulator |
| 2 | Channels / input guardrail | `google-cloud-modelarmor` `sanitizeUserPrompt`; `google-cloud-pubsub` approver inbox | |
| 3 | Runtime | `vertexai.Client.agent_engines.create(source_packages, entrypoint_module, class_methods)` | assembled from a source package; see limits |
| 4 | Gateway | Agent Platform `agentGateways` + `mcpServers` + `agentPolicies` (Cedar) via `google-auth` AuthorizedSession | no Google client library exists for these resources; MCP over streamable HTTP |
| 5 | Approval | Pub/Sub + Cloud Run function + Firestore ledger | **assembled from parts**, not a workflow orchestrator (owner decision) |
| 6 | Knowledge search | `aiplatform_v1.VertexRagServiceClient.retrieve_contexts`, Discovery Engine (Vertex AI Search) | embeddings are lexical hashes without a model |
| 7 | Tools | `google-cloud-functions` v2 (Cloud Run functions) + `google-cloud-firestore` | functions are plain Google client code |
| 8 | Observability | `trace_v2` / `trace_v1`, `logging.Client`, `monitoring_v3` | Monitoring is gRPC-only in the SDK |
| 9 | Memory | `vertexai.Client.agent_engines.sessions` + `.memories` (Memory Bank) | |
| 10 | Models | `google-genai` (`vertexai=True`): models.list/get, generateContent, function calling, embedContent, Model Armor on a call | needs a model for generation |
| 11 | Response | grounded answer with RAG citations; Model Armor `sanitizeModelResponse`; generateContent with the RAG retrieval tool | |
| 12 | Pipeline | `google-cloud-storage`, bucket notifications, `google-cloud-eventarc`, function, `import_rag_files` | |
| 13 | Governance | `google-cloud-kms` envelope encryption with AAD; Cloud Audit Logs read back with `logging` | |

Resource names follow the cross-lane contract: users project `facilities-users`, corpus `facilities-kb`, gateway `facilities-gateway`, approval topic
`work-order-approval`, ledger collection `approval-ledger`, approver subscription `approver-inbox`, Model Armor template `facilities-guardrail`, engine
`facilities_supervisor`, memory `facilities_memory`, KMS key ring `facilities` / key `ledger-key`.

## Transport policy (honest)

* **Pub/Sub and Firestore use the SDK defaults (gRPC)** and are pointed at the data plane through the standard `PUBSUB_EMULATOR_HOST` /
  `FIRESTORE_EMULATOR_HOST`. The simulator front door is HTTP/1.1 only, so these need the real emulators (`VYOMI_GCP_REAL_BACKENDS=1`); without them
  the components report BLOCKED(`gcp-ref-realbackend`) instead of falling back to REST.
* Every other API uses the vendor client's REST transport (`transport="rest"`, `api_endpoint`) or `google-genai` / `vertexai.Client`, which are HTTP by design.
  `logging.Client(_use_grpc=False)` is the library's documented HTTP mode; `monitoring_v3` has no REST transport, so it uses the gRPC front door (lane realbackend).
* No hand-rolled HTTP stands in for an SDK call. Where no client library exists (Identity Platform end-user sign-in, Agent Platform gateways, the MCP
  endpoint) the documented REST API is called with `requests` / `google-auth` AuthorizedSession.

## Layout

| path | what |
| --- | --- |
| `facilities/gcp/components/cNN_*.py` | one module per architecture component, Google SDK calls |
| `facilities/gcp/runtime.py` | `GcpCtx`: client factories, contract names, BLOCKED classification (lane owners) |
| `facilities/gcp/io.py` | adapter that lets the cloud-neutral LangGraph agents (`facilities/agents.py`) use Gemini, the agent gateway, Pub/Sub + Firestore |
| `facilities/gcp/functions/*.py` | Cloud Run function sources (kb-search, asset-status, MCP tool server, approval-decision, create-work-order, ingest-docs) |
| `facilities/gcp/agent_engine_app.py` | Agent Engine entrypoint (`set_up`, `query`) for the supervisor |
| `facilities/gcp/emulators.py` | dev helper behind `--start-emulators` (own containers, exact names) |
| `run_e2e.py --cloud gcp`, `report.py` | shared harness (cloud-neutral) and report |

## Notes and honest limits

* With no reachable model the supervisor routes with keyword rules and the answer is extractive; the report says so. generateContent, function calling,
  Memory Bank fact generation and grounded generation are BLOCKED(local model) until a model is reachable. Model quality is a non-goal.
* Components 5, 7 and 12 run inside the simulator's Cloud Run function sandbox; a function that imports `google.cloud.*` needs lane gcp-ref-sandbox.
* The simulator's Agent Engine does not run user code (pickle or source packages); see the status table in the branch doc for the current state.
* Cloud Armor rules are not evaluated by the simulator. Cloud Audit data-access logs are opt-in on GCP and are not asserted.
* Tier gating: Firestore is Max-tier on a licensed appliance; the in-process harness skips the gate.
