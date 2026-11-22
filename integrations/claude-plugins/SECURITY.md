# Security policy

This policy covers the `vyomi` plugin in this repository (its manifests, skills
and MCP configuration) and the MCP server it starts, `vyomi-tunnel mcp`.

## Reporting a vulnerability

Email **support@vyomi.cloud** with "Security" in the subject. Please do not
open a public issue or pull request for a security problem.

Include what you can of:

- the affected component and version: plugin version (`/plugin` in Claude
  Code, or `version` in `plugin.json`) and `vyomi-tunnel --version`;
- the coding agent and its version, and your OS;
- what an attacker can do, and the steps or a minimal repository that shows it;
- whether you have told anyone else, and any date you plan to publish.

Do not send real cloud credentials or Vyomi access keys; redact them.

## What to expect

We aim to acknowledge a report within a few working days, to keep you updated
while we look into it, and to credit you when a fix ships unless you would
rather not be named. We cannot promise a fixed timeline for a fix.

## Supported versions

| Component | Supported |
|---|---|
| `vyomi` plugin 4.2.x (latest minor) | Yes |
| `vyomi-tunnel` 1.4.x | Yes |
| Older plugin or tunnel versions | No: upgrade first (`/plugin marketplace update vyomi`, `npm i -g vyomi-tunnel@latest` or `brew upgrade vyomi-tunnel`) |

Fixes ship as a new plugin or tunnel release; installed plugins update when the
version changes.
