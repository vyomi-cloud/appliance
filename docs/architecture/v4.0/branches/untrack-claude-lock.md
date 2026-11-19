# v4/untrack-claude-lock

Owner: Claude session for Rohith - Started: 2026-11-20 - Base: origin/v4-on-main - Status: in review

## Purpose
`.claude/scheduled_tasks.lock` was committed by the rebrand sweep (a48ff1d65, 2026-06-15). Claude Code rewrites it in every
session, so any worktree with a Claude Code session shows a tracked change; `prerelease-it.sh package` failed its
`tracked-clean` check on the owner's Mac for that reason alone (vyomi-tunnel 1.3.2 run, 2026-11-20).

## Architecture
- `git rm --cached .claude/scheduled_tasks.lock`; `.gitignore` ignores `.claude/*.lock` and `.claude/settings.local.json`
  (Claude Code runtime files). `.claude/settings.json` (the v4 guard hook) stays tracked.
- `prerelease-it.sh package` `tracked-clean` now prints the changed files when it fails.

## Open issues
- none

## Testing
`git check-ignore` matches the lock; shellcheck clean; the new failure message checked in a scratch repo.
