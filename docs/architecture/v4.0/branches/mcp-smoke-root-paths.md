# v4/mcp-smoke-root-paths

Owner: Claude (chat session with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (64262b075) - Status: in review

## Purpose
The first production deploy (`mcp-hosted-v0.1.2`, run 45069329846, deployment d99f36d2 ACTIVE 9/9) is live and every
MCP check passed, but the smoke script also POSTed to `https://vyomi.cloud` and `https://vyomi.cloud/`. In production
those paths are the **portal** (App Platform routes only `/mcp*` to this component), which answers 405, so the job
failed. Locally and in Docker the root is the same process, where those shapes do matter (D-I6).

## Architecture
`tools/mcp-hosted-smoke.sh` decides whether the root is this server from `GET <root>/healthz` (the MCP health
answer carries `"tools":`; the portal's does not), and checks the root POST shapes only then. The `/mcp` health
check now also requires `"tools":`, so a portal answer can't pass for it.

## Verification
- Against production `https://vyomi.cloud/mcp`: all checks pass; root shapes skipped with a note.
- Against a local hosted server: all checks pass, including POST on `/` and `""`.

## Open issues
- None.
