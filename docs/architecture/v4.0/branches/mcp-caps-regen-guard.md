# v4/mcp-caps-regen-guard

Owner: claude (with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (4a9f89f) - Status: ready for integrator

## Purpose
`Tunnel + MCP checks` run #160 on `v4/terraform-studio-v4` (commit d5e27cf) failed at "MCP knowledge is up to date": the merge of
`v4/tf-azure-complete` brought in an edit to `core/capabilities/azure/common.json` without regenerating `cmd/vyomi/mcp_caps.json.gz`.
Nothing told the author to regenerate, and every branch that merged the change inherited the failure. This branch makes the rule
explicit and enforces it at commit time for Claude sessions.

## Architecture
- `CLAUDE.md` rule 10: inputs of `scripts/gen_mcp_matrix.py` and their outputs are committed together; capability text never lands
  on the trunk ahead of the code it describes.
- `scripts/claude-hooks/v4-guard.py`: new `mcp_check()` on every `git commit` Bash call. It collects the paths the commit will
  carry (staged, `git add`ed earlier in the same command, and unstaged tracked changes for `-a`/`--all`). If any is an MCP input,
  it runs `gen_mcp_matrix.py --check` and refuses (exit 2) when the outputs are stale, or when they are regenerated in the working
  tree but left out of the commit. Commits that touch no input never run the generator. Any error fails open, like the rest of the guard.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Check in the PreToolUse guard at commit time | Only CI | CI catches it after the push, on every downstream branch too; the guard catches it before the commit exists |
| Run the generator only when an input is in the commit | Run `--check` on every commit | ~2 s per commit for nothing; most commits touch no input |
| Refuse unstaged regenerated outputs | Only check staleness | `--check` reads the working tree, so a regenerated-but-unstaged gz passes it while the commit is still stale |
| Do not port the `azure/common.json` text to the trunk here | Port it with the regenerated gz | The text documents the ARM deploy engine / azurerm mapping that only exist on `v4/tf-azure-complete`; on the trunk it would advertise capabilities the trunk lacks |

## Open issues
- [ ] `v4/tf-azure-complete` still fails the check: it needs the regenerated `mcp_caps.json.gz` (owner: Rohith to decide; regen commit is ready to push)
- [ ] `v4/terraform-studio-v4` carries 845299f (same regen); becomes a no-op once tf-azure-complete has it (owner: integrator)
- [ ] Humans are not covered: `.githooks` has only `pre-push`. A `pre-commit` running the same check is a follow-up (owner: unassigned)
- [ ] `MCP_INPUTS` in the guard duplicates the generator's docstring list; keep them in step if the generator gains inputs

## Testing
Hook driven directly with hook JSON in this worktree, using the real azure/common.json edit from tf-azure-complete:
clean commit passes; input added+committed in one command with stale outputs refused; staged input refused; `git -C` form refused;
regenerated but unstaged gz refused; gz added in the same command passes; `-am` passes; `add -A` and trunk push still refused.
Not run: an end-to-end Claude Code session with the hook installed.
