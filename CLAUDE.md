# Vyomi appliance repo — rules for every session (human or agent)

The full rule is `docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md` (owner-approved 2026-11-09). Read it. The short version:

1. **`v4-on-main` is the trunk and the source of truth for v4.** Every new branch starts from a fresh `origin/v4-on-main`:
   `scripts/v4-session-start.sh <topic>` (portal: `--portal`). Never branch from `release/v4.0.0-dev` (superseded).
2. **One worktree per session and topic.** Never edit another session's worktree or branch. Add your row to
   `docs/architecture/v4.0/SESSION-CLAIMS.md` before editing shared paths, and read it before touching someone else's.
3. **Push your topic branch at once and after every batch** (`git push -u origin v4/<topic>`). Nothing is ever lost, no approval needed.
4. **Do NOT push** `v4-on-main`, `release/v4.0.0`, `v4-nano-portal`, `main`, or any tag. The integrator (the owner until one is named)
   merges to the trunk; `main` and tags are the owner's go only. Never force-push.
5. **Shared files change only on the trunk:** `core/*.py`, `consoles/src/**`, `core/capabilities/**`, the Nano core lists, `wasm/**`.
   The portal receives the Nano bundle only through `python3 wasm/vendor_to_portal.py --apply` (check-only without the flag).
6. **Before building a gap, grep `origin/v4-on-main` for it** — another session may have landed it already.
7. **A branch from a stale base is ported, not merged** (re-apply its intent on a fresh topic branch; rebuild `wasm/v4` / `static/v4` /
   `wasm/core` with `cd consoles && node build.mjs` and `python3 wasm/build_cores.py`, never merge them by hand).
8. **Commit hygiene:** `git add <explicit paths>`, never `git add -A`/`.`; never bare `git stash` (shared across worktrees; use a WIP
   commit); keep branches under 3 days and rebase daily.
9. **Test in the right substrate:** Nano on the localhost portal (:8099) with the service worker; headless on the real Docker stack.
   A dev server is not a substitute for container-backed features.

Enforcement in this repo: `.claude/settings.json` runs `scripts/claude-hooks/v4-guard.py` (blocks add -A, bare stash, force-push,
push to main/trunk, tags). Humans: run `scripts/v4-install-hooks.sh` once (committed `pre-push`: topic branches are never blocked,
only warned when stale). Only GitHub branch protection cannot be bypassed — owner to enable.
