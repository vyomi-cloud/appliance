# Hourly conformance agent — instructions

You run once an hour in GitHub Actions on the `vyomi-cloud/appliance` repo, after
the test beds have run, as one of three fixers working in parallel (see
"Parallel fixers"). The offline appliance stack is up at `$VYOMI_BASE_URL`
(http://localhost:9000) and the Nano relay at `$RELAY_HTTP` (http://127.0.0.1:8090).
Your job is to make Vyomi's UI and SDK/CLI/API surface work like the real clouds,
fast, and to prove it with conformance tests.

## Inputs (already produced this run)

- `tests/conformance/hourly/out/ui-nano.json`, `ui-offline.json` — UI crawler
  findings per service/tab: PAGE_ERROR, HTTP_5XX, HTTP_501, HTTP_404, BAD_TEXT,
  EMPTY_PANEL, DEAD_TAB, PLACEHOLDER_CELL, CREATE_* and SAVINGS_* findings.
- `tests/conformance/hourly/out/results.json` — every suite's pass/fail + log tail
  (full logs in `out/logs/<suite>.log`).
- `tests/conformance/hourly/out/new_features.json` — the feature inventory diff
  against the last run, for both targets:
  - `new` / `removed`: console services, tabs, create fields, grid columns and
    actions (from each cloud's catalog; Nano = `wasm/fixtures/*-catalog.json`), SDK
    operations each engine implements (`core/*_core.py`, `wasm/core/*_core.py`) and
    `/api` routes added or dropped since the last run
  - `parity`: features only one of Nano / offline has
  - `untested_ops`: SDK operations no Java/Go/Python/CLI test calls
  - `uncovered`: `/api` routes no test references

- `tests/conformance/hourly/out/upstream_issues.json` — open GitHub issues
  labelled `upstream-drift`: real AWS/GCP/Azure changes (new/changed/removed
  operations, new API versions, deprecations, retirements) found by the hourly
  upstream watcher (`tests/conformance/upstream/`). Each body says what changed
  and what to do.

## Parallel fixers

Three agents run at the same time, one per cloud: `aws`, `gcp`, `azure` (yours is
in the prompt and in `$SLICE`). Each has its own appliance stack and relay.

- **Your work list is `tests/conformance/hourly/out/slices/$SLICE.json`** (summary:
  `slices/$SLICE.md`). Work only on what is in it: `ui_root_causes` (findings
  already grouped by root cause, largest first — fix the cause, then re-crawl the
  affected services, don't patch rows one by one), `failing_suites`, `parity`,
  `new`, `untested_ops`, `uncovered`, `upstream_issues`. Items marked
  `"shared": true` are cross-cloud and were assigned to you.
- **Stay in your cloud's files**: `static/$SLICE-console.html`,
  `wasm/$SLICE-console.html`, `providers/$SLICE*` / `routes/$SLICE*`, your cloud's
  cores and tests. Never edit another cloud's console or provider files. Shared
  files (`server.py`, `core/`, `wasm/sw.js`, `wasm/clouds.html`, `suites.json`) are
  allowed when the fix needs them: keep those edits small and self-contained, so a
  rebase over the other fixers' pushes stays clean.
- **Push small and often**: one finding (or one root cause) per commit, pushed as
  soon as it's verified, so the others rebase over short changes. If
  `git pull --rebase` conflicts, `git rebase --abort`, drop that fix and move on —
  the next run will retry it from the new base.
- Don't re-run every suite to confirm a fix: run the suites and crawls for what you
  touched (`run_suites.py --only <ids>`), plus any green suite that shares a file
  you edited.

## Priorities, in order

0. **User-reported issues first** (`user_reported` in your slice): GitHub issues filed
   automatically when a user's simulator (Nano, offline or a sandbox) hit an unexpected
   failure. They are real users blocked right now, so they go before everything below.
   For each: reproduce it from the report (cloud, service, action, status, error, stack
   frames; the details are scrubbed, so recreate the resource yourself), add a
   conformance test that fails before the fix, fix it, and put `Fixes #<issue>` in the
   commit subject. The release that ships it comments "Shipped in vX.Y.Z" on the issue
   and closes it (scripts/close_shipped_issues.py), so never close it yourself. If you
   can't reproduce it, say what you tried in your summary and leave it open.

1. **Broken or unimplemented UI.** Work through UI findings, Nano and offline.
   Fix the product, not the test: the consoles are `static/{aws,gcp,azure}-console.html`
   (offline) and `wasm/{aws,gcp,azure}-console.html` (Nano); APIs live in `routes/`,
   `providers/`, `core/`, `server.py`; Nano cores in `wasm/core/` (vendored from
   `core/` by `wasm/build_cores.py` — change `core/` and rebuild, never fork).
2. **No resource without real details.** Any resource created through the UI,
   including with the form's default values, must come out fully populated: id/ARN/
   resource name, region/location, status, created time, size/tier, owner, and every
   column the grid shows, filled with realistic, provider-shaped values. A grid must
   never show `-`, `—`, blank, `undefined` or `null` for a field the real cloud fills.
   Fix PLACEHOLDER_CELL and CREATE_* findings at the source (the create handler / the
   provider model), not by hiding the column. Never invent a value the real
   cloud wouldn't show: where the real console itself shows `-` (e.g. CloudFormation
   "Status reason" on a successful event), leave it and list it in your summary.
3. **Implement the console: no static or unimplemented surfaces.** Each
   `ui-*.json` service row has `surfaces`: the service page, create, resource
   detail and every detail tab, each classified `live` (loads data from the API or
   shows this resource's own data), `partial` (API-backed but blank fields),
   `static` (hard-coded or generic text: synthesized metrics, a fixed `vol-root`,
   "No X configured. Currently at defaults" on every service, "Missing instance_id")
   or `unimplemented` (errors, 404/501, dead/empty). Turn `static` and
   `unimplemented` surfaces into real ones, the way the cloud's own console works:
   back them with the service's API (add the route/engine operation if missing),
   show the resource's real values, and make their actions (Edit, Add tag, Save…)
   persist through the API and show up when the tab is reopened. Do both consoles
   (`static/*-console.html` and `wasm/*-console.html`; shared logic in `core/`).
   Work service by service, most-used first (compute, storage, databases,
   functions), finishing a service's tabs before moving on; each one gets a
   Playwright check that the tab shows the resource's data and a saved edit
   survives a reload.
   These arrive as findings: `PLACEHOLDER_PANE` (a "This pane mirrors…", "Not yet
   wired", fixed Activity/Permissions sentence or a value marked "(simulated)") and
   `STATIC_TAB` / `STATIC_DETAIL` (no API call and nothing about the resource). They
   are cleared only by real data: never by rewording or hiding the text, adding an
   API call whose result the tab doesn't show, or printing the resource name above
   generic content. Activity = this resource's real events (`/api/cloudsim/events`,
   Nano `nano_events`); Permissions = the real IAM bindings that apply to it;
   Metrics = recorded series (`/api/metrics/series`), not synthesized curves.
4. **Upstream changes** (`upstream_issues.json`): keep Vyomi faithful to the
   real clouds. Oldest first, prefer lifecycle (deprecation/retirement) and
   changed/removed operations over brand-new operations. Implement or adapt in
   `core/` (+ Nano via `wasm/build_cores.py`), add a conformance test with the
   official SDK/CLI, and put `Fixes #<issue>` in the commit subject so the daily
   PR closes it. If a change doesn't affect behaviour Vyomi simulates, comment on
   the issue why and leave it for a human to close — never close it yourself.
5. **Every resource moves the cost-savings metrics, on every cloud.** Creating a
   resource (UI or SDK/CLI) must raise the active space's `cost_savings.resource_count`
   and that cloud's `by_provider` savings; using it (objects stored, items written,
   messages sent, instance hours) must raise `savings_usd` too, because the real
   cloud bills that usage. Fix SAVINGS_* findings and `offline-cost-savings` failures
   in `core/cost_model.py` (add per-service and usage-based rates from the providers'
   public price lists) and in the space tick in `server.py`, for AWS, GCP and Azure,
   and mirror the change in Nano. Never inflate numbers to pass; use real list prices.
6. **Failing suites** in `results.json`. This includes `offline-ui-sdk-roundtrip`
   (`tests/conformance/roundtrip/`): a resource made with the official SDK must show in the
   console with the SDK's own ARN/id and type; one made in the console (form defaults) must be
   visible to the SDK with the same values; a delete on either side must reach the other. A
   failure there is a product bug on one side, so fix the console or the API, never the test.
   When it is green, extend it: add the next service to `SERVICES` (and its SDK calls to
   `sdk_side.py`), then GCP and Azure.
7. **New features** (`new_features.json` → `new`): a new SDK operation with
   `tested: false` gets a Java or Go test (official SDK, endpoint changed only); a
   new service/tab/action is crawled live — fix whatever the crawl finds and add a
   Playwright validator for its main flow. A `removed` feature is a likely
   regression: confirm it was intended (commit message) or restore it.
8. **Nano ↔ offline parity** (`parity`): implement the missing side so both
   targets expose the same services, tabs and operations (shared logic lives in
   `core/` and is vendored to `wasm/core/` by `wasm/build_cores.py`). If an entry is
   only a naming difference, not a missing feature, say so in the summary.
9. **Untested SDK operations** (`untested_ops`) then **untested routes**
   (`uncovered`): add tests, a few per run.

## Product bug or harness bug?

Before fixing a finding, confirm it reproduces for a real user (open the console
with Playwright, or call the API the console calls). The crawler is heuristic: if
a finding is the harness's mistake (e.g. it counted rows on the wrong screen, or
clicked a non-submit button), fix the harness under `tests/conformance/hourly/`
so it reports accurately, say so in the commit, and move on. Harness fixes may
only make reporting more accurate, never hide a real problem.

## Every fix ships with a conformance test

- UI fixes → a Playwright validator in `wasm/ui-tests/validate-<cloud>-<area>.mjs`
  (Nano; reuse `lib.mjs`) and, for offline, a matching check driven against
  `$VYOMI_BASE_URL/console/<cloud>`. Print one `[PASS]`/`[FAIL]` line per check and
  `process.exit(1)` on any failure.
- SDK/CLI/API coverage → Java (`tests/conformance/*-sdk-java`) and Go
  (`tests/conformance/*-sdk-go`) using the **official, unmodified SDKs** with only the
  endpoint changed; CLI smokes in `tests/cli/`. Same PASS/FAIL line convention.
- Register every new test bed in `tests/conformance/hourly/suites.json`.
- The test must fail before your fix and pass after it. Run it to show both.

## Before you push

1. Re-run what you touched: `python3 tests/conformance/hourly/run_suites.py --only <ids>`.
2. Re-run every suite that was green this hour and could be affected. Nothing that
   was green may go red.
3. Commit with a message starting `conformance-agent:` describing the finding fixed
   and the test added, then push to today's daily branch (`$DAILY_BRANCH`, already
   checked out): `git pull --rebase origin "$DAILY_BRANCH" && git push origin HEAD:"$DAILY_BRANCH"`.
   Never push to main: the day's work reaches main through the daily PR, which a
   human approves, and approval cuts the release. If the rebase conflicts, abort and
   leave that fix for the next run.
4. Commit in small, separate commits — one finding (or one closely related group) each.

## Never

- Never delete, skip, loosen or comment out a test, lower a threshold
  (`check_pass_rate.sh` floors only go up), or special-case the crawler to hide a
  finding. If a test is genuinely wrong about real cloud behavior, fix it to match the
  real provider and say why in the commit.
- Never edit `.github/`, release/version files (`VERSION`, `CHANGELOG.md`, packaging),
  secrets, or anything outside this repo (the portal is deployed separately — do not
  touch it).
- Never push to `main`, `git push --force`, rewrite history, or create tags/releases.
- Never put secrets, tokens or license keys in code, tests, logs or the summary — the
  conformance page is public.

## Time budget and summary

You have about 80 minutes. Stop starting new work after ~70 minutes. Last, write
`tests/conformance/hourly/out/agent_summary.md` (do not commit it): first line a
one-sentence summary (e.g. "Fixed 3 UI findings (Azure Cosmos blank Region…), added
4 tests, 0 regressions"), then a short list of fixes, tests added, and what you left
for the next run and why.
