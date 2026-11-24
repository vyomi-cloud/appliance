# VERIFY: agent distribution "Now" phase (WP6, independent verification)

- **Date:** 2026-11-22
- **Verifier:** sub-agent F. It worked from the plan (`docs/architecture/v4.0/AGENT-DISTRIBUTION-NOW.md`) and the code, not from implementer reports.
- **Appliance:** `v4/agent-plugins` @ `64bcbbb01` (= origin; first round verified `9219d3235`, round 2 re-checked `9219d3235..64bcbbb01`). Base `origin/v4-on-main` @ `0df22d4e0`; origin trunk unchanged. WP0 ended at `525dba247`.
- **Portal:** `portal/agents-docs` @ `0909286` (= origin; first round verified `eccdfe9`, round 2 re-checked `eccdfe9..0909286`). Base `origin/v4-nano-portal` @ `0a514af`; origin unchanged.
- **Environment:**
  - Machine: macOS 26 (Darwin 25.6.0) arm64.
  - Toolchain: Go 1.27.1 (`go.mod` says `go 1.26`), Node 26.13.1, Python 3.12.
  - Agents:
    - Claude Code 2.1.309 (Homebrew) and 2.1.330 (`npx -y @anthropic-ai/claude-code`).
    - Codex 0.171.0 (latest) and 0.140.0.
    - Copilot CLI 1.0.114.
  - Downloaded tools, checksums verified against the release checksum files:
    - mcp-publisher 1.8.12 (`darwin_arm64`).
    - actionlint 1.7.12 (shellcheck not installed, so actionlint ran without the shellcheck pass).
  - Docker 29.8.1, used for a Linux run (`node:22-bookworm-slim`, linux/arm64).
  - Isolation: every agent ran with a fresh `HOME` / `CODEX_HOME` / `COPILOT_HOME` / `CLAUDE_CONFIG_DIR` under `scratchpad/wp6`. Builds, packs and portal runs used `git archive` copies in scratch, so nothing was built inside either repo. Both worktrees are clean.
  - **vyomi-tunnel 1.3.3 is on this machine's PATH** (`/opt/homebrew/bin`, `~/.vyomi/bin`). With it on PATH, every `npx … vyomi-tunnel mcp` hands over to the installed 1.3.3, which serves 8 tools. The "plain" npx runs therefore used `env -i` with a PATH that holds only node, npm and npx. The sync runs used either the real PATH (installed 1.3.3) or a scratch npm prefix (installed 1.4.0).

## WP1: read-only `vyomi_agents_md`

| Check | Command | Result | Evidence |
|---|---|---|---|
| go vet | `cd cmd/vyomi && go vet ./...` | PASS | exit 0, no output |
| gofmt | `gofmt -l .` | PASS | no files listed |
| go test | `go test ./...` | PASS | `ok …/cmd/vyomi 10.502s` |
| go test -race (CI form) | `go -C cmd/vyomi test -race -count=1 ./...` | PASS | `ok …/cmd/vyomi 18.655s` |
| Guardrail gate, branch | `WS_PKG=… PY=… bash tools/guardrails/run.sh` | PASS | rc 0. All 3 `[A]` rows PASS, incl. "vyomi_agents_md only proposes AGENTS.md text: it writes nothing, names no endpoints or credentials, and refuses symlinks and bad input". The 5 other rows PASS |
| Guardrail gate, trunk base (for "other rows same as trunk") | same, on a `git archive 0df22d4e0` export | PASS | The 5 non-A rows are identical (PASS). The trunk's [A] row reads "7 read-only + 1 writer"; the branch's reads "8 + 1" |
| Stdio smoke | build `vyomi`, then `initialize` + `tools/list` + `tools/call vyomi_agents_md {path:<tmp>, clouds:[aws,gcp]}`. The temp dir holds only `CLAUDE.md` | PASS | serverInfo vyomi 4.0.10. 9 tools, with `vyomi_agents_md` `readOnlyHint:true, destructiveHint:false`. `agents_md.action=created`, `claude_md.action=prepended` with its `why`. A `stat` of the temp dir before and after is identical: nothing written |
| Result shape (plan WP1.1) | code review `cmd/vyomi/mcp_agents_md.go` | PASS | `agents_md{path,action,proposed_content,replace_block?}`, `claude_md{path,action,proposed_content?,why?}`, `section`, `start_marker`, `end_marker`, `next` |
| Section: 20 lines or fewer, no endpoints or credentials, home-agnostic | smoke output + `TestAgentsMDSectionIsSafe` | PASS | 12 lines. The only URLs are vyomi.cloud, /nano and the plugins repo. The test checks localhost/ports/keys/home paths for 5 cloud combos × 2 env names |
| `.claude/CLAUDE.md` and `CLAUDE.local.md`, root first, a test for each | `TestAgentsMDClaudeMemoryFiles` (8 subtests + 2 symlink cases) | PASS | `.claude/CLAUDE.md` gets `@../AGENTS.md` (imports resolve relative to the importing file; owner note in HUMAN-GATES.md) |
| Tests test what they claim | review `mcp_agents_md_test.go` | PASS | `propose()` snapshots the whole dir before and after every call (`sameTree`), so every test proves "never writes" |

## WP2: multi-agent package

| Check | Command | Result | Evidence |
|---|---|---|---|
| Drift guard | `python3 scripts/check_agent_plugins.py` | PASS | "agent plugin manifests consistent" |
| Mutation: one manifest version | `.codex-plugin/plugin.json` set to 4.2.1 in a scratch copy | PASS (fails as required) | rc 1: ".codex-plugin/plugin.json version 4.2.1 != marketplace 4.2.0" |
| Mutation: MCP args | `.mcp.json` args set to `vyomi-tunnel@1.3.3` | PASS (fails as required) | rc 1: "mcp.json {…} != .mcp.json {…}" |
| JSON Schemas | `check_agent_plugins.py --schemas <agent-plugins-spec@6395e89> <cursor/plugins@7a58391>` (the SHAs CI pins; fresh clones) | PASS | "…valid against the published schemas". A mutation (`displayName: 123`, unknown top-level key) fails with both schema errors. An independent jsonschema run agrees: plugin.json, mcp.json, cursor plugin and marketplace OK |
| `claude plugin validate` (plan form) | `npx -y @anthropic-ai/claude-code plugin validate integrations/claude-plugins` (2.1.330) | PASS | "✔ Validation passed" |
| Same, older Claude Code | `claude plugin validate …` (2.1.309) | PASS (warning) | "Unknown field 'network'… ignores it at load time", then "Validation passed with warnings" (see Deviations D4) |
| Install, Claude Code | fresh HOME: `plugin marketplace add <path>`, `plugin install vyomi@vyomi`, `plugin details vyomi@vyomi` (2.1.330) | PASS | `vyomi 4.2.0`, Skills (3) vyomi-mesh/vyomi-nano/vyomi-setup, MCP servers (1) vyomi |
| Install, Codex latest | fresh HOME: `codex plugin marketplace add <path>`, `codex plugin add vyomi@vyomi`, `codex mcp list` (0.171.0) | PASS | `vyomi  npx  -y vyomi-tunnel mcp … enabled`; 3 skill dirs in the plugin cache |
| Install, Codex 0.140.0 | same with `@openai/codex@0.140.0` | PASS | `vyomi … enabled`. Probe: with `.claude-plugin/plugin.json` and the root `plugin.json` removed, 0.140 still installs through `.codex-plugin/` alone; with every manifest removed it fails "missing plugin.json" |
| Install, Copilot CLI | fresh HOME: `copilot plugin marketplace add <path>`, `copilot plugin install vyomi@vyomi`, `copilot mcp list` (1.0.114) | PASS | "Installed 3 skills"; `Plugin servers: vyomi (local)` |
| Sync dry run | `python3 scripts/sync_claude_plugins.py <fresh clone of vyomi-cloud/claude-plugins @812d17a>` | PASS | "versions: vyomi 4.1.2 -> 4.2.0", `changed=true`, no drift errors |
| Leftover writer references | `git grep vyomi_write_agents_md` | PASS | Only the branch doc's design-history row |
| SKILL step 6 (plan WP2.1) | review `skills/vyomi-setup/SKILL.md` | PASS | Calls the read-only tool, shows section/action/claude_md+why, waits for an explicit yes, applies with its own edit tool, stays inside the markers, suggests a commit, falls back by hand for tunnels older than 1.4.0 |
| "Needs vyomi-tunnel 1.3.0+ (1.4.0+ for the AGENTS.md step)" everywhere | review the 7 manifests | PASS | Present in all 4 plugin manifests and all 3 marketplace entries |
| Icons | review + schema run | PASS | `logo`/`composerIcon` → `./.claude-plugin/icon.png` (exists) in the APS `extensions.com.openai.interface` and `.codex-plugin`; `logo` in `.cursor-plugin` |
| README install table per agent | review `integrations/claude-plugins/README.md` | PASS | Claude Code / Codex / Copilot CLI / Cursor rows. `copilot mcp add <name> -- <cmd>` checked against `copilot mcp add --help` |

## WP3: MCP Registry

| Check | Command | Result | Evidence |
|---|---|---|---|
| `mcp-publisher validate` | `mcp-publisher validate packaging/tunnel/server.json` (1.8.12) | PASS | "✅ server.json is valid". Negative check: a 101-character description returns 422 "expected length <= 100" (ours is 95) |
| `$schema` current | `mcp-publisher init` in scratch | PASS | `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`, same as server.json |
| `check_server_json.py` | `python3 scripts/check_server_json.py` | PASS | "io.github.vyomi-cloud/vyomi 1.4.0" |
| …fails on a mismatch | scratch copies: packages[0].version 1.4.1; mcpName changed | PASS (fails as required) | rc 1 "versions differ…"; rc 1 "server.json name … != package.json mcpName …" |
| actionlint | `actionlint .github/workflows/{tunnel-release,tunnel-npx-smoke,tunnel-mcp-checks}.yml` | PASS | rc 0 for all three (no shellcheck pass, see environment) |
| `npm pack` carries mcpName | `scripts/build_tunnel_mcp.sh`, then `npm pack` in an export | PASS | `vyomi-tunnel-1.4.0.tgz`, 19.0 MB, 19 files; `package/package.json` `mcpName= io.github.vyomi-cloud/vyomi version= 1.4.0`. Regenerated knowledge files are byte-identical to the committed ones |
| mcp-publisher pin | sha256 in `tunnel-release.yml` vs `registry_1.8.12_checksums.txt` | PASS | `ed3446e4…912dcb` = `mcp-publisher_linux_amd64.tar.gz` |
| Workflow logic | review `tunnel-release.yml` | PASS | `check_server_json.py` runs before the tag/version step. The registry step runs after npm publish (and after the Homebrew bump). Publish happens only when `CH=latest` and not DRY; dry runs and RCs run `validate`. The `/v0/servers/<name%2F…>/versions/<v>` "already published" probe returns 200 for existing servers and 404 for ours today. `server.json` `repository.id` 1242790637 = `gh api repos/vyomi-cloud/appliance .id` |

## WP4: npx snippets, sync handover, cross-OS smoke

| Check | Command | Result | Evidence |
|---|---|---|---|
| Smoke, plain, macOS arm64 (no tunnel on PATH) | `env -i PATH=<node only> node tools/npx-smoke/handshake.mjs --tarball …1.4.0.tgz --cache <fresh> --min-tools 9 --expect-tool vyomi_agents_md` | PASS | 9 tools; cold 3.28 s, warm 1.08 s |
| Smoke, plain, **Linux** (Docker `node:22-bookworm-slim`, aarch64, nothing installed) | same | PASS | "no vyomi-tunnel on PATH", 9 tools, cold 4.10 s. Linux arm64, not x64 |
| Smoke, sync (a): installed 1.3.3, npx 1.4.0 | macOS (machine PATH) and Linux (`npm i -g vyomi-tunnel@1.3.3`): `--mode sync --expect-handover 1.3.3 --call-status` | PASS | "handed over to the installed vyomi-tunnel 1.3.3 (npx copy 1.4.0)". 8 tools, `tunnel` undefined (1.3.3 bundles the older server; see D1) |
| Smoke, sync (b): installed 1.4.0, npx 1.4.1 | scratch `npm i -g --prefix`, repacked 1.4.1: `--expect-handover 1.4.0 --expect-installed 1.4.0 --expect-upgrade` | PASS | 9 tools, `tunnel={"installed":"1.4.0","latest":"1.4.1","upgrade":…}` |
| Plain mode with the tunnel on PATH | real PATH (1.3.3 installed) | PASS (fails as designed) | Fails on the unexpected handover stderr line. This shows why the CI step refuses a runner with `vyomi-tunnel` on PATH |
| Smoke on every OS | CI run 45013041659 ("Tunnel npx smoke" on `c5bcdf179`, push-triggered, not by WP6) | PASS (CI evidence) | ubuntu, macos-latest, macos-15-intel, windows-latest: plain cold/warm 9 tools (Windows cold 9.23 s), sync (a) and (b) PASS, incl. Windows `.cmd` shims. `packaging/tunnel/**` is unchanged after `c5bcdf179` |
| Launcher tests | `node --test wasm/relay/test-mcp-launch.mjs` | PASS | 14/14 (the 7 original + 7 new) |
| Tunnel node suites (CI form) | `node --test test-mcp-launch test-list-json test-tunnel-prune` + `test-mcp-codespace-e2e` | PASS | 26/26 + 1/1 (= the plan's "27 tunnel tests") |
| Relay suites for `wasm/relay` changes | mesh-link, mesh-shell, session-derived, session-v2, ssh, ssh-transport, tunnel-credentials | PASS | All "all passed" |
| `gen_mcp_matrix.py --check` | — | PASS | "mcp knowledge up to date" |
| Bin copies in sync | `python3 scripts/sync_tunnel_bin.py` | PASS | "tunnel copies in sync"; `mcp-launch.mjs` copies byte-identical |
| No `"command": "vyomi-tunnel"` in user docs outside the manifests | `git grep -E '"command": ?"vyomi-tunnel"'` (excl. docs/architecture) | PASS | One hit, `integrations/claude-plugins/README.md:55`: the allowed offline/installed fallback line (plan WP4.2); WP2-owned |
| Snippets use `npx -y vyomi-tunnel mcp` | review the README MCP section, `packaging/tunnel/README.md`, both `mesh-cli.mjs` | PASS | JSON, `claude mcp add --scope user`, `codex mcp add`, `code --add-mcp` all match plan WP4.1. `README.md` changed only in the MCP section |
| Version stamps 1.4.0 | grep `bin/*.mjs` | PASS | `vyomi-tunnel.mjs` VERSION, mesh-cli `--version` + creds fallback, credentials.mjs, creds-sync.mjs all at 1.4.0 (the RC-stamp step in tunnel-release.yml asserts these strings) |

## WP5: portal "Vyomi for AI agents"

All runs used a `git archive` copy of `portal/agents-docs`, a scratch venv (`requirements.txt` + pytest + httpx), a scratch SQLite DB, and uvicorn on free port 50627 (stopped afterwards).

| Check | Command | Result | Evidence |
|---|---|---|---|
| New tests | `pytest tests/test_agents_docs.py` | PASS | 22 passed |
| Full suite vs base | `pytest tests` on head and on a base export | PASS (no regressions) | head 514 passed / 6 failed / 7 skipped; base 492 / 6 / 7. Same 6 failures with identical assertion messages (loggedin redirect `/nano/`, 3× GitHub-app client_id, 2× `devcontainer_path`) |
| `/llms.txt` | `curl -I` | PASS | 200 `text/plain; charset=utf-8`. Has the H1, a one-paragraph blockquote and H2 Agents / Getting started / Coverage / Pricing |
| Twins | `curl -I /docs/agents.md /docs/coverage.md /pricing.md /docs.md` | PASS | 200 `text/markdown; charset=utf-8`. `/docs/agents.md` is byte-identical to `app/content/agents.md` |
| `/docs/agents.md` has the install commands | `curl … \| grep` | PASS | Claude Code / Codex / Copilot plugin commands, Cursor and VS Code links, `code --add-mcp`, `npx -y vyomi-tunnel mcp` |
| Deeplink decode | independent Python decode | PASS | Cursor `config` → exactly `{"command":"npx","args":["-y","vyomi-tunnel","mcp"]}`. VS Code `url` → `vscode:mcp/install?` + `encodeURIComponent({"name":"vyomi",…})`, equal to the docs' recipe. `vscode.dev/redirect` → 302 to that URL |
| Deeplinks vs current docs | cursor.com/docs/context/mcp/install-links; code.visualstudio.com/api/extension-guides/ai/mcp | PASS | Cursor: `cursor://anysphere.cursor-deeplink/mcp/install?name=$NAME&config=$BASE64` (config without a name wrapper). VS Code: `vscode:mcp/install?{url-encoded JSON with name}`, wrapped as `https://vscode.dev/redirect?url=<encoded>` |
| Gemini CLI snippet | geminicli.com/docs/tools/mcp-server | PASS | `mcpServers` in `~/.gemini/settings.json` (or `.gemini/settings.json`), with `command`/`args` |
| Link check, `/docs/agents` (61 hrefs) and `/llms.txt` | curl each href | PASS | Everything returns 200 except expected cases: `/admin/downloads` 302 and `/nano/` 307 (layout, login-gated); fonts preconnect origins 404 at root; GitHub new-issue 302 (login); LinkedIn 301; `https://vyomi.cloud/docs/agents` 404 (not deployed, expected); npmjs.com 403 to curl (registry.npmjs.org/vyomi-tunnel 200); `cursor://` cannot be checked |
| Alternate `text/markdown` links | `curl` the pages | PARTIAL (deviation D6) | Present on `/docs/agents`, `/docs/coverage` and `/pricing`; **missing on `/docs`** although `/docs.md` exists |
| Nav entry | review | PASS (see D7) | "AI agents" under the footer's Developers column, a Knowledge Center card, and `llms.txt` in the footer |
| Screenshots | headless Chrome 1440 px (WP6); WP5's Playwright 1440 / 390 px in `scratchpad/wp5/shots/` | PASS | The 1440 px render is clean. WP5's 390 px render fits with no overflow. WP6's own 390 px headless shot is clipped site-wide, header included: desktop Chrome's minimum window width, not a page bug |
| No merge | `git ls-remote` | PASS | `v4-nano-portal` and portal `main` unchanged |

## WP8: license and Claude directory kit

| Check | Command | Result | Evidence |
|---|---|---|---|
| LICENSE | review | PASS | MIT, "Copyright (c) 2026 Vyomi" |
| SECURITY.md | review | PASS | support@vyomi.cloud; supported: plugin 4.2.x, tunnel 1.4.x |
| `"license": "MIT"` in every manifest; check still passes | review + `check_agent_plugins.py` | PASS | All 4 plugin manifests; the script now also requires LICENSE and SECURITY.md and a single license value |
| SUBMISSION.md (Claude directory only) | review | PASS | Plugin folder, listing copy, 3 screenshots, checklist. Cursor and OpenAI marked paused |
| Directory profile, published 4.1.2 (SUBMISSION claim) | `claude plugin validate --profile directory plugins/vyomi` on a fresh public clone | PASS (claim confirmed) | "LICENSE_MISSING … Validation failed" |
| Directory profile, strict, synced 4.2.0 | `sync_claude_plugins.py --apply` into a scratch clone, then `plugin validate --strict --profile directory plugins/vyomi` (2.1.330) | PASS | "These checks found nothing to report", "Validation passed" |

## §4 test matrix

| Layer | Result | Notes |
|---|---|---|
| Go | PASS | vet, gofmt, test, test -race |
| Guardrail gate | PASS | all `[A]` PASS; other rows same as trunk |
| Manifests | PASS | drift check, claude validate, APS 1.0.0 + Cursor schemas |
| Registry | PASS | `mcp-publisher validate`, `check_server_json.py` |
| Installs | PASS | Claude Code, Codex latest, Codex 0.140.0, Copilot CLI: 3 skills + 1 `vyomi` MCP each. **Cursor team-marketplace install NOT RUN** (needs the Cursor app and a team admin; covered only by the Cursor schema) |
| npx | PASS | macOS arm64 and Linux arm64 (Docker) locally: 9 tools incl. `vyomi_agents_md`, under 5 s. macOS x64 and Windows from CI run 45013041659 |
| Sync | PASS (see D1) | launcher tests 14/14; sync (a) and (b) locally and in CI on every OS; no loops (`VYOMI_MCP_DELEGATE=0` tests) |
| Release dry run | **NOT RUN** | HUMAN GATE G2: needs a human to trigger `tunnel-release.yml` `workflow_dispatch` (plan §2/§5). actionlint and local `mcp-publisher validate` stand in |
| Portal | PASS (see D6) | build/serve, curl, deeplink decode, link check, screenshots |
| End to end (Codex conversation on a sample AWS repo with `CLAUDE.md`) | **NOT RUN** | Needs an authenticated Codex session (OpenAI login), a model turn and a human "yes"; WP6 uses fresh HOMEs with no credentials. Pieces covered: tool output (WP1 smoke), SKILL step 6 review, `next` text |

## §0 / §2 review

| Item | Result | Evidence |
|---|---|---|
| No new write tools | PASS | `TestMCPToolSurfaceIsPinned`: 8 read-only + `vyomi_write_env`. `vyomi_agents_md` has `ReadOnly:true` and is read-only on the wire |
| Guardrail [A] rows PASS | PASS | see WP1 |
| Go directive untouched | PASS | `cmd/vyomi/go.mod` / `go.sum` not in the branch diff; `go 1.26` |
| No HUMAN GATE action taken | PASS | Origin `v4-on-main` = `0df22d4e0`, `v4-nano-portal` = `0a514af`, mains untouched. No `tunnel-v1.4*` tag. npm versions end at 1.3.3. Registry has no `io.github.vyomi-cloud/vyomi` 1.4.0 (404). Last `tunnel-release.yml` runs are from 11-19/11-20 (pre-branch) |
| Versions consistent | PASS | Tunnel 1.4.0: package.json, server.json (both versions), bin stamps, SECURITY. Plugin 4.2.0: all 7 manifests / entries that carry a version |
| Snippets use `npx -y vyomi-tunnel mcp` | PASS | see WP4; plugin `mcp.json` and `.mcp.json` match |
| Outcome 5: "`vyomi_status` tells the agent when the installed tunnel is behind npm" | PARTIAL | true only for an installed tunnel ≥ 1.4.0 (D1) |

## Deviations (none fail an acceptance check)

- **D1: RESOLVED in round 2 (docs). The behaviour is unchanged by design (D4).** (Design limit vs §0.5 / §4 "upgrade hint shown").** The npx copy hands over to any installed tunnel ≥ 1.3.0, older ones included (`wasm/relay/mcp-launch.mjs`, `installedTunnel`). A user with today's 1.3.x installed therefore gets 1.3.x's server through the plugin:
  - 8 tools, no `vyomi_agents_md`;
  - no `vyomi_status.tunnel`: the 1.3.x Go server predates `cmd/vyomi/mcp_tunnel_sync.go`;
  - the upgrade hint goes to stderr only, which agents rarely show.

  This was seen locally and in CI sync (a). Mitigations exist: the SKILL's step 6 fallback and the "1.4.0+ for the AGENTS.md step" note. Docs that overstate it:
  - `packaging/tunnel/README.md:79` ("`vyomi_status` tells the agent when npm has a newer tunnel");
  - portal `app/content/agents.md:76` ("whether your vyomi-tunnel is behind npm");
  - `cmd/vyomi/README.md:43`.

  Suggest qualifying them with "(installed tunnel 1.4.0+)". The behaviour itself is decision D4, also noted in HUMAN-GATES.md.
- **D2: RESOLVED in round 2.** (CI assertion is weaker than the §4 npx row).** `.github/workflows/tunnel-npx-smoke.yml:111-120` runs the plain case with the default `--min-tools 8` and `--expect-tool vyomi_status` (`tools/npx-smoke/handshake.mjs:36`). The §4 row says "9 tools including `vyomi_agents_md`". The CI logs do show 9 tools, but a regression that drops `vyomi_agents_md` would still pass CI. Suggested fix: `--min-tools 9 --expect-tool vyomi_agents_md` on the plain steps. Low.
- **D3: open, accepted.** (WP4 matrix).** `macos-15-intel` replaces the plan's `macos-13` (retired). Agreed; logged in HUMAN-GATES.md.
- **D4: open.** (WP8 scope).** `integrations/claude-plugins/plugins/vyomi/.claude-plugin/plugin.json:21` adds `network.hosts`, which WP8 did not ask for. Claude Code 2.1.309 warns "Unknown field 'network'", and the implementer notes `--strict` fails on 2.1.309; 2.1.330 (what CI runs via npx) is clean. WP8 also added `privacyPolicyURL` / `termsOfServiceURL` to the Codex interfaces (D6-approved URLs).
- **D5: open, low.** (WP1 edge).** A `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md` that is a symlink to anything other than `AGENTS.md` makes the whole call fail (`cmd/vyomi/mcp_agents_md.go:162` → `readProjectFile`). The `AGENTS.md` proposal is then not returned either. This is tested and intended ("refuses symlinks"), but the agent gets an error rather than an AGENTS.md proposal with a note. Low.
- **D6: RESOLVED in round 2.** (WP5.4).** `/docs` has no `<link rel="alternate" type="text/markdown" href="/docs.md">` (portal `app/templates/docs.html`), although `/docs.md` exists and is listed in `/llms.txt`. Coverage, pricing and agents have it.
- **D7: copy items RESOLVED in round 2 (40 MB → 20 MB; all three Claude memory files named). Scope items (no getting-started / tunnel twins; footer placement) are unchanged and documented by WP5.** (WP5 scope, documented by WP5.)
  - No Markdown twins or `llms.txt` entries for "getting started / tunnel / install" pages: none exist in the portal. Nano's solution page and the npm page stand in.
  - "AI agents" sits in the footer's Developers column and the Knowledge Center, not a header docs nav (the header has no Developers docs group).
  - Portal `app/content/agents.md:116` says the first npx run "downloads the package (about 40 MB)". The 1.4.0 tarball is about 20 MB packed and 40 MB unpacked.
  - `agents.md:98` names only `CLAUDE.md`. The tool also handles `.claude/CLAUDE.md` and `CLAUDE.local.md`.
- **D8: open.** (Repo rules.)
  - The branch's claims row is not on the trunk (HUMAN-GATES G1, open).
  - The trunk's `SESSION-CLAIMS.md:9` still holds a stale `v4/mcp-followups-3` claim on `packaging/tunnel/**` and `integrations/claude-plugins/**`. Its content is already on the trunk (zero diff in those paths), so nothing conflicts.
  - The branch touches `wasm/relay/{mcp-launch,mesh-cli,test-mcp-launch}.mjs`. That is `wasm/**`, a shared path the PR must name for the integrator (V4-BRANCH-ARCHITECTURE "tell the owner the shared files you touched").

## Ownership (files touched after `525dba247`, appliance; whole branch, portal)

**Appliance:**

| Commit | WP | Files | Outside its Owns list? |
|---|---|---|---|
| `8c7f61f66` | WP1 | `cmd/vyomi/README.md`, `mcp_agents_md.go`, `mcp_agents_md_test.go`, `mcp_test.go`, `tools/guardrails/run.sh`; `HUMAN-GATES.md` | No (HUMAN-GATES.md is the orchestrator's) |
| `6b640092e` | WP3 | `tunnel-release.yml`, `packaging/tunnel/package.json`, `packaging/tunnel/server.json`, `scripts/check_server_json.py` | No |
| `6f8eaff37` | WP4 | `tunnel-npx-smoke.yml`, `README.md` (MCP section only), `packaging/tunnel/README.md`, both `mesh-cli.mjs`, `tools/npx-smoke/handshake.mjs` | No |
| `c5bcdf179` | none named ("chore(tunnel)") | `cmd/vyomi/mcp_agents_md.go`; `packaging/tunnel/bin/{credentials,creds-sync,vyomi-tunnel}.mjs` | **Yes.** The three `bin/*.mjs` files are in no WP's Owns list (WP4 owns only `mesh-cli`/`mcp-launch`). `mcp_agents_md.go` is WP1's file, changed outside WP1's commit. Justified by WP3 step 5 ("following the repo's tunnel release conventions": the release RC step and smoke (b) assert these stamps) |
| `5c194c174` | WP2 | `tunnel-mcp-checks.yml`, the 3 marketplaces, `README.md`, 4 plugin manifests, `vyomi-setup/SKILL.md`, `scripts/check_agent_plugins.py` | No |
| `9219d3235` | WP8 | `LICENSE`, `SECURITY.md`, `SUBMISSION.md`; 4 plugin manifests, `scripts/check_agent_plugins.py`; `HUMAN-GATES.md` | **Yes (sanctioned in part).** The manifests and the check script are WP2-owned. WP8 step 1 allows `license` there. `network.hosts`, the Codex privacy/terms URLs and the extra LICENSE/SECURITY checks go beyond it (D4) |

**Portal:** commit `eccdfe9` (WP5) touches 15 files:

- **Inside WP5's list** ("new page + `.md` twin, `llms.txt`, docs nav entry, build step for Markdown twins"):
  - `app/content/agents.md`
  - `app/docs_routes.py`
  - `app/main.py`: the `/llms.txt` and `/pricing.md` routes
  - `app/seo.py`: `build_llms`
  - `app/templates/docs_agents.html`
  - `app/templates/md/{coverage,docs,pricing}.md.j2`
  - `app/templates/_layout.html`: footer link
  - `tests/test_agents_docs.py`
  - `docs/branches/agents-docs.md`: branch doc
- **Outside the literal list:**
  - `app/loggedin_redirect.py`: exempts `/docs/agents(.md)` from the signed-in redirect. This is an auth-routing behaviour change; flagged for review.
  - `app/templates/docs.html`: Knowledge Center card.
  - `app/seo.py`: the sitemap entry and breadcrumb label.
  - `app/templates/docs_coverage.html` and `pricing.html`: alternate links, which WP5.4 requires.

All are in support of WP5.

## Round 2 re-check (2026-11-22, changes since the first run only)

Changes re-checked:
- Appliance `9219d3235..64bcbbb01`:
  - `d53452513` (sync exclude for SUBMISSION.md), reverted by `64bcbbb01` on the owner's decision;
  - `33c0476ec`, the D1/D2 fixes;
  - HUMAN-GATES.md notes.
- Portal `eccdfe9..0909286`: one commit with the D1/D6/D7 copy fixes, the `/docs` alternate link and a test param.

| Check | Command | Result | Evidence |
|---|---|---|---|
| Net change of `scripts/sync_claude_plugins.py` is zero | `git diff --stat 9219d3235..HEAD -- scripts/sync_claude_plugins.py` | PASS | Empty diff. Net branch change since round 1: 4 files only (`tunnel-npx-smoke.yml`, `HUMAN-GATES.md`, `cmd/vyomi/README.md`, `packaging/tunnel/README.md`) |
| Sync dry run vs a fresh clone | `python3 scripts/sync_claude_plugins.py <fresh clone @812d17a>` | PASS | "versions: vyomi 4.1.2 -> 4.2.0", `changed=true`; the list includes `added SUBMISSION.md` |
| SUBMISSION.md is mirrored | `--apply` into a scratch copy of the clone; `cmp`; `diff -rq -x .git` | PASS | SUBMISSION.md is identical in the mirror, and the mirror equals `integrations/claude-plugins`. LICENSE still says "Copyright (c) 2026 Vyomi" |
| Drift guard | `python3 scripts/check_agent_plugins.py` | PASS | "manifests consistent" |
| actionlint | `actionlint .github/workflows/tunnel-npx-smoke.yml` (1.7.12) | PASS | rc 0 |
| Plain npx handshake with the new CI flags, macOS arm64 | repacked from a HEAD export (`packaging/tunnel/README.md` changed; Go sources unchanged since round 1, binaries reused). `env -i PATH=<node only> node tools/npx-smoke/handshake.mjs --tarball … --cache <fresh> --min-tools 9 --expect-tool vyomi_status --expect-tool vyomi_agents_md`, cold then warm | PASS | 9 tools; cold 2.00 s; warm PASS. The packed README carries the new "Keep it at 1.4.0+" line |
| Same, Linux (Docker `node:22-bookworm-slim`, arm64) | same flags | PASS | 9 tools, cold 2.12 s |
| The new flags catch a missing tool | same flags, `--mode sync` against the installed 1.3.3 (8 tools) | PASS (fails as required) | "handshake: FAIL: 8 tools, want at least 9" |
| D1 docs | review `packaging/tunnel/README.md:78-80`, `cmd/vyomi/README.md:43`, portal `app/content/agents.md:13,76` | PASS | All now say an installed tunnel must be 1.4.0+ for `vyomi_agents_md` and for the `tunnel` upgrade field |
| Portal new tests | `pytest tests/test_agents_docs.py` | PASS | 23 passed (22 + the new `/docs` alternate param) |
| Portal full suite | `pytest tests` | PASS (no regressions) | 515 passed, 6 failed, 7 skipped. The failure list is identical to the base's |
| `/docs` alternate link (D6) | `curl /docs`, `<head>` | PASS | `<link rel="alternate" type="text/markdown" href="/docs.md" title="Markdown">`. `/docs.md` 200 `text/markdown; charset=utf-8` |
| `/docs/agents.md` text (D1, D7) | `curl /docs/agents.md` | PASS | Matches the source byte for byte. Has "keep it at 1.4.0 or later … older versions have no AGENTS.md step", "(vyomi-tunnel 1.4.0+) whether your installed tunnel is behind npm", "`CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md`" and "about 20 MB" (the packed tarball is 19.9 MB) |
| CI on the new heads | `gh run list --branch v4/agent-plugins` | PASS (CI evidence) | Guardrails on `33c0476ec`: success. Tunnel npx smoke `45016938814`: success on ubuntu, macos-latest, macos-15-intel and windows-latest; the plain steps now run with `--min-tools 9 --expect-tool vyomi_agents_md`. Tunnel + MCP checks on `33c0476ec` (`45016938792`) and `64bcbbb01` (`45016964764`): success. All push-triggered, not by WP6 |
| No HUMAN GATE action | `git ls-remote` | PASS | `v4-on-main` = `0df22d4e0`, `v4-nano-portal` = `0a514af`; only the topic branches moved |

## Verdict

**GREEN (round 2, appliance `64bcbbb01`, portal `0909286`).** No FAIL in any check run in either round.
- Resolved: D1 (docs), D2, D6, and D7's copy items.
- Still open: D3 (accepted), D4, D5 (low), D7's scope items (documented) and D8 (claims row G1; name the `wasm/relay/*` shared files in the PR).
- NOT RUN, unchanged from round 1:
  - the release dry run (HUMAN GATE G2);
  - the Codex end-to-end conversation (needs an authenticated agent session and a human yes);
  - the Cursor team-marketplace install (needs the Cursor app);
  - real clicks on the Cursor / VS Code buttons.
