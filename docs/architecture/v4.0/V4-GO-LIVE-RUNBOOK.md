# v4.0.0 go-live runbook

Owner: Sudhir. Order proposed 2026-11-12. Every step marked **OWNER** writes to `main`, creates a tag/release, publishes an image/package or deploys prod: it is run only on the owner's explicit go for that step. Tick a box only after verifying the result, not the command.

## Pre-flight findings (read-only, 2026-11-12)
- `origin/main` = `199aa7696`, VERSION 3.0.47. Tag `v3.0.47` points at `a49f552f2`, **4 commits behind main** (#555, #556, #564, #565 landed after it).
- `main` has 13 commits not on `v4-on-main`; merging trunk into main gives **21 conflicted files** (server.py, core/azure_*, core/sqs_core.py, persistent_store.py, wasm/*, cmd/vyomi/*, docker-compose.appliance.yml, console-conformance.yml, .gitignore). Rule: v4 wins, but the main-only fixes (#556 JWT padding, #564 docker-publish, #565 Azure apt mirror, Service Bus AMQP #188, Siftly #194) must be checked to still exist after the merge.
- `v4-on-main` VERSION file says 3.0.45; it must become 4.0.0 before the EOD release guard (skips when VERSION is not 4.x).
- **Tag clash:** `v1.1.0` already exists in this repo (appliance conformance commit `9d9c686a1`). Tunnel tags need their own prefix, e.g. `tunnel-v1.1.0`, `tunnel-v1.2.0`.
- Tunnel: main package.json 1.1.0 = npm latest 1.1.0; trunk 1.2.0 unpublished; Homebrew tap serves 1.0.0.
- Known-issues: no open S1 rows. AZ-10 text stale (sandbox PR #4 merged 2026-11-12 15:37 UTC).
- Repo secrets present: CLAUDE_CODE_OAUTH_TOKEN, CONFORMANCE_BOT_TOKEN, DOCKERHUB_*, HOMEBREW_TAP_TOKEN, NPM_TOKEN. Not seen: NIGHTLY_CODESPACES_PAT (needed only for live Mesh crawl). Repo variables V4_AUTO_RELEASE / V4_RELEASE_PAUSE: none set.

## 0. Before anything
- [x] Pause the v3 automation (done 2026-11-12 15:47 UTC): `V4_RELEASE_PAUSE=true` set; hourly, daily-pr, release-on-daily-PR-merge and service-gate disabled (verified in `gh workflow list --all`). Watchdog, Release, Docker Publish left active (tag-only).
- [ ] Freeze: no merges to `main` or `v4-on-main` except runbook steps.
- [ ] Update AZ-10 row in `V4.0.0-KNOWN-ISSUES.md`; confirm AWS/GCP rows are final.

## 1. Snapshot v3 (OWNER)
- [ ] Appliance: `git tag v3.0.47 199aa7696` is wrong (tag exists at a49f552f2). Decide: keep tag, and create branch `release/v3.0.47-final` at `origin/main` (199aa7696) to preserve the 4 later commits.
- [ ] Portal: tag portal `main` as `v3.0.47` (portal repo; not visible from the appliance session).
- [ ] Tunnel: tag appliance `main` as `tunnel-v1.1.0` (NOT `v1.1.0`, taken).
- [ ] Verify: `git ls-remote --tags origin` shows the new refs at the intended SHAs.

## 2. Appliance v4.0.0 (OWNER)
- [ ] Set VERSION=4.0.0 on `v4-on-main` (one commit), run `python3 tests/release/v4_checklist.py` (all PASS/WAIVED) and `run_suites.py --strict` for offline+nano per cloud.
- [ ] Merge `v4-on-main` into `main` on a branch `merge/v4-into-main` (v4 wins conflicts), resolve the 21 files, re-verify the five main-only fixes above, run suites on the merge result, then fast-forward `main`.
- [ ] Create `release/v4.0.0` from the merged main.
- [ ] Tag `v4.0.0` (triggers release.yml + docker-publish.yml: real image publish incl. `vyomi/appliance:v4.0.0`).
- [ ] Verify: GitHub Release exists, images multi-arch (amd64+arm64), `brew upgrade vyomi-docker && vyomi update` reaches 4.0.0.

## 3. Portal v4.0.0 (OWNER)
- [ ] DigitalOcean env vars (Mesh): VYOMI_SIMULATOR_IMAGE (v4 tag), MESH_* (repo `vyomi-cloud/sandbox`, no `MESH_REPO_REF`), GitHub App id/key/client id+secret, `VYOMI_LICENSE_BACKEND_URL=https://vyomi.cloud`. Values from the owner's local `.env`; never paste them in chat or commit.
- [ ] GitHub App `vyomi-mesh`: Email permission on, production callback URLs added, localhost/trycloudflare callbacks removed.
- [ ] Remove scaffolding: `mesh-quick-test` branch in vyomi-cloud/sandbox, local quick tunnel.
- [ ] Vendor Nano into portal (`wasm/vendor_to_portal.py`, portal session) + `fetch_pyodide.py` (AZ-8).
- [ ] Merge portal `v4-nano-portal` into portal `main`, create `release/v4.0.0`, deploy (each deploy costs money: one deploy).
- [ ] Verify on vyomi.cloud: login, Nano launch, Mesh start (Pro one cloud, Max all), Open console.

## 4. Tunnel v1.2.0 (OWNER)
- [ ] Prefer BEFORE step 3 (portal's Mesh needs tunnel 1.2.0 client).
- [ ] Confirm npm trusted publisher (OIDC) configured for `vyomi-tunnel`; merge to main; tag `tunnel-v1.2.0`; release workflow publishes npm + tap.
- [ ] Verify: `npm view vyomi-tunnel version` = 1.2.0; tap formula 1.2.0 (it currently lags at 1.0.0).

## 5. Release checklist auto-trigger
- [ ] `v4-release-checklist.yml` on main with trigger on tag `v4.*` / release published (add if missing; workflow file push = owner).
- [ ] Verify one run on the v4.0.0 tag is green.

## 6. Daily/hourly/EOD runners
- [ ] Owner moves `ci/v4/v4-eod-release.yml` and `v4-bidi-daily.yml` into `.github/workflows/` on main; merge `v4/ci-bidi-daily`.
- [ ] Re-enable only v4-aware workflows; keep `service-gate` auto-merge → patch release OFF until its interaction with EOD release is decided.
- [ ] Dispatch each once manually (EOD as dry run); confirm rows appear under "Auto-detected" in the known-issues file.
- [ ] Only then set `V4_AUTO_RELEASE=true` (image publish on every EOD release) and unset `V4_RELEASE_PAUSE`.
- [ ] Add `NIGHTLY_CODESPACES_PAT` if live-Mesh crawl is wanted.

## Rollback
Appliance: re-point `latest`/brew to v3.0.47 images; `main` reset only by owner from `release/v3.0.47-final`. Portal: redeploy previous DO build. Tunnel: `npm deprecate`, tap formula revert.
