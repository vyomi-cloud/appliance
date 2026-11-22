# v4/vyomi-cloud-plugin

Owner: claude (hosted MCP, PR 4) - Started: 2026-11-23 - Base: v4/hosted-mcp-deploy (stacked, PR #710) - Status: in progress

## Purpose
PR 4 of `HOSTED-MCP-IMPLEMENTATION-PLAN.md`, which is `OPENAI-DIRECTORY-PLAN.md` WP-O3: the `vyomi-cloud` plugin
package — the thing a user installs, and the thing submitted to the Claude and OpenAI directories. It points at
the hosted server (`https://vyomi.cloud/mcp`) and needs nothing installed, which is what both directories accept
from an unverified organization (design §1).

Nothing is submitted here. The ZIP is built and checked locally; the submissions are owner gates.

## Architecture
```
integrations/claude-plugins/
  .claude-plugin/marketplace.json     + a vyomi-cloud entry      (Claude Code, Copilot CLI)
  .agents/plugins/marketplace.json    + a vyomi-cloud entry      (Codex)
  .cursor-plugin/marketplace.json     + a vyomi-cloud entry      (Cursor teams)
  plugins/vyomi/                      unchanged, except two OpenAI listing fields (below)
  plugins/vyomi-cloud/                NEW
    plugin.json                       Agent Plugins 1.0 + extensions.com.openai.interface (the OpenAI listing)
    mcp.json                          {"type": "streamable-http", "url": "https://vyomi.cloud/mcp"}
    .mcp.json                         {"type": "http",            "url": "https://vyomi.cloud/mcp"}
    .claude-plugin/plugin.json        only the fields the Claude directory accepts from an unverified org
    .claude-plugin/icon.png           the shared icon (logo + composerIcon must live inside the plugin)
    .codex-plugin/plugin.json         older Codex, with the same interface block
    .cursor-plugin/plugin.json        older Cursor
    README.md                         what it answers, what it cannot do, and the data-handling table (design §8)
    LICENSE                           MIT
    skills/{vyomi-setup,vyomi-nano,vyomi-mesh}/SKILL.md
scripts/package_openai_plugin.sh      -> dist/vyomi-cloud-openai.zip
scripts/check_agent_plugins.py        hosted-aware, plus the OpenAI length limits
```

**The two transport spellings are deliberate.** Claude Code's `.mcp.json` key for Streamable HTTP is `http`; the
portable Agent Plugins schema calls it `streamable-http`. `check_agent_plugins.py` compares the two files by
server name and URL, so they stay in step.

**The skills branch on the tools they find** rather than being a second copy of the local flow. Each one has a
table: `vyomi_status` / `vyomi_scan_repo` present means the local server, so use its flow; `get_scan_rules` /
`propose_env_file` present means the hosted server, so the agent asks which home the user is on, greps with the
rules, and writes files itself after a yes.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| `shortDescription` is "Local AWS/GCP/Azure simulator" (29 characters) | The brief's exact "Local AWS, GCP, Azure simulator" (31) | OpenAI's limit is 30 (`OPENAI-DIRECTORY-PLAN.md` WP-O1, read 2026-11-22). Same words, two commas fewer. Flagged for the owner: if the real limit is higher, put the commas back |
| `developerName` is a literal `TODO pending O-D1: ...` placeholder | A guess at "Vyomi" or a person's name | O-D1 (individual vs business identity) is open, and the listing name has to match the verified OpenAI identity. `check_agent_plugins.py` **reports** the placeholder on every run without failing, so it cannot be forgotten and cannot break CI |
| The new OpenAI limit check applies to every plugin, so `plugins/vyomi`'s 63-character `shortDescription` and missing `supportURL` are fixed here too | Checking only the hosted plugin | The plan already lists that 63-character description as work (WP-O1); a check that skips the one plugin that fails it is not a check. The local plugin now says "Run cloud code on your machine" (30) |
| A remote plugin must NOT carry the "Needs vyomi-tunnel ..." note, and a stdio plugin still must | One rule for both | The hosted plugin needs no tunnel and no install; promising one in a listing would be wrong in exactly the place a user reads before installing. The checker now derives which rule applies from the plugin's own `mcp.json` |
| Remote server URLs must be `https` on a `vyomi.cloud` host | Any URL | A listing must never be able to point an installed plugin at someone else's server |
| `vyomi-cloud` is listed in all three marketplaces | Only shipping the folder | It has to be installable, and `check_agent_plugins.py` only covers plugins the marketplace lists |
| Version 4.2.1, the same as `vyomi` | Its own version line | The marketplace's `metadata.version` must equal every plugin entry's version; one package, one version |

## Open issues
- [ ] O-D1: the verified OpenAI identity, which decides `developerName` (owner: Rohith)
- [ ] The directory submissions themselves (Claude, OpenAI, cursor.directory) and the privacy-policy update are
  owner gates (plan §9, WP-O5); nothing here submits anything
- [ ] `vyomi.cloud/support` is referenced as `supportURL` by both plugins; it must exist before submission
  (owner: Rohith)
- [ ] `scripts/check_agent_plugins.py` and `integrations/claude-plugins/**` are also claimed by
  `v4/agent-plugins` and `v4/directory-fixes` (owner: Rohith to sequence the merges)
- [ ] The three WP-O4 negative cases ("deploy to production AWS", "the weather in Bangalore", "store my real AWS
  keys") were not run: they need a human reading the agent's judgement, not an assertion (owner: Rohith, at
  submission time)

## Testing
Run on macOS (darwin/arm64), 2026-11-23, against the hosted server built from this branch
(`vyomi mcp --hosted --listen :8080`, 8 tools, knowledge v4.0.10).

| What | Result |
|---|---|
| `python3 scripts/check_agent_plugins.py integrations/claude-plugins` | consistent; one note (the `developerName` placeholder) |
| `claude plugin validate integrations/claude-plugins/plugins/vyomi-cloud` | **Validation passed** |
| `claude plugin validate integrations/claude-plugins` (marketplace) | **Validation passed** |
| `bash scripts/package_openai_plugin.sh` | `dist/vyomi-cloud-openai.zip`, 20 entries, one plugin root, no hooks or git metadata |
| `claude mcp add --transport http vyomi-hosted http://localhost:8080/mcp` → `claude mcp list` | `✔ Connected` |

The five WP-O4 positive prompts, each run with `claude -p` against that server, with only the hosted MCP tools
allowed (no Bash, Read, Write, Grep), four of them from an empty temporary directory:

| Prompt | Tool actually called | Outcome |
|---|---|---|
| "Does Vyomi support SQS FIFO queues?" | `check_capability` | "Yes — fully, in every home", citing `sqs.queue.fifo` at level full on both |
| "Which GCP services does Vyomi emulate?" | `list_services` | 28 GCP services, 18 released + 10 v4, with levels per home |
| "Show Python boto3 code to put an object in S3 on Vyomi Nano." | `get_code_snippet`, then `get_sdk_settings` | Working boto3 code against `http://127.0.0.1:8090` with the dummy credentials and path-style addressing |
| "What environment variables point the Azure SDK for Python at a Vyomi mesh?" | `get_sdk_settings` | The mesh variables, with the TLS-only Cosmos / Key Vault warnings |
| "Write a .env.vyomi for a project using AWS and GCP on Nano." | `propose_env_file` | The full file contents, "nothing written yet", and the temporary directory was still empty afterwards |

The `vyomi-hosted` registration was removed from `~/.claude.json` afterwards (both project scopes), so no local
configuration was left changed.

Not run: ChatGPT, Codex and Cursor against production (`https://vyomi.cloud/mcp` does not exist yet — that is PR
3's deploy and gates O-G2/O-G3), and the three negative cases.
