# v4/mcp-claims-cleanup

Owner: Claude session for Rohith - Started: 2026-11-19 - Base: origin/v4-on-main - Status: done (one line)

## Purpose
Release the `mcp-codespace-followups` claim in `SESSION-CLAIMS.md`: that branch merged as #666 (vyomi-tunnel 1.3.1), and its
row came onto the trunk with the merge. Done as a PR because sessions never push the trunk.

## Open issues
- none

## Testing
Docs only; the claims table keeps its other rows unchanged (`git diff` shows one removed line).
