# Claude directory submission kit: `vyomi`

What to submit to the Claude plugin directory, and the checks it passed. A
person submits it; nothing here submits anything. This file covers the Claude
directory only.

## 1. What and where

- **Plugin folder:** `plugins/vyomi` in
  [`vyomi-cloud/claude-plugins`](https://github.com/vyomi-cloud/claude-plugins).
  The repository root holds `LICENSE` (MIT), `SECURITY.md` and `README.md`.
- **Submit after the 4.2.0 release has synced.** The release workflow
  (`tunnel-release.yml`, on tag `tunnel-v1.4.0`) mirrors this folder to
  `vyomi-cloud/claude-plugins`. The repository must show `vyomi` 4.2.0 and a
  `LICENSE` before you submit. 4.1.2 is published there today, and it fails the
  directory's license check (see §5).
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
  - MCP server `vyomi` (`npx -y vyomi-tunnel mcp`) with 9 tools: 8 read-only,
    plus `vyomi_write_env`, which writes only `.env.vyomi` and only after the
    user approves.
  - Skills `vyomi-setup`, `vyomi-nano` and `vyomi-mesh`.
- **Network hosts it reaches** (also in `plugin.json` under `network.hosts`):
  - `registry.npmjs.org`: npx fetches `vyomi-tunnel`.
  - `127.0.0.1`: the local tunnel on :8090, and the mesh or appliance on :9000
    and :9443.
  - `relay.vyomi.cloud`: only when `VYOMI_ENDPOINT` names the Nano cloud relay.
  - `api.github.com`: through `gh`, only for a Codespace mesh.

## 3. URLs and contact

| Field | Value |
|---|---|
| Website | https://vyomi.cloud |
| Privacy policy | https://vyomi.cloud/privacy |
| Terms of service | https://vyomi.cloud/terms |
| Support / docs | https://vyomi.cloud/docs/agents. Use it only after the portal PR (`portal/agents-docs`) is merged and the page loads. Until then, give the email below. |
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
   - Capture the panel: version 4.2.0, 3 skills, 1 MCP server.
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

Run on 2026-11-22 against the working tree of `v4/agent-plugins`, and against
a scratch mirror made by `sync_claude_plugins.py --apply` into a fresh clone of
`vyomi-cloud/claude-plugins`. Before you submit, re-run them on the synced
public repository.

| Check | Command | Result |
|---|---|---|
| Manifests agree (version, MCP server, tunnel note, icons, license, LICENSE + SECURITY.md present) | `python3 scripts/check_agent_plugins.py` | pass |
| Agent Plugins 1.0.0 and Cursor JSON Schemas | `python3 scripts/check_agent_plugins.py --schemas <agent-plugins-spec@6395e89> <cursor-plugins@7a58391>` | pass |
| Marketplace | `claude plugin validate integrations/claude-plugins` (Claude Code 2.1.330) | pass |
| Plugin, with the directory's rules, strict | `claude plugin validate --strict --profile directory plugins/vyomi`, run from the mirror so the repository root is the public repo's (2.1.330) | pass: "These checks found nothing to report". Info line: "Hosts not read for: mcpServers (1), skills (3)" (the hosts are declared under `network.hosts` instead) |
| Older Claude Code | `claude plugin validate` (2.1.309) | pass with one warning: "Unknown field 'network'. Claude Code ignores it at load time." (`network.hosts` is newer than 2.1.309; install works) |
| Installs | fresh `HOME`, `claude plugin marketplace add <path>` + `claude plugin install vyomi@vyomi` + `claude plugin details vyomi@vyomi` (2.1.309 and 2.1.330) | 4.2.0, 3 skills, 1 MCP server |
| Published 4.1.2, for comparison | `claude plugin validate --profile directory plugins/vyomi` on the current public repo | fails: `LICENSE_MISSING`. 4.2.0 fixes it |
| LICENSE / SECURITY.md | present at the repository root (mirrored by `sync_claude_plugins.py`) | yes |
| Sync dry run | `python3 scripts/sync_claude_plugins.py <fresh clone>` | versions 4.1.2 -> 4.2.0, no drift errors; LICENSE and SECURITY.md added |

## 6. Not part of this submission

- **Cursor Marketplace and the OpenAI (Codex/ChatGPT) directory are paused.**
  See §7 of `docs/architecture/v4.0/AGENT-DISTRIBUTION-NOW.md` in the
  appliance repo. The MIT license, `SECURITY.md` and the Codex
  `privacyPolicyURL` / `termsOfServiceURL` fields are already in place for
  when they resume.
- **MCP Registry:** nothing to submit. `tunnel-release.yml` publishes
  `io.github.vyomi-cloud/vyomi` when `vyomi-tunnel` 1.4.0 is released.
