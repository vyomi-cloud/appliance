---
name: vyomi-setup
description: Use when the user wants to run, test or develop cloud code locally instead of against real AWS, GCP or Azure - "run this against Vyomi", "test locally without the cloud", "set up a local cloud", "use Vyomi instead of LocalStack", "add Vyomi to AGENTS.md", "tell my team's agents about Vyomi" - or asks whether Vyomi supports the services a project uses.
---

# Set a project up to run against Vyomi

Vyomi is a local simulator of AWS, GCP and Azure. Real cloud SDKs, CLIs and
Terraform talk to it instead of the real cloud during development; production
keeps running on the real cloud. The `vyomi` MCP server (bundled with this
plugin) knows what Vyomi emulates, where the user's simulator lives and how to
point code at it.

The plugin starts its MCP server with `npx -y vyomi-tunnel@1.4.0 mcp`, which needs
Node.js 18+ (`npx` on the PATH). When the user has `vyomi-tunnel` installed
(1.3.0 or newer), that command runs the installed one, so it is the same server
as `vyomi-tunnel mcp`; without an install it runs the npm copy. The tunnel is
still needed to reach Nano; the `vyomi-nano` skill covers installing it. If
`vyomi_status` returns `tunnel.upgrade`, pass that suggestion to the user.

In v4 the simulator lives in one of these **homes**:

- **Nano** (`nano-local`, `nano-cloud`): a browser tab at https://vyomi.cloud/nano
  (Free and up), reached from this machine through the `vyomi-tunnel` local
  tunnel (`http://127.0.0.1:8090`) or the cloud relay URL shown in the Nano footer.
- **Local mesh** (`mesh-local`): the headless Pro/Max appliance on `:9000`.
- **Codespace mesh** (`mesh-codespace`): a Pro/Max mesh in the user's own
  GitHub Codespace, reached through `vyomi-tunnel forward`.
- **Offline** (`offline`): a v4.0.0 or v3 Docker appliance on `:9000`.

## Workflow

1. **Find the home.** Call `vyomi_status`.
   - `selected` is set: use that home. Pass its kind as `home` (`nano`, `mesh`
     or `offline`) to every later tool call.
   - `selected` is null and several homes are listed: ask the user *"Which space
     are you working in — the one in your browser (Nano) or your mesh?"* and use
     the answer.
   - `selected` is null and nothing is reachable: hand off to the `vyomi-nano`
     skill (the default), or to `vyomi-mesh` if the user says they are on
     Pro/Max. Knowledge, scan and env still work without a running simulator.
   - Follow the `hint` it returns. It is specific to the home (open the Nano
     tab, run a forward, renew a locked mesh).
   - `readiness` below 100% right after start-up only means backend containers
     are still starting.
2. **Scan the project.** Call `vyomi_scan_repo` with the absolute path of the
   project root and the `home`. Report back briefly, per cloud:
   - services that are emulated, with their `level` in this home (`full`,
     `limited`, `config_only`),
   - services that carry a `tier` of `pro` (they need a Pro licence),
   - services that **need a Pro/Max mesh** (`mesh: true`) when the home is Nano
     or offline - never wire them to that home,
   - services that are **not emulated** - those keep using the real cloud (or a
     stub) during local runs,
   - every `warning` verbatim in substance (they differ per home: for example on
     Nano, Key Vault is not available and Pub/Sub / Firestore need their REST
     APIs; offline, Cosmos DB and Key Vault need TLS on :9443),
   - `already_wired`: existing endpoint overrides to reuse, not duplicate.
   For a single feature ("does Vyomi do S3 object lock?") call `vyomi_capability`.
3. **Get the exact settings.** Call `vyomi_env` for each cloud found, with the
   `lang` the scan suggests and the `home`. Use its values and pass on its
   `warnings`; never invent endpoints, ports, keys or account names.
4. **Propose the change, then ask.** Prefer the least invasive option:
   - a `.env.vyomi` file (`vyomi_write_env` with the `home`) loaded only for
     local runs,
   - a docker compose override or test fixture that sets the variables,
   - code changes only where an SDK cannot be pointed at an endpoint through
     configuration.
   Show the exact change (the path and the full `.env.vyomi` contents, or the
   diff) and then **stop and wait** for the user's explicit yes to that change.
   A request to "set this up", "run this against Vyomi" or "make it work" is
   not that approval: it asks you to propose, not to write. Only a reply that
   approves the change you showed ("yes", "write it") counts.
5. **Verify.** After the change is approved and written, run the project's own
   tests or a smoke command with the variables loaded (ask first if that needs
   installing dependencies), and report what passed and what failed. `vyomi_snippet`
   gives a one-line CLI / SDK / curl call aimed at the home's endpoint for a
   quick check. If a failure looks like a missing API in Vyomi, say so plainly
   rather than working around it.
6. **Offer the AGENTS.md section.** Once local runs work, offer to add a short
   "Local cloud: Vyomi" section to the project's `AGENTS.md`, the instructions
   file Codex, Cursor, Copilot, Gemini CLI and most other coding agents read on
   their own. Committed, it tells every agent that opens the repo (a teammate's,
   or a cloud / PR agent with no plugin) to load `.env.vyomi`, leave the
   simulator for the developer to start, and keep away from the real cloud.
   - Call `vyomi_agents_md` with the absolute project `path` and the `clouds`
     from the scan. It is read-only: it writes nothing and returns the
     proposal.
   - Show the user the returned `section` and `agents_md.action` (`created`,
     `appended`, `updated` or `unchanged`; `unchanged` means there is nothing
     to do). If `claude_md.action` is `prepended`, also show
     `claude_md.path`, the `@AGENTS.md` import line it adds and its `why`:
     that file hides `AGENTS.md` from Claude Code unless it imports it.
     (`not_needed` and `unchanged` need nothing.)
   - **Stop and wait** for the user's explicit yes to that exact change. Only
     then apply it with your own file-edit tool, so that the file ends up
     exactly as `agents_md.proposed_content`:
     - `created`: create `agents_md.path` with `agents_md.proposed_content`;
     - `appended`: append the `section` to the end of the existing file;
     - `updated`: replace `agents_md.replace_block` (from `start_marker` to
       `end_marker`) with the `section` (without its final newline);
     - `claude_md` `prepended` (same approval): add the import line at the
       top of `claude_md.path`, giving `claude_md.proposed_content`.
     In `AGENTS.md`, never change any text outside the
     `<!-- vyomi:start -->` / `<!-- vyomi:end -->` markers; in the Claude
     memory file, add only the import line. If a file changed since the call,
     call `vyomi_agents_md` again rather than editing from a stale proposal.
   - Then suggest committing `AGENTS.md` (and the Claude memory file, if it
     changed) so teammates' agents pick it up.
   - If `vyomi_agents_md` is not available (`vyomi-tunnel` older than 1.4.0),
     suggest upgrading the tunnel, or show a section of the same shape,
     wrapped in those markers, and with the user's OK write it yourself:
     only between the markers, no endpoints or keys (those stay in
     `.env.vyomi`).

## Rules

- Never modify production configuration, deployment manifests or secrets. Add
  local/dev overrides only.
- Writing `.env.vyomi`, `AGENTS.md`, `CLAUDE.md` (or any file), editing code
  and installing packages each need the user's explicit OK to that specific
  change, shown first. A general "set this up" request is not that OK.
- Never put endpoints, access keys or credentials in `AGENTS.md`: it is
  committed and shared.
- For local-dev work, do not use MCP tools that act on a real cloud account
  (for example AWS's `aws-mcp`, or Azure / Google Cloud MCP servers) to create,
  read or change resources. Use the Vyomi tools and the local simulator; reach
  for a real-cloud tool only if the user explicitly asks for the real cloud.
- Services marked not emulated must not be silently pointed at Vyomi.
- Respect the scan and env warnings; they describe real protocol limits.
- Tell the user to run `vyomi up` only when `vyomi_status` reports the
  `offline` or `mesh-local` home.
- Never start the tunnel, a forward, a Codespace or `vyomi up` yourself, and
  never through Bash, not even in the background. The MCP never starts them
  either. Give the user the exact command (use the one `vyomi_status` gives:
  it picks a free local port) and let them run it in their own terminal.
- If the `vyomi` MCP tools are unavailable: the agent could not start
  `npx -y vyomi-tunnel@1.4.0 mcp`. Ask the user to check `node --version` (18 or
  newer) and that `npx` is on the PATH the coding agent sees (GUI editors
  started from the Dock may not see an nvm or Homebrew Node), and that npm can
  reach the registry on the first start. Then restart the coding agent (Claude
  Code, Codex, Cursor, Copilot, ...). On native Windows, an agent that cannot
  start `npx` directly needs it registered as `cmd /c npx -y vyomi-tunnel@1.4.0 mcp`.
  Offline machines: install the tunnel (`npm i -g vyomi-tunnel`) and register
  `vyomi-tunnel mcp` instead. v4.0.0 offline users: `vyomi mcp` from the
  `vyomi-docker` install keeps working.
