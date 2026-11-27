# v4/endurance-gate-enable

`ci/v4/endurance-release-gate.yml` moved to `.github/workflows/endurance-release-gate.yml` (owner go 2026-11-27: "enable endurance in the release workflow").

- Runs after every "Release" workflow (tag `vX.Y.Z`), on demand and on PRs that touch cores/routes/server/endurance tests. Red -> issue labelled `release-gate`.
- Jobs: `fast` (the 8 `tests/conformance/test_endurance_*_core.py` suites + coverage map: about 10 s locally, 1-2 min on a runner with pip install) and `estate-aws` (AWS reference estate full cycle: validate, apply, no-diff re-plan, destroy, rebuild, final destroy; `timeout-minutes: 60`).
- Time: the AWS estate has no recorded full-run time; stage 1 alone applies in 39 s (34 resources), and the Azure estate cycle measured 143 s apply + 94 s destroy + 144 s reapply + 94 s final destroy. Expect roughly 15-30 minutes for the AWS job; the first Actions run gives the real figure.
- Not covered yet: GCP and Azure estates (their `estate/<cloud>` dirs exist; Azure needs the HTTPS front `front.py`), the proof layers (SDK/CLI/UI), and an endurance section in RELEASE-CHECKS.md.
- Caveat: GitHub reads `workflow_run` workflows from the default branch (`main`). On `v4-on-main` the file is in place but only gates releases once it reaches `main`; run it by hand with `workflow_dispatch` meanwhile.
