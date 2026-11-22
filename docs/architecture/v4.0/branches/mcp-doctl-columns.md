# v4/mcp-doctl-columns

Owner: Claude (chat session with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (bba64416a) - Status: in review

## Purpose
The hosted-MCP release's deploy job asked doctl for `--format ID,DefaultIngress,ActiveDeployment.Phase` and
`ActiveDeployment.Phase,InProgressDeployment.Phase`. doctl 2.7.0 (what `digitalocean/action-doctl@v2` installs) has no
such columns and fails with `unknown column`, so the step would fail right after `doctl apps update` started the
deploy, and the production smoke test would never run. Found while checking the real portal app with doctl 2.7.0.

## Architecture
`doctl apps update ... --wait --format ID,DefaultIngress`, then `doctl apps list-deployments <id> --format
ID,Phase,Progress,Created` (both checked against the real app). A test pins it.

## Open issues
- None.
