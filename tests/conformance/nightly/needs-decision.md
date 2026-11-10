# Nightly needs-decision (owner/other-cloud items; the agents append, never delete)

## Azure, 2026-11-11 baseline on a bare simulator (v4-preview, no sibling backends)
ENV, not product (need sibling containers, the Docker socket, azure SDK / playwright installed): offline-sdk-python-azure-ops, offline-sdk-python-azure-vm-runcommand
(no `azure` python module), offline-ui-azure-* (playwright not resolvable from the checkout), offline-cli-azure (SQL connectionInfo needs real Postgres),
offline-cli-azure-app job executions (needs Docker to run the job), offline-post-create-azure-event-delivery (webhook delivery to the test receiver).
To verify on the runner stack (nightly-v4.yml), not here.
UNCLEAR: offline-sdk-go-azure-operationalinsights prints PASS lines but is scored 0 passed / 400 failed: check how the Go runner output is counted (harness bug?).

## Azure Key Vault data plane is per SPACE, not per VAULT (found 2026-11-11, real product gap)
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
