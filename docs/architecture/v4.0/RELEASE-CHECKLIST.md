# v4.0.0 release checklist (manual steps, in order)

Prepared on branch `release/v4.0.0` (from `origin/v4-on-main`). Nothing below has been run: no tag, no push to `main`, no workflow, no deploy.
Standing rules: do not touch `main`/tags/portal/deploy until the user says "go"; every portal merge is one paid DigitalOcean deploy; never touch Homebrew locally (the tap is bumped by CI).

State legend: DONE (in this branch), TODO (manual), BLOCKED (needs the user).

## 0. Prepared in this branch (DONE)
- `VERSION` = 4.0.0 (the only version file; packages read it at build time, `release.yml` rewrites it from the tag).
- `CHANGELOG.md` `## [4.0.0]` entry (release.yml extracts it as the GitHub Release body), README "Latest release" + "What's in v4.0.0" + history line, version badge.
- Long-form notes: `docs/releases/v4.0.0-native-fidelity.md` (paste into the GitHub Release if you want more than the CHANGELOG section).
- Dry runs: see section 9.

## 1. Booster GitHub App (BLOCKED: needs the user / org owner)
State: code-complete against fakes only. See `BOOSTER-GOLIVE-CHECKLIST.md` for detail.
1. Register "Vyomi Booster" GitHub App (Codespaces write, Codespaces lifecycle admin write, Metadata read; no secrets). Callback `https://vyomi.cloud/api/booster/github/callback`, request user authorisation on install, expiring user tokens.
2. Install it on the `vyomi-cloud` org (repo `vyomi-cloud/sandbox`); answer open question 1 (non-member App token can `POST /repos/vyomi-cloud/sandbox/codespaces`?). Choose `BOOSTER_REPO_MODE` (auto|direct|fork).
3. Confirm `.devcontainer/booster/` (devcontainer.json, boot-booster.sh, docker-compose.booster.yml) is on the default branch of that repo.
4. Portal env vars (DO app): `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET`, `BOOSTER_TOKEN_KEY`, `BOOSTER_SESSION_KEY` (same value as the relay's `VYOMI_BOOSTER_SESSION_KEY`), `BOOSTER_RELAY_URL` (wss://), optional `BOOSTER_REPO`, `BOOSTER_REPO_MODE`, `PORTAL_BASE_URL`. Do not set `BOOSTER_WORKER=0`.
5. Deploy the relay (`wasm/relay/local-relay.mjs`) behind wss:// and set `VYOMI_RELAY_ORIGINS`.

## 2. One real Codespace boot (BLOCKED: needs the user's personal GitHub Free account)
Run the whole checklist in `BOOSTER-GOLIVE-CHECKLIST.md` section 4 and 4b: connect, start, boot-booster.sh ready, Nano chip, a real EC2/Lambda/AI call, stop, heartbeat auto-stop, 8 h TTL, extend refused, failure matrix, then measure real RSS of `llm-chat` (update `ram_mb` in `core/booster_ai.py` MODELS), first-boot model download time, tok/s. If anything fails, fix on this branch before tagging.

## 3. Final verification on this branch (TODO)
```
git fetch origin && git checkout release/v4.0.0 && git log -1
cat VERSION                                  # 4.0.0
python3 scripts/release_notes.py --version 4.0.0 --prev v3.0.45 --kind "Major release" --out /tmp/notes.md   # preview only, no --write flags
python3 tests/conformance/test_capabilities.py 2>/dev/null || python3 -m pytest tests/conformance/test_capabilities.py -q
```
Re-run the hourly conformance suite locally or via a manual dispatch of `conformance-hourly.yml` only with the user's OK.

## 4. Merge to main (BLOCKED: needs the user's "go")
`release/v4.0.0` -> `main` (v4 wins merge conflicts). Do it as a PR or fast-forward the user chooses:
```
git push origin release/v4.0.0
gh pr create --base main --head release/v4.0.0 --title "release(v4.0.0)" --body "v4.0.0"
```
Note: the hourly/daily conformance agent auto-bumps PATCH releases on merge (3.x -> next). Do not merge a `daily-release`-labelled PR before the tag; disable or label-guard it first (memory: "v3.0.45 = last Nano release").

## 5. Tag (starts release.yml + docker-publish.yml) (BLOCKED: user go)
```
git checkout main && git pull --ff-only
git tag -a v4.0.0 -m "Vyomi v4.0.0" && git push origin v4.0.0
git branch release/v4.0.0-final && git push origin release/v4.0.0-final   # per standing rule: release branch release/vX.Y.Z also exists
```
(The `release/v4.0.0` branch already exists; if you keep it as the release branch, fast-forward it to the tagged commit instead of creating `-final`.)
`release.yml` then builds the tarball, `.deb`/`.rpm` (cloud-learn + vyomi-docker), Windows MSI, `services.json`, pins compose files to the 4.0.0 images, creates the GitHub Release from the CHANGELOG section, and closes shipped issues.

## 6. Docker multi-arch images (automatic on tag; verify)
`docker-publish.yml` builds amd64 + arm64 `vyomi/appliance:4.0.0` + `:latest` to Docker Hub and GHCR. Never push a local arm64-only build.
```
gh run list --workflow docker-publish.yml --limit 3
docker buildx imagetools inspect vyomi/appliance:4.0.0     # expect linux/amd64 and linux/arm64
docker buildx imagetools inspect ghcr.io/vyomi-cloud/appliance:4.0.0
```
Booster images: the booster boots `ghcr.io/ggml-org/llama.cpp:server` (confirm linux/amd64 manifest) and the appliance image must include `core/booster_llm_gateway.py` (it does if built from this branch). `docker/booster-lang` all-languages image needs an amd64 build (open item in the go-live checklist).

## 7. Homebrew tap (automatic via brew-bump job; do not run brew locally)
`release.yml` `brew-bump` updates `vyomi-cloud/homebrew-tap` (`vyomi.rb`, `vyomi-docker.rb`) with the new url+sha256 using `HOMEBREW_TAP_TOKEN`. Verify only:
```
gh run view --workflow release.yml --log | grep -i "brew"
gh api repos/vyomi-cloud/homebrew-tap/commits --jq '.[0].commit.message'   # "vyomi 4.0.0 (vyomi + vyomi-docker)"
```
Users on CLI <= 3.0.23 need `brew update && brew upgrade vyomi-docker && vyomi update` once.

## 8. Portal: Nano bundle sync + the single paid deploy (BLOCKED: user go; one deploy only)
The portal serves its own copy of Nano (`portal/app/nano`). Current drift is large (84 of 168 bundle files differ), as expected before the first v4 sync.
```
python3 wasm/vendor_to_portal.py --portal ~/Applications/simulator/portal/app/nano     # check only
gh workflow run portal-nano-sync.yml -f force=true      # opens ONE portal PR (patch-based, keeps portal-only edits, updates APPLIANCE_SYNC.json)
```
Review the portal PR, set the portal env vars from section 1, confirm `/api/runtime/traction` and the booster routes are in the portal, then merge the PR once: that merge is the single paid DO deploy. After deploy: reload vyomi.cloud/nano and smoke-test (section 10).
Also publish `vyomi-tunnel` only if it changed (the relay ships inside the booster; no separate 1.2.0).

## 9. Dry-run results from preparation
- `scripts/release_notes.py --version 4.0.0 --prev v3.0.45` runs (used with `--write-changelog --write-readme` to produce the committed entries). The auto fix lists only cover first-parent commits (68 attributed fixes of ~1,450 commits); the summary line was replaced with a plain statement and the highlights are hand-written.
- `python3 wasm/vendor_to_portal.py --portal <portal>/app/nano` (check mode): drift detected (84 differing, 407 listed lines incl. new `v4/*` files); no files changed. The default portal path does not resolve from inside a worktree, so pass `--portal`.
- Packaging: `bash -n` passes for `packaging/debian/build-deb.sh` and `packaging/docker/build-docker-packages.sh`; real package builds need `fpm` and run in CI (not run locally).
- No per-package version manifests exist besides `VERSION` (`packaging/scoop/vyomi.json` is a dead 3.0.8 leftover; Scoop is retired). `packaging/homebrew/Formula/vyomi-docker.rb` carries a template url (3.0.33) that CI overwrites.
- `tests/conformance/test_azure_vm_guest_views.py` references the fixture image `vyomi/appliance:3.0.45` (a test fixture, intentionally not bumped).

Capability counts (rerun to refresh the notes):
```
python3 - <<'PY'
import json,glob,collections
for cl in ('aws','gcp','azure'):
  for s in ('nano','offline'):
    c=collections.Counter()
    for f in glob.glob(f'core/capabilities/{cl}/*.json'):
      for v in json.load(open(f)).values():
        if isinstance(v,dict) and 'level' in v: c[v['level'].get(s)]+=1
    print(cl,s,dict(c))
PY
```

## 10. Smoke checks after release (TODO)
- GitHub Release v4.0.0 exists with .tar.gz, .deb, .rpm, .msi, services.json and the CHANGELOG body.
- `vyomi update && vyomi --version` -> 4.0.0; `vyomi up` serves the API and no console UI; `curl http://localhost:<port>/health`.
- boto3 / gcloud / az smoke against the appliance and against Nano via the tunnel; `tests/release/cli_crosscheck.py` and `tests/release/nano_cli_check.mjs`.
- Nano at vyomi.cloud/nano: three consoles load, badges show "Dev Simplified"/"Config only", Pro-gated pages show the pill for Free users, boot screen only once per launch.
- Booster: connect GitHub, start, chip shows connected, AI call returns tokens, stop.
- `release-checks.yml` report (deb/rpm/brew/MSI install) is green on the `release/v4.0.0` branch front page.
- Announce only after all of the above (no announcement email without the user's say-so).

## 11. Open product decisions (not release blockers unless the user says so)
Booster price/purchase flow, signed images, compute IAM, certs/hostname, how a repo copy is kept in sync, explainer videos placement, remaining Not-simulated queue (`V4-GAP-QUEUE.md`).
