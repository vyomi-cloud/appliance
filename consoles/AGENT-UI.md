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
node consoles/tests/smoke-aws.mjs                           # (aws) existing pilots still pass
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
