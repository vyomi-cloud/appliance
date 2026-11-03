# Release checklist

Every appliance release (daily conformance PR merge, or a manual `v*.*.*` tag). Items marked **(auto)** are done by the pipeline; the rest are yours.

## Before tagging
- [ ] `VERSION`, `CHANGELOG.md` entry and release notes (`scripts/release_notes.py`) — **(auto)** for daily conformance releases.
- [ ] Nano bundle synced to the portal: `python3 wasm/vendor_to_portal.py --portal ../portal/app/nano --apply` (dry-run first), one portal PR per release.
- [ ] No stray `*.bak` files under `wasm/` (the sync would copy them).

## vyomi-tunnel (the Nano local tunnel — versioned separately)
The tunnel ships on npm + the Homebrew tap, not with the appliance. If `packaging/tunnel/package.json` changed in this release:
- [ ] `packaging/tunnel/package.json` version and `const VERSION` in `bin/vyomi-tunnel.mjs` are bumped **together**.
- [ ] **(auto)** `release.yml` → `tunnel-publish`: publishes to npm through **trusted publishing** (OIDC, no token), then points `homebrew-tap` `Formula/vyomi-tunnel.rb` at the *settled* registry tarball (3 equal sha256 fetches — a fetch right after publish can be wrong).
- [ ] One-time: npmjs.com → `vyomi-tunnel` → Settings → **Trusted Publisher** → GitHub Actions, repo `vyomi-cloud/appliance`, workflow `release.yml`. (npm is retiring bypass-2FA publish tokens, so there is deliberately no `NPM_TOKEN`.)
- [ ] If trusted publishing is not set up yet, do it by hand: `cd packaging/tunnel && npm publish --access public --otp=<code>` → `python3 scripts/tunnel_sync.py sha <ver>` → update `url` + `sha256` in the tap formula and in `packaging/brew/vyomi-tunnel.rb` → push the tap.
- [ ] **(auto)** `release-checks.yml` → `tunnel` row in RELEASE-CHECKS.md: `python3 scripts/tunnel_sync.py status` must show npm ✅ and tap ✅ for the source version.
- [ ] Anything in Nano that needs a minimum tunnel version (e.g. VM SSH needs `vm-tcp`, >= 1.1.0) names that version in its hint.
- Users upgrading: `brew upgrade vyomi-tunnel` (or `npm i -g vyomi-tunnel@latest`). A stale `npm i -g` copy shadows brew's: `npm uninstall -g vyomi-tunnel && brew link --overwrite vyomi-tunnel && hash -r`.

## Tag and ship
- [ ] Release branch `release/vX.Y.Z` and merge into `main` — **(auto)** via `conformance-release.yml`.
- [ ] **(auto)** GitHub Release + Homebrew (`vyomi`, `vyomi-docker`) + Docker images.
- [ ] **(auto)** Release checks: deb, rpm, brew, tunnel, CLI, Nano CLI, console UI, Nano UI, MSI, startup, Windows E2E → `RELEASE-CHECKS.md` on the release branch.

## After
- [ ] Portal PR (Nano sync) merged — this is the paid deploy, only on go.
- [ ] RELEASE-CHECKS.md has no ❌ rows; file issues for any.

## Secrets the pipeline can use
| Secret | Purpose | Without it |
|---|---|---|
| `HOMEBREW_TAP_TOKEN` | push `vyomi*` formulae and the tunnel formula to `homebrew-tap` | brew bump skipped |
| _(none)_ | npm uses trusted publishing (OIDC) — nothing stored | the job only reports the manual steps |
