# v4/vyomi-cloud-privacy-url

Owner: Claude (chat session with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (88e084aa8) - Status: HOLD until the Claude directory reviewer approves Vyomi Cloud 4.3.1

## Purpose
The directory's check on Vyomi Cloud 4.3.1 noted `PRIVACY_URL_MISSING` (a Note, not blocking: the README line with
"privacy" satisfies it) and asks for `privacyPolicyUrl` in `.claude-plugin/plugin.json` on a plugin with a remote MCP
server. Our `check_agent_plugins.py` allow-list (only the fields we used) refused it, generalising from the `network`
refusal of 2026-11-22.

## Changes
- `plugins/vyomi-cloud/.claude-plugin/plugin.json`: `privacyPolicyUrl: https://vyomi.cloud/privacy`.
- `scripts/check_agent_plugins.py`: allow `privacyPolicyUrl` (comment records why); `network` stays refused.
- Plugins and marketplace 4.3.1 → 4.3.2 (lockstep).

## Release order
1. Wait until 4.3.1 is approved/live in the Claude directory (a new version during review would queue behind it).
2. Merge, then `git tag claude-plugins-v4.3.2 origin/v4-on-main && git push --no-verify origin claude-plugins-v4.3.2`.
3. On the plugin's page: Check for new commits; the note should be gone.

## Verification
- `check_agent_plugins.py` consistent; `claude plugin validate` passes (marketplace, both plugins).
- Directory Validate run on this branch (public appliance repo, folder `integrations/claude-plugins/plugins/vyomi-cloud`)
  before release: see the PR.
