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

## Update 2026-11-09: Mesh work that must ship with v4.0.0 (nothing below is in prod; prod is v3.0.45)

### Done locally, NOT yet committed or pushed (push set, portal worktree portal-v4nano, branch v4-nano-portal)
- Portal: `app/booster_keepalive.py` + `tests/test_booster_keepalive.py` (DO-side `gh codespace ssh` probe every 240 s so Pro/Max sessions beat GitHub's 240 min idle timeout; hooked into the existing worker in `booster_session.py`; status exposes `keepalive`).
- Portal: GitHub App connect flow renamed to `/api/mesh/github/{connect,callback}` (old `/api/booster/github/*` routes removed, v4 is the first release); redirect URI, links, tests updated.
- Portal: Mesh naming in the user-visible places: Codespace display name `vyomi-mesh`, per-user repo copy `vyomi-mesh`, error text; env `GITHUB_APP_SLUG=vyomi-mesh`.
- Portal: console sign-out + user avatar in the AWS/GCP/Azure headers (`app/nano/vyomi-appbar.js`), Mesh Join/Leave in the avatar menu, JS terms modal, dismiss (x) on the session notice (`app/nano/booster-link.js`), landing architecture groups in equal boxes (`home.html`), redesigned OAuth-setup page with admin-only setup steps (`oauth_setup_needed.html`).
- Appliance (worktree appliance-v4headless, uncommitted): booster devcontainer gets the `sshd` feature and the "Vyomi Mesh" display name. It only takes effect once synced to `vyomi-cloud/sandbox` (new Codespaces only).
- Files in the portal worktree edited by OTHER sessions (access_routes, admin_console, checkout, enterprise_sandbox, oauth, booster-widget, clouds.html, v4 index pages, main.py) must be reviewed before they are committed together with the above.

### External config (owner)
- GitHub App renamed "Vyomi Mesh" (slug `vyomi-mesh`); callbacks set: `http://localhost:8099/api/mesh/github/callback` and `https://vyomi.cloud/api/mesh/github/callback`. Remove any ngrok/`/api/booster/...` entries. Regenerate the client secret (the old one was shared in chat) and delete `~/vyomi-booster-secret.txt`.
- GitHub OAuth app (sign-in): callback `https://vyomi.cloud/api/auth/oauth/github/callback` (+ localhost for local tests); remove the ngrok entry.
- DigitalOcean app `vyomi-portal` (18ad3cfa-ce3a-4c42-98b0-abb0cb1a6bfc): the booster env vars already exist. Only `GITHUB_APP_SLUG` must change to `vyomi-mesh`; prepared spec `do-spec-v4-ready.yaml` (scratchpad), applied ONLY at deploy time (an env change redeploys). `BOOSTER_RELAY_URL` still missing. Do not set `BOOSTER_REPO_REF`.

### New or changed blockers
1. Hosted Booster relay does not exist. `relay.vyomi.cloud` (Cloudflare Worker, `wasm/relay/worker.js`) is the Nano cloud tunnel and has no Booster routes; the Booster relay is the Node `local-relay.mjs` only. Decision needed: host the Node relay (small DO droplet, about $12-24/month) or port the Booster hub to a Durable Object.
2. SSH access DECIDED (2026-11-09, owner): `vyomi-tunnel` is THE access path for both Mesh Codespace VMs and Nano browser VMs.
   - Design: `ssh my-vm.vyomi` -> `ProxyCommand vyomi-tunnel connect %h` -> Cloudflare relay (routes by VM name, portal token) -> far end = Mesh agent (Codespace: TCP to the Docker VM's sshd:22) or the open Nano tab (browser VM). `ssh` does handshake/auth/encryption end to end; the tunnel only carries bytes. `vyomi-tunnel forward my-vm 3000:8080` adds a local listener for non-SSH TCP (HTTP/ws/db).
   - Setup: install (brew/npm), then `vyomi-tunnel login` writes `~/.vyomi/ssh_config` plus one `Include` line (wildcard `Host *.vyomi`; asks first; `--no-ssh-config` to skip). No installer edits `~/.ssh`.
   - Build list: Mesh agent TCP-forward stream + VM registry (many containers per Codespace), Nano tab registers with the relay, `connect`/`login`/`forward` commands, portal VM list + token endpoint, unique VM names across both kinds, per-user stream cap, honour the key pair at launch (Docker VM backend ignores user keys today). Relay Durable Object MUST use WebSocket hibernation (about $55-60/month at 300 concurrent vs about $400 without).
   - v4.0.0 fallback: if the tunnel route is not finished in time, ship `gh codespace ports forward` for Codespace VMs (+ `ServerAliveInterval 30` in the Connect tab) and the existing local `vyomi-tunnel` listener for browser VMs. Hosted TCP gateway (droplet, about $4-6/month) stays optional post-v4 for zero-install.
2b. Browser VM toolchain (verified by listing the committed image, 2026-11-09): `wasm/vm/image/rootfs.cpio.gz` (identical in `portal-v4nano/app/nano/vm/image/`) contains git, python3.12 and pip (+ apk, curl, bash, dropbear). Not re-booted this session. Gap: pip/apk/git downloads in the VM go through `/egress` on the LOCAL tunnel relay (`127.0.0.1:8090`); the Cloudflare Worker (`wasm/relay/worker.js`) has no `/egress`. `egress.mjs` uses only web-standard `fetch`, so port it into the Worker when the relay is hosted, so `pip install` / `git clone` work without a local install.
3. 5-minute heartbeat rule ends the whole Mesh session when the Vyomi tab is closed; decide: keep, or replace by idle destroy/pause (+ `tmux`-backed shells).
4. Keep-alive is unit-tested only. Live check needs a Codespace with sshd (devcontainer change synced to `vyomi-cloud/sandbox`) and proof that `gh` accepts a GitHub App user token (GitHub-login users hold an OAuth token with the `codespace` scope, which should work).
5. Rerun the full Mesh E2E (GitHub login as admin@vyomi.cloud with EC2 + AI on all three clouds; Google/LinkedIn login + GitHub App connect) once a public tunnel/relay exists; local ngrok is gone.
6. Cleanup: about 10 old `vyomi-booster-*` Codespaces on vyomi-admin (storage quota).

## Must ship together in v4.0.0 (owner decision, 2026-11-09)

Each pair is useless or harmful if only one half ships. Do not release one half alone.

| Feature | Appliance half | Portal half | State |
|---|---|---|---|
| Sandbox access gate (Codespace console privacy) | `v4/sandbox-access-gate` (core/sandbox_access.py, whoami label) | `portal/sandbox-open-gate` (`/sandbox/open/{ref}`, signed token) | both pushed + tested; NOT on a trunk. The portal gate redirects to `/_vy/access`, which older appliance images lack, so the appliance image must be released first or together. |
| Automatic issue reporting + first-load consent (Nano + headless Pro/Max) | `v4/issue-reporting` (core, routes, SW, console build) | merged to `v4-nano-portal` (aa0248c) | portal done; appliance half waiting for the `v4-on-main` push. Then a vendor PR brings the Nano files into the portal. |

Before go-live: merge the two appliance branches to `v4-on-main` (integrator push), run `node consoles/build.mjs` and commit the regenerated consoles, vendor PR for `app/nano/**`,
register the Vyomi GitHub App and set its credentials on the portal (issue reporting "file under my account"), then fast-forward `v4-nano-portal` to `portal/sandbox-open-gate`.
