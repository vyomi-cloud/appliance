# v4/iam-nano-e2e (WP nano-e2e)

Base: `origin/v4/iam-faithful` (d4b716218). Makes the faithful-IAM engine work for real inside the browser build (Nano) for AWS, GCP and Azure: the REAL request maps (`map_aws|gcp|azure`), engines (`aws|gcp|azure_eval`), gate/modes/audit/api, and new host adapters that build each engine's `state` and resolve the calling principal from the IN-BROWSER stores. Predecessor: `iam-nano-hook.md` (hook design, paths A/B/C). Contract: `IAM-ENGINE-CONTRACT.md`.

## 1. What was added
| File | What |
|---|---|
| `core/iam_state_nano.py` (vendored to `wasm/core/`) | Pure-Python adapters over `core.nano_registry.get()`: AWS state/principal (shared with Mesh: re-exports `iam_state_adapters.aws_*`, one definition), GCP and Azure built here. `NeedCatalogs` (a `CatalogUnavailable` listing EVERY missing catalog), `on_preload` (mirrors a preloaded catalog into the Pyodide FS and drops the engine caches that read it). |
| `core/iam_engine/nano_bridge.py` | state/principal via `iam_state_nano`; multi-catalog `need`; `map_aws.set_catalog_loader` (served from preloaded text, not disk); unidentified-credential rule (below). |
| `wasm/sw.js` | `/_wire/api/iam/<cloud>/...` (the address the consoles use) handled like `BASE/api/iam/<cloud>/...`; ARM `/_wire/subscriptions/...` now forwards `Authorization` (+ body) so the gate can run. **Bug fixed here**: the previous `startsWith("/api/iam/")` shadowed the console adapter routes `/api/iam/users|roles|policies|groups|attachments`; the faithful API route is now `^/api/iam/(aws|gcp|azure)/`. |
| `wasm/nano-boot.js` | `armGuarded`: `("azure","_arm")` tuples that carry headers go through `guardWire` (denial returned in the `__http` shape the SW already understands). |
| `wasm/ui-tests/iam/iam-hook-e2e.mjs` | rewritten: no stand-ins (`standin/` deleted); three clouds + both paths + reload + overhead. |
| `tests/conformance/test_iam_state_nano.py` (9) | adapters, lazy multi-need, and the full bridge (real map + engine + gate) per cloud, host side. |

## 2. Where state and principal come from (Nano stores)
| | principal | state |
|---|---|---|
| AWS | access key id (SigV4 header / presigned / SigV2) -> `reg["iam"].access_keys` -> user; STS sessions from `extras["sts_sessions"]` | `iam_state_adapters.aws_state(reg["iam"])`: users/roles/groups with inline + attached managed policy documents, boundaries, SCPs (when the store attaches them) |
| GCP | `x-cloudlearn-principal` > Bearer JWT `email` claim; opaque `ya29.` tokens carry no identity in Nano (the token endpoint keeps no token table) | `reg["gcp_iam"]`: `gcp_iam_policies` -> `allow_policies`; `gcp_deny_policies`; `gcp_custom_roles`; `hierarchy` = every GCS bucket of `reg["gcs"]` -> the project when exactly one project has a policy; `catalog` (role -> permissions) from the preloaded `gcp/<service>.json` of the roles actually bound (a basic role needs every service) |
| Azure | `x-cloudlearn-principal` > Bearer JWT `oid` \| `appid` \| `azp` \| `sub`; `groups` claim | `reg["az_arm"].state` records `roleAssignments` / `roleDefinitions` (custom) / `denyAssignments` -> the engine's flat shapes; `groups` from `reg["az_graph"].group_members`; `builtin_roles` = only the built-ins the assignments reference (see 5) |

Unidentified credentials (same rule as `core/middleware.py` for AWS, extended): an AWS key that is not in the IAM store, a GCP/Azure token with no identity claim act as the account root / project owner / subscription owner, so turning enforcement on never locks out default-credential users. `unknownPrincipal: "deny"` makes the engine deny them. Credential-less traffic (the console) is never gated (as on Mesh).

## 3. Console-adapter path C (`/api/<svc>/...`)
Decision: **not gated; parity with Mesh.** Mesh's gate skips `/api/` (`INTERNAL_PREFIXES`; console traffic is admin), so gating the adapter ops on Nano alone would make the two substrates behave differently, and the adapter ops (`prov,svc,op`) are not wire requests `map_*` can map (it would need a per-adapter op->permission table). The wire calls the v4 consoles make (`/_wire/...`) ARE gated whenever they carry a credential; the console sends none, so they pass. The e2e asserts the console paths stay open under `enforce` (`/_wire` unsigned, `/api/iam/users`).

## 4. Results (Chrome stable via Playwright channel `chrome`, Pyodide 0.26.2, headless)
`NODE_PATH=.../appliance-v4nightaws/.ci-node/node_modules NANO_DIR=<worktree>/wasm node wasm/ui-tests/iam/iam-hook-e2e.mjs` (about 5 minutes, needs the Pyodide CDN): **`RESULT: PASS (34/34)`**.
- AWS (path B, `/_wire`): user + access key + inline policy created through the IAM Query core, S3 + SQS signed calls: allowed vs `AccessDenied` (S3 XML `<Error>`, IAM query `ErrorResponse`), unknown key = root, `unknownPrincipal: deny`, explicit Deny, per-service `off`, `audit` mode (`would_deny`), record shape, `evaluate`, `catalog`, off path = 0 gate calls / 0 engine mounts / 0 catalog fetches.
- GCP: bucket + object + project `setIamPolicy` through the GCP cores; Bearer JWT `email`: read allowed (project binding inherited by the bucket), DELETE -> 403 `PERMISSION_DENIED` naming `storage.objects.delete` and `//storage.googleapis.com/projects/_/buckets/gb1/objects/hello.txt`; custom role from the GCP IAM core grants a delete; opaque token = owner; `deny` setting.
- Azure (ARM through `/_wire/subscriptions`): built-in Reader + custom role definition/assignment through ARM; Reader GET 200, PUT -> 403 `AuthorizationFailed` (client, object id, action, scope text); custom role allows write, not delete.
- Path A: real `local-relay.mjs` copy -> WebSocket -> relay SharedWorker (own Pyodide): AWS S3 + SQS allowed/denied, GCP allowed/denied, Azure ARM allowed/denied; the worker's deny record shows in the page's `/api/iam/aws/audit`.
- `/api/iam/<cloud>/...` on both `BASE/api/iam` and `BASE/_wire/api/iam`; settings for all three clouds persist across a page reload and still enforce (the IAM store is restored too); console traffic (unsigned `/_wire`, `/api/iam/users`) stays open under `enforce`.

Per-request overhead (REAL engines + REAL state adapters, page context, batches of 20, 30 batches; time for `hook.guard`: JS -> bridge -> state build from the stores -> map -> evaluate -> audit):
| decision | p50 | p95 |
|---|---|---|
| AWS allow (S3 GET) / deny (S3 PUT) | 0.34 / 0.31 ms | 0.375 / 0.335 ms |
| GCP allow (GCS GET) / deny (GCS DELETE) | 0.53 / 0.275 ms | 0.55 / 0.285 ms |
| Azure allow (ARM GET) / deny (ARM PUT) | 0.14 / 0.155 ms | 0.145 / 0.175 ms |
| AWS allow / Azure allow after +20 IAM users (with policies) / +20 resource groups | 0.335 / 0.15 ms | 0.345 / 0.155 ms |
| space off (`guard()`) | 0.2 us, 0 Python calls | |
| first request after enabling (engine mount + first catalogs), measured once per cloud in exploration runs | AWS ~52 ms (s3 catalog), Azure ~21 ms (before the casing fix), GCP ~250 ms (`_methods` 0.8 MB parsed twice + role catalogs) | once, then cached in memory and IndexedDB |
End-to-end SDK-style S3 GET through the service worker is dominated by the wire (165-226 ms here, drifting upward as the stores grow during the run; off 165/204 ms vs enforce 187/226 ms in alternating rounds): the gate adds a few tenths of a millisecond; the difference is within run-to-run drift and was not separable.

Host-side: `test_iam_state_nano.py` 10, `test_iam_nano_hook.py` 9 pass; `test_iam_e2e_engine.py`, `test_iam_gate.py`, `test_iam_enforcement_api.py` (58) pass; `test_nano_triggers.py`, `test_nano_aws_iam_detail.py`, `test_nano_persist_delete_sync.py` pass; `test_nano_registry_pglite_core.py` passes with `PYTHONPATH=.:wasm/core` (its documented invocation). `python3 wasm/build_cores.py --check` clean.

## 5. Findings and fixes along the way
- `gcp_eval.load_catalog`, `map_gcp._load`, `azure_eval._builtin`, `map_azure._catalog`, `map_aws.catalog` all read `core/iam_catalog/**` from disk. In Pyodide that directory does not exist: the GCP map silently produced no mapping (cached empty forever), GCP roles resolved to no permissions (everything implicitly denied) and Azure built-ins to `{}`. Fix without touching the engine modules: the host hands the data over (`state["catalog"]`, `state["builtin_roles"]`, `set_catalog_loader`) and `on_preload` mirrors `gcp/_methods.json`, `azure/*.json` into the in-memory FS and clears the caches.
- `azure_eval.resolve_role` scans and lower-cases every built-in role key per assignment (~490): 5.4 ms/request in Pyodide (0.09 ms native). The adapter passes only the built-in roles the assignments reference: 0.5-1 ms. (An index inside the engine would be the real fix; engine file untouched here.)
- The relay SharedWorker needs no change: it already wraps `handle` with `guardWire`; proven end to end through a real `local-relay.mjs` (copied to a temp dir, on `:RELAY_TEST_PORT`, default 18090, own worker named `iam-e2e-relay` with a `start` config pointing at it; the owner's tunnel on :8090 is never contacted by the e2e).
- Opaque GCP access tokens (`ya29.`) have no identity in Nano, so a real GCP SDK using a service-account key is "root" until the token endpoint records issued tokens (open).

## 6. Open issues
- Resource policies (S3 bucket policy, SQS/SNS/KMS/Lambda) are not fed to the AWS engine (identity-only): same gap as Mesh.
- GCP project hierarchy: buckets inherit the project policy only when exactly one project has a policy (Nano has one project). Folders/orgs are not modelled by the store.
- GCP `groups`, PAB policies/bindings and Azure `management_groups`/`subscriptions` are not fed (the stores do not model them; Entra groups come from `az_graph`).
- Azure data-plane (blob/keyvault hosts) and SDK token flows were not exercised through a real SDK; ARM and GCS REST were.
- `tests/conformance/test_nano_core_manifest.py`, `test_nano_embed.py`: pre-existing failures, untouched.
- Audit ring (two Pyodide contexts) is last-writer-wins in IndexedDB (unchanged from nano-hook).
