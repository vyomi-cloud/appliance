# Nightly needs-decision (owner/other-cloud items; the agents append, never delete)

## Azure, 2026-11-11 baseline on a bare simulator (v4-preview, no sibling backends)
ENV, not product (need sibling containers, the Docker socket, azure SDK / playwright installed): offline-sdk-python-azure-ops, offline-sdk-python-azure-vm-runcommand
(no `azure` python module), offline-ui-azure-* (playwright not resolvable from the checkout), offline-cli-azure (SQL connectionInfo needs real Postgres),
offline-cli-azure-app job executions (needs Docker to run the job), offline-post-create-azure-event-delivery (webhook delivery to the test receiver).
To verify on the runner stack (nightly-v4.yml), not here.
UNCLEAR: offline-sdk-go-azure-operationalinsights prints PASS lines but is scored 0 passed / 400 failed: check how the Go runner output is counted (harness bug?).

## FIXED 2026-11-12 (v4/azure-kv-per-vault, test_azure_keyvault_per_vault_core.py): secrets + certificates are now scoped per vault (vault from `/azure-data/keyvault/{vault}/`, `x-vyomi-vault` or `<vault>.vault.azure.net`; unknown/deleted vault -> 404 VaultNotFound; vault/RG delete purges its secrets+certs). Keys stay per-space (CMK envelopes resolve them from the unscoped store); returned ids still carry the request host (one relay host). Requests with no vault keep the legacy shared namespace.
## (was) Azure Key Vault data plane is per SPACE, not per VAULT (found 2026-11-11, real product gap)
Repro (v4-preview): create RG + vault `va`, `PUT /azure-data/keyvault/va/secrets/s1?api-version=7.4`, then
`GET /azure-data/keyvault/neverexisted/secrets/s1?api-version=7.4` -> 200 with the same secret. Deleting the vault, or the whole RG, leaves the secret readable (200);
the secret id is `https://<host>/secrets/s1/<ver>` without a vault name. Cause: `core/azure_keyvault_secrets_core.py` KvStore is one store per space; the vault
only reaches enforcement via the `x-vyomi-vault` header (core/wire_ingress.py ~L601, azure_arm_core `keyvault_network_denied`).
Real Azure: secrets belong to a vault; a missing/deleted vault is 404/`VaultNotFound`, and ids are `https://<vault>.vault.azure.net/secrets/...`.
Impact: `offline-sweepA-azure` "RG delete destroyed Key Vault secrets" stays red (it was masked by a stale test missing api-version until now).
Decision needed: scope the KvStore by vault name (key = vault + secret; keys/certs too; Nano path as well) = a data-model change in shared KV code. Not done overnight.
||||||| parent of 2bee3b11b (nightly-aws: needs-decision entries from the AWS offline baseline)


## AWS-1, 2026-11-11 offline baseline (own simulator `nightly-aws-sim`, v4-preview image, no sibling backends, no Docker socket)
Baseline: 46/75 offline AWS suites green. After fixes below, re-run shows the SDK suites green except the items listed.
FIXED (branch `v4/aws-nightly-checks`, each with a test that fails without it):
- DynamoDB wire timestamps (CreationDateTime / TableCreationDateTime / BackupCreationDateTime) were ISO strings; Go + Java SDK CreateTable failed. Now epoch numbers.
- Describe{Vpcs,Subnets,RouteTables,InternetGateways,NatGateways,VpcEndpoints} returned an empty list for unknown ids; real EC2 raises `<Kind>.NotFound`.
- ELBv2 Go check expected instant target removal; the core enforces real deregistration draining (7fe1784db). Test now asserts draining.
- test_schedule_core.py expiry check depended on the wall-clock date (date bomb).
DECISION NEEDED (owner / console owner), NOT fixed tonight:
1. IAM list wire shape is not AWS's. `ListUsers/ListRoles/ListGroups/ListPolicies` (+ GetGroup users, ListGroupsForUser) emit `<Users><User>..</User></Users>`; real IAM emits `<Users><member>..</member></Users>`. boto3 tolerates it, Go v2 sees 0 users (offline-sdk-go-aws "iam ListUsers contains new user"). Fix = core `iam_core.py` list contexts use `<member>`, AND every console reader of `Users?.User / Roles?.Role / Groups?.Group / Policies?.Policy` must accept `member` (consoles/src/aws/services/{iam,kms,eks,lambda,rds,ec2}/api.js, older wasm consoles) plus core tests that assert the old shape. Wide blast radius (breaks IAM pages if half done); proposal: one PR, console parsers accept BOTH shapes first, then flip the core.
2. The v4 headless image serves no UI: `/console/aws` is 404. These offline UI suites cannot run on v4 and fail by construction (UI is Nano-only): offline-ui-aws-*, offline-ui-console-home, offline-ui-drawer, offline-ui-default-cloud, offline-ui-sdk-roundtrip. Decide: delete/retarget them to Nano (the owner or manifest owner, I will not delete tests myself). Check 5 (UI<->SDK) for AWS therefore has no offline runner on v4; it must run on Nano.
3. `test_request_metrics.py` reads `static/aws-console.html` (does not exist on v4); same root cause as 2, needs a retarget to `consoles/src/aws` / `wasm/v4/aws`.
ENV (not product; not fixed): offline-sdk-python-aws `aws.s3.minio:object.get.via-minio-direct` (needs the MinIO sibling); offline-cost-savings azure part (needs Azurite on :10000); Lambda-runtime suites (offline-api-aws-detail-tabs Code/Test/Env sections, offline-sweepA-aws Function URL 500, offline-cli-aws-apigatewayv2 invoke 404s, offline-post-create-aws-*) need the Docker socket; offline-cli-aws-sns needs `host.docker.internal` receiver reachability.
AWS-1 addendum (Nano target): the manifest suite `nano-cores` (`pytest tests/conformance/test_*_core.py` with PYTHONPATH=wasm/core) aborts at COLLECTION: test_sns_size_ttl_core.py imports `core.sns_delivery`, others import `core.wire_ingress` / `core.k3s_runtime`, none of which are vendored into `wasm/core` (offline-only cores). The runner then scores the text fallback (1091 pass / 407 "fail"), so the suite is red by construction on all clouds. Decide per owner: vendor those cores into Nano, or have the offline-only tests skip when the module is absent (never skip by deleting the check); this touches `suites.json`/vendoring, so I did not change it.

## AWS-1, 2026-11-11 tunnel / Mesh check (Codespace `vyomi-mesh-69w55v9x5x43p6w`, Max, via `vyomi-tunnel forward vyomi-mesh-simulator-1 9201:9000`)
RAN (token-free, tunnel layer only): `vyomi-tunnel list mesh` shows the appliance; `ssh host.vyomi` reaches the Codespace; the forward answers (HTTP 401 `MeshSessionRequired` JSON = appliance alive through the tunnel). AUTO-RECOVERY: restarting `vyomi-mesh-simulator-1` inside the Codespace -> link back after 16 s with no user action; the forward process survived.
NOT VERIFIED: state survival across that restart and any SDK/CLI/API call through the Mesh (needs the portal-signed session token `X-Vyomi-Session-Token`, which the owner's tunnel session holds; I did not read or mint it). The shared relay (:8090, owner's `vyomi-tunnel`) and the SSH-session-drop / kill-relay faults were NOT exercised (they would cut the owner's live link).
FOUND (Mesh pack / tunnel owner, not fixed by AWS-1):
1. Mesh appliance container is permanently `unhealthy`: its Docker healthcheck is `curl -fsS http://127.0.0.1:9000/healthz`, which core/mesh_session.py answers `401 MeshSessionRequired` when no token is configured (the token check runs before the `/healthz` exemption), so the healthcheck can never pass. Decide: exempt `/healthz` for loopback, or give the healthcheck the token env.
2. The Mesh pack has no NATS container (`vyomi-nats`): the appliance logs a `getaddrinfo` traceback every loop ("nats: encountered error"). NATS backs the AWS messaging stores (`core/nats_backed_store.py`, `sns_delivery`), so SQS/SNS/EventBridge on the Mesh are unverified/likely degraded. Needs the pack (`vyomi-cloud/sandbox`) to start NATS or the stores to fall back cleanly. Not testable by AWS-1 until the token question is settled.

## AWS-1, 2026-11-11 Nano UI crawl triage (baseline run: 162 findings in 20 AWS services)
- 138 x HTTP_5XX = `https://relay.vyomi.cloud/health -> 503 no Nano tab registered`: the Nano tunnel status panel (`wasm/nano-tunnel-tabs.js` `probe('cloud', ...)`, plus `nano-connect.js`) probes the HOSTED relay, which answers 503 when no tab is registered. The crawler scores any 5xx as a failure. Decide (Nano tunnel owner): drop the hosted-relay probe now that the Mesh plane runs inside the user's vyomi-tunnel, or tell the crawler this probe is expected. 19 x HTTP_404 = `/vendor/pyodide/pyodide.mjs` is not vendored in the bare `wasm/` served by the test harness (ENV; the portal build vendors it).
- FIXED: Secrets Manager "Secret value" tab showed `-` for Last changed on a secret with no version yet (details section fell back to nothing); now falls back to creation time (`test_secrets_detail_last_changed_core.py`).
- NOT REPRODUCED alone: EventBridge / Step Functions SAVINGS_NOT_UPDATED (3 findings) are clean when those services are crawled on their own; they only appeared in the 4-hour full crawl (likely the census refresh racing the check). Left open.
- OPEN, unexplained: RDS `CREATE_NO_ROW` (create with defaults adds no row to the list within the crawler's wait) reproduces alone; likely an async "creating" row that appears late, but not confirmed. Needs a look at the Nano RDS create flow.

## AWS-1: v4 console UI <-> SDK bi-directional report (2026-11-11)
Suite: `wasm/ui-tests/validate-aws-v4-roundtrip.mjs` (+ `_aws_roundtrip_sdk.py`). UI = the v4.0.0 console (`/v4/aws/`) in Playwright, SDK = boto3 on the same `/_wire`
(run: `python3 consoles/dev_server.py --port 8741`, then `BASE=http://127.0.0.1:8741 PY=<python+boto3> node wasm/ui-tests/validate-aws-v4-roundtrip.mjs`).
Result: 84/84 checks pass across 20 services (A UI create->SDK, B SDK create->UI, C SDK delete->UI, D UI delete->SDK): s3 sqs sns dynamodb kms secretsmanager iam vpc ec2 ssm kinesis ecr eventbridge cloudwatch apigateway backup networkmanager states lambda rds (+ cloudformation B,C).
Product bug found + fixed: RDS ModifyDBInstance ignored DeletionProtection=false (a UI-created instance, default protected, could never be unprotected/deleted). core/rds_core.py + test_rds_modify_deletion_protection_core.py.
NOT verified (printed as SKIP): EKS (needs k3s backend), Image Builder (pipelines adapter), CloudFormation UI create/delete wizard (B,C pass). Field-level comparison limited to existence/name (+ KMS PendingDeletion, RDS deleting semantics).
Not covered: bedrock, securityhub, cost-explorer (read-mostly, no create flow). Nano old-console variant (`validate-aws-roundtrip.mjs`): s3 sqs sns dynamodb kms secretsmanager 24/24.

## GCP (2026-11-11): product gaps found by the v4 round-trip
||||||| parent of a74a74d71 (test+fix(mesh): live-Mesh E2E (EC2, Bedrock, Azure AI/VM, GCP GCE), tunnel recovery, 3 fixes)


## Azure VM compute on the Mesh (live run 2026-11-11, `wasm/ui-tests/azure-mesh/vm-bidirectional.mjs`: 25 PASS, 6 FAIL, 1 NOT-AUTOMATED)
Fixed in this batch (with tests): VM GET/list no longer echo `osProfile.adminPassword` (test_azure_vm_no_password_echo.py).
UPDATE 2026-11-12: items 1-5 FIXED on v4-on-main (016ffb155, 75876893f; tested, live on the Mesh only after the image is rebuilt). 6 is by design; 7 in progress.
Open, owner decision (release-known gaps; each is backend work, not hot-fixable on the published image):
1. **powerOff / deallocate are metadata-only**: ARM + instanceView say stopped/deallocated but the Docker container keeps running until delete (the power route's own note says "metadata-only"). Real: stop frees compute. Fix = call the compute backend stop/start from the power route.
2. **runCommand is not real compute**: returns 200 "The VM guest agent is not reachable: this virtual machine has no guest runtime (it is metadata-only)" although a Docker container with sshd exists. Fix = `docker exec` into the VM container for runCommand (and align the console text).
3. **OS disk is not an ARM resource**: `osDisk.managedDisk.id` GET -> 404 (no `Microsoft.Compute/disks` handler). NIC exists.
4. **Short password accepted over ARM** (3 chars, 200). Real: 6-72 chars + 3 of 4 complexity classes, error InvalidParameter. Wizard only checks the two fields match; with a 3-char password no VM was created and no message shown (unexplained).
5. **`GET ...?$expand=instanceView` returns no instanceView** (only the separate /instanceView route works).
6. **Capacity**: the Mesh admits ONE running B1s VM at a time (409 AllocationFailed, mesh admission control, by design); EC2 side admits about 2 instances (500 InsufficientInstanceCapacity with an "Availability Zone" message that reads wrong). A second concurrent user/run will be refused.
7. Console has no **Deallocate** button (Start/Restart/Stop only).
Azure OpenAI data plane: anonymous call was accepted (fixed: now 401, test_azure_openai_route_auth.py). The Mesh image must be rebuilt for both fixes to reach the Mesh.

## Azure, 2026-11-12: harness fixes
- FIXED run_suites.count(): the Go suite offline-sdk-go-azure-operationalinsights was green (39 PASS, 0 FAIL) but scored 0/400 because the check name "unsupported KQL -> 400 error" matched the pytest summary regex (`400 error`). `error(s)` now counts only on a timed pytest summary line (test_run_suites_count.py).
- `*-ui-azure-flat-create` (nano + offline) drive the OLD console (wasm/azure-console.html), so they are marked `pending` (reported every run, not gating v4). Decide: retarget to `/v4/azure/` (NSG + Role Definition flat create) or retire.
||||||| parent of 24794b111 (fix(azure): Function app wizard sets kind; Service Bus shown endpoint is an appliance route)


## Azure crawl + offline-red triage (2026-11-12, session Azure; branch v4/azure-crawl-triage)
Source: nightly-v4 run 42956759997 (after-azure artifact): Nano UI crawl 23 findings, offline Azure 10 red suites.
FIXED (tests fail without the fix): Function app wizard sent no `kind` -> site stored as Web App -> Functions tab 404 (`test_azure_functionapp_wizard_kind.py`; core/azure_wizards.py + wasm/fixtures/azure-catalog.json);
Service Bus ARM `serviceBusEndpoint` showed Nano's `/api/servicebus/topics` on the appliance (404) -> `/azure-data/servicebus/<ns>` off Nano (`test_azure_shown_endpoints.py`).
ENV, not product: 22 of 23 crawl findings are the same `/vendor/pyodide/pyodide.mjs -> 404` (wasm/vendor/ is git-ignored; the loaders fall back to the CDN, the crawler scores the 404 HEAD probe).
  Fix on the runner: add `python3 wasm/fetch_pyodide.py` to nightly-v4.yml before the crawl (workflow file: owner pushes, vyomi-admin has no `workflow` scope).
DECISIONS: (1) offline-ui-azure-* (metrics, rg-nav, flat-create, resource-group-detail, apim-appinsights) target `/console/azure`, which the headless v4 image does not serve -> they fail by construction (same as AWS item 2): retarget to the v4 consoles or retire.
  (2) offline-post-create-azure-sql-fqdn: the appliance has no HTTP data plane for `fullyQualifiedDomainName` (shows Nano's `/api/azuresql/servers`, 404): decide a shown endpoint (e.g. /azure-data/sql/<server>) or accept "no TDS" text only.
  (3) offline-post-create-azure-event-delivery needs the webhook receiver (env); offline-sweepA-azure: Key Vault is now per vault on trunk (c72c1dadb); re-check on the next nightly.
HAZARD (found while vendoring; not fixed here): core/azure_arm_core.py now imports `azure_compute_disks_vm` (my VM disks merge 016ffb155) but `azure_compute_disks_vm.py` is not in the CORES lists
(wasm/build_cores.py, wasm/nano-boot.js, wasm/relay/relay-shared-worker.js, wasm/relay/nano-endpoint.html): `python3 wasm/build_cores.py` aborts until it is added, and wasm/core/azure_arm_core.py is stale (VM password strip etc. not in Nano yet). wasm/core also lags aws_wire_router.py (az-openai provider fix). Vendoring is the owner's/portal session's step.

## Azure Nano target, 2026-11-12 (run_suites --target nano --cloud azure: 24/26 green, flat-create pending, nano-ui-crawl red)
nano-ui-crawl (25 Azure services, 3 finding classes): 103 x HTTP_5XX `https://relay.vyomi.cloud/health -> 503 no Nano tab registered` = the hosted-relay probe of the Nano tunnel panel (Nano tunnel owner, same as the AWS finding; not an Azure bug);
23 x `/vendor/pyodide/pyodide.mjs -> 404` = `wasm/vendor/` is git-ignored, loaders fall back to the CDN (env: nightly needs `python3 wasm/fetch_pyodide.py`);
1 real finding FIXED: Function apps "Deployment slots" tab 404 (cef90d80a: tab removed, core refuses slots on a function app).
Nano VM compute is metadata-only for power actions (no Docker backing); runCommand runs only echo/hostname/whoami/date/uname/IMDS+Key Vault and refuses everything else with exit 1 "nothing was executed" (honest, unchanged).
||||||| parent of 096073ddf (docs(nightly): Azure Nano UI run - only the hosted-relay probe remains)

## Azure Nano UI, 2026-11-12 (local Nano run, all 25 services + 25 nano-ui-azure-* suites)
Result: 24/26 nano suites green; `nano-ui-azure-flat-create` is pending (old console, see above); `nano-ui-crawl` red.
Crawl: 102 findings, ALL `HTTP_5XX https://relay.vyomi.cloud/health -> 503 no Nano tab registered` (hosted-relay probe in shared `wasm/nano-tunnel-tabs.js` / `nano-connect.js`), i.e. 0 Azure-specific deviations. Same root cause AWS-1 recorded: Nano tunnel owner must drop or soften that probe (the crawler scores any 5xx as a failure). Not touched here (shared Nano tunnel code).
The one Azure finding (Function apps "Deployment slots" tab 404) was already fixed on trunk (cef90d80a); re-crawl of Function apps shows only the relay probe.

## Nano crawl findings, 2026-11-12: FIXED at source (branch v4/nano-crawl-findings)
- hosted-relay `relay.vyomi.cloud/health -> 503` (103 findings per cloud): the tunnel panel now probes it only while the Cloudflare tab carries traffic (`wasm/nano-tunnel-tabs.js`); idle shows 'not in use'. Applies to AWS and GCP crawls too.
- `/vendor/pyodide/pyodide.mjs -> 404` (24 per cloud): loaders read tracked `wasm/pyodide-source.json` ({"local": false}); `wasm/fetch_pyodide.py` flips it to true. No nightly-workflow change is needed for the crawl any more; a deploy that ships vendor/pyodide must run fetch_pyodide.py (it does the flip).
- Azure Nano crawl after: 33/34 services clean (was 0/25, 127 findings); remaining: PLACEHOLDER_CELL 'Topic type' blank after create (2). `nano-ui-azure-tags-tab` fails 9 (Event Grid namespace/topics/domain/partner*, rediscache, dataexplorer have no Tags tab) - pre-existing on trunk, not from this change.

## GCP nightly, 2026-11-13
- FIXED: Cloud SQL `instances.insert` never set `createTime` (Nano grid "Created" blank; nano-ui-gcp-create-defaults red -> green). Touched shared `core/gcp_cloudsql_core.py` (record is built there); `wasm/core` re-vendored.
- Offline GCP suites red in the baseline AND re-run here (pubsub-tabs-project NOT_FOUND on a just-created topic, gce-ssh 400, ui-* waitForFunction timeouts; `/console/gcp` is 404 on the local :9000 stack and `static/*-console.html` no longer exists in v4). Looks like the offline stack/suites are stale vs v4 (decision for the trunk owner: retire or port these suites). Not guessed at.
- `gcp-eventarc-nano-http-bridge` shows fail with exit 0 and an "ok" log: runner marks it fail although the test passes (harness/runner owner; not changed).
- Not fixed, need Docker/Go modules/network: offline-sdk-go-gcp, offline-sdk-go-gcp-artifactregistry, offline-post-create-gcp-event-delivery, offline-post-create-gcp-apigateway-invoke.

## GCP nightly, 2026-11-15
- FIXED: Nano KMS detail tabs (Labels/Versions/Rotation/Import jobs/Metrics) 404'd for any key outside the default ring (`_NanoKey` hard-coded global/demo); now resolves the key's real ring. Test: `test_gcp_console_tabs.py` kms[nano] (3 tests red -> green).
- FIXED: `updatePrimaryVersion` accepted a non-ENABLED version; now FAILED_PRECONDITION like Cloud KMS. Touched `core/gcp_kms_core.py` (GCP core); `wasm/core` re-vendored.
- Still red in `test_gcp_console_tabs.py[nano]` (pre-existing, not touched): cloudsql backups/connectivity/replicas/users, firestore x3, pubsub encryption/schema, secret versions, storage x3.
- Not run: UI Playwright, roundtrip/tunnel legs (no Codespace), offline stack (stale vs v4, see 2026-11-13).

## Azure nightly 2026-11-16
- FIXED (harness): nano-ui-azure-cognitiveservices asked Nano for `qwen2.5-7b`, a mesh-only model; Nano lists only the four web LLMs, so DeploymentModelNotSupported was correct. Validator now deploys `smollm2-360m`.
- FIXED (product): Microsoft.Sql/servers on the appliance showed Nano-only `/api/azuresql/servers` (404). Now `/api/console/azure-sql/databases` + `/execute`. The running simulator image predates this: offline-post-create-azure-sql-fqdn turns green only after the next image build.
- FIXED (harness): offline-sweepA-azure APIM probe created an API with no operations; the gateway (like real APIM) 404s that. The probe now defines `GET /healthz`. Wrong/missing key -> 401 pass again.
- OPEN, UNCLEAR: sweepA "APIM valid key proxies to the backend" now gets 502 `TimeoutError` when `serviceUrl` is the simulator itself (`http://127.0.0.1:9000`). Suspect the synchronous gateway fetch (`aws_wire_router` azure-apim-gw sync branch, `gateway_common.fetch`) blocking the loop it is calling back into. Shared wire router: not changed overnight; decide whether self-referential backends must work or the probe should use a different backend.
- OPEN, ENV: offline-post-create-azure-openai (local LLM `vyomi-llm` not running), offline-post-create-azure-event-delivery (receiver), offline-sdk-python-azure-vm-runcommand (the sim has a real guest runtime here, test expects none), offline-ui-azure-{metrics,rg-nav,resource-group-detail,apim-appinsights} (60-120 s waits for the console rail; playwright/console boot on this runner, not triaged).
- OPEN, harness limit: nano-ui-crawl STATIC_TAB on "Event Grid partner configurations" Overview/JSON view: the only resource is named `default` (the real, fixed name), which the crawler's token filter (needs a digit or punctuation) can't use as a "this resource" token, and those tabs make no API call. Not loosened.

## AWS nightly 2026-11-17
- FIXED (product): offline Lambda detail tabs (Code, Environment, Configuration, Role, Versions, Aliases, Resource policy, saved test events) edited a `legacy_view` copy of the unified engine's function, so every save was lost on the next read. Now written back to the engine / routed through its REST. Test: `test_aws_detail_tabs_api.py lambda` (Code/Test/Env/Versions/Aliases red -> green). Touched only `routes/aws_console_detail.py`.
- OPEN (same class, not fixed): offline detail tabs for Secrets Manager, KMS, EventBridge rules read legacy stores (`vault_routes._kms_keys`, `aws_extras`) that the unified engines no longer populate: `secretsmanager/kms/eventbridge: section ran` (KeyError) in `test_aws_detail_tabs_api.py`; SQS "Encryption: visible to GetQueueAttributes"; S3 "Versions: two versions of a.txt". Each needs the same engine write-back/read-through as Lambda; Nano passes (nano-core-aws-detail-tabs 104/104).
- OPEN, ENV: offline-ui-* AWS suites need `static/aws-console.html` (gone in v4 headless) or a console rail the runner times out on; offline-sdk-python-aws MinIO-direct, offline-cost-savings (azure storage), offline-api-aws-console-savings (Secrets/KMS savings do not rise: red without this change too) were red in this sandbox before and after.
- Nano: nano-cores/nano-ui-default-cloud red in baseline are non-AWS (GCP agentgov/identity need uvicorn; mesh/sns_delivery cores are not in the Nano vendor list). All AWS `test_*aws*core.py` and sns core tests pass with `PYTHONPATH=.:wasm/core`.

## GCP, 2026-11-18 nightly (nightly/gcp-2026-11-18)
DECISION: `offline-post-create-gcp-event-delivery` (Eventarc -> Cloud Function) is red. `core/gcp_eventarc_core.py` refuses `destination.cloudFunction` ("1st-gen destinations are not simulated; deploy the function as a Cloud Run service"), but the probe (tests/conformance/post_create/probes/event_delivery.py) creates a 2nd-gen function and targets it that way. Real GCP: a gen2 function is a Cloud Run service of the same name, so `destination.cloudRun.service=<fn>` is the right shape, but the simulator does not register functions in the Cloud Run store (verified: 400 "Destination Cloud Run service '<fn>' does not exist"). Options: (a) project gen2 functions into the Run store and deliver through it; (b) accept `cloudFunction` destinations naming a gen2 function. Shared engine (core/gcp_eventarc_core.py + functions/run stores), not changed tonight.
ENV (not product): offline-ui-gcp-* (pubsub-subscriptions, activity-detail, grid-defaults, pubsub-grid, create-defaults, properties) time out waiting for the rail of `/console/gcp`: the offline image on :9000 is headless (no `static/`, `/console/gcp` and `/v4/gcp/` are 404). They need the full image; the v4 console is covered by consoles/dev_server.py based nightly scripts.
NOT RUN here: nightly-gcp-tunnel-recovery and the bidi-/crawl-/validation- gcp legs (pending: need the Codespace leg).

## GCP, 2026-11-19 nightly
DECISION: Eventarc `destination.cloudFunction` is refused (core/gcp_eventarc_core.py ~L126, "1st-gen destinations are not simulated") but real Eventarc accepts a Cloud Functions (v1/v2) resource name. offline-post-create-gcp-event-delivery (probes/event_delivery.py gcp) uses exactly that, so 3 checks fail. Options: implement cloudFunction delivery (resolve to the function's invoker, deliver the CloudEvent) in shared core, or change the probe to cloudRun. Not guessed tonight.
NOT REPRODUCED (green on re-run against the live stack, likely cold-start / fresh-stack timing): offline-api-gcp-vault-console-secrets (0 -> 0 savings on a fresh space; passes at 31 -> 32), nano-ui-gcp-create-defaults Cloud SQL (first service, fixed sleep too short; validator now waits for the POST).
ENV (not run here): offline-ui-gcp-* Playwright suites timed out waiting for the offline console rail (60s) in the baseline.

## Azure, 2026-11-20 nightly
ENV on this runner (no Playwright module, no azure SDK, embedding model returns zero vectors, APIM backend proxy times out): offline-ui-azure-{metrics,rg-nav,resource-group-detail,apim-appinsights}, offline-sweepA-azure (APIM 502 timeout), offline-post-create-azure-openai (zero embeddings). Not product-verified; verify on the full runner stack.
FIXED (harness): offline-sdk-python-azure-vm-runcommand assumed no guest runtime; with Docker the command really runs. Test now asserts real `uid=` output when a runtime exists, failed status otherwise.

## Azure nightly 2026-11-21 (nightly/azure-2026-11-21)
FIXED: post_create/probes/azure_openai.py was not re-runnable: Cognitive Services accounts are soft-deleted, so a second run failed `FlagMustBeSetForRestore`. The probe now purges the deleted account before and after (real Azure flow).
DECISION: the probe asserts a 1536-d embedding, but since dbb1b47cb deployments serve the booster-mesh model (`nomic-embed-text`, backend 768-d or hash fallback 256-d). Either the Azure embeddings op reports ada-002's 1536 dims, or the probe asserts the model's real dimension. Not changed (would loosen a test).
ENV, not product: offline-sdk-java-azure* (Maven cannot fetch com.azure:azure-sdk-bom 1.2.31, Central returns 404 from this runner); offline-sweepA-azure APIM proxy (backend outbound timeout); azure-openai chat (no vyomi-llm sibling); offline-ui-azure-{metrics,rg-nav,resource-group-detail,apim-appinsights} Playwright boot timeouts on the runner, not reproduced as product bugs.
Tunnel check (6): NOT RUN, no Codespace leg. Checks 2-5: only the existing suites ran; crawl-azure-ui, validation-azure-ui and bidi-azure-* are still `pending` in suites.json.

## AWS nightly 2026-11-22
- FIXED (product): offline Lambda Function URL (`GET /lambda-url/<id>/`) returned 500 (`KeyError: 'function_name'` in `routes/aws_lambda.py`); now delegates to `core.lambda_core.url_invoke`. Test `test_aws_lambda_function_url_api.py` (suite `offline-api-aws-lambda-function-url`).
- OPEN (same class as 2026-11-17, not fixed): offline-api-aws-detail-tabs Secrets/KMS/EventBridge/SQS-encryption legacy-store reads; offline-post-create-aws-event-delivery "EventBridge: Lambda target invoked once with the InputTransformer payload".
- DECISION: nano-cores is red only for tests of modules outside the Nano vendor list (`sns_delivery`, `mesh_selfcheck`, `k3s_runtime`) and uvicorn-needing GCP/identity cores. Either vendor them (trunk-owned list) or make `nano-cores` skip tests that import non-vendored modules. Shared, not changed.
- NOT REPRODUCED: offline-sdk-{go,java}-aws-sns email delivery (green on re-run; baseline suite ran while the 30-entry delivery log was shared).
- ENV: offline-ui-* / nano UI suites need Playwright + fastapi (absent on this runner); the runner exports `AWS_REGION` in a form the CLI rejects (offline-cli-aws is green with `AWS_REGION=us-east-1`).

## GCP nightly 2026-11-23 (nightly/gcp-2026-11-23)
- FIXED (product): offline `/gcf/{project}/{location}/{function}` answered 422 `query.request Field required` for every call (unresolved `request: Request` annotation under `from __future__ import annotations` in core/gcp_eventing.py), so the API Gateway data plane could never reach its function backend. Test `test_gcp_gcf_trigger_url_api.py` (suite `offline-api-gcp-gcf-trigger-url`), fails before, passes after.
- FIXED (harness): post_create event_delivery probe read the Eventarc create LRO's `name` as the trigger name; real Eventarc returns an operation, the trigger is its `response.name`/`metadata.target`. Delivery itself was already green.
- NOT REPRODUCED: offline-api-gcp-vault-console-secrets (green on re-run).
- ENV: the appliance image on this runner serves no console (`/console/gcp` is 404; `static/` holds only swagger, the v4 consoles are built by `consoles/build.mjs` and are not in the image), so every offline-ui-gcp-* Playwright suite times out waiting for the rail. DECISION: build/bake the v4 console into the CI image (shared, `.github`/packaging, not touched) or point those suites at the v4 console.
- Checks 2-5 (UI actions, validation, bidi, crawl): only existing suites ran; crawl-gcp-ui, validation-gcp-ui, bidi-gcp-* remain `pending`. Check 6 (tunnel): NOT RUN, no Codespace leg.
