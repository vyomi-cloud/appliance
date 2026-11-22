---
name: vyomi-setup
description: Use when the user wants to run, test or develop cloud code locally instead of against real AWS, GCP or Azure - "run this against Vyomi", "test locally without the cloud", "set up a local cloud", "use Vyomi instead of LocalStack", "add Vyomi to AGENTS.md", "tell my team's agents about Vyomi" - or asks whether Vyomi supports the services a project uses.
---

# Set a project up to run against Vyomi

Vyomi is a local simulator of AWS, GCP and Azure. Real cloud SDKs, CLIs and Terraform talk to it instead of the
real cloud during development; production keeps running on the real cloud.

## First: which server are you talking to?

This skill works with either Vyomi MCP server. **Look at the tool names you have** and follow that column.

| You have | That is | What it can do |
|---|---|---|
| `vyomi_status`, `vyomi_scan_repo`, `vyomi_write_env` | the **local** server (`vyomi-tunnel mcp`) | Finds the simulator on this machine, scans the project itself, writes `.env.vyomi` after approval |
| `get_scan_rules`, `summarize_scan_hits`, `propose_env_file` | the **hosted** server (`https://vyomi.cloud/mcp`) | Knowledge and proposals only. It cannot see this machine: **you** grep, **you** write files |

With the local server, use its own flow (`vyomi_status` first). The rest of this skill is the hosted flow.

## The hosted flow

### 1. Find out which home the user is on — by asking, not by probing

The hosted server cannot see this machine, so nothing is auto-detected. Vyomi runs in one of three kinds of home:

- **nano** — a browser tab at https://vyomi.cloud/nano, reached from this machine through the `vyomi-tunnel`
  local tunnel on `http://127.0.0.1:8090`, or through the cloud relay URL shown in the Nano footer.
- **mesh** — a Vyomi mesh on `http://127.0.0.1:9000` (TLS on `9443`).
- **offline** — the Vyomi appliance on `http://127.0.0.1:9000` (TLS on `9443`).

Check it yourself with your own tools, if you have them, before asking:

```sh
curl -s --max-time 2 http://127.0.0.1:8090/health   && echo "nano tunnel is up"
curl -s --max-time 2 http://127.0.0.1:9000/healthz  && echo "a mesh or the appliance is up"
```

Nothing answers, or you have no shell: ask *"Which Vyomi are you using — the one in your browser (Nano), or a
mesh / appliance on this machine?"* and pass that as `home` on every later call. Default to `nano`, the common
case. If the user says nothing is running, hand off to the `vyomi-nano` or `vyomi-mesh` skill.

**Cloud relay.** If the user reaches Nano through the relay rather than the tunnel, pass `nano_access=relay`. The
answers then carry the literal placeholder `${VYOMI_RELAY_URL}`; substitute the URL from the user's Nano footer
yourself, or have them `export VYOMI_RELAY_URL=...`. **Never send that URL to the server**: anyone holding it can
drive the user's tab, and the server has no input that accepts it.

### 2. Find out what the project uses

Two calls, with your own grep in the middle, so no source code leaves the machine:

1. `get_scan_rules` — optionally `languages: ["python", "nodejs", "java", "go", "terraform"]`. You get rules with
   an id, file globs, a regular expression and which capture group holds the service name, plus `skip_dirs` and
   the exact grep forms to use.
2. Run each rule over the files its globs match, skipping `skip_dirs`. Keep capture group 1 — that is the service
   name, for example `s3` from `boto3.client("s3")`.
3. `summarize_scan_hits` with `home` and `hits: [{rule, file, line, token}]`, at most 2000 per call. Send
   **identifiers only**: never a matched line, never file contents. The `already-wired` rule captures nothing —
   send `{rule, file, line}` with no token for those.

You get, per service: whether Vyomi emulates it, its level in that home, how often and where it is used, the
warnings that apply, and which endpoint overrides the project already has (reuse those instead of adding new
ones). Services Vyomi does not emulate keep using the real cloud, or a stub.

No shell or grep tool (ChatGPT on the web, for instance)? Skip the scan. Ask the user which clouds the project
uses and go straight to step 3; say that you are skipping the repo scan and why.

### 3. Get the settings

`get_sdk_settings` for each cloud found, with `cloud`, `home`, and `lang` when you only need one SDK. You get the
environment variables with notes, the formatted env text, the per-SDK client settings, the Terraform provider
block and the warnings for that home (data planes that need TLS, services that are separate emulators, transports
that are not available). Credentials in the answer are the simulator's fixed dummy values.

`get_code_snippet` gives a first call to verify the wiring, for example `cloud=aws service=s3 lang=python`.

### 4. Propose the files — and write nothing without a yes

`propose_env_file` with the clouds and the home returns `{filename, content}`: the exact `.env.vyomi`. Show the
user the file name and the full contents, say it is for local runs only, and create it **with your own edit tool
only after they explicitly approve it**. A general request such as "set this project up" is not approval.

Then tell them how to load it for local runs only — `set -a; . ./.env.vyomi; set +a`, `docker compose
--env-file .env.vyomi`, or their framework's dotenv loader — and that production config stays untouched. Suggest
adding `.env.vyomi` to `.gitignore` if the project commits env files.

### 5. Offer the AGENTS.md section

So every coding agent that opens the repo runs against Vyomi, not the real cloud:

1. Read `AGENTS.md` and the project's Claude memory file (`CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md`)
   if they exist.
2. `propose_agents_md_section` with `clouds`, the text of those files (`agents_md`, `claude_md`, plus
   `claude_md_file` naming which memory file it was), and `env_file` if it is not `.env.vyomi`. Leave a field out
   when that file does not exist.
3. Apply the result with your own edit tool, after approval: `created` → create `AGENTS.md`; `appended` → append
   the section; `updated` → replace `replace_block` with the section; `unchanged` → nothing to do. Never touch
   text outside the markers. If `claude_md.action` is `prepended`, write that file too.
4. Suggest committing `AGENTS.md` so teammates' agents pick it up.

## Rules

- **Never point local runs at a real cloud account**, and never change production config, deployment manifests or
  secrets to make a local run work. Add local overrides only.
- For local-dev tasks, do not use MCP servers or CLIs that act on a real cloud account (`aws-mcp`, the Azure or
  Google Cloud MCP servers) unless the user explicitly asks for the real cloud.
- Respect the warnings in each answer: they differ per home.
- Do not tell the user to run `vyomi up` for Nano — that command starts an appliance or a mesh. For Nano the fix
  is the `vyomi-tunnel` plus an open Nano tab.
- Never ask the user for a credential, a token or a relay URL to pass to the server. It needs none, and accepts
  none.
