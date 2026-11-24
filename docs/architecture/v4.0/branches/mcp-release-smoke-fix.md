# v4/mcp-release-smoke-fix

Owner: Claude (chat session with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (034909e97) - Status: in review

## Purpose
Fixes from the first hosted-MCP release run (tag `mcp-hosted-v0.1.0`, run 45064058818), plus the owner's decision to
keep the GHCR image private.

## Architecture
- `tools/mcp-hosted-smoke.sh`: the ~300 KB oversize body is sent from a file (`--data-binary @file`). As one
  command-line argument it exceeds Linux's per-argument limit (MAX_ARG_STRLEN, 128 KiB), so curl never ran on the
  Ubuntu runner ("Argument list too long"); macOS allows it, which is why it passed locally. Every server check passed.
- `.github/workflows/mcp-hosted-release.yml`: build with `load: true`, smoke the local image, then `docker push`.
  Before, the image was pushed first and smoked after, so 0.1.0 reached GHCR even though the job failed.
- Private image (decided 2026-11-23): `add-component.py` adds `image.registry_credentials` from
  `GHCR_PULL_CREDENTIALS` ("user:token", `read:packages`), never prints it, writes the spec mode 600, keeps an
  existing `EV[...]` value when the env is unset (re-runs stay no-ops), rotates when it is set, and refuses to add
  the component without credentials unless `--public`. `set-image-tag.py` already changes only the tag, so releases
  keep the encrypted credentials. Nothing secret is committed.
- RUNBOOK §0a/§0b/§4, `portal-app-component.yaml` comment, plan §3/§9 (O-G1b), design §5 updated.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Private GHCR + encrypted pull token in the app spec | Public package | Owner's choice; App Platform supports GHCR credentials |
| Credentials only from an env var at apply time | A secret in the repo or in the component file | Never commit a token |
| Push after smoke | Push then smoke | A failing build must not publish a version tag |

## Verification
- `deploy/mcp-hosted/test_spec_scripts.py`: 54 checks pass (new: refuse without credentials; token never printed;
  mode 600; EV kept; rotation; malformed refused; --public; set-image-tag keeps credentials).
- Smoke script against a local hosted server: all checks pass, including `oversize body -> 413`.

## Open issues
- [ ] The 0.1.0 image already in GHCR passed every server check; reuse it, or tag 0.1.1 after this merges (owner).
- [ ] Track the pull token's expiry (owner).
