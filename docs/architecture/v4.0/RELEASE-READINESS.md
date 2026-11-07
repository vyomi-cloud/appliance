# v4.0.0 go/no-go readiness (prepared 2026-11-07, nothing executed)

Prepared from `origin/v4-on-main` dbb1b47c, merged into `release/v4.0.0`. No tag, no merge to main, no workflow run, no portal main push. Results below are real; "not run" means not run.

Verdict: NOT READY to cut until the OWNER blockers below are cleared. Engineering gates that could run locally are green or explained.

## Gates

| Gate | Result | Detail |
|---|---|---|
| release/v4.0.0 == v4-on-main + release prep | PASS | VERSION 4.0.0, CHANGELOG [4.0.0], README badge/Latest release, notes, checklist updated; pushed |
| Capability registry vs backend (`tests/conformance/test_capabilities.py`, nano substrate, clean venv py3.13) | PASS with caveats | Final run 1412/1416. The 4 misses: `azure.aks.defender`, `azure.defender.kubernetes`, `azure.defender.compliance` (test_kubescape_core.py) PASS when run standalone (needs Docker; failed inside the full run, cause not isolated - re-run in CI); `azure.functionapp.extensions` needs `consoles/node_modules` (not installed here), NOT run. An earlier run with unpinned azure-mgmt-monitor gave 26 failures, all SDK-version/missing-package artefacts (needs `azure-mgmt-monitor<7`), all pass once fixed |
| Shared AI model catalogue (`tests/conformance/test_ai_model_catalog.py`) | PASS | 24 passed |
| Offline-substrate capability levels (`CAP_BASE=...` against a running appliance) | NOT RUN | needs a booted appliance; do not run concurrently with other Docker work |
| Nano v4 console boot (AWS, GCP, Azure) from the re-vendored portal bundle (Playwright, static serve of portal-v4nano/app/nano, SW controller + `__vyomiNanoReady`) | PASS | 3/3, 0 page errors. One transient AWS timeout under CPU load, passed on retry |
| Section-level E2E on portal :8099 | NOT RUN | :8099 redirects /nano to the login gate; the legacy `smoke.mjs` harness expects `#rail` and does not understand v4 consoles (times out). No per-section v4 E2E harness exists in this tree. The v4 gap probe (`V4-GAP-STATUS.md`) is a static scan, not an E2E |
| Hourly conformance sweep | N/A for v4 | Hourly agent runs on `main` (v3 line); last 4 runs green, none on release/v4.0.0 |
| release-checks.yml (deb/rpm/brew/MSI, CLI checks) | NOT RUN | needs workflow dispatch on the branch (forbidden here) |
| Package builds, multi-arch images | NOT RUN | CI only |
| Portal vendor sync | DONE on branch `v4-nano-portal` (pushed) | see below |

## Portal re-vendor (branch v4-nano-portal, commits ed59670 and f62fefe)
- Copied all bundle drift except portal-owned files; `v4/*/index.html` got hash-only updates; videos and `booster-link.js` skipped (portal has `apiFetch` the appliance lacks - back-port it to the appliance before the sync workflow runs, or it will be overwritten/conflict).
- `sw.js` hand-ported: Resource Graph route plus Azure VM guest and SSM session routes (needed by the new VM runtime); now byte-identical to the appliance sw.js.
- NOT committed (other sessions): `app/main.py`, `app/templates/home.html`, staged `home_v2.html` deletion, `app/booster_account.py`, `app/trial.py`.
- Remaining drift after sync is exactly the protected files (clouds.html, vyomi-appbar.js, nano-connect.js, vyomi-cloudpick.js, *-console.html, index.html) and videos: portal-owned, intentionally different. Whether the portal-owned files need v4 changes was not reviewed.

## Open blockers (need the owner)
1. Booster GitHub App not registered/installed; portal env vars, relay deployment (checklist sections 1-2).
2. No real Codespace boot of the booster has been done (needs a personal GitHub Free account).
3. Booster terms of use (`BOOSTER-TERMS-DRAFT.md`) are a draft: sign-off needed.
4. Open daily PR #533 "Daily conformance fixes -> v3.0.46" on appliance main: merging it, or any daily-release PR, auto-bumps a v3 patch release. Close/hold it and pause the hourly/daily agents before the merge.
5. Release-checks workflow (installers on Win/mac/Linux) has never run on v4; needs one dispatch with your OK.
6. Portal main is a paid deploy: `home.html`/`main.py`/trial/booster account edits in progress in portal-v4nano must land (or be excluded) before the single sync PR merge.
7. Section-level E2E for v4 consoles does not exist; decide whether the capability registry plus boot checks is sufficient.
8. Runner LLM mesh spike is merged but off by default: confirm it stays off in the released portal/relay config.

## Cut commands (in order; only after "go")
```
# 0. freeze automation
gh workflow disable conformance-hourly.yml -R vyomi-cloud/appliance
gh workflow disable conformance-daily-pr.yml -R vyomi-cloud/appliance   # then close/hold PR #533 and any daily-release PRs
# 1. final verification of the branch
git fetch origin && git checkout release/v4.0.0 && git log -1 && cat VERSION     # 4.0.0
gh workflow run release-checks.yml -R vyomi-cloud/appliance --ref release/v4.0.0   # wait for green
# 2. merge to main (v4 wins conflicts; do not use any daily-release PR)
gh pr create --base main --head release/v4.0.0 --title "release(v4.0.0)" --body "v4.0.0"
#    merge it (merge commit), then:
git checkout main && git pull --ff-only
# 3. tag (starts release.yml + docker-publish.yml)
git tag -a v4.0.0 -m "Vyomi v4.0.0" && git push origin v4.0.0
# 4. verify multi-arch images
gh run list --workflow docker-publish.yml --limit 3
docker buildx imagetools inspect vyomi/appliance:4.0.0            # amd64 + arm64
docker buildx imagetools inspect ghcr.io/vyomi-cloud/appliance:4.0.0
# 5. verify Homebrew tap (CI bumps it; do not run brew locally)
gh api repos/vyomi-cloud/homebrew-tap/commits --jq '.[0].commit.message'
# 6. portal Nano sync: one PR (one paid deploy)
gh workflow run portal-nano-sync.yml -R vyomi-cloud/appliance -f force=true
#    review the portal PR (it must not drop portal-owned files; confirm booster-link apiFetch survives), set booster env vars, then merge ONCE
# 7. re-enable automation only after the v4 line is the main line
gh workflow enable conformance-hourly.yml -R vyomi-cloud/appliance
# 8. smoke
vyomi update && vyomi --version                                   # 4.0.0
python3 tests/release/cli_crosscheck.py; node tests/release/nano_cli_check.mjs
# vyomi.cloud/nano: three consoles load, badges, Pro pills, boot screen once, booster connect/AI call/stop
```
Announce nothing until all smoke checks pass and you say so.
