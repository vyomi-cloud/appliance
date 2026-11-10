# AWS nightly agent: Analyse -> Find -> Fix -> Test -> Merge (v4)

You are the AWS fixer. Follow `tests/conformance/hourly/AGENT.md` for method (priorities, product-vs-harness bug,
every fix ships with a test), EXCEPT where this file differs: base is `v4-on-main`, you push to the nightly branch,
and a green run is merged by the workflow, not by a PR. Same shape as `AZURE-AGENT.md` / `GCP-AGENT.md`.

## Scope
AWS only: `consoles/src/aws/**` (v4 console; built to `wasm/v4/aws` by `consoles/build.mjs`, Nano is the only v4 UI target),
`wasm/aws-console.html`, `core/*aws*` and the AWS service cores (`core/aws_wire_router.py` routes), AWS providers,
`tests/conformance/*aws*`, `tests/conformance/nightly/aws-*`. `wasm/core/` is vendored: change `core/` and rebuild with
`wasm/build_cores.py`, never fork. Never edit Azure/GCP files; write the need to `needs-decision.md` ("Requests to <cloud>").
Shared files (`server.py`, shared `core/` modules, `wasm/relay/`, `packaging/tunnel/`, `.github/`, `suites.json`, `run_suites.py`)
are off limits unless the finding cannot be fixed otherwise; then fix minimally and say so in the commit. `suites.json` is append-only text inserts.

## The six checks (every night)
1. SDK/CLI/API conformance, all AWS services: `run_suites.py --target offline --cloud aws` and `--target nano --cloud aws`
   (AWS core scripts `tests/conformance/test_*core.py` are standalone: run each as `python3 <file>` with `PYTHONPATH=.:wasm/core`).
2. UI actions (Playwright): every button, tab and create form does something real (`wasm/ui-tests/validate-aws-*.mjs`, crawler with `CLOUDS=aws`).
3. Broken functionality: PAGE_ERROR, 5xx, 501, dead tabs, placeholder panes, empty panels.
4. Form validation + errors: invalid input refused with the real AWS wording and codes (`ValidationException`, `InvalidParameterValue`,
   `BucketAlreadyOwnedByYou`, ...), field-level where the real console is. Never a raw stack trace, `[object Object]`, `undefined`,
   "Internal Server Error" or "Something went wrong". Fix both the API response and the console text.
5. UI <-> SDK/CLI/API both ways: `tests/conformance/nightly/lib/roundtrip.py` with an AWS adapter (`aws-roundtrip.py`). Compare data
   (names, ids, ARNs, status), not presence; created in UI -> read by SDK/CLI, created by SDK/CLI -> in the UI after reload, deleted both ways.
6. Tunnel: `tests/conformance/nightly/lib/tunnel_recovery.py` with AWS faults (kill relay, drop ssh session, restart the Codespace
   appliance). Needs the Codespace leg and my tunnel slot on the board; if it did not run, say so, do not mark it green.

## Rules
- Every fix ships with a test that fails without it. Never delete, skip or loosen a test or the crawler to turn it green.
- A real upstream change or a product decision goes to `tests/conformance/nightly/needs-decision.md`, not a guess.
- Commit by path (`git add <paths>`), small commits, message starts `nightly-aws:`. Never `git add -A`, force-push, tag, release,
  touch `main`, the portal, or publish an image.
- Before pushing: re-run the suites you touched AND every suite green this run; nothing green may go red (`nightly/gate.py`).
- Push: `git pull --rebase origin "$NIGHTLY_BRANCH" && git push origin HEAD:"$NIGHTLY_BRANCH"`. The workflow re-runs everything and
  fast-forwards to `v4-on-main` only if no suite is red that was green on the base.
- Never print or commit secrets, tokens, `.env`, `~/.vyomi/credentials`.
- Local runs (outside Actions): `CLOUDLEARN_STATE_DIR=$(mktemp -d)`, `PYTHONDONTWRITEBYTECODE=1`, own relay port (`RELAY_PORT`, not 8090) and
  VM ssh range (`VM_PORT_MIN/MAX`), never 9000/8099/8100; `consoles/dev_server.py --port <free>` is a no-Docker backend. Check `df -h /` first.

## Summary
Last, write `tests/conformance/hourly/out/agent_summary.md` (do not commit): one sentence, then fixes, tests added, per-check status
(ran / not run + why), and what is left.
