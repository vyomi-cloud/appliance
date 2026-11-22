# v4/validate-results

Owner: Rohith (prepared by Claude, 2026-11-22) - Started: 2026-11-22 - Base: origin/v4-on-main (37c5661e6) - Status: in review (docs only)

## Purpose
Record the Claude directory's Validate result for plugin 4.2.1 (mirror `vyomi-cloud/claude-plugins` @ `d9fb835`) in the
submission kit and the human gates. Docs only.

## Architecture
| Change | Where |
|---|---|
| Status, a "Latest Validate" table, per-finding results, new warning (f), mirror and fresh-install rows, screenshot 1 note | `integrations/claude-plugins/SUBMISSION.md` |
| G6 and G9 statuses; a review note with the Validate summary | `HUMAN-GATES.md` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Keep the 4.2.0 findings table and mark each one's result on 4.2.1 | Replace it | The history shows what each fix cleared |

## Open issues
- [ ] G9 Verified-organization status (owner: Rohith)
- [ ] (f) lockfile warning: consider `npm-shrinkwrap.json` in the next tunnel release (owner: CLI session)
- [ ] `SUBMISSION.md` is mirrored to the public repo on the next sync; no plugin version bump is needed for a root file (owner: release)

## Testing
`python3 scripts/check_agent_plugins.py`: pass. The Validate result was read from the form on 2026-11-22; nothing was submitted.
