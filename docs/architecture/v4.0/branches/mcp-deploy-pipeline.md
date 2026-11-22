# v4/mcp-deploy-pipeline

Owner: Claude (chat session with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (52bf48830) - Status: in review

## Purpose
Make the first install of the hosted MCP component part of the release pipeline (owner's request), so nobody runs
`doctl` locally. One tag push now builds, smoke-tests, pushes, adds or updates the portal app's `mcp` component,
deploys and smoke-tests production.

## Architecture
- `.github/workflows/mcp-hosted-release.yml` deploy job: `add-component.py --tag <version> --apply` replaces
  `set-image-tag.py`. It adds the component and `/mcp` rule when missing, updates them otherwise, and refuses to
  write if anything else in the portal spec would change. Pull credentials for the private image come from the
  new `GHCR_PULL_CREDENTIALS` secret; the job-summary diff drops the credentials line; the spec file is written
  under `umask 077` and deleted after the update. Runs in the `production` environment, so a required reviewer
  gates every deploy.
- Updating the `GHCR_PULL_CREDENTIALS` secret rotates the token on the next release.
- `set-image-tag.py` stays for manual rollback (no token needed: the encrypted value is kept).
- RUNBOOK §0a/§0b/§0d/§1 and plan §9 (O-G2) updated; the manual `doctl` path is kept as a fallback.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| The pipeline adds the component | A one-time manual `doctl` step | Owner's request; one path for install and release; the script already refuses unrelated changes |
| Re-send credentials from the secret each release | Send once, keep EV forever | Rotation is just updating the secret |
| Gate with the `production` environment's required reviewer | No gate | The deploy changes the live portal app's spec |

## Verification
- `deploy/mcp-hosted/test_spec_scripts.py` passes, with new workflow checks (add-component used with `--tag`,
  credentials from the secret, summary diff filtered, production environment).
- The workflow YAML parses.

## Open issues
- [ ] Owner: add the `GHCR_PULL_CREDENTIALS` secret and a required reviewer on `production`, then push `mcp-hosted-v0.1.1`.
