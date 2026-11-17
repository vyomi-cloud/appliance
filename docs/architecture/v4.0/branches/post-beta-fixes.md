# v4/post-beta-fixes

Small corrections found after the v4.0.3 AI Beta cut (base `v4-on-main` 4141d0577). PR #617, not merged.

## Changes
- `packaging/brew/vyomi-tunnel.rb`: 1.0.0 -> 1.2.5 with the sha256 recomputed from the npm tarball (the tap already served 1.2.5). Clears the `tunnel-version-sync` item of the v4 release checklist.
- Notices: HashiCorp Vault 1.15 was listed as MPL-2.0 in v4.0.3. The LICENSE at hashicorp/vault v1.15.0 and v1.15.6 is BUSL-1.1 (Additional Use Grant: production use allowed, but not a hosted or embedded competing offering). `tools/notices/notices.json` corrected, Vault LICENSE shipped as `licenses/LicenseRef-HashiCorp-Vault-BUSL-1.1.txt`, generated notices/SBOM/console JSON regenerated.

## Design decisions
- The Prompt Routers "How it works" text names Claude and Llama routers: left as is, it is AWS's own captured console copy and consoles match the real ones.

## Open issues
- The generated console notices JSON changed, so the console bundles must be rebuilt and synced to the portal for the Notices page to show the Vault correction. Ship with the next patch release.
- Replacing Vault with OpenBao (MPL-2.0) and the MinIO plan: see `BACKEND-LICENCE-PLAN.md` on `v4/post-beta-licplan`. Counsel to review our current use of Vault.
