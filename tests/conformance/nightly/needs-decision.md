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
- Eventarc and API Gateway have NO v4 console service (`consoles/src/gcp/services` has neither), though both have native cores. Build the consoles or drop them from the catalog?
- v4 IAM "Create service account": the Service account ID field is not derived from the name (the real console derives it live).
- Storage accepts 2-char bucket names (real GCS: 3-63). Tighten after renaming the unit-test fixtures that use `bo`, `lc`, `sc`, `v1`.
- v4 Monitoring: the alert-policy list is read-only (no select/delete/detail/edit); the real console can delete and edit a policy. Build it? (`gcp-v4-roundtrip` skips step D for monitoring with this reason.)
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
