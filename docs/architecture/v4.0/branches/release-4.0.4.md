# v4/release-4.0.4

Integration branch for the v4.0.4 fix release (base `v4-on-main` 4141d0577).

## Changes
- Merges `v4/post-beta-fixes`, `post-beta-hookverify`, `post-beta-licplan`, `post-beta-capfix`, `post-beta-meshexample` (all clean, no conflicts).
- VERSION 4.0.4, CHANGELOG entry, `docs/releases/v4.0.4-fixes.md`.
- Consoles rebuilt (`wasm/v4/*`) so the Vault BUSL-1.1 correction shows on the Notices page; AI claims register regenerated (only the results-commit stamp changed).

## Design decisions
- The Mesh compose adds dummy `AWS_*` defaults (`test`/`test`/`us-east-1`, overridable). The simulator accepts any credentials; this only gives in-simulator Lambda boto3 ambient credentials, as real Lambda has.
- The `ghcr.io/ggml-org/llama.cpp:server` tag is NOT pinned in this release (needs a tested pin).

## Open issues
- No Codespace measurement (budget 402). Tag push is owner only (`--no-verify`).
