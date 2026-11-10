# Nightly GCP agent — instructions

Runs once a night (`.github/workflows/gcp-nightly.yml`). Base is `origin/v4-on-main`.
You never tag, release, or push to `main` or `v4-on-main`: you commit to the daily
branch `nightly/gcp-<date>`; the workflow opens ONE pull request into `v4-on-main`
for the owner to review. The release stays the owner's step.

## What was measured tonight (inputs)

`tests/conformance/hourly/out/` from a run against a real Codespace appliance
(`$VYOMI_BASE_URL` forwarded from the Codespace), GCP only:

- `results.json` — every GCP suite (SDK Go/Java/Python, CLI, API, UI crawl).
- `ui-offline.json` — crawler findings per service/tab (PAGE_ERROR, HTTP_5XX, HTTP_501,
  DEAD_TAB, BAD_TEXT, EMPTY_PANEL, CREATE_* ...).
- `out/nightly/*.json` — the nightly-only dimensions below.
- `slices/gcp.json` — the work list, grouped by root cause, largest first.

## The six dimensions (each must end green or explained)

1. **SDK / CLI / API** conformance for every GCP service (existing suites).
2. **UI actions** (Playwright): every button/tab/create form does something real.
3. **Broken functionality**: PAGE_ERROR, 5xx, 501, dead tabs, placeholder panes.
4. **Form validation and errors**: invalid input (empty name, bad characters, duplicate,
   over-length, wrong region, missing required field) must be refused with the message the
   real console or API gives, never a raw stack trace, `[object Object]`, `undefined`,
   "Internal Server Error" or a generic "Something went wrong". Replace any such text with
   the real GCP wording (`INVALID_ARGUMENT`, `ALREADY_EXISTS`, `NOT_FOUND`, field-level
   hints) in BOTH the API response and the console.
5. **UI <-> SDK/CLI/API both ways** (Playwright + client): created in the UI is read by the
   SDK/CLI/API with the same data; created by SDK/CLI/API appears in the UI after reload;
   delete both ways. Compare data (names, ids, self links, status), not just presence.
   A read/write inconsistency is a bug: fix the backend or the UI, whichever is wrong.
6. **Tunnel**: conformance of the link (credentials, session, relay) and auto-recovery:
   kill the relay / drop the SSH session / restart the Codespace appliance, and the link
   must come back with no user action and without losing the state.

## Pending suites you must build first (listed `pending` in suites.json)

`nightly-gcp-validation`, `nightly-gcp-roundtrip`, `nightly-gcp-tunnel-recovery`.
Build them (one script each under `tests/conformance/nightly/`), print `[PASS]`/`[FAIL]`
lines, then drop the `pending` key. Never leave a check that cannot fail.

## Rules

- Fix the cause, not the symptom; add a conformance test for every fix.
- Fixes must pass on the local stack (`$VYOMI_BASE_URL`) before you commit.
- Never weaken a test to make it green; if a failure is real upstream drift or needs a
  decision, write it in `out/nightly/needs-decision.md` instead.
- No real-cloud credentials, no network egress beyond the package registries.
- Commit small and often on the current branch; do not push.
