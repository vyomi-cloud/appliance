# v4/iam-ui-live - IAM UI (Enforcement, Effective access, Audit) driven against the real appliance

Branch `v4/iam-ui-live` off `origin/v4/iam-faithful` (d4b716218). Only `consoles/src/**` and the rebuilt `wasm/v4/*` changed.

## Method
Real appliance (`uvicorn server:app` on 127.0.0.1:8431, CLOUDLEARN_TIER_ENFORCE=0; the appliance is headless, it does not serve consoles). A Playwright (Chrome) harness served the built `wasm/v4/<cloud>/` bundle and proxied `/_wire/*` and `/api/*` to the appliance, so the UI used its production address `/_wire/api/iam/<cloud>/...` against the real server. nano-boot/kernel/mesh-link scripts were stubbed (no Mesh state); the live Mesh drawer therefore could not be exercised.

## Verified live
- AWS: created user + inline policy (Allow sqs:CreateQueue, Deny sqs:PurgeQueue) via the IAM wire API. Enforcement: sqs service set to Audit in the UI, persisted (GET /api/iam/aws/enforcement), re-rendered after reload with "the service setting". A signed SQS ListQueues by that user in audit mode returned 200 and appeared in Audit with the "Would deny" badge. Effective access: CreateQueue Allowed (matched `inline:q#AllowQueueCreate`), PurgeQueue Denied by explicit deny (`inline:q#DenyPurge`), ListQueues implicit deny. Matched-statement table renders.
- GCP: global mode set in the UI persisted live; Audit lists a live record (storage.buckets.list, Would deny) created by a real request carrying `x-cloudlearn-principal`; Effective access renders the live engine result.
- Azure: subscription resource override persisted live; live audit records (storage account read/write with a long ARM id) render; Effective access renders the live result.

## UI fixes
1. Audit `Time` showed the raw epoch float (appliance sends `ts` float + ISO `time`): `normalizeAudit` now prefers `time`, converts numeric `ts` to ISO (test added in iamEnforce.test.mjs).
2. Azure Audit grid: long resource ids/principals/actions overflowed into neighbouring columns; cells now wrap (`wrapCell`, full value in tooltip).

## Backend bugs found (NOT fixed here; owners of iam_state_adapters.py)
- `gcp_state()` returns `policies`/`bindings`, but `gcp_eval` reads `allow_policies` (attachment point -> policy): after a real `POST /v1/projects/vyomi-project:setIamPolicy` (objectViewer to user:alice) evaluate storage.objects.get returns implicit_deny. GCP evaluate/enforce is always implicit deny today.
- `azure_state()` passes ARM-shaped role assignment records (`properties.principalId`, `roleDefinitionId`) while `azure_eval` expects flat `principal_id`/`role_definition_id`; a real Reader assignment (PUT roleAssignments) for the principal still evaluates implicit deny on `Microsoft.Storage/storageAccounts/read`. Also the `root` principal gets `would_deny` on ARM reads of `Microsoft.Authorization/roleDefinitions` in audit mode (root should be allowed).
- GCP project id in the consoles shows `nano-project` while the appliance project is `vyomi-project` (console not bound to the live project in this harness; not verified further).

## Screens looked at
AWS/GCP/Azure at 1440x900 (enforcement, audit, effective access) and 390px. Dock/footer: no IAM content is overlapped; the only overlap is the pre-existing "Issue reporting" link (`#vyomi-ir-link`, issue-reporter.js) colliding with "Start tunnel" in the bottom dock on all pages. Phone: GCP side nav stays open and squeezes content, AWS overflow pre-existing, Azure blade has a large blank gap above the tabs (all pre-existing shell behaviour, not IAM).

## Tests
`node consoles/src/common/iamEnforce.test.mjs` passes; `consoles/tests/smoke-iam-ui.mjs` 34 PASS, 0 FAIL (mesh and nano address modes, mocked API).

## Open
- Re-run the live driver for GCP/Azure allow cases once the adapters are fixed (expect Allowed + matched binding/role assignment).
- Live Mesh drawer (top) overlap check needs a real Mesh session.
