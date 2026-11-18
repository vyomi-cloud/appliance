# v4/release-4.0.8

Release prep for v4.0.8 (GCP reference architecture, PR #659/#660), base `v4-on-main` 999940d18.

## Changes
- VERSION 4.0.8, CHANGELOG entry, `docs/releases/v4.0.8-gcp-reference.md`.
- `wasm/build_cores.py` rebuild: `wasm/core/*` mirrors synced with `core/` (new `gcp_identityplatform_core.py`); `wasm/v4/gcp` bundle rebuilt.

## Design decisions
- Same cut recipe as 4.0.4: owner pushes the tag with `--no-verify`; portal synced with `wasm/vendor_to_portal.py`, not `portal-nano-sync.yml`.

## Open issues
- No Codespace run (budget 402). Azure reference app not started.
