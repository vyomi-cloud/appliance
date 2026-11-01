# v4 console-UI agent — instructions

You build ONE service's page set in ONE cloud lens of the Vyomi v4 consoles, wired to the
real Vyomi backend through the service's native API. Read first:
`docs/architecture/v4.0/V4-NATIVE-FIDELITY-CONSOLES-PLAN.md`.

## Inputs
- `ui-spec/<cloud>/<service>.json` — what the native console page set contains (nav, pages,
  columns, actions, tabs, sections, form fields). If it is missing, the workflow generated a
  draft from captures (`status: "draft"`): fix obvious extraction errors as you go.
- `captures/<cloud>/live/` (only if the workflow could check out the private captures repo) —
  screenshots (`*.png`, view them) and page text (`*.txt`) of the real console. Reference only.
- The pilot implementations to copy patterns from: `consoles/src/aws/services/s3/` and
  `consoles/src/aws/services/dynamodb/` (list page, create form, detail page with tabs,
  type-to-confirm delete, honest gaps, native-wire `api.js`, `spec-map.json`).
- Backend: `core/aws_wire_router.py` (routes native requests) and the service's core in
  `core/` (e.g. `core/<svc>_core.py`). Run `python3 consoles/dev_server.py -q &` for a
  no-Docker backend serving `/_wire` with the same router.

## Cloud lenses — use YOUR cloud's kit and patterns
| | AWS | GCP | Azure |
|---|---|---|---|
| UI library | Cloudscape | MUI (`@mui/material`) | Fluent UI v9 |
| Lens kit | `consoles/src/aws/kit/` | `consoles/src/gcp/kit/` (`ResourceTable`, `Section`, `NotSimulated`, `DeleteDialog`) | `consoles/src/azure/kit/` (`BrowseGrid`, `ResourceBlade`/`TitleRow`, `CreateWizard`, `NotSimulated`, `DeleteDialog`, `arm.js`) |
| Pattern to copy | `aws/services/{s3,dynamodb,kms}/` | `gcp/services/storage/` | `azure/services/storage/` |
| Native wire | `awsJson` / `awsQuery` / `s3` | `restJson` on the Google REST paths (`/v1/projects/{p}/…`, `/storage/v1/…`), project from `gcp/project.js` | ARM via `azure/kit/arm.js` (`/subscriptions/{sub}/…?api-version=`) + data planes through the routes `azure/services/storage/api.js` uses |
| Backend router | `core/aws_wire_router.py` routes all three clouds' native requests to the cores | | |

- **GCP product ids with a slash** (`security/secret-manager`, `security/kms`): the service
  directory is `consoles/src/gcp/services/security/secret-manager/`, the spec
  `ui-spec/gcp/security/secret-manager.json`; the queue file spells it `gcp-security__secret-manager`.
- **Fixtures** for GCP/Azure call `wire(method, path, { svc: null, headers, body })` — `svc: null`
  sends no AWS signature. Create through the same native REST/ARM call the SDK makes.
- **Capabilities:** add `core/capabilities/<cloud>/<service>.json` (same schema as the AWS
  files). Feature ids start with `<cloud>.` (`gcp.kms.keyring.crud`) — all clouds share one id namespace. For GCP/Azure give each supported feature `"tests": [<core conformance test>]` — the
  probe helper speaks AWS wire. Render gaps with your lens kit's `NotSimulated`, wording from
  the registry's `limitations`.
- **Existing cores** (check `tests/conformance/test_gcp_*`, `test_azure_*` before writing new
  backend code): GCP storage, firestore, pubsub, secretmanager, kms, iam, cloudsql,
  cloudscheduler, artifactregistry, container, monitoring, …; Azure ARM (`core/azure_arm_core.py`
  — control plane for every resource type), blob, queue, cosmos, keyvault keys/secrets, sql,
  servicebus, monitor, rbac, app, …
- Smoke: add your round-trip to `consoles/tests/smoke-gcp.mjs` / `smoke-azure.mjs`.
- Write "Vyomi" as plain text in page copy. The logo (`VyomiMark`) is reserved for the top-bar
  brand and the AWS Console Home welcome banner header — never use it in service pages.

## What to build
1. `consoles/src/<cloud>/services/<service>/` — `index.jsx` (nav + routes), pages, `api.js`
   (native wire only: `awsJson` / `awsQuery` / `s3` / `restJson` from `consoles/src/common/wire.js`;
   never a bespoke `/api/*` call), `spec-map.json` (spec page id → route, fixtures, honest_page).
2. Register the service in `consoles/src/<cloud>/services/registry.js` (set `load`).
3. **Read your queue file** `consoles/agent-queue/<cloud>-<service>.json` — it may carry
   extra goals (specific backend operations or pages to build). They are mandatory.
4. Every element in the spec must be either:
   - **present and real** — rendered and backed by a real native call, or
   - **honestly absent** — inside a `NotSimulated` / `NotSimulatedContainer` panel. A whole
     page may be `honest_page: true` in `spec-map.json` ONLY if it is listed in
     `consoles/honest-allowlist.json` (out-of-scope products). The gate reads that list from
     the base branch; editing it does nothing.
   A control that looks like it works but does nothing is the one thing you must never ship.
   A not-simulated page or section renders ONLY its title and a NotSimulated note — never a
   disabled skeleton of the real UI (copied column headers with empty cells, disabled
   buttons, "Not simulated" input stubs). The gate rejects that pattern.
   "Not simulated" is for things Vyomi genuinely cannot do — not a shortcut. Pages that need
   no backend (dashboards over existing data, console preference pages stored in
   localStorage) and operations a core can reasonably model (backups as snapshots, PartiQL
   over the store, TTL, UpdateTable…) must be BUILT.
5. **Backend gaps.** If the spec needs an operation the core does not implement and it is a
   reasonable, self-contained addition (a stateful sub-resource, a describe/list call), add it
   to the core with a conformance check in `tests/conformance/` (follow the existing style:
   run with `PYTHONPATH=. python3 tests/conformance/<file>.py`), then re-vendor with
   `python3 wasm/build_cores.py`. Unmodelled operations must return the native "not
   implemented" error (S3: 501 `NotImplemented`), never a silent success.
6. If you add a fixture for the conformance check, add it to `FIXTURES` in
   `consoles/tests/ui-conformance.mjs`.

## The gate (run by the workflow, not by you — your own claims are not trusted)
- fidelity ≥ 90 %; real coverage and the count of present elements must not drop;
- no `honest_page` outside the base-branch allowlist;
- **no statics**: every built list/detail page has a `"live"` check in `spec-map.json` backed by a
  fixture in `consoles/src/<cloud>/services/<service>/fixtures.mjs` that creates a uniquely named
  resource over the native wire; the page must then show it (see the S3/DynamoDB fixtures);
- the spec and the smoke tests are taken from the BASE branch (you can add checks, not remove);
- `tests/conformance/test_capabilities.py` passes: update `core/capabilities/<cloud>/<service>.json`
  for every feature you wire (level per substrate, limitations, a probe) and render sections with
  `<CapabilityContainer id=…>` — never hand-written disclaimers;
- smoke tests and every core conformance test you touched pass.

## Verify (all must pass before you push)
```
cd consoles && npm ci && node build.mjs && cd ..
python3 consoles/dev_server.py -q &          # wait until curl -s localhost:8740/_wire/ answers
node consoles/tests/ui-conformance.mjs <cloud> <service>   # fidelity ≥ 90 %, exit 0
node consoles/tests/smoke-<cloud>.mjs                       # existing pilots of your cloud still pass
PYTHONPATH=. python3 tests/conformance/<any core test you touched>.py
```
Add a UI ↔ wire round-trip for your service to `consoles/tests/smoke-<cloud>.mjs` (create in
the UI → read back over the native wire, and the reverse), following the S3/DynamoDB blocks.

## Rules
- The repo is PUBLIC. Never copy anything from `captures/` into the repo (no screenshots,
  no page text). The spec is the only capture-derived artifact allowed in git.
- No AWS/Google/Microsoft logos, service icons or product-name page titles. Layout,
  labels and interaction follow the native console; branding is Vyomi.
- Touch only: your service directory, `registry.js` (one line), the core(s) your service
  needs + their conformance tests, `wasm/core` re-vendor output, `ui-spec/<cloud>/<service>.json`,
  the two test files above. Other agents are building other services in parallel.
- Never edit anything under `.github/` (CI and your own gate). Those changes are reverted
  before push.
- Commit on the branch the workflow gave you; the workflow opens the PR. Never push to
  `main` or to `release/v4.0.0-dev` directly.
- End with a short summary: fidelity / coverage before → after, backend changes, honest gaps.

## Headless runs: never wait on background work
The runner invokes you with `claude -p`: the job ends the moment you end your turn. Never start a
command in the background (`&`, `nohup`, `run_in_background`) and never end a message with "waiting
for …" — run builds, gates and smokes in the foreground (split long suites into parts), read their
results, and only send your final message once the work is committed.

## Nothing leaves the simulator (hard rule)
Every export, backup, snapshot export, replication target, log/metric sink, notification and
delivery destination resolves to the simulator's OWN stores: AWS → simulator S3/SQS/SNS/…,
GCP → simulator GCS/Pub/Sub/…, Azure → simulator Blob/queues/…, on Nano and offline alike.
A destination that doesn't exist in the simulator (an unknown bucket, a real `*.amazonaws.com` /
`*.googleapis.com` / `*.windows.net` host) makes the operation FAIL with the native error; it is
never resolved on the internet. Shared cores never import urllib.request / http.client / socket /
requests / httpx / boto3 / aiohttp (tests/conformance/test_no_cloud_egress.py enforces this).

## Offline + Nano parity checklist (hard rule — run before you commit)
`consoles/dev_server.py` is the shared router with IN-MEMORY stores, i.e. Nano's logic. The
shipped offline appliance is `server.py` (its own routes + durable, space-scoped stores). A
capability claimed for `offline` must work on `server.py`, and one claimed for `nano` must be
loadable + persisted in Pyodide. The gate now smokes your cloud on both. For every NEW core,
store or wire surface you add:
1. **Nano:** add the core to `wasm/build_cores.py` AND the load list in `wasm/nano-boot.js`;
   register its store in `core/nano_registry.py` and name it in `core/nano_persist.py`; wire
   runtime links (`_REG[...]`) there too. Run `tests/conformance/test_nano_core_manifest.py`.
2. **Offline:** route the native wire on `server.py` (e.g. `core/wire_ingress.py` mounts /
   unified services, `routes/aws_s3.py` + `server.py aws_query_root` for Query/JSON targets) and
   give the store a DURABLE appliance store (`core/appliance_stores.py`, space-scoped slot) —
   never the router's in-memory default. Declare runtime links (`cw_store`, `vpc_store`, …) as
   class attributes, not persisted fields (`tests/test_appliance_store_fields.py`).
   Both offline routers (`appliance_router()` and `mount_new_services`) take every router key
   from `core/wire_ingress.appliance_stores()` / `offline_runtime_stores()` — add a NEW router key
   there (with its durable store) or it silently falls back to the in-memory default offline.
   A JSON/Query service the router recognises by SigV4 scope / X-Amz-Target is served by it on
   `POST /` automatically (routes/aws_s3.py fallback); a REST one whose paths would hit the S3
   catch-all needs its scope in `_ROUTER_REST_SERVICES` there or an explicit mount.
3. **Verify offline for real:** `CLOUDLEARN_STATE_FILE=/tmp/vyomi-agent/state.json python3 -m
   uvicorn server:app --port 8791 &` then run your cloud's smoke with
   `BASE=http://127.0.0.1:8791 UI_PATH=/v4/<cloud>/ node consoles/tests/smoke-<cloud>.mjs`.
   If something can't work offline, claim `offline: not_simulated` with the concrete reason —
   never claim a level only the router delivers.
