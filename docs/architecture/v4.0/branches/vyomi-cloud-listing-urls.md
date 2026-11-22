# v4/vyomi-cloud-listing-urls

Owner: Claude (chat session with Rohith) - Started: 2026-11-23 - Base: origin/v4-on-main (210b4c7fc) - Status: in review

## Purpose
Fix what the Claude directory's Listing step showed for `vyomi-cloud` (Validate on the mirror @ 610d501 passed, 7
checks, 0 blocking): the **Support** and **Terms of service** links both pointed at the privacy policy, because the
README had all three on one line. The directory reads these from the README for an unverified organization: setting
`supportUrl` / `termsOfServiceUrl` / `privacyPolicyUrl` / `displayName` in `.claude-plugin/plugin.json` is refused
from an unverified org (our `check_agent_plugins.py` already encodes that), so the fix is in the README.

## Changes
- `plugins/vyomi-cloud/README.md`: a `## Links` section, one link per line (privacy, terms of service, support,
  security policy).
- Request-log retention worded as "up to 30 days" (README and the Codex/agent-plugins long descriptions), matching
  the directory's "Under 30 days" data-handling answer.
- Plugins and marketplace 4.3.0 → 4.3.1 (the marketplace keeps one version for all plugins).

## Verification
`check_agent_plugins.py` consistent; `claude plugin validate` passes for the marketplace and both plugins.

## Open issues
- [ ] After merge: tag `claude-plugins-v4.3.1`, then re-validate in the directory portal.
