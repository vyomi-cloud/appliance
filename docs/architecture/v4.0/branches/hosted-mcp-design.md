# v4/hosted-mcp-design

Owner: Rohith (prepared by Claude, 2026-11-22) - Started: 2026-11-22 - Base: origin/v4-on-main (5d042d5f6) - Status: in review (docs only)

## Purpose
A design for a hosted (remote) Vyomi MCP server at `https://mcp.vyomi.cloud/mcp`. The Claude directory accepts a remote
server from an unverified organization, which would clear its last block on the `vyomi` plugin (G9) and bring Vyomi to
claude.ai and Cowork. Docs only; nothing is built here. The design: `../HOSTED-MCP-DESIGN.md`.

## Architecture
| Change | Where |
|---|---|
| Design doc: tool split (the server supplies knowledge and proposals, the agent does the local steps), Streamable HTTP, hosting options, auth phases, packaging as `plugins/vyomi-cloud`, data handling, policy checklist, plan, decisions | `docs/architecture/v4.0/HOSTED-MCP-DESIGN.md` |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Proposed, not decided: see the doc's §11 (D-H1 to D-H6) | — | The owner decides; the doc recommends |

## Open issues
- [ ] Owner decisions D-H1 to D-H6 (owner: Rohith)
- [ ] Anthropic's answer on G9, which changes D-H1 (owner: Rohith)

## Testing
Docs only. The facts in §3 were checked against `v4-on-main` @ `5d042d5f6` and portal `v4-nano-portal` on 2026-11-22.
