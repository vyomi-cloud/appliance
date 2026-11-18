# v4/tunnel-release-hardening

Owner: Claude session for Rohith - Started: 2026-11-19 - Base: origin/v4-on-main (3466e571e) - Status: in review

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

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Move `next` in the release, OIDC dist-tag permission | a stored npm token | no long-lived secret; the setting is one checkbox |
| E2E with the real tunnel binary + Go MCP + fakes for GitHub/Codespace only | canned list JSON (what `homes` did) | canned JSON cannot notice the tunnel changing its rows |
| Bring wasm/relay up to the packaged copy | the reverse | the packaged copy was strictly newer (nothing only in wasm/relay) |

## Open issues
- [ ] Owner: enable "Allow npm dist-tag" on the vyomi-tunnel trusted publisher; until a release runs, move `next` by hand.

## Testing
E2E passes here and fails on tunnel-v1.3.0's code; copies check passes and fails on a one-line drift; relay suites pass
(creds-sync, mesh-ssh, k3s, reset-portal, transport, gate). `test-tunnel-instance-key` needs an `ssh` binary (absent in this
sandbox, present on GitHub runners). actionlint clean.
