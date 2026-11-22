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

## Also in this branch: publishing the Claude plugins (owner's request)
- New `.github/workflows/claude-plugins-sync.yml`: a `claude-plugins-v*` tag mirrors `integrations/claude-plugins` into
  the public `vyomi-cloud/claude-plugins` through the existing `scripts/sync_claude_plugins.py` (version guard, npm
  guard on the npx pin), `check_agent_plugins.py` first and `claude plugin validate` before the push. Plugin-only
  changes (the hosted `vyomi-cloud` plugin) no longer wait for a tunnel release.
- `tunnel-release.yml`'s `plugin-sync` job joins the same concurrency group (`claude-plugins-mirror`).
- Runbook: `docs/architecture/v4.0/CLAUDE-PLUGINS-SYNC-RUNBOOK.md` (kept out of the plugins folder so it is not
  mirrored publicly).
- Local dry run against the real mirror: `vyomi 4.2.1 -> 4.3.0, vyomi-cloud (new) -> 4.3.0`, `changed=true`,
  `claude plugin validate` passes for the marketplace and for `plugins/vyomi-cloud` (URL `https://vyomi.cloud/mcp`).

| Decision | Alternatives rejected | Why |
|---|---|---|
| Tag-triggered sync (`claude-plugins-v*`) | Sync on every merge to `v4-on-main`; manual push | The mirror is what users install, so publishing is a deliberate owner step, like the tunnel and MCP releases; the guards make it safe to run any time |

## Open issues
- None.
