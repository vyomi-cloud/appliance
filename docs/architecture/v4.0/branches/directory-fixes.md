# v4/directory-fixes

Owner: Rohith (prepared by Claude, 2026-11-22) - Started: 2026-11-22 - Base: origin/v4-on-main (42fa43b77) - Status: in review

## Purpose
Make the `vyomi` plugin pass every Claude directory check this repository controls. The directory's Validate refused
4.2.0, and Anthropic's pre-submission checklist adds two more blocks. This branch ships plugin 4.2.1 with those fixed. The one
block it cannot fix, local MCP servers from unverified organizations, is the owner's (HUMAN-GATES G9). Execution plan:
`../AGENT-DISTRIBUTION-NOW.md`; finding-by-finding status: `integrations/claude-plugins/SUBMISSION.md` §0.

## Architecture
| Change | Where |
|---|---|
| `network` removed from the Claude manifest; the other manifests never had it | `integrations/claude-plugins/plugins/vyomi/.claude-plugin/plugin.json` |
| `npx -y vyomi-tunnel@1.4.0 mcp` pinned in both MCP files, the skills and the README | `plugins/vyomi/{.mcp.json,mcp.json,skills/*/SKILL.md,README.md}` |
| Drift guard: the npx pin is exact and equals `packaging/tunnel/package.json`, including JSON snippets in texts; a README in the plugin folder with 40+ words outside code; only allowlisted Claude manifest fields | `scripts/check_agent_plugins.py` |
| Mirror guard: `--tunnel-version X.Y.Z` rewrites the pin in the mirrored copy; `--apply` refuses a pin registry.npmjs.org does not serve (404s retried for CDN lag, other errors fail closed); `--allow-unpublished` for dry runs only | `scripts/sync_claude_plugins.py`, `.github/workflows/tunnel-release.yml` (plugin-sync) |
| Disclosure README: command, five hosts and when each is contacted, the only writer, 9 tools, installs, MIT | `plugins/vyomi/README.md` |
| Icon re-encoded from its pixels (no metadata chunks before or after; new bytes) | `plugins/vyomi/.claude-plugin/icon.png` |
| Plugin 4.2.1 everywhere the drift guard checks | four plugin manifests, `.claude-plugin/marketplace.json` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| The pin equals `packaging/tunnel/package.json`, enforced at PR time | Pin to whatever is newest on npm at sync time | One source of truth. A tunnel bump without a pin bump fails CI, and the version guard then forces a plugin version bump, so installed copies update |
| The sync checks npm before it mirrors | Rely on job ordering alone | `plugin-sync` needs `publish`, so a release already publishes first; the check also covers a manual `--apply` and a failed publish |
| Hosts disclosed in the README, not in `network.hosts` | Keep `network.hosts` | The directory refuses non-allowlisted fields from unverified organizations; the README is what the security scan reads for disclosure |
| `vyomi.cloud` listed as a fifth host | Only the four hosts in the request | `vyomi_status` and `vyomi_reach` run `vyomi-tunnel list mesh` when credentials exist, which POSTs a signed session request to the portal; an undisclosed destination fails the scan |
| Claims row on this branch, not pushed to the trunk | Push to `v4-on-main` | The owner asked for no trunk pushes in this session; the row lands with the merge |
| The marketplace-root README (`integrations/claude-plugins/README.md`) keeps unpinned MCP-only snippets | Pin them too | Out of the plugin folder the directory checks; users who add the MCP by hand should get the latest tunnel. Same for the portal `/docs/agents` snippets |

## Open issues
- [ ] Verified-organization status for local MCP (G9) (owner: Rohith)
- [ ] Mirror 4.2.1 to `vyomi-cloud/claude-plugins` (see the PR: a manual sync after merge, or the next tunnel release) (owner: Rohith)
- [ ] Merge and promote portal PR #62 before submitting, so the support URL resolves (G10) (owner: Rohith)
- [ ] Re-run the form's Validate after the mirror has 4.2.1; check the icon warning is gone (owner: Rohith)
- [ ] `TestMCPEnvRendersTargetAndWarnings` and `TestMCPScanRepo` fail when a live Nano tunnel answers on :8090; make them hermetic (owner: CLI session)
- [ ] Retake screenshot 1 at 4.2.1 (owner: Rohith)

## Testing
On the Mac (darwin/arm64), 2026-11-22:
- `claude plugin validate` on the plugin folder and the marketplace (2.1.309, 2.1.330): pass. The strict directory profile from a mirror copy: "nothing to report".
- `check_agent_plugins.py`: pass; `--schemas` against the pinned spec commits: pass. Mutations fail it as expected: unpinned, `@latest`, a skill pinned 1.3.3, `package.json` bumped without the pin, `network` re-added, README removed or 32 words, an unpinned JSON snippet, a version mismatch.
- Sync against a fresh clone of the mirror: 4.2.0 -> 4.2.1, README mirrored, npm check passes for 1.4.0, re-run is a no-op. With the npm lookup stubbed: an unpublished pin and an unpublished `--tunnel-version` are refused, the mirror is left untouched, and `--allow-unpublished` lets a dry run through.
- Guardrail gate (CI deps): exit 0; all `[A]` rows PASS.
- `go test ./...` in `cmd/vyomi`: 2 failures with a live Nano tunnel on :8090 (pre-existing, environmental); pass, also with `-race`, when `RELAY_PORT` points at a free port. vet and gofmt clean.
- `node wasm/relay/test-mcp-launch.mjs`: 14/14.
- `npx -y vyomi-tunnel@1.4.0 mcp` initialize + tools/list: 9 tools, with and without an installed tunnel.
- actionlint 1.7.12 on `tunnel-release.yml` and `tunnel-mcp-checks.yml`: clean.
NOT run: the form's Validate (it reads the public mirror, still 4.2.0).
