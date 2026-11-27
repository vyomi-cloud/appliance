# v4/tunnel-1-4-1

Owner: Claude session (with Rohith) - Started: 2026-11-27 - Base: origin/v4-on-main (b660a62) - Status: in review

## Purpose
Release `vyomi-tunnel` 1.4.1 so the MCP that plugin users run (`npx -y vyomi-tunnel@<pin> mcp`, bundled `vyomi-mcp`
binaries) is built from the 4.1.1 code. 1.4.0 (2026-11-22, 6d50c46) predates v4.1.0 and v4.1.1: no MCP knowledge for
IAM, Terraform import/export or Vyomi Labs, and the hosted-MCP relay fix is missing. The hosted MCP at vyomi.cloud/mcp
was moved to 4.1.1 on 2026-11-27 (mcp-hosted-release run 45939473618, image 0.1.3).

## Architecture
| Change | Files |
|---|---|
| Tunnel version 1.4.0 -> 1.4.1: the five strings `tunnel-release.yml` stamps for an RC, plus the package and the MCP Registry entry | `packaging/tunnel/bin/{vyomi-tunnel,mesh-cli,credentials,creds-sync}.mjs`, `packaging/tunnel/package.json`, `packaging/tunnel/server.json` (2) |
| Plugin pin `vyomi-tunnel@1.4.1` (check_agent_plugins.py requires pins == package.json) | `integrations/claude-plugins/plugins/vyomi/{.mcp.json,mcp.json,README.md,skills/vyomi-mesh/SKILL.md,skills/vyomi-setup/SKILL.md}` |
| Plugin version 4.3.1 -> 4.3.2, all manifests in step | `integrations/claude-plugins/**/*.json` (11 fields) |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Bump the plugin version with the pin | Pin only | The release's plugin-sync refuses changed plugin content at an unchanged version ("installed copies would never update"); checked against the public mirror. |
| Bump both plugins (vyomi, vyomi-cloud) | Only `vyomi` | All manifests have moved in step; the sync guard allows a bump with unchanged content. |
| Leave dated records at 1.4.0 (`SUBMISSION.md`, `HUMAN-GATES.md`, architecture docs) | Rewrite them | They record what was submitted/tested then. |

## Open issues
- [ ] After merge: tag `tunnel-v1.4.1` on the merge commit (owner's go; publishes npm `latest`, Homebrew, the plugin mirror, the MCP Registry). (owner: Rohith)
- [ ] After the release: `npx -y vyomi-tunnel@1.4.1 mcp` initialize reports 4.1.1 knowledge. (owner: Claude)

## Testing
- `scripts/check_server_json.py`: server.json matches package.json, io.github.vyomi-cloud/vyomi 1.4.1.
- `scripts/check_agent_plugins.py`: manifests consistent.
- `scripts/sync_claude_plugins.py <public mirror clone> --tunnel-version 1.4.1` (report only): `vyomi 4.3.1 -> 4.3.2`, `vyomi-cloud 4.3.1 -> 4.3.2`, `changed=true`, no guard error (before this branch it failed: "content changed but the version did not").
- `vyomi-tunnel --version` prints `vyomi-tunnel 1.4.1`; `test-tunnel-credentials.mjs` passed.
- `tunnel-release.yml` dry run on this branch (every gate, `npm publish --dry-run`): see the PR.
