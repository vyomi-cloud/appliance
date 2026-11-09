# P1 — back-port the portal-side Nano edits to the trunk

Status: 2026-11-09. Hand-off for the session that picks this up. Rule source: `V4-BRANCH-ARCHITECTURE.md` (section 6, item P1;
rule 2 "shared files change only on the trunk"). Branch: `v4/p1-nano-backport` (claim row already in `SESSION-CLAIMS.md`).

## Why

`python3 wasm/vendor_to_portal.py --apply` copies `wasm/` over `app/nano/` in the portal. Some Nano files were edited **directly in the
portal** (logout, avatar, dismissible notices, Mesh session wiring). Those edits exist only in the portal, so the next `--apply`
silently deletes them. They must exist on the trunk (`wasm/`) **before** any vendor PR is made.

Measured on 2026-11-09 (portal `origin/v4-nano-portal` at `a291141`, trunk `origin/v4-on-main` at `8424b286`): the two files below
differ from `wasm/` by about 209 and 206 lines. Most of that is the trunk being *ahead* of the portal (harmless: the vendor step
brings it over). The portal-*ahead* part is the feature list below.

## What to port (inventory)

Portal file paths: `app/nano/vyomi-appbar.js` and `app/nano/booster-link.js` at `origin/v4-nano-portal`. Line numbers are from that
ref and will move.

### `vyomi-appbar.js` (trunk already has the account menu `#vy-acct-menu`; it lacks the pieces that make it work inside the v4 consoles)

| # | Feature | Where in the portal file | Marker to grep |
|---|---|---|---|
| 1 | The v4 consoles render their own account chip in React *after* this script runs, so the header button never attached. Native chips are hooked with a **capture-phase** click handler that opens `#vy-acct-menu` (so "Sign out" is reachable). | ~lines 236-253 | `capture` / "native chips" comment |
| 2 | `skin()`: show the user's avatar / initial / name per cloud on those chips, re-run by a `MutationObserver` (debounced 150 ms) because the consoles re-render. | ~254-276 | `function skin`, `MutationObserver` |
| 3 | Mesh row in the menu: `a[data-act="booster"]`, painted from the `vyomi-booster-session` event and refreshed every 15 s. | ~217, 226, 332 | `data-act`, `booster`, `paintBooster` |
| 4 | Sign-out confirm dialog (`#vy-so`, "Sign out of Vyomi?") that calls `POST /api/auth/logout` with credentials and then goes to `/`. | ~307-320 | `vy-so-t`, `/api/auth/logout` |

Check first: the trunk copy already contains a lot of `vy-acct-menu` code (30 matches) and one `/api/auth/logout`. Port only what is
missing, feature by feature (1 and 2 are definitely missing: the trunk has no `MutationObserver` / `skin(`).

### `booster-link.js`

| # | Feature | Where | Marker |
|---|---|---|---|
| 5 | The "ended / error" notice chip can be dismissed (x), remembered in `sessionStorage` key `vyb-dismissed`. | ~185 | `vyb-dismissed` |
| 6 | `portalApi()` + `ensureHeartbeat()`: while a Mesh session is active, `POST /api/booster/heartbeat` every 60 s (the portal ends a session whose tab has been closed for 5 minutes). | ~421-427 | `ensureHeartbeat`, `heartbeat` |
| 7 | `sessionStart()` / `sessionStop()` (portal `start` / `stop`) exported on `window.VyomiBooster`. | ~502-511 | `sessionStart`, `sessionStop` |
| 8 | `termsModal()`: JS modal ("Mesh uses your GitHub account, no cost to you") resolving true on "Agree & start". **Overlaps another session's work**: `booster-widget.js` (portal-only, `window.VyomiBoosterWidget`, commit `12e0bb6`) has its own per-cloud terms modal. Keep the widget path first (`if (W) return W.agreed()`), keep `termsModal` as the fallback when the widget is absent. | ~464-509 | `termsModal`, `VyomiBoosterWidget` |
| 9 | Connect link renamed to `/api/mesh/github/connect` (the portal route lives in `app/booster_session.py`, `mesh_router`). | ~497 | `api/mesh/github/connect` |

`booster-widget.js` and `APPLIANCE_SYNC.json` exist only in the portal; the vendor script leaves them alone, so they are not at risk.
Decision for the owner (do not decide here): move `booster-widget.js` to `wasm/` so it follows the ownership map, or list it as
portal-only. Until then do not touch it.

## How (do it by hand; do not use `git merge-file`)

A three-way merge against the old vendor base (`feb4e0f6`) conflicts and **duplicates code**, because the portal and the trunk have both
moved far from it. Re-apply each feature onto the trunk's current file instead.

1. `git fetch`; you are on `v4/p1-nano-backport` (worktree `appliance-p1-nano-backport` off `origin/v4-on-main`). Rebase on
   `origin/v4-on-main` first if it moved.
2. Keep a read-only portal checkout: `git -C ../portal-v4nano worktree add --detach ../portal-vendorcheck origin/v4-nano-portal`
   (already exists on this machine). Do **not** read from or edit the shared `portal-v4nano` working tree: it holds other sessions'
   uncommitted edits.
3. For each feature in the tables: read it in `../portal-vendorcheck/app/nano/<file>`, find the matching place in `wasm/<file>`, and apply
   only that feature. Keep every trunk change that is not in the list. Do not paste whole portal files over `wasm/`.
4. `node --check wasm/vyomi-appbar.js wasm/booster-link.js` after each file.
5. Marker check (all of these must print a non-zero count for `wasm/`):
   ```
   for m in "MutationObserver" "function skin" "data-act" "api/auth/logout" ; do printf "%-24s %s\n" "$m" "$(grep -c -- "$m" wasm/vyomi-appbar.js)"; done
   for m in "vyb-dismissed" "ensureHeartbeat" "sessionStart" "termsModal" "api/mesh/github/connect"; do printf "%-24s %s\n" "$m" "$(grep -c -- "$m" wasm/booster-link.js)"; done
   ```
6. Test in a **scratch** portal worktree, never in a shared one:
   `git -C ../portal-v4nano worktree add ../portal-vendor-try -b portal/vendor-try origin/v4-nano-portal` (or a detached one), then
   `python3 wasm/vendor_to_portal.py --apply --portal ../portal-vendor-try/app/nano`, run the portal from it
   (`set -a; . ./.env; set +a; .venv/bin/python -m uvicorn app.main:app --port 8099`, with the portal's own venv; a bare restart without `.env` loses the token key),
   sign in, open each cloud console and check: avatar/initial in the header, the account menu opens, "Sign out" asks to confirm and
   logs out, a Mesh session start/stop works (stub the portal call if no Codespace is wanted), the ended notice has a working x.
7. Run the relay tests that touch these files' neighbours (no code in them changes, but the preflight asks for them):
   `test-booster-link`, `test-booster-shell`, `test-booster-session-derived`, `test-mesh-ssh` (need `WS_PKG`; the shell test needs a Python with uvicorn).
8. Commit with explicit paths (`git add wasm/vyomi-appbar.js wasm/booster-link.js`), push `v4/p1-nano-backport`, tell the integrator.

## After the integrator merges it into the trunk

1. Remove the claim row from `SESSION-CLAIMS.md`.
2. Make the **first vendor PR** into the portal: new worktree `portal/vendor-<date>` off `origin/v4-nano-portal`;
   `python3 wasm/vendor_to_portal.py --apply --portal <that>/app/nano` from a named trunk SHA (it writes `APPLIANCE_SYNC.json`; the
   architecture doc also wants `app/nano/.vendored-from`; add it if the script does not); run the portal on `:8099`; push `portal/vendor-<date>`.
3. Only then add the CI rule that fails any portal PR touching `app/nano/**` other than a vendor PR.

The vendor check on 2026-11-09 also listed 11 trunk files "missing in portal" (relay tests, `mesh-cli.mjs`, `booster-mesh.mjs`,
`core/k8s_tier_gate.py`, `core/kube_state_core.py`) and about 40 drifted files that are simply older in the portal. None of those needs
a back-port; the vendor PR brings them over.

## Do not

- Edit `app/nano/**` in the portal (that is how P1 happened).
- Run `--apply` against the shared `portal-v4nano` checkout.
- Push `main`, a tag or a deploy; merge into the trunk yourself (the integrator does).
- Use `git add -A` or bare `git stash`.

## Done when

All markers above are present in `wasm/`, both files pass `node --check`, the scratch-portal run shows the behaviour in step 6,
`v4/p1-nano-backport` is pushed, and the integrator has merged it.

## Status and owner-question defaults (2026-11-09)

Back-port is done and pushed: `v4/p1-nano-backport` at 6cdbbb18 (`wasm/vyomi-appbar.js`, `wasm/booster-link.js`). `node --check` passes and
`test-booster-link`, `test-booster-shell` and `test-mesh-ssh` pass. The scratch-portal browser run (step 6) has NOT been done; the integrator
or the vendor-PR author should do it. Not ported: the `#vy-so` z-index change, the open-spaces/open-marketplace handlers, and the
Booster-to-Mesh wording rename outside the new blocks. The trunk's own unreachable/stale-state logic in `booster-link.js` was kept.

Defaults chosen (the owner may overrule):
1. `booster-widget.js` stays portal-only. Not moved to `wasm/`; the vendor script does not touch it.
2. Use the existing `APPLIANCE_SYNC.json`. Do not add `app/nano/.vendored-from`.

Integrator next steps: merge `v4/p1-nano-backport` into `v4-on-main`; remove the `mesh/tunnel` claim row from `SESSION-CLAIMS.md`;
make the first vendor PR on `portal/vendor-<date>`; then add the CI rule for `app/nano/**`.
