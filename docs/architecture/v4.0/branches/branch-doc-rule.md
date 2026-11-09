# v4/branch-doc-rule

Owner: mesh/tunnel session (at the owner's request) - Started: 2026-11-09 - Base: origin/v4-on-main (55257e3a) - Status: merged

## Purpose
Every topic branch documents its architecture, design decisions and open issues, so the reasoning survives after the branch is deleted.

## Architecture
- Rule 11 in `docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md` (section 3) plus lines in the session checklist (5.5).
- `scripts/v4-session-start.sh` writes a template to `docs/architecture/v4.0/branches/<topic>.md` (appliance) or `docs/branches/<topic>.md` (portal worktree).
- `.githooks/pre-push`: on a topic branch with no such file, prints a warning (never blocks).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| The document lives in the repo and is kept after the branch is deleted | A wiki page; the PR description | It is versioned with the code and found by grep; PR text disappears with the branch. |
| The hook only warns | Block the push | The branch rules say topic branches are never blocked, so work is never lost; the integrator enforces the document at merge time. |
| One template, written by the existing start script | A separate command | Sessions already run the script, so the document appears with no extra step. |

## Open issues
- [ ] The portal repo has its own CLAUDE.md and guard hook; they do not yet mention rule 11 (owner: portal session).
- [ ] Branches that existed before this rule have no document; the integrator decides whether to backfill the open ones.
- [ ] `--portal` worktrees were not exercised in a real run (the appliance path and the hook were).

## Testing
Created a throwaway topic with the script: the template appeared with the right path and base; the hook warned without the document and was silent with it. `sh -n` passes on both scripts.
