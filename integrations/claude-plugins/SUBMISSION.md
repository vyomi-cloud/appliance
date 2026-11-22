# Claude directory submission kit: `vyomi`

What to submit to the Claude plugin directory, and the checks it passed. A
person submits it; nothing here submits anything. This file covers the Claude
directory only.

**Status (2026-11-22): not ready to submit.** 4.2.1 is mirrored to
`vyomi-cloud/claude-plugins` (`d9fb835`). Validate on that commit: **1 blocking,
1 policy hold, 1 warning**, 6 of 7 checks passed. The one block is (a): the
directory accepts a local MCP server only from a Verified organization (owner:
Rohith, G9). Everything this repository controls is fixed (§0). A hosted MCP
server is the alternative to G9 (`docs/architecture/v4.0/HOSTED-MCP-DESIGN.md`).

## Latest Validate (2026-11-22, `vyomi-cloud/claude-plugins` @ `d9fb835`, plugin 4.2.1)

| Result | Finding | Location | Meaning |
|---|---|---|---|
| **Blocking** | Local MCP servers accepted only from Verified organizations | `.mcp.json` · `mcpServers.vyomi` | (a), G9 |
| **Policy hold** | Runs a pinned npx or uvx package | `.mcp.json` · `mcpServers.vyomi` | Expected for any pinned launcher: a reviewer reads it. Validate says to act on (a) first |
| **Warning** | No lockfile for a pinned npx or uvx launch | `.mcp.json` · `mcpServers.vyomi` | (f), new. Validate says to act on (a) first. Warnings do not stop a submission |
| Note | Local MCP server: not on claude.ai | `.mcp.json` | It runs in Claude Code and Cowork only |
| Note | agent-plugins manifest detected | `plugin.json` · `$schema` | The portable root manifest is ignored by Claude; expected |
| Note | Images and fonts passed without a code check | `.claude-plugin/icon.png` | The re-encoded icon passed; the earlier warning (c) is gone |

Gone since 4.2.0: (b) the `network` field, (c) the icon warning, and "Can't
confirm which code runs". (d) and (e) did not appear: the launcher is pinned and
the README is present.

## 0. Blocking findings and their status

| # | Finding | Source | Status |
|---|---|---|---|
| (a) | "Local MCP servers accepted only from Verified organizations" (`.mcp.json` · `mcpServers.vyomi`); on 4.2.0 also "Can't confirm which code runs" (gone on 4.2.1) | Directory Validate on 4.2.0 and 4.2.1 | **Blocking, open (still on 4.2.1).** The plugin's MCP is local by design (`npx`). Needs Verified-organization status: owner, via Help and appeals on the submissions page or directory@anthropic.com (HUMAN-GATES G9) |
| (b) | "Config file fields outside the allowed list accepted only from Verified organizations" (`.claude-plugin/plugin.json` · `network`) | Directory Validate on 4.2.0 | **Fixed in 4.2.1:** `network` removed. `check_agent_plugins.py` refuses any `.claude-plugin/plugin.json` field outside name, version, description, author, homepage, repository, license, keywords. The hosts are disclosed in `plugins/vyomi/README.md` instead. **Cleared on 4.2.1** (Validate, `d9fb835`) |
| (c) | Warning: "Contains a download-and-run command" (`.claude-plugin/icon.png`) | Directory Validate on 4.2.0 | **Re-encoded in 4.2.1.** The PNG had no text or EXIF chunks and nothing after IEND, and no download-and-run pattern was found in its bytes, so the match was in compressed pixel data. It is re-encoded from the same pixels with new bytes (1024x1024 RGB, IHDR/IDAT/IEND only). **Cleared on 4.2.1:** Validate lists the icon only as "passed without a code check" |
| (d) | "Unpinned npx launcher" | [Pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist.md) | **Fixed in 4.2.1:** `npx -y vyomi-tunnel@1.4.0 mcp` in `.mcp.json`, `mcp.json`, the skills and the README. `check_agent_plugins.py` requires the pin to equal `packaging/tunnel/package.json`. Validate on 4.2.1 confirms: no unpinned-launcher finding; **Policy hold** "Runs a pinned npx or uvx package", as expected |
| (e) | "README missing" in the plugin folder | Pre-submission checklist | **Fixed in 4.2.1:** `plugins/vyomi/README.md` (about 740 words outside code blocks) says what the plugin runs, the five hosts it contacts and why, what it writes, the 9 tools, install steps and the license. Validate on 4.2.1 raises no README finding |
| (f) | Warning: "No lockfile for a pinned npx or uvx launch" | Directory Validate on 4.2.1 | **Open, not blocking.** The pinned package's own dependencies (`ws ^8.18.0`) resolve at install time. A likely fix is to publish `vyomi-tunnel` with an `npm-shrinkwrap.json`, which npm honours on install, in the next tunnel release; check the directory's docs first. Validate defers it until (a) is resolved |

## 1. What and where

- **Plugin folder:** `plugins/vyomi` in
  [`vyomi-cloud/claude-plugins`](https://github.com/vyomi-cloud/claude-plugins).
  The repository root holds `LICENSE` (MIT), `SECURITY.md` and `README.md`.
- **Submit only after all of these:** (a) is resolved (G9); 4.2.1 is mirrored to
  `vyomi-cloud/claude-plugins` (the repository must show `vyomi` 4.2.1, a
  `LICENSE` and `plugins/vyomi/README.md`: done, `d9fb835`); the portal page
  https://vyomi.cloud/docs/agents is live (G10); and Validate on the form passes
  with no Blocking findings.
- **Where:** https://claude.ai/directory/manage
  - You need a paid Claude plan, with GitHub connected on claude.ai to an
    account that can read `vyomi-cloud/claude-plugins`.
  - Send one submission per plugin folder. Here that is one submission:
    repository `vyomi-cloud/claude-plugins`, folder `plugins/vyomi`.
  - The directory runs a safety scan and a policy review that
    `claude plugin validate` does not. Answers come back through the same
    page.

## 2. Listing copy

These match the manifests (`plugins/vyomi/.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json`). If you change the wording, change the
manifests in the appliance repo too.

- **Name:** Vyomi (plugin id `vyomi`)
- **One-line description:** Run AWS, GCP and Azure code locally against the
  Vyomi simulator.
- **Long description:**

  > Run and test cloud code locally against Vyomi, the AWS / GCP / Azure
  > simulator: Nano in your browser tab, or a Pro/Max mesh on your machine or in
  > your own GitHub Codespace. The plugin adds the Vyomi MCP server and three
  > skills. Your agent can then find your simulator, scan a repo for AWS, GCP
  > and Azure usage, show what Vyomi emulates where you run it, and write a
  > dev-only `.env.vyomi` that points your SDKs at it. It can also propose a
  > short Vyomi section for `AGENTS.md`, so every coding agent that opens the
  > repo uses the simulator instead of the real cloud. Every file change is
  > shown first and written only after you say yes. Production config is never
  > touched. Needs Node.js 18+ and vyomi-tunnel 1.3.0+ (1.4.0+ for the
  > `AGENTS.md` step).

- **Category:** Development (`category: "development"` in `marketplace.json`).
  If the form's list has no exact match, pick the closest developer-tools
  category.
- **Keywords:** aws, gcp, azure, local-cloud, emulator,
  localstack-alternative, testing
- **What it adds:**
  - MCP server `vyomi` (`npx -y vyomi-tunnel@1.4.0 mcp`) with 9 tools: 8 read-only,
    plus `vyomi_write_env`, which writes only `.env.vyomi` and only after the
    user approves.
  - Skills `vyomi-setup`, `vyomi-nano` and `vyomi-mesh`.
- **Network hosts it reaches** (disclosed in `plugins/vyomi/README.md`; the
  directory refuses a `network` field from an unverified organization):
  - `registry.npmjs.org`: npx fetches `vyomi-tunnel@1.4.0`.
  - `127.0.0.1`: the local tunnel on :8090, and the mesh or appliance on :9000
    and :9443.
  - `vyomi.cloud`: only when `~/.vyomi/credentials` exists; `vyomi-tunnel list
    mesh` asks the portal for the Mesh session (a signed request; the secret is
    never sent).
  - `relay.vyomi.cloud`: only when `VYOMI_ENDPOINT` names the Nano cloud relay.
  - `api.github.com`: through `gh`, only for a Codespace mesh.

## 3. URLs and contact

| Field | Value |
|---|---|
| Website | https://vyomi.cloud |
| Privacy policy | https://vyomi.cloud/privacy |
| Terms of service | https://vyomi.cloud/terms |
| Support / docs | Give the support email below. Switch to https://vyomi.cloud/docs/agents only once the portal PR (`portal/agents-docs`, #62) is promoted and the page loads (G10); it returns 404 until then. |
| Support email | support@vyomi.cloud |
| Repository | https://github.com/vyomi-cloud/claude-plugins |
| License | MIT (`LICENSE` at the repository root; `"license": "MIT"` in every plugin manifest) |
| Security contact | `SECURITY.md` at the repository root (support@vyomi.cloud) |

## 4. Screenshots to take (3)

Take them in Claude Code, in a light or dark terminal theme, at a readable size
(about 1600 px wide). Before saving, check that no access key, relay session
URL, Codespace name or home-directory path is visible. Blur any you find.

1. **Installed plugin.**
   - Use a fresh `HOME` (or a machine without the plugin). Run
     `claude plugin marketplace add vyomi-cloud/claude-plugins`, then
     `claude plugin install vyomi@vyomi`.
   - Open `claude`, run `/plugin`, and select `vyomi` on the Installed tab.
   - Capture the panel: version 4.2.1, 3 skills, 1 MCP server. (Retaken at 4.2.1
     on 2026-11-22 from a fresh install from GitHub; screenshots 2 and 3 were
     taken on 4.2.0, and their content is the same on 4.2.1.)
   - Terminal alternative: the output of `claude plugin details vyomi@vyomi`.
2. **Setup conversation.**
   - Use a small sample repo that uses AWS (for example, a boto3 script that
     writes to S3 and reads from DynamoDB).
   - Start Vyomi Nano: run `vyomi-tunnel` and open https://vyomi.cloud/nano
     with a Free key.
   - In `claude` in that repo, ask: *"Set this project up to run against
     Vyomi."*
   - Capture the turn where the agent has called `vyomi_status` and
     `vyomi_scan_repo`. It lists the services found and what Nano emulates,
     and proposes the `.env.vyomi` contents, waiting for your yes.
3. **AGENTS.md proposal.**
   - Use the same session. For the `@AGENTS.md` import proposal to show, give
     the sample repo a `CLAUDE.md`.
   - After the env step, let the agent call `vyomi_agents_md` (tunnel 1.4.0+).
   - Capture the proposed "Local cloud: Vyomi" section between
     `<!-- vyomi:start -->` and `<!-- vyomi:end -->`, the action
     (create / append / replace), and the `@AGENTS.md` import with its reason.
     Take it before you approve.

## 5. Pre-submission checklist

Run on 2026-11-22 against `v4/directory-fixes` (plugin 4.2.1) and against a
scratch mirror made by `sync_claude_plugins.py --apply` into a fresh clone of
`vyomi-cloud/claude-plugins`. 4.2.1 was then mirrored (`d9fb835`) and the
form's Validate re-run on it.

| Check | Command | Result |
|---|---|---|
| Manifests agree; npx pinned to `packaging/tunnel/package.json`; README of 40+ words; only allowed Claude manifest fields | `python3 scripts/check_agent_plugins.py` | pass |
| Agent Plugins 1.0.0 and Cursor JSON Schemas | `python3 scripts/check_agent_plugins.py --schemas <agent-plugins-spec@6395e89> <cursor-plugins@7a58391>` | pass |
| Plugin folder | `claude plugin validate ./integrations/claude-plugins/plugins/vyomi` (2.1.309 and 2.1.330) | pass |
| Marketplace | `claude plugin validate integrations/claude-plugins` | pass |
| Directory profile, strict | `claude plugin validate --strict --profile directory plugins/vyomi` from the mirror (2.1.330) | pass: "These checks found nothing to report". Advisory: "Hosts not declared: list what these parts reach under network.hosts", which the directory itself refuses from an unverified organization (finding (b)); the README discloses the hosts instead |
| MCP starts from npm | `npx -y vyomi-tunnel@1.4.0 mcp`, initialize + tools/list, no tunnel installed | 9 tools; 8 with `readOnlyHint`, `vyomi_write_env` with `destructiveHint`, all 9 with a title |
| Sync to the mirror | `sync_claude_plugins.py <clone> --apply --tunnel-version 1.4.0` | 4.2.0 -> 4.2.1; README added; npm serves 1.4.0; a re-run reports no changes |
| Mirror | `vyomi-cloud/claude-plugins` @ `d9fb835` vs trunk `5d042d5f6` `integrations/claude-plugins` | identical byte for byte; strict directory profile on the mirror: nothing to report |
| Fresh install from GitHub | Claude Code 2.1.309, fresh `HOME` | 4.2.1, 3 skills, 1 MCP server |
| Form Validate | claude.ai/directory/manage, repository `vyomi-cloud/claude-plugins`, path `plugins/vyomi` (`d9fb835`) | 1 blocking (a), 1 policy hold (pinned npx), 1 warning (f); 6 of 7 checks passed. Not submitted |

## 6. Not part of this submission

- **Cursor Marketplace and the OpenAI (Codex/ChatGPT) directory are paused.**
  See §7 of `docs/architecture/v4.0/AGENT-DISTRIBUTION-NOW.md` in the
  appliance repo. The MIT license, `SECURITY.md` and the Codex
  `privacyPolicyURL` / `termsOfServiceURL` fields are already in place for
  when they resume.
- **MCP Registry:** nothing to submit. `tunnel-release.yml` publishes
  `io.github.vyomi-cloud/vyomi` when `vyomi-tunnel` 1.4.0 is released.
