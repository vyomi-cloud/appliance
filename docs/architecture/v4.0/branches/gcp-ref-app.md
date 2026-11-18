# v4/gcp-ref-app: GCP implementation of the 13-component reference application

Lane 1 of the GCP 13/13 reference-architecture build. Base: `origin/v4-on-main` a54fc442f. Work in progress; sections are filled as component groups land.

## Changes
- Harness made cloud-neutral without changing the AWS run (`examples/enterprise-facilities-agent`): `facilities/runtime.py` imports boto3 lazily and
  `Ctx.blocked_lane()` / `Ctx.COMPONENTS` are overridable; `facilities/agents.py` routes model, tool, approval and statistics calls through an IO adapter
  (`AwsIO` default, `facilities/gcp/io.py` for GCP); `run_e2e.py --cloud gcp`; `report.py` shows the cloud. AWS e2e step statuses are identical before and
  after (75 steps; 11 PASS, 2 BLOCKED on "local model", as before).

- GCP app: `examples/enterprise-facilities-agent/facilities/gcp/` (13 components, `GcpCtx`, IO adapter, Cloud Run function sources, Agent Engine entrypoint),
  `run_e2e.py --cloud gcp`, `README-GCP.md`, `requirements-gcp.txt`, `tests/conformance/test_gcp_ref_app.py` (no model needed).
- Results (committed with `git add -f`, the folder is gitignored): `results/gcp-e2e-result.json` + `gcp-report.html` = this branch on trunk a54fc442f (no lane work);
  `gcp-e2e-result-integ.json` + `gcp-report-integ.html` = local merge branch `v4/gcp-ref-app-integ` (this branch + the four lane tips below).

## Design decisions
- Approval is assembled (owner decision): ledger row PENDING + Pub/Sub request, approver reads `approver-inbox`, `approval-decision` function records APPROVED/REJECTED in Firestore,
  the waiting caller polls the ledger, `create-work-order` refuses anything not APPROVED and is idempotent.
- Pub/Sub and Firestore use the SDK default gRPC clients via `PUBSUB_EMULATOR_HOST` / `FIRESTORE_EMULATOR_HOST` (real emulators; `VYOMI_GCP_REAL_BACKENDS=1`). Without them the
  components are BLOCKED(gcp-ref-realbackend); there is no REST fallback. Other APIs use the vendor REST transport. Own code: only the harness and a dev helper (`--start-emulators`)
  that starts the Google emulator image in two uniquely named containers; no backend was built.
- Tools are exposed to the gateway as an MCP server implemented as one Cloud Run function (plain JSON-RPC), because `agentGateways` front MCP servers, not functions.
- `--dev-local-functions` runs function handlers in the harness process to exercise logic before the sandbox lane existed; it forces a non-zero exit and is never a result.
- BLOCKED classification lives in `facilities/gcp/runtime.py` (`classify`): the lane is named only for known gap texts; anything else stays FAIL.

## Status (observed runs, macOS arm64, Python 3.13, real emulators in Docker, no model)
| # | trunk a54fc442f | integ (app + corefix 8bb39ad93, sandbox d45c53327, realbackend 4a208ccc4, identity c8152c32c) |
|---|---|---|
| 1 | FAIL 2/5 (identity) | PASS 9/9 |
| 2 | FAIL 5/6 | FAIL 5/6 (Model Armor createTemplate through the SDK) |
| 3 | BLOCKED (agent engine runtime, no lane) | BLOCKED (same) |
| 4 | BLOCKED (sandbox) | PASS 6/6 |
| 5 | BLOCKED (sandbox) | PASS 9/9 |
| 6 | PASS 4/4 | PASS 4/4 |
| 7 | BLOCKED (sandbox) | PASS 4/4 |
| 8 | BLOCKED | BLOCKED 5/6 (Monitoring gRPC needs the lane-4 front door port, see open issues) |
| 9 | FAIL (events append) | FAIL 3/6 |
| 10 | FAIL | FAIL 2/6 (models.get gemini id 404; generation needs a model) |
| 11 | BLOCKED | BLOCKED 3/4 (model) |
| 12 | BLOCKED | FAIL 5/7 (bucket notification does not reach the emulator; Eventarc function BLOCKED) |
| 13 | BLOCKED | BLOCKED 5/6 (Pub/Sub audit with the emulator data plane) |
Totals: trunk 1 PASS / 8 BLOCKED / 4 FAIL; integ 5 PASS / 4 BLOCKED / 4 FAIL. AWS app: identical 75 step statuses before and after the refactor (11 PASS, 2 BLOCKED local model).

## Open issues (what stands between this and 13/13)
Findings that belong to nobody yet (no lane): 
1. Model Armor `createTemplate` via `google-cloud-modelarmor`: simulator rejects the SDK's integer enums (`alt=json;enum-encoding=int`), "raiFilters.filterType must be one of [...]". Real Google accepts both.
2. Agent Engine does not host user code: `vertexai.Client.agent_engines.create(source_packages..., class_methods)` is stored but the response (snake_case `spec.class_methods`) fails SDK validation, and `:query` does not run pickle/source. AWS has this (ai-runtime lane); GCP needs the equivalent.
3. Sessions: `sessions.events.append` (`:appendEvent`) returns 405, so session replay cannot be written.
4. `models.get(gemini-2.0-flash)` is 404 (only the local model is listed); AWS resolves standard ids as aliases.
Cross-lane integration findings:
5. corefix x realbackend: GCS notifications publish through `gcp_ps._publish` on the core store (`aws_wire_router._gcs_notify_publish`), not the real-backend wrapper, so a gRPC subscriber on the emulator never receives OBJECT_FINALIZE.
6. realbackend: with the emulator as data plane no Pub/Sub admin audit entries are produced (CreateTopic missing from Cloud Audit Logs).
7. realbackend: Monitoring needs a gRPC channel to the simulator (`VYOMI_GCP_GRPC_PORT` front door); the app currently opens an insecure channel to the simulator HTTP port (BLOCKED). The app should read the front-door port (contract to settle).
8. identity: API Gateway does not forward `X-Apigateway-Api-Userinfo` to the backend (caller shows anonymous); minor.
9. Eventarc -> function -> RAG import (c12) stays BLOCKED until the notification/Eventarc path is proven against the emulator data plane (needs finalize event delivery to the sandbox function).
Model-dependent steps (10, 11, 9 generate, hosted routing) need a real model run on Mesh.
