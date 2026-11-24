# v4/mcp-guardrails-gate

Owner: Rohith (prepared by Claude, 2026-11-21) - Base: origin/v4-on-main (73e201d, 2026-11-21) - Status: ready for review

## Purpose
The "easy" part of the guardrails design (`../MCP-GUARDRAILS-INCIDENT-DESIGN.md`, revision 2): a hard release gate with one check
per premise item, and two server-side fixes found while writing it.

## What is in it
| Change | Where |
|---|---|
| Design rewritten: enforcement for every caller, not "at the MCP boundary"; threat A/B split; findings F1-F4; Nano section | `docs/architecture/v4.0/MCP-GUARDRAILS-INCIDENT-DESIGN.md` |
| F1 fix: admin-key checks apply on a Mesh (`VYOMI_ROLE=mesh`) as well as in appliance mode | `core/admin_auth.py` (`admin_checks_apply`) |
| F1 fix: `/api/runtime/budget/{disable,enable}` refused on a Mesh even with the key | `routes/licensing.py` |
| Server-side checks for items 5 and 7 (13 tests; 3 fail on the base, all pass here) | `tests/test_mcp_guardrails_server.py` |
| Suite runner: PASS / FAIL / GAP per item, job summary. Go checks require each named test to report PASS (`go test -run` exits 0 when nothing matches) | `tools/guardrails/run.sh` |
| Workflow + hard gate in `release.yml`, `release-candidate.yml`, `docker-publish.yml`, `tunnel-release.yml`; `release-gate` issue on red | `.github/workflows/` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Enforce admin checks by role (`VYOMI_ROLE=mesh`) | Switch the Mesh to `CLOUDLEARN_DISTRIBUTION_MODE=appliance` | Appliance mode also changes CORS, the readiness gate and the compute runtime (LXD), which would break the Mesh's docker backend |
| Gate the build/publish jobs with `needs:` | A pre-tag check | A tag push cannot be blocked; the artifacts can |
| Report missing coverage as GAP | Leave unbuilt items out | A green gate must not imply items 2, 3, 4 and 6 are covered |
| Notify through a labelled issue | Slack / email now | No channel exists in the repo yet; issues need no secret |
| Endurance cycles stay out of the hard gate | Block on them | Long, flaky runs would push people to skip the gate |

## Open issues
- [ ] F2: the Codespace holds the session HMAC key, so a Pro user can mint a Max token for their own Mesh. Ed25519 needs a portal change.
- [ ] F3: CORS `*` + ambient token on a Mesh `/api/*`. Check Nano-on-Mesh before narrowing the origins.
- [ ] F4: wire `vyomi-lockdown` into boot (real-Codespace test).
- [ ] Check that no console view calls `/api/shared/*`, `/api/tenants`, `/api/security/audit-*` or `/api/runtime/budget/*` against a Mesh (they now answer 403 there without the key).
- [ ] `core/*.py` is a shared path: add a claims row before pushing (CLAUDE.md rule 2/5).

## Testing
- `tools/guardrails/run.sh`: green on 73e201d with this branch (5 PASS incl. the #676 tool-surface tests, 4 GAP); red on the base (item 5/7 check fails); the Go helper fails when a named test is missing.
- `tests/test_mcp_guardrails_server.py`: 13 passed; on the base, the 3 Mesh tests fail.
- `test-mesh-gate.mjs`, `test-mesh-ssh-transport.mjs`, `go test -run TestMCPWriteEnv`: pass (Go run with a local 1.24 toolchain; CI uses 1.26).
- actionlint: clean on all five workflows.
- Not run: a real Mesh with the patched image (see the Mac checklist in the PR text).
