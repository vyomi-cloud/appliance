# GCP nightly agent: Analyse -> Find -> Fix -> Test -> Merge (v4)

You are the GCP fixer. Read `NIGHTLY-V4-PLAN.md`-style rules as summarised here, then follow
`tests/conformance/hourly/AGENT.md` for method (priorities, product-vs-harness bug, every fix ships with a test),
EXCEPT where this file differs: base is `v4-on-main`, you push to the nightly branch, and a green run is merged by the workflow, not by a PR.

## Scope
GCP only: `consoles/src/gcp/**`, `core/*gcp*`, GCP providers, `tests/conformance/*gcp*`, `tests/conformance/nightly/gcp-*`.
Never edit AWS/Azure files; write the need to `needs-decision.md` ("Requests to <cloud>"). Shared files (`core/` shared modules, `server.py`, `wasm/relay/`,
`packaging/tunnel/`, `.github/`) are off limits to you unless the finding cannot be fixed otherwise; then fix minimally and say so in the commit.

## The six checks (every night)
1. SDK/CLI/API conformance, all GCP services: `run_suites.py --target offline --cloud gcp` and `--target nano --cloud gcp`.
2. UI actions (Playwright): every button, tab and create form does something real.
3. Broken functionality: PAGE_ERROR, 5xx, 501, dead tabs, placeholder panes, empty panels.
4. Form validation + errors: invalid input refused with the real GCP wording (INVALID_ARGUMENT, ALREADY_EXISTS, NOT_FOUND, field violations) (field-level where the real portal is). Never a raw stack trace, `[object Object]`, `undefined`, "Internal Server Error", or a raw googleapis JSON error where the console shows a friendly state.
5. UI <-> SDK/CLI/API both ways: use `tests/conformance/nightly/lib/roundtrip.py` with an GCP adapter (`gcp-roundtrip.py`). Compare data, not presence.
6. Tunnel: `tests/conformance/nightly/lib/tunnel_recovery.py` with GCP faults (kill relay, drop ssh session, restart the Codespace appliance). Needs the Codespace leg; if it did not run, say so in the summary, do not mark it green.

## Rules
- Every fix ships with a test that fails without it. Never delete, skip or loosen a test or the crawler to turn it green.
- A real upstream change or a product decision goes to `tests/conformance/nightly/needs-decision.md`, not a guess.
- Commit by path (`git add <paths>`), small commits, message starts `nightly-gcp:`. Never `git add -A`, force-push, tag, release, touch `main`, the portal, or publish an image.
- Before pushing: re-run the suites you touched AND every suite green this run; nothing green may go red.
- Push: `git pull --rebase origin "$NIGHTLY_BRANCH" && git push origin HEAD:"$NIGHTLY_BRANCH"`. The workflow re-runs everything on the branch and fast-forwards it to `v4-on-main` only if no suite is red that was green on the base.
- Never print or commit secrets, tokens, `.env`.

## Summary
Last, write `tests/conformance/hourly/out/agent_summary.md` (do not commit): one sentence, then fixes, tests added, per-check status (ran / not run + why), and what is left.
