# v4/issue-report-501 — report Nano 501 "NotTranslatedYet" and adapter 5xx failures

Target: ship with v4.0.8. Trunk: `origin/v4-on-main`. Not merged, not released.

## Why
A user hit HTTP 501 on EC2 tiles in the v4.0.7 Nano console and no GitHub issue was filed. Two holes in `wasm/sw.js`:
1. the `r.miss` path returned `501 NotTranslatedYet` without calling `reportFailure`;
2. the adapter-5xx report sat after an early `return json(...)` (dead code).

## Architecture / decisions
- `reportFailure` now derives cloud/service with `classifyReq(path)` and builds the action as `METHOD service collection [verb]`
  (`_rfShape`): resource ids/names are dropped, so distinct unsimulated actions file distinct issues and a tile that polls a
  missing action files one (per-page `seen[key]` dedupe in `send()`, server-side `+1`s, 20 reports/user/hour).
- The 501 miss is reported as `kind:"http"`, `status:501`, `code:"NotTranslatedYet"` — no new kind, because the portal and
  `core/issue_report.py` coerce unknown kinds to `http`; the code is the triage label ("not simulated yet" vs a real failure).
- Responses the worker already reported carry `X-Vyomi-Reported: 1`; the page-side fetch wrapper skips those (no double issue).
  The wrapper still covers the offline appliance (no worker).
- The four `issue-reporter.js` copies stay byte-identical; the v4 pages' `?v=` cache-buster is the file's sha256[:12].

## Tests
`tests/conformance/test_nano_sw_issue_501.mjs` (real `sw.js` harness; registered as `nano-sw-issue-501`) plus the existing
`test_issue_reporter_js.mjs` and `test_nano_sw_issue_reporting.mjs`.

## Open issues
- EC2 console calls that still miss in Nano (now reported): `POST /api/aws/ec2/instances/{id}/instance-connect`,
  `POST /api/aws/ec2/metrics/collect`. Implementing them is out of scope here.
- Nothing is filed unless the user consented, is signed in, and the portal has `VYOMI_ISSUES_BOT_TOKEN`.
- Reaches users only with the next Nano release (v4.0.8) + portal sync.
