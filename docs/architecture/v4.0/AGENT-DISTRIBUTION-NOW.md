# Agent distribution, "Now" phase: execution plan

Status: ready to run · Written 2026-11-22 against `vyomi-cloud/appliance` `v4-on-main` @ `0df22d4e` · Owner: Rohith
Executor: Claude Code CLI in auto mode, one orchestrator session dispatching sub-agents.

**Progress (2026-11-22): WP0 is done.**
- Worktree `~/Documents/appliance-agent-plugins` on `v4/agent-plugins`, from `origin/v4-on-main` @ `0df22d4e`.
- Patches 0001–0005 applied as commits.
- Docs committed: this plan, `AGENT-DISTRIBUTION-PRODUCT-GAPS.md`, `AGENT-DISTRIBUTION-PLUGIN-AND-AGENTS-MD.md`, `branches/agent-plugins.md`.
- Verified on the Mac: Go suite, full guardrail gate, 27/27 tunnel tests, drift check, `claude plugin validate`.
- Still open from WP0: the claims row on the trunk (HUMAN GATE).
- Start at WP1 (verify + tighten) and run WP1–WP8 from here; do not re-apply the patches.

**Progress (2026-11-22, later): WP1–WP8 done and released; the Claude directory submission is blocked.**
- PR #702 merged (`6d50c4606`); WP6 `VERIFY.md` GREEN; `tunnel-v1.4.0` released: npm 1.4.0, MCP Registry `io.github.vyomi-cloud/vyomi`, Homebrew, plugin 4.2.0 mirrored to `vyomi-cloud/claude-plugins`.
- Portal PR #62 (`/docs/agents`, `/llms.txt`) is open, not merged (HUMAN-GATES G5, G10).
- The directory's Validate refused 4.2.0: a local MCP server and a non-allowlisted manifest field (`network`) are accepted only from Verified organizations, plus an icon warning. Anthropic's pre-submission checklist adds an unpinned npx launcher and a missing plugin-folder README.
- `v4/directory-fixes` (plugin 4.2.1) fixes the four this repo controls: `network` removed, `npx -y vyomi-tunnel@1.4.0 mcp` pinned and kept equal to `packaging/tunnel/package.json` by `check_agent_plugins.py`, a disclosure README in `plugins/vyomi/`, and a re-encoded icon. The sync refuses to mirror a pin npm does not serve. Verified-organization status stays with the owner (G9). Status per finding: `integrations/claude-plugins/SUBMISSION.md` §0.

## 0. Outcome

When this plan is done:

1. The `vyomi` plugin 4.2.0 installs with one command in Claude Code, Codex, GitHub Copilot CLI and Cursor (team marketplace), with the MCP server and all three skills.
2. A read-only MCP tool `vyomi_agents_md` proposes a Vyomi section for the user's `AGENTS.md`; the agent applies it with its own edit tool after the user says yes. The tool surface becomes 8 read-only + 1 writer, and the guardrail gate stays green.
3. `vyomi-tunnel` 1.4.0 is listed in the official MCP Registry as `io.github.vyomi-cloud/vyomi`, published from the release workflow.
4. vyomi.cloud has a "Vyomi for AI agents" page with install buttons per agent, plus `/llms.txt` and Markdown copies of the key pages.
5. The plugin and every MCP config snippet use `npx -y vyomi-tunnel mcp`, so no global install is needed for the MCP. When `vyomi-tunnel` is installed, `npx -y vyomi-tunnel mcp` hands over to it, so the two commands always run the same server; `vyomi_status` tells the agent when the installed tunnel is behind npm.
6. The repo carries an MIT `LICENSE` and a `SECURITY.md`, and the Claude directory submission is prepared; you submit it. **Cursor Marketplace and OpenAI directory submissions are paused** (see §7).

Out of scope here: `vyomi-tunnel init`, cloud-agent recipes, inspection tools, a hosted MCP. Those are the "Next" and "Later" phases.

## 1. Facts verified on 2026-11-22 (do not re-derive)

- `npx -y vyomi-tunnel@1.3.3 mcp` starts the MCP server on Linux with no global install: `serverInfo` vyomi 4.0.10, 8 tools listed. Cold start 1.5 s, warm 0.6 s, offline from the npx cache works (on a fast link; the package is ~40 MB unpacked because every platform binary is bundled). macOS and Windows are not tested yet (WP4 adds CI for them).
- Sync handover (patch 0005), tested on Linux. A packed tunnel run through `npx` handed over to an installed `vyomi-tunnel` 1.3.3, which served 8 tools. With nothing installed, the npx copy ran itself. The launcher has 7 new tests, and all 27 tunnel node tests pass.
- Tool-surface guardrail: `cmd/vyomi/mcp_guardrails_test.go` pins the tools, and `tools/guardrails/run.sh` is a hard dependency of `release.yml`, `release-candidate.yml`, `docker-publish.yml` and `tunnel-release.yml`. A writer tool for AGENTS.md would fail it; the read-only design passes.
- Claude Code (2.1.277+) reads `AGENTS.md` only when there is no `CLAUDE.md`. A `CLAUDE.md` hides `AGENTS.md` unless it contains `@AGENTS.md`.
- The website is in the separate repo `vyomi-cloud/portal` (Nano under `app/nano`). Every merge to portal `main` triggers a paid DigitalOcean deploy.
- npm publishing in `tunnel-release.yml` already uses trusted publishing (`id-token: write`). The MCP Registry can use `mcp-publisher login github-oidc` from the same job.
- Registry `server.json` for an npm package with an argument: `packages[0].registryType: "npm"`, `identifier: "vyomi-tunnel"`, `transport: {"type":"stdio"}`, `packageArguments: [{"type":"positional","value":"mcp"}]`, `runtimeHint: "npx"`. `package.json` needs a matching `"mcpName"`.
- Claude directory: submitted at claude.ai/directory/manage (paid Claude plan, GitHub connected on claude.ai), one submission per plugin folder.
- Cursor Marketplace: form at cursor.com/marketplace/publish. Open source only, manual review, no status page; replies come by email.
- OpenAI (Codex/ChatGPT) directory: a ZIP upload at platform.openai.com/plugins. MCP servers must be public HTTPS; a local MCP goes through the "Skills only" / desktop-only path. Requires: owner role or Apps Management Write, developer verification, privacy policy, terms, website and support URLs (HTTPS), logo and composer icon, 5 positive + 3 negative test cases, a video walkthrough URL and release notes. No hooks.

## 2. Ground rules for the orchestrator (auto mode)

- Follow the repo's `CLAUDE.md` and `docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md`. Start the session with `scripts/v4-session-start.sh agent-plugins`; never create branches by hand.
- One appliance branch: `v4/agent-plugins`, one PR into `v4-on-main`. One portal branch: `portal/agents-docs`, created by running `scripts/v4-session-start.sh agents-docs --portal` inside `~/projects/portal` (worktree `~/projects/portal-agents-docs`, base `origin/v4-nano-portal`), one PR into `v4-nano-portal`.
- Sub-agents own disjoint files (table in §3). The orchestrator commits, with explicit paths only, never `git add -A`. Each sub-agent returns a short report: files changed, commands run, results.
- **HUMAN GATE — stop and list it in `HUMAN-GATES.md` at the worktree root; never do it:**
  - merge any PR, push to `main` / `v4-on-main`, push or create tags;
  - `npm publish`, `mcp-publisher publish`, run `tunnel-release.yml` other than as a dry run;
  - submit to any directory, or change GitHub org settings or secrets;
  - add or change legal pages (privacy, terms). Exception: WP8 adds the MIT LICENSE decided in D5;
  - anything that needs a decision from §6 not yet made.
- Do not weaken the guardrail: no new write tools. `run.sh` Threat A rows must PASS.
- Go 1.26 is required (`cmd/vyomi/go.mod`); do not edit the `go` directive.
- Commit trailers: as the repo's attribution rule says.

## 3. Work packages

| WP | Repo | Runs | Owns (only these files) | Depends on |
|---|---|---|---|---|
| WP0 Session setup | appliance | orchestrator | claims row, `docs/architecture/v4.0/branches/agent-plugins.md` | — |
| WP1 Read-only AGENTS.md tool + status sync field | appliance | sub-agent A | `cmd/vyomi/mcp_agents_md*.go`, `cmd/vyomi/mcp_tunnel_sync*.go`, `mcp.go`, `mcp_tools.go`, `mcp_test.go`, `mcp_guardrails_test.go`, `cmd/vyomi/README.md`, `tools/guardrails/run.sh`, `MCP-GUARDRAILS-INCIDENT-DESIGN.md` | WP0 |
| WP2 Multi-agent package | appliance | sub-agent B | `integrations/claude-plugins/**`, `scripts/check_agent_plugins.py`, `scripts/sync_claude_plugins.py`, `.github/workflows/tunnel-mcp-checks.yml` | WP1 (tool name) |
| WP3 MCP Registry | appliance | sub-agent C | `packaging/tunnel/package.json`, `packaging/tunnel/server.json` (new), `scripts/check_server_json.py` (new), `.github/workflows/tunnel-release.yml` | WP0 |
| WP4 npx snippets, sync handover, smoke | appliance | sub-agent D | `packaging/tunnel/README.md`, `packaging/tunnel/bin/{mesh-cli,mcp-launch}.mjs`, `wasm/relay/{mesh-cli,mcp-launch,test-mcp-launch}.mjs`, `README.md` (MCP section only), `.github/workflows/tunnel-npx-smoke.yml` (new), `tools/npx-smoke/**` (new) | WP0 |
| WP5 Agents docs page | portal | sub-agent E | new page + its `.md` twin, `llms.txt`, docs nav entry, build step for Markdown twins | install commands from WP2/WP4 |
| WP6 Independent verification | both | fresh sub-agent F (no prior context) | none (read-only, writes `VERIFY.md`) | WP1–WP5 |
| WP7 PRs | both | orchestrator | PR bodies | WP6 green |
| WP8 License + Claude directory kit | appliance | sub-agent G | `integrations/claude-plugins/{LICENSE,SECURITY.md,SUBMISSION.md}` (new) | WP2 |

Order: WP0 → {WP1, WP3, WP4, WP5 draft} in parallel → WP2 → WP5 final → WP8 → WP6 → WP7.

### WP0 — Session setup (orchestrator)

1. `scripts/v4-session-start.sh agent-plugins`. Confirm the branch is based on fresh `origin/v4-on-main`.
2. Apply the prepared patches (built and tested on `0df22d4e`; all five apply cleanly there): `git am -3 patches/000*.patch`.
   - 0001: read-only `vyomi_agents_md` + guardrail pin 8 + 1.
   - 0002: multi-agent package.
   - 0003: manifest drift check.
   - 0004: plugin MCP via `npx -y vyomi-tunnel mcp`.
   - 0005: npx → installed-tunnel handover + `vyomi_status.tunnel`. On conflicts, keep trunk's content and re-apply only this plan's intent. The usual conflict is a version string: use 4.2.0.
3. Claims row: `| agent-plugins | v4/agent-plugins | appliance | integrations/claude-plugins/**, cmd/vyomi/mcp_agents_md*.go, tools/guardrails/run.sh, packaging/tunnel/{package.json,server.json,README.md}, scripts/check_*.py | <date> |`. If the script cannot push it to trunk, put it in `HUMAN-GATES.md`.
4. Branch doc from the template, filled from §0 and §3.

### WP1 — Read-only `vyomi_agents_md` (sub-agent A)

Patch 0001 already contains the implementation. The sub-agent verifies it and tightens it:

1. Confirm: tool `ReadOnly: true`, never writes. Returns `agents_md{path, action, proposed_content, replace_block?}`, `claude_md{path, action, proposed_content?, why?}`, `section`, `start_marker`, `end_marker`, `next`. `claude_md` actions: `not_needed` (no CLAUDE.md), `unchanged`, `prepended`.
2. Confirm the section holds no endpoints or credentials and stays at 20 lines or fewer; it is home-agnostic.
3. Also check for `.claude/CLAUDE.md` and `CLAUDE.local.md`: each hides `AGENTS.md` from Claude Code too. Report `claude_md.action = "prepended"` against whichever file exists (root `CLAUDE.md` first), with a test for each.
4. Acceptance:
   - `cd cmd/vyomi && go vet ./... && gofmt -l . && go test ./...`: clean.
   - `bash tools/guardrails/run.sh`: the three `[A]` rows PASS, including "vyomi_agents_md only proposes AGENTS.md text".
   - Stdio smoke: build, send `initialize` + `tools/list` + one `tools/call vyomi_agents_md` against a temp dir. 9 tools listed, nothing written in the temp dir.

### WP2 — Multi-agent package (sub-agent B)

Patches 0002 and 0003 add: the portable `plugin.json` + `mcp.json` (Agent Plugins 1.0), `.codex-plugin/`, `.cursor-plugin/`, the shared `.mcp.json`, the `.agents/plugins/` and `.cursor-plugin/` marketplaces, version 4.2.0, and the `check_agent_plugins.py` drift guard wired into the sync and CI. Remaining work:

1. **Fix the leftover writer references.** `vyomi-setup` SKILL.md step 6 and `integrations/claude-plugins/README.md` still name `vyomi_write_agents_md` with `dry_run` / `claude_md`. Rewrite step 6:
   - Call `vyomi_agents_md` (path, clouds from the scan).
   - Show the user the section and the action, plus the `claude_md` proposal when present, with its `why`.
   - Only after an explicit yes, apply with your own file-edit tool: create / append / replace `replace_block`. Never touch text outside the markers.
   - Suggest committing.
   - Fallback for tunnels older than 1.4.0: write the same marker block by hand after approval.
   Update the README tool list.
2. Descriptions: "Needs vyomi-tunnel 1.3.0+ (1.4.0+ for the AGENTS.md step)" in every manifest and marketplace entry. `check_agent_plugins.py` must still pass.
3. Icons: reuse `plugins/vyomi/.claude-plugin/icon.png`. Add `logo` / `composerIcon` under `extensions.com.openai.interface` and in `.codex-plugin`, and `logo` in `.cursor-plugin`, only where the schema allows. Validate against agentplugins/agent-plugins-spec `schemas/1.0.0` and cursor/plugins `schemas/` (clone both from GitHub; validate with `jsonschema`).
4. README install table per agent. Patch 0004 already switched the plugin manifests, skills and the README's MCP-only snippets to `npx -y vyomi-tunnel mcp`. Keep them that way; `check_agent_plugins.py` requires `mcp.json` and `.mcp.json` to match.
5. Acceptance:
   - `python3 scripts/check_agent_plugins.py` passes, and a mutation spot-check (change one manifest version) fails it.
   - `npx -y @anthropic-ai/claude-code plugin validate integrations/claude-plugins` passes.
   - Real installs from the local marketplace path, each in a fresh `HOME`:
     - Claude Code: `claude plugin marketplace add <path>`, `claude plugin install vyomi@vyomi`, `claude plugin details vyomi@vyomi` → 3 skills, exactly 1 MCP server.
     - Codex latest: `codex plugin marketplace add <path>`, `codex plugin add vyomi@vyomi`, `codex mcp list` → `vyomi` enabled.
     - Codex 0.140.0 (`npm i @openai/codex@0.140.0`): same, through `.codex-plugin/`.
     - Copilot CLI: `copilot plugin marketplace add <path>`, `copilot plugin install vyomi@vyomi`, `copilot mcp list` → 3 skills, `vyomi` under plugin servers.
   - `python3 scripts/sync_claude_plugins.py <fresh clone of vyomi-cloud/claude-plugins>` dry run: 4.1.2 → 4.2.0, no drift errors.

### WP3 — MCP Registry (sub-agent C)

1. `packaging/tunnel/package.json`: add `"mcpName": "io.github.vyomi-cloud/vyomi"`, or the name chosen in D2.
2. New `packaging/tunnel/server.json`:
   - `$schema`: take the current URL from `mcp-publisher init`; the 2025-12-11 schema was current on 2026-11-22.
   - `name` = the `mcpName`; `title` "Vyomi"; a short `description` (check the registry's length limit with `validate`); `repository` = `{url: https://github.com/vyomi-cloud/appliance, source: github, subfolder: packaging/tunnel}`; `version` = the package version.
   - `packages`: `[{registryType: npm, registryBaseUrl: https://registry.npmjs.org, identifier: vyomi-tunnel, version, runtimeHint: npx, transport: {type: stdio}, packageArguments: [{type: positional, value: mcp}]}]`.
3. New `scripts/check_server_json.py`: fails unless `server.json.version` == `packages[0].version` == `package.json.version` and `name` == `mcpName`. Call it from `tunnel-release.yml` next to the existing tag/version check.
4. `tunnel-release.yml`, publish job, after the npm publish step:
   - Install a pinned `mcp-publisher` release binary and verify its checksum.
   - `mcp-publisher login github-oidc && mcp-publisher publish`, only on final (non-rc) tags and never on dry runs. The job already has `id-token: write`.
   - On dry runs, run `mcp-publisher validate` instead.
   - Order matters: the registry checks that the npm tarball for this version carries `mcpName`, so npm must publish first.
5. Version bump to 1.4.0 (package.json + server.json), following the repo's tunnel release conventions. Leave the Homebrew formula to the release workflow.
6. Acceptance:
   - `mcp-publisher validate packaging/tunnel/server.json` passes; `check_server_json.py` passes and fails on a deliberate mismatch.
   - `actionlint` (or a YAML parse) on `tunnel-release.yml`.
   - `npm pack` in `packaging/tunnel` → the tarball's `package.json` has `mcpName`.

### WP4 — npx snippets + cross-OS smoke (sub-agent D)

0. The handover from patch 0005 is in `wasm/relay/mcp-launch.mjs` (source) and `packaging/tunnel/bin/mcp-launch.mjs` (copy), kept identical by `scripts/sync_tunnel_bin.py`. Rules:
   - Runs only when the launcher is in npm's `_npx` cache, or with `VYOMI_MCP_DELEGATE=1`.
   - Skips its own `.bin` shim; needs an installed tunnel ≥ 1.3.0; sets `VYOMI_MCP_DELEGATE=0` on the child, so it can never loop.
   - On Windows, `.cmd` shims run with `shell: true`.
   - Do not change this behaviour without updating its 7 tests in `wasm/relay/test-mcp-launch.mjs`.
1. Replace every MCP config snippet:
   - JSON: `{"command": "npx", "args": ["-y", "vyomi-tunnel", "mcp"]}`.
   - Claude Code: `claude mcp add --scope user vyomi -- npx -y vyomi-tunnel mcp`.
   - Codex: `codex mcp add vyomi -- npx -y vyomi-tunnel mcp`.
   - VS Code: `code --add-mcp '{"name":"vyomi","command":"npx","args":["-y","vyomi-tunnel","mcp"]}'`.
   Files: `packaging/tunnel/README.md`, the root `README.md` MCP section, and both copies of `mesh-cli.mjs` (`packaging/tunnel/bin/` and `wasm/relay/`, edited identically). `scripts/sync_tunnel_bin.py` must still pass. `integrations/claude-plugins/README.md` belongs to WP2.
2. Keep one line per doc for people with the tunnel installed and for offline appliance users (`vyomi-tunnel mcp`, or `vyomi mcp` on v4.0.0 offline). Drop the GUI-editor PATH note where npx removes the problem.
3. New `.github/workflows/tunnel-npx-smoke.yml`, run on changes to `packaging/tunnel/**` or `wasm/relay/mcp-launch.mjs`:
   - matrix `ubuntu-latest`, `macos-latest` (arm64), `macos-13` (x64), `windows-latest`;
   - `npm pack` the tunnel, then run `tools/npx-smoke/handshake.mjs`, which spawns `npx -y ./vyomi-tunnel-*.tgz mcp`, sends `initialize` + `tools/list`, asserts 8 or more tools including `vyomi_status`, and fails after 60 s;
   - also record cold-start time in the step summary;
   - **sync case** on every OS, including Windows `.cmd` shims: `npm i -g vyomi-tunnel@1.3.3`, then run the packed tarball through `npx -y --package=<tgz> vyomi-tunnel mcp`. Assert that the installed copy serves, that `vyomi_status` returns `tunnel.installed = 1.3.3` and `tunnel.upgrade`, and that nothing else is on stderr.
4. Acceptance: the smoke script passes locally on Linux against the packed tarball; `sync_tunnel_bin.py` passes; a grep finds no remaining `"command": "vyomi-tunnel"` in user-facing docs outside the plugin manifests.

### WP5 — "Vyomi for AI agents" page, `llms.txt`, Markdown (sub-agent E, portal repo)

1. Discovery first: read the portal's README and build files. Report the framework, where docs pages live, how routes map to files, and how static files are served. Change nothing until you have that report.
2. New page at `/docs/agents` (or the portal's convention), titled "Vyomi for AI agents". Sections:
   - **Why**: run cloud code against Vyomi from your agent, no cloud bill.
   - **Install**: one card per agent:
     - Claude Code: `/plugin marketplace add vyomi-cloud/claude-plugins` then `/plugin install vyomi@vyomi`.
     - Codex: `codex plugin marketplace add vyomi-cloud/claude-plugins` then `codex plugin add vyomi@vyomi`.
     - Copilot CLI: `copilot plugin marketplace add vyomi-cloud/claude-plugins` then `copilot plugin install vyomi@vyomi`.
     - Cursor: an "Add to Cursor" button, `cursor://anysphere.cursor-deeplink/mcp/install?name=vyomi&config=<base64 of {"command":"npx","args":["-y","vyomi-tunnel","mcp"]}>`.
     - VS Code: an install button with VS Code's MCP install link.
     - Gemini CLI / others: the JSON snippet.
     Verify both deeplink formats against current Cursor and VS Code docs before shipping.
   - **First prompt**: "Set this project up to run against Vyomi."
   - **What the agent can do**: the 9 tools in one line each.
   - **AGENTS.md**: what the section says and why to commit it.
   - **Cloud agents**: "coming soon", one line.
   - **Troubleshooting**: tunnel not running, key missing, npx slow on first run.
3. `/llms.txt` per llmstxt.org: H1 "Vyomi", a one-paragraph blockquote summary, then link sections: Agents (the new page), Getting started (Nano, tunnel, install), Coverage (matrix, launch claims), Pricing.
4. Markdown twins: `<page>.md` for the agents page and the top docs pages (getting started, tunnel, coverage matrix, pricing), generated at build from the same source, served as `text/markdown`. Add `<link rel="alternate" type="text/markdown">` on those pages and a footer link to `/llms.txt`.
5. Docs nav: add "AI agents" under Developers.
6. Acceptance:
   - Local build and serve.
   - `curl -I /llms.txt` → 200, `text/plain`; `curl /docs/agents.md` → 200 with the install commands.
   - A test decodes the Cursor deeplink's base64 back to the exact JSON.
   - Link check on the new pages; screenshots at desktop and mobile widths for WP6.
   - Do not merge: a portal merge is a paid deploy (HUMAN GATE).

### WP6 — Independent verification (fresh sub-agent F)

Give F only this plan, the two branch names and the acceptance lists, not the implementers' reports. F re-runs every acceptance command for WP1–WP5, reviews the diffs against §0 and §2, and writes `VERIFY.md`: pass/fail per check, any deviation, any file touched outside its owner's list. On a failure, the orchestrator sends it back to the owning sub-agent; F re-checks only what changed.

### WP7 — PRs (orchestrator)

- Appliance PR `v4/agent-plugins` → `v4-on-main`: summary, the tool-surface change called out for review (8 + 1), test evidence from `VERIFY.md`, the release steps from §5, and a link to `HUMAN-GATES.md`.
- Portal PR `portal/agents-docs` → `v4-nano-portal`: screenshots and curl outputs. Note that promoting it to portal `main` is a paid deploy.
- Do not merge either.

### WP8 — License + Claude directory kit (sub-agent G)

Prepare, don't submit.

1. Commit `integrations/claude-plugins/LICENSE`: MIT, `Copyright (c) 2026 Vyomi`, or the legal entity name if the owner gives one. `sync_claude_plugins.py` mirrors it to `vyomi-cloud/claude-plugins`. Add `"license": "MIT"` to every plugin manifest whose schema allows it, and keep `check_agent_plugins.py` passing.
2. Commit `integrations/claude-plugins/SECURITY.md`: how to report a vulnerability (support@vyomi.cloud unless the owner names another address) and the supported versions.
3. Write `integrations/claude-plugins/SUBMISSION.md` for the **Claude directory only**:
   - plugin folder `plugins/vyomi` in `vyomi-cloud/claude-plugins`;
   - listing copy: name, one-line and long description, categories, keywords;
   - 3 screenshots to take: installed plugin, setup conversation, AGENTS.md proposal;
   - the pre-submission checklist results (`claude plugin validate`).
4. MCP Registry: nothing to submit; the release publishes it (WP3).

## 4. Test matrix (WP6 runs all of it)

| Layer | Check | Pass when |
|---|---|---|
| Go | `go vet`, `gofmt -l`, `go test ./...` in `cmd/vyomi` | clean |
| Guardrail gate | `bash tools/guardrails/run.sh` | all `[A]` rows PASS; other rows same as trunk |
| Manifests | `check_agent_plugins.py`, `claude plugin validate`, JSON Schema (Agent Plugins 1.0.0, cursor/plugins) | pass |
| Registry | `mcp-publisher validate`, `check_server_json.py` | pass |
| Installs | Claude Code, Codex latest, Codex 0.140.0, Copilot CLI from the local marketplace | 3 skills + 1 `vyomi` MCP each |
| npx | `tools/npx-smoke/handshake.mjs` on the packed tarball (Linux locally; macOS/Windows in CI) | 9 tools including `vyomi_agents_md`, under 60 s |
| Sync | launcher tests (`node --test wasm/relay/test-mcp-launch.mjs`), plus the smoke workflow's sync case on every OS | npx copy hands over to the installed tunnel; upgrade hint shown when npm is newer; no loops |
| Release dry run | `tunnel-release.yml` with `workflow_dispatch` dry run on the branch (needs a human to trigger, see §5) | all gates green; `mcp-publisher validate` step green |
| Portal | build, curl checks, deeplink decode, link check, screenshots | pass |
| End to end | sample AWS repo with a `CLAUDE.md`; in Codex: "Set this project up to run against Vyomi" | env proposed and written after yes; AGENTS.md section and `@AGENTS.md` import proposed; applied only after yes; text outside markers unchanged on re-run |

## 5. Release sequence (human, after both PRs are approved)

1. Merge the appliance PR into `v4-on-main`.
2. Run `tunnel-release.yml` as a dry run and confirm it is green, including the guardrail gate and `mcp-publisher validate`.
3. Tag `tunnel-v1.4.0`. The workflow publishes npm 1.4.0, then the MCP Registry, bumps the tap and syncs plugin 4.2.0 to `vyomi-cloud/claude-plugins`.
4. Check:
   - `npm view vyomi-tunnel@1.4.0 mcpName`;
   - `https://registry.modelcontextprotocol.io/v0/servers?search=vyomi`;
   - `vyomi-cloud/claude-plugins` at 4.2.0;
   - fresh installs from GitHub (not a local path) in Claude Code, Codex and Copilot CLI.
5. Merge the portal PR (paid deploy). Check `/docs/agents`, `/llms.txt` and the install buttons in a real Cursor and VS Code.
6. Submit to the Claude directory from `SUBMISSION.md` (claude.ai/directory/manage; paid Claude plan, GitHub connected). Cursor and OpenAI: paused, see §7.

## 6. Decisions (as of 2026-11-22)

| # | Decision | Status |
|---|---|---|
| D1 | Tool surface grows to 8 read-only + 1 writer | **Approved** |
| D2 | Registry name `io.github.vyomi-cloud/vyomi` (GitHub OIDC; no DNS setup) | **Approved** |
| D3 | Tunnel version 1.4.0 for the new tool | **Approved** |
| D4 | Plugin manifests and docs use `npx -y vyomi-tunnel mcp`; the npx copy hands over to an installed tunnel so the two commands stay in sync | **Decided** (patches 0004, 0005) |
| D5 | License for `vyomi-cloud/claude-plugins` | **MIT** (WP8 adds it) |
| D6 | Listing URLs: privacy https://vyomi.cloud/privacy and terms https://vyomi.cloud/terms (both exist, updated 17 Jul 2026), website https://vyomi.cloud | **Approved**. Support URL still needed: the docs agents page or a contact page; support@vyomi.cloud is the email |
| D7 | Agents page at `/docs/agents`, nav "AI agents" | **Approved** |
| D8 | OpenAI directory submission | **Paused** |
| D9 | Cursor Marketplace submission | **Paused** (MIT license still added now) |

## 7. Paused for later: Cursor Marketplace and OpenAI directory

Kept here so a later run can pick them up:

- **Cursor:** submit the form at cursor.com/marketplace/publish from your Cursor account and accept the publisher terms. You need the repo URL, LICENSE, `SECURITY.md`, https://vyomi.cloud/privacy, https://vyomi.cloud/terms and support@vyomi.cloud. Review is manual; answers come by email; every update is re-reviewed.
- **OpenAI:**
  - Submit as skills-only / desktop-only, because the MCP is local.
  - Account: owner or Apps Management Write role, plus individual or business verification.
  - URLs: privacy, terms, website and an HTTPS support URL.
  - Assets: logo and composer icon.
  - Review: a test Vyomi account with a Free key and no MFA; 5 positive + 3 negative test cases; a video walkthrough; release notes.
  - Package: a single-root ZIP of `plugins/vyomi` with no hooks.
