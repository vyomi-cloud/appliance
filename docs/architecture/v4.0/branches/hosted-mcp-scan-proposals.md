# v4/hosted-mcp-scan-proposals

Owner: claude (hosted MCP, PR 2) - Started: 2026-11-22 - Base: v4/hosted-mcp-transport (stacked, PR #708) - Status: in progress

## Purpose
PR 2 of `HOSTED-MCP-IMPLEMENTATION-PLAN.md`, stacked on PR 1 (`v4/hosted-mcp-transport`, #708). It completes the
hosted surface: the repo scan is split in two so the agent greps and the server only grades, and the two proposal
tools (`.env.vyomi` and the AGENTS.md section) return text the agent applies after the user says yes. The hosted
pin goes from 4 to 8 read-only tools, still with no writer.

Why a split: a hosted server cannot walk the user's project. `get_scan_rules` hands out the same rule table
`vyomi_scan_repo` uses; the agent runs it with its own grep; `summarize_scan_hits` turns the matches into the same
per-service report. No source line and no file content is ever sent — only a rule id, a repo-relative
`file:line`, and the captured service token (D-I1), which is what maps a hit to a service.

## Architecture
| File | Change |
|---|---|
| `cmd/vyomi/mcp_scan.go` | `scanRule` / `scanRuleTable()` (stable rule ids `<cloud>-<lang>-<n>` plus `already-wired`), `summarizeHits()`, `newScanService()` and `collectScanServices()` extracted so the local walk and the hosted summary grade a service with the same code; `summarizeWith()` so `next_steps` names each mode's own tools; the hit and report shapes lose the fields the other mode cannot fill |
| `cmd/vyomi/mcp_agents_md.go` | `proposeAgentsMDFromText()` (the splice and import logic over text instead of files), `normalizeClouds()`, `envFileName()`, `claudeMemoryFileNames()`, `agentsMDMaxTextBytes` |
| `cmd/vyomi/mcp_tools.go` | `envFileContent()` extracted from `vyomi_write_env`, so the proposal is byte for byte the file that gets written |
| `cmd/vyomi/mcp_hosted_tools.go` | `get_scan_rules`, `summarize_scan_hits`, `propose_env_file`, `propose_agents_md_section` |
| `cmd/vyomi/mcp_hosted_scan_test.go` (new) | the parity tests, the input bounds, and the `get_scan_rules` contract |
| `cmd/vyomi/testdata/scan/` (new) | the fixture repo: Python, Node.js, Java, Go and Terraform, all three clouds, plus a file that is already wired |
| `cmd/vyomi/mcp_hosted_test.go`, `tools/guardrails/run.sh`, `tools/mcp-hosted-smoke.sh` | pin and labels at 8 tools; the new tools in the shared no-outbound / no-file-access call table and in the smoke script |

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Rule ids are `<cloud>-<lang>-<n>` in knowledge order, plus `already-wired` | A hash of the pattern; an index into the list | Readable in a log and in an agent's reasoning, and stable as long as the rule order is; the knowledge is generated, so order is deterministic |
| `summarize_scan_hits` validates the token against `^[A-Za-z0-9_.\-/]{1,64}$` and refuses anything else | Accepting any string and sanitising it | D-I1 is that only an identifier is sent. Refusing makes it visible when a client tries to send a matched line |
| The `already-wired` rule takes `{rule, file, line}` and **no** token | Reusing the token field for the matched text | The local scan clips the line into `already_wired[].text`; the hosted report must not carry it, so the field is simply never filled (D-I1) |
| `propose_env_file` keeps the caller's cloud order, de-duplicated | Canonical `aws, gcp, azure` order | `vyomi_write_env` writes them in the order given; the plan requires the proposal to equal the file, so the order has to match too. `propose_agents_md_section` canonicalises, because the local tool does |
| The Nano cloud relay is a `nano_access: tunnel \| relay` switch, and the relay endpoint renders as the literal `${VYOMI_RELAY_URL}` | An earlier `relay_url` input that the server echoed but never fetched | That URL is a bearer capability for the user's tab: whoever holds it can drive their simulator. A hosted server must not be able to receive one at all — not by a prompt injection, not in a log, not in a crash dump. A placeholder the agent substitutes locally gives the same answer and the server never learns the URL |
| `claude_md_file` is an enum of the three Claude memory files | Taking a path; always assuming `CLAUDE.md` | The import line is relative to the importing file (`.claude/CLAUDE.md` needs `@../AGENTS.md`), so the server has to know which one it is; a fixed enum is not a path and nothing is opened |
| Parity is asserted on the report with the mode-specific fields stripped | Comparing raw JSON | `root` / `files_scanned` (local) and `hits_received` (hosted), the examples' source text, and the `next_steps` tool names cannot match by design; everything else must, per service |

## Open issues
- [ ] `HOSTED-MCP-DESIGN.md` §4 and §8 could not be updated here: the file lands with PR #705, which is still open,
  so it does not exist on this base. The exact edit is below; it belongs on that branch or on a follow-up once it
  merges (owner: Rohith)
- [ ] `cmd/vyomi/{mcp_scan.go,mcp_tools.go,mcp_agents_md.go,mcp_test.go}` and `tools/guardrails/run.sh` are also
  claimed by `v4/agent-plugins` (owner: Rohith to sequence the merges)

### The D-I1 edit for HOSTED-MCP-DESIGN.md, ready to apply

§4, the `vyomi_scan_repo` row of the split table — replace the "What the server receives" cell:

> ~~rule ids with `file:line`; **no file contents, no matched text**~~
> rule ids with `file:line` and the **captured service token** (regex group 1, e.g. `s3`); **no file contents and
> no matched text**. The token is what maps a hit to a service (D-I1); it is validated against
> `^[A-Za-z0-9_.\-/]{1,64}$`, so only an identifier is accepted. The "already wired" rule sends `file:line`
> alone — the local scan's clipped line text is never sent.

§4, the two-call scan description — replace step 2:

> The agent runs them locally (Grep, which every agent has) and calls `summarize_scan_hits(home, hits: [{rule,
> file, line, token}])`, at most 2,000 hits per call. The report maps each token to a service through the same
> alias table the local scan uses, reports unknown tokens as unrecognized, adds coverage and warnings for the
> home, and returns the same shape as today's `vyomi_scan_repo`.

§8, the data-handling table — replace the scan row:

> | Scan hits: rule ids, file paths, line numbers, captured service tokens | `summarize_scan_hits` | Not stored,
> and not logged. The token is an identifier such as `s3` or `storage-blob`, never source text; "already wired"
> hits carry no text at all |

## Testing
Run on macOS (darwin/arm64), 2026-11-22, Go 1.27.1.

| What | Command | Result |
|---|---|---|
| Go suite | `go -C cmd/vyomi test -count=1 ./...` | `ok` (no environment overrides: the two home=auto tests are hermetic since PR 1) |
| Guardrail suite | `WS_PKG=... PY=... bash tools/guardrails/run.sh` | all seven hosted rows PASS; every pre-existing row PASS except the Mesh boot-script row (macOS BSD sed, see PR 1's branch doc) |
| Hosted server | `/tmp/vyomi mcp --hosted --listen :8080` | 8 read-only tools, knowledge v4.0.10 |
| Smoke | `tools/mcp-hosted-smoke.sh http://localhost:8080/mcp` | 26/26 PASS |

`TestHostedNanoRelayIsAPlaceholderNeverAnInput` covers the relay rule: no schema takes a URL (or a token, key or
secret) under any name, a URL smuggled through `host` is refused, `nano_access=relay` renders the placeholder in
the endpoint, the env text, the snippet and the proposed file, the answer carries the substitution note, and the
answer never contains a concrete relay URL. The default stays the local tunnel, which is the common case.

Parity evidence: `TestHostedScanParityWithLocalScan` runs `get_scan_rules` + a Go-regexp grep of
`cmd/vyomi/testdata/scan/` + `summarize_scan_hits` against the local `scanRepo` for `home=nano|mesh|offline` and
compares the whole report per service; the fixture covers all three clouds, all five rule languages and an
already-wired file. `TestHostedProposeEnvFileMatchesWriteEnv` compares the proposal with what `vyomi_write_env`
writes and with the bytes on disk, for four cloud combinations times three homes.
`TestHostedProposeAgentsMDMatchesLocal` replays every `mcp_agents_md_test.go` scenario (created, appended,
updated, unchanged, and each Claude memory file case) through both tools. Symlink cases stay local-only: the
hosted tool is given text, so there is no link to follow.

Not run here: Docker, the real Docker stack, Nano on :8099. The container and real-client checks are PR 3 and PR 4.
