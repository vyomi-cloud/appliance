# v4/tunnel-release-hardening

Owner: Claude session for Rohith - Started: 2026-11-19 - Base: origin/v4-on-main (3466e571e) - Status: in review (1.3.2)

## Purpose
Close three holes that bit the vyomi-tunnel 1.3.x releases: npm `next` left behind `latest`, a release whose gates passed while
the Codespace flow was broken (1.3.0), and the tunnel's two module copies drifting apart.

## Architecture
- `tunnel-release.yml`, publish job: after a final release, `npm dist-tag add vyomi-tunnel@<ver> next` when `next` is older
  (semver; a newer RC line is left alone). Uses the trusted publisher's opt-in "Allow npm dist-tag" (GitHub changelog
  2026-09-30); without it the step warns and the release stands.
- `wasm/relay/test-mcp-codespace-e2e.mjs` (in `tunnel-mcp-checks.yml`): the packaged tunnel + an MCP built from the tree against
  a fake Codespace (fake gh, a node fake ssh that answers the docker questions and carries `-W` streams to a fake simulator,
  the stub portal). `vyomi_status` hint -> run exactly that `forward` -> `vyomi_status` serving (unlocked, tier) -> `list` says
  already forwarded; core names refused. Fails on the code tagged tunnel-v1.3.0 with its exact symptom (api_target unknown, a
  placeholder forward command).
- `scripts/sync_tunnel_bin.py` (in `tunnel-mcp-checks.yml`): every `packaging/tunnel/bin/*.mjs` has an identical
  `wasm/relay/` copy apart from version stamps (only `vyomi-tunnel.mjs` is package-only); `--to-package` / `--to-relay NAME`
  copies one way and keeps the target's stamps. The trunk had drifted: the packaged `mesh-cli.mjs` had `reset`, the automatic
  VM key fetch and newer ssh help that `wasm/relay` lacked; `creds-sync.mjs` existed only in the package. Both now match.
- `test-tunnel-creds-sync.mjs` read the version from package.json (it hard-coded "1.3.0" and broke at 1.3.1).

- **1.3.2, faster Codespace status:** `vyomi-tunnel list mesh --json --quick` answers the Mesh part from the signed session alone
  (it already names the Codespace and its state): the `api` row and the forwards, no gh / ssh (7-9 s -> about 1 s). A Mesh that
  is not running is reported (`... is Shutdown. Start Mesh ...`), never woken. A `--codespace` / `VYOMI_MESH_CODESPACE` override
  takes the full path. The MCP's status probe passes `--quick` (older tunnels ignore it); `vyomi_reach` runs the full list
  (VMs, k3s, LLMs) and drops the quick note.
- **1.3.2, `vyomi-tunnel prune [--yes]`:** lists stopped Mesh Codespaces (vyomi-mesh-*, Shutdown or Failed) and deletes them only
  with --yes. Never touched: a running or starting Mesh, the session's current Mesh, the newest Mesh, non-Mesh Codespaces. Uses
  the session's GitHub token when there is one, else the user's gh login.
- **`prerelease-it.sh codespace`:** the real-Mesh check run by hand on 2026-11-19, as a stage with PASS/FAIL rows: list (api row,
  no core names), `--quick` within 5 s, `vyomi_status` hint, busy-port and core-name refusals, `forward api` on the suggested
  port, serving + unlocked + tier, `home=mesh` env, `vyomi_reach`, "already forwarded", S3 through the forward; the forward is
  stopped at the end. `all` runs it when a Mesh Codespace is Available.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Move `next` in the release, OIDC dist-tag permission | a stored npm token | no long-lived secret; the setting is one checkbox |
| E2E with the real tunnel binary + Go MCP + fakes for GitHub/Codespace only | canned list JSON (what `homes` did) | canned JSON cannot notice the tunnel changing its rows |
| Bring wasm/relay up to the packaged copy | the reverse | the packaged copy was strictly newer (nothing only in wasm/relay) |
| `--quick` trusts the session's Codespace + state | `gh codespace list` (~1 s, still a GitHub call) | the session is fetched anyway; zero extra calls; the full list stays one command away |
| `prune` keeps the newest and the current Mesh even when stopped | delete every stopped Mesh | a stopped current Mesh resumes with its state; deleting it loses work |

## Open issues
- [ ] Owner: enable "Allow npm dist-tag" on the vyomi-tunnel trusted publisher; until a release runs, move `next` by hand.

## Testing
1.3.2 additions: Go 66/66 `-race` (`TestMCPStatusQuickReachFull`: status runs one `--quick` list, reach the full one);
`test-list-json` --quick (no gh / ssh call, under 8 s; a Shutdown Mesh reported, not woken); `test-tunnel-prune` (lists without
--yes; deletes exactly the two old stopped Meshes; session token used); the e2e test passes through `--quick`. The new
`prerelease-it.sh codespace` stage ran here against a fake Codespace from an npm-packed install: 10 PASS, 2 SKIP (no aws CLI,
nothing on :9000).
E2E passes here and fails on tunnel-v1.3.0's code; copies check passes and fails on a one-line drift; relay suites pass
(creds-sync, mesh-ssh, k3s, reset-portal, transport, gate). `test-tunnel-instance-key` needs an `ssh` binary (absent in this
sandbox, present on GitHub runners). actionlint clean.
