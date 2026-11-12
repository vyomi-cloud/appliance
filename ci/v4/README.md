# ci/v4: workflow files for the v4 pipeline

`vyomi-admin` cannot push under `.github/workflows/` (no `workflow` scope). Files here are the pushable copies: the owner copies each one to
`.github/workflows/` (same file name) and pushes with a token that has the `workflow` scope. Keep both copies identical.

| File | What |
|---|---|
| `v4-known-issues-hourly.yml` | hourly, per cloud: fix one fixable row of `docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md`, gate, fast-forward `v4-on-main`. Kill switch: repo variable `V4_KNOWN_ISSUES_PAUSE=true`. |
| `v4-bidi-daily.yml` | daily, all three clouds: run the UI <-> SDK/CLI/API bi-directional suites, `tests/conformance/nightly/bidi_report.py` writes each failing check as `AUTO-<cloud>-<suite>-<check>` into the known-issues file and resolves rows whose checks pass again. Optional live-Mesh job (needs `NIGHTLY_CODESPACES_PAT` + variable `NIGHTLY_MESH_SIM_URL`). |
