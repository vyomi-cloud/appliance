# Known-issues fixer (hourly, v4.0.x beta): one row of `V4.0.0-KNOWN-ISSUES.md` per cycle, per cloud

You fix ONE open row of `docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md` for the cloud you were started for (`$CLOUD` = azure | aws | gcp).
The workflow already picked the row (`$ISSUE_ID`, from `tests/conformance/nightly/known_issues_pick.py`), checked out `$FIX_BRANCH`
(`known-issues/<cloud>-<yyyymmddHH>`, fresh from `origin/v4-on-main`) and ran the cloud's suites into `before.json` + `tests/conformance/hourly/out/`.
Method and priorities: `tests/conformance/hourly/AGENT.md`. Rules and scope: `NIGHTLY-V4-PLAN.md` (the same ones the nightly follows). This file only adds what is specific to this job.

## Do
1. Read your row (`python3 tests/conformance/nightly/lib/known_issues.py list --cloud $CLOUD`) and the "where to start" pointer. Reproduce it first (a failing test or a
   live repro on a local stack: `CLOUDLEARN_STATE_DIR=$(mktemp -d)`, a free port, `PYTHONDONTWRITEBYTECODE=1`). If you cannot reproduce it, say so and stop.
2. Fix it at the SOURCE (the product code), not in the test or the crawler. Both targets matter: if you change `core/`, re-vendor Nano with `python3 wasm/build_cores.py`
   (no arguments: it runs immediately) and check the Nano path too.
3. Add a test that FAILS without the fix and passes with it. Run it, then every suite that was green in `before.json` for your cloud: nothing green may go red.
4. Close the row: `python3 tests/conformance/nightly/lib/known_issues.py resolve --id $ISSUE_ID --by <fix commit>` (moves it to "Resolved after the cut"); commit that with the fix.
   If you only fixed part of it, edit the row text to say what remains instead of resolving it.
5. Commit by path with a message starting `known-issues-$CLOUD:`; `git pull --rebase origin "$FIX_BRANCH" && git push origin HEAD:"$FIX_BRANCH"`.

## Skip, do not force
If the row cannot be fixed in code in this cycle (needs an owner decision, a real backend, Docker/Azurite/Postgres we do not have in CI, the portal, the Mesh image,
a sandbox/portal PR, another cloud's files, or a design change): change nothing and say why in the summary. The workflow records the attempt and the picker moves on
to the next row after 24 h. Never invent a fix, weaken a test or edit the register to hide a problem.

## Hard limits
Own cloud's paths only (azure: `consoles/src/azure/**`, `core/*azure*`, Azure providers, `tests/conformance/*azure*`; aws and gcp the same pattern). Shared files
(`core/` shared modules, `server.py`, `wasm/relay/`, `packaging/tunnel/`, `.github/`, `suites.json`, `run_suites.py`): only if the row cannot be fixed otherwise, minimally,
append-only for `suites.json`, and say so in the commit. Never: `main`, tags, releases, image publish, the portal, `gh auth`, bare `git stash`, `git add -A`, force-push, secrets in output.
One row per cycle. Subscription auth only (`CLAUDE_CODE_OAUTH_TOKEN`); never an API key.

## Summary
Last, write `tests/conformance/hourly/out/agent_summary.md` (do not commit): the row id, fixed / partly / skipped (+ why), the test you added, suites re-run (ran / not run + why).
