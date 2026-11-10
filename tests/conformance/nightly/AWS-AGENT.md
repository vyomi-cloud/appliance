# AWS nightly conformance agent — instructions

Runs once a night (GitHub Actions, base `origin/v4-on-main`) for the AWS cloud only.
Rules live in `NIGHTLY-V4-PLAN.md`; the live board is `Collab-AWS-GCP-Azure.md`
(both in the parent folder of the repo checkout). Template: `tests/conformance/hourly/AGENT.md`.
Goal: find every deviation of Vyomi's AWS surface from real AWS, fix the product (never the
test), prove each fix with a test that fails without it, and land it on `v4-on-main`.

## Scope (own paths only)
`consoles/src/aws/**` (v4 console source, built to `wasm/v4/aws` by `consoles/build.mjs`; Nano is the only v4 UI target), `wasm/aws-console.html`, `tests/conformance/*aws*`,
`tests/conformance/nightly/aws-*`, `core/*aws*`, `providers/*aws*`, `wasm/core/*aws*` (vendored: change `core/`,
rebuild with `wasm/build_cores.py`, never fork). Anything shared (`server.py`, shared `core/`, `wasm/relay/`,
`.github/workflows/`, `suites.json`, `run_suites.py`, `nightly/lib/`, `docs/`) needs a lock-board line first;
another cloud's files or the tunnel/portal code: file a request on the board, never edit.

## The six checks (all AWS services every night)
1. **SDK / CLI / API.** `python3 tests/conformance/hourly/run_suites.py --target offline --cloud aws` and
   `--target nano --cloud aws`. Official SDKs/CLI with only the endpoint changed.
2. **UI actions (Playwright).** Every button, tab and create form does something real. UI crawl for the AWS
   console (`CLOUDS=aws`), plus `wasm/ui-tests/validate-aws-*.mjs`.
3. **Broken functionality.** PAGE_ERROR, HTTP_5XX, HTTP_501, DEAD_TAB, PLACEHOLDER_*, EMPTY_PANEL findings.
4. **Form validation and errors.** Invalid input is refused with real AWS wording and error codes
   (`ValidationException`, `InvalidParameterValue`, `BucketAlreadyOwnedByYou`, ...), field-level where AWS is.
   Never a raw stack trace, `[object Object]`, `undefined`, "Internal Server Error", "Something went wrong".
   Fix both the API response and the console text.
5. **UI <-> SDK/CLI/API both ways.** Created in UI => read by SDK/CLI with the same names, ids, ARNs, status;
   created by SDK/CLI => appears in the UI after reload; deleted either way => gone in the other. Compare data,
   not presence. Reuse `tests/conformance/nightly/lib/` helpers (Azure session); AWS specifics in `aws-*` files.
6. **Tunnel.** Conformance (credentials in `~/.vyomi/credentials`, session, relay) and auto-recovery on the
   AWS-pinned Codespace: kill the relay, drop the SSH session, restart the Codespace appliance — the link returns
   with no user action and no state loss. Tunnel bugs are reported on the board, not edited here.

## Environment (do not collide with the owner's running stack)
- `export CLOUDLEARN_STATE_DIR=$(mktemp -d) PYTHONDONTWRITEBYTECODE=1`; pick a free port
  (never 9000/8099/8100/8090 if in use: `lsof -iTCP:<port> -sTCP:LISTEN`). Point suites at it with
  `VYOMI_BASE_URL` / `RELAY_HTTP`. Never test against the owner's running appliance or portal.
- Check free disk (`df -h /`) before image builds; never touch Homebrew; never `rm -rf` data you cannot recreate.
- One Codespace, yours only, recorded on the board; stop it at the end (also on failure). Never `gh auth switch`.
- Never print or commit a token, `.env`, or `~/.vyomi/credentials`.

## Rules for tests
A check that cannot fail is not a check. Never weaken or skip a test to turn it green. A real upstream change or
product decision goes into `needs-decision.md`. Not-yet-built suites are listed `pending` in `suites.json`
(append-only text insert; never re-serialise the file).

## Landing the work
- Branches start fresh from `origin/v4-on-main`; commit small, `git add <paths>` only (never `-A`).
- End of run, only when ALL six checks pass after fixes and the new tests fail without the fixes:
  rebase on current `origin/v4-on-main`, re-run the AWS suites once on the rebased tree, then fast-forward
  `v4-on-main` (`VYOMI_INTEGRATOR=1`, owner-authorised 2026-11-11: no PR). If any check is red or the rebase
  conflicts: do not merge; push `nightly/aws-<date>`, open ONE PR with the report and `needs-decision.md`.
- Never touch `main`, tags, GitHub Releases, `docker-publish.yml` / the `v4-preview` image, packages, or the
  portal deploy. The v4 release is the owner's step. If the hourly or daily-PR workflows are about to release v4: STOP and tell the owner.

## Report (always, even when green)
Per dimension: pass/fail counts, fixes (commit + the test that proves it), still-red items with log excerpts,
skipped/`pending` items with reasons, and what was NOT verified. Be truthful.
