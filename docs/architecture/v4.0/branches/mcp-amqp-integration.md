# v4/mcp-v4-merge — integrate the MCP (#609) and Service Bus AMQP (#552) work into v4

Base: `origin/v4-on-main`. Integrates two long-open PRs into trunk so they ship in v4.0.x.

## What it contains
- **MCP v4** (`v4/mcp-v4-knowledge`, 28 commits): `vyomi-tunnel mcp` (Nano + mesh homes), Claude plugin 4.1.0, MCP knowledge generator,
  gated tunnel release workflows. Tunnel version becomes **1.3.0** (trunk was 1.2.5; npm `latest` is 1.2.5).
- **Service Bus AMQP** (`fix/servicebus-amqp-metadata-and-ports`, PR #552, was based on v3 main): stale "AMQP unsupported" metadata corrected,
  AMQP ports 5672/5671 published on the Docker/Homebrew tier.

## Conflict resolution
- Five tunnel files conflicted on the version string only (1.2.5 vs 1.3.0) → 1.3.0; `test-tunnel-creds-sync.mjs` updated to match.
- `scripts/mcp_wiring.json` was restructured per-home by the MCP branch → took the MCP structure and re-applied the AMQP wording by text
  (one Service Bus note + one pitfall). `mcp_matrix.json`, `mcp_caps.json.gz`, `mcp_docs.json.gz` regenerated (`gen_mcp_matrix.py --check` clean).
- Go golden `cmd/vyomi/testdata/mcp_env_azure_offline_42d870e.golden.json` updated for the AMQP wording (intentional change).

## Verified
- `go test ./cmd/vyomi/...` ok; tunnel tests (mcp-launch, list-json, mesh-ssh-transport, tunnel-credentials, creds-sync) pass with `ws` installed.
- Service Bus conformance (core, amqp transport/lifecycle/siftly gate) and `test_azure_offline_wiring` pass.

## Not done here
- `packaging/brew/vyomi-tunnel.rb` still pins 1.2.5 (updated by the tunnel release against the published tarball).
- Publishing vyomi-tunnel 1.3.0 to npm (gated tunnel release) — owner action.
