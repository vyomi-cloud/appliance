# Hourly conformance agent — instructions

You run once an hour in GitHub Actions on the `vyomi-cloud/appliance` repo, after
the test beds have run. The offline appliance stack is up at `$VYOMI_BASE_URL`
(http://localhost:9000) and the Nano relay at `$RELAY_HTTP` (http://127.0.0.1:8090).
Your job is to make Vyomi's UI and SDK/CLI/API surface work like the real clouds,
fast, and to prove it with conformance tests.

## Inputs (already produced this run)

- `tests/conformance/hourly/out/ui-nano.json`, `ui-offline.json` — UI crawler
  findings per service/tab: PAGE_ERROR, HTTP_5XX, HTTP_501, HTTP_404, BAD_TEXT,
  EMPTY_PANEL, DEAD_TAB, PLACEHOLDER_CELL, CREATE_* and SAVINGS_* findings.
- `tests/conformance/hourly/out/results.json` — every suite's pass/fail + log tail
  (full logs in `out/logs/<suite>.log`).
- `tests/conformance/hourly/out/new_features.json` — routes/pages/cores added since
  the last run (`new`) and every `/api` route no test mentions (`uncovered`).

## Priorities, in order

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
   provider model), not by hiding the column.
3. **Every resource moves the cost-savings metrics, on every cloud.** Creating a
   resource (UI or SDK/CLI) must raise the active space's `cost_savings.resource_count`
   and that cloud's `by_provider` savings; using it (objects stored, items written,
   messages sent, instance hours) must raise `savings_usd` too, because the real
   cloud bills that usage. Fix SAVINGS_* findings and `offline-cost-savings` failures
   in `core/cost_model.py` (add per-service and usage-based rates from the providers'
   public price lists) and in the space tick in `server.py`, for AWS, GCP and Azure,
   and mirror the change in Nano. Never inflate numbers to pass; use real list prices.
4. **Failing suites** in `results.json`.
5. **New features** (`new_features.json` → `new` with `covered: false`): add tests.
6. **Uncovered routes** (`uncovered`): add tests, a few per run.

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

You have about 40 minutes. Stop starting new work after ~32 minutes. Last, write
`tests/conformance/hourly/out/agent_summary.md` (do not commit it): first line a
one-sentence summary (e.g. "Fixed 3 UI findings (Azure Cosmos blank Region…), added
4 tests, 0 regressions"), then a short list of fixes, tests added, and what you left
for the next run and why.
