# v4/mcp-followups-3

Owner: claude (with Rohith) - Started: 2026-11-19 - Base: origin/v4-on-main (a40ad02d3) - Status: ready for review

## Purpose
Closes the remaining MCP / plugin items from the readiness sheet: pre-release checks for the Nano cloud relay, the
Mesh TLS API and Max extras (VMs, k3s), an agent eval for a Free-tier user asking about a Pro feature, setup docs for
Cursor / VS Code / Codex, the plugin icon, and the wrong AWS CLI command names in the Nano console's SDK & CLI tab.
Ships as vyomi-tunnel 1.3.3 and plugin 4.1.2.

## Architecture
- `tools/mcp-eval/prerelease-it.sh`
  - new `relay` stage (also in `all`): `IT_RELAY_URL` = the relay URL in the Nano footer. Checks the relay answers,
    `vyomi_status` selects `nano-cloud`, `vyomi_env` and the S3 CLI snippet point at the relay (and use `s3api`),
    and an `aws s3 mb/ls/rb` round trip through it when the AWS CLI is installed.
  - `codespace` stage extras: `forward api <free>:9443` (port from the MCP's `forward_tls_command`) and an https
    `/mesh/status`; `ssh <vm>.vyomi true` for the first Docker instance (SKIP until `vyomi-tunnel config` ran);
    `forward <k3s> <port>:6443` and `GET /version` (200/401/403 = the API answers). Each SKIPs when the Mesh has none.
  - `agent` stage A07: runs only when the appliance on :9000 reports `license.active_tier == "free"`; asks about
    DynamoDB exports to S3 (a Pro capability) and passes when the agent looked it up (`vyomi_capability` or
    `vyomi_services`), says "pro", and wrote no `.env.vyomi`.
- `scripts/gen_nano_docs.py`: the AWS CLI word is botocore's service name (`secretsmanager`, `logs`, `elbv2`,
  `events`, `stepfunctions`), and `s3api` for low-level S3, not the serviceId slug. 16 entries in 13 `wasm/docs/aws`
  files regenerated.
- `scripts/gen_mcp_matrix.py --check` fails when any `wasm/docs/aws` api entry has a wrong CLI word (guard).
- `packaging/tunnel/README.md`: Cursor, VS Code (`.vscode/mcp.json`, `code --add-mcp`, portable `.mcp.json`) and
  Codex (`codex mcp add`, `config.toml`) setup for `vyomi-tunnel mcp`, plus the PATH note for GUI-launched editors.
- `integrations/claude-plugins/plugins/vyomi/.claude-plugin/icon.png`: 1024x1024 from `wasm/assets/brand/vyomi-icon.svg`.
- Versions: tunnel 1.3.2 -> 1.3.3 (6 stamps), plugin 4.1.1 -> 4.1.2 (the marketplace guard refuses new content
  under a published version).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Fix the CLI word in the generator and add a `--check` guard | Hand-edit the JSON | The next regeneration would bring the wrong words back |
| A07 gated on the live `active_tier` | Fake a Free license | The eval must reflect what a real Free appliance tells the agent |
| A07 env switches off only Nano and the Codespace | Reuse `$off` | `$off` also hides :9000, so A07 would never see the appliance |
| VM / k3s / TLS checks SKIP when absent | Require a Max Mesh | Most test Meshes are Pro; the stage must still pass there |
| Editor docs in the tunnel README | A separate page | The README is what npm and the plugin link to |

## Open issues
- [ ] Run on the Mac: `prerelease-it.sh relay` (with `IT_RELAY_URL`), `codespace` on a Mesh, `agent` with a Free appliance on :9000 (owner: Rohith)
- [ ] Product decisions not built here: Nano space vs mesh space, Nano RDS state, Node for browser-only Nano users, live capabilities from the simulator (owner: Rohith)

## Testing
- Sandbox (Linux): `relay` stage against a fake relay on a non-loopback address: 4 PASS, 1 SKIP (no AWS CLI).
- A07 gate against a fake :9000 appliance: true for `free`, false for `pro`.
- `node --test` test-mcp-launch, test-list-json, test-tunnel-prune, test-mcp-codespace-e2e: all pass (CI setup: `WS_PKG`).
- `gen_mcp_matrix.py --check` passes, and fails when an `s3` CLI word is reintroduced. `sync_tunnel_bin.py` in sync.
- `claude plugin validate` passes (no ICON_MISSING); the marketplace sync guard accepts 4.1.1 -> 4.1.2.
- `bash -n` and shellcheck (warning level) clean.
- NOT run: the new codespace extras and A07 against a real Mesh / Free appliance / claude CLI (needs the Mac).
