# Vyomi (hosted)

Run and test cloud code locally against **[Vyomi](https://vyomi.cloud)**, the local AWS / GCP / Azure simulator,
through Vyomi's **hosted MCP server** at `https://vyomi.cloud/mcp`.

Real cloud SDKs, CLIs and Terraform talk to Vyomi instead of the real cloud while you develop. Production keeps
running on the real cloud. This plugin is the knowledge your agent needs to wire a project to the simulator, with
**nothing to install**: no Node.js, no `npx`, no tunnel, no local server.

Working on a machine where you want the full local experience — simulator detection, reachability and writing
files for you? Install the **`vyomi`** plugin from the same marketplace instead; it runs the MCP server on your
own machine and sees more. The two can be installed side by side.

## What it answers

| Tool | What you get |
|---|---|
| `list_services` | Which AWS, GCP and Azure services Vyomi emulates, and how completely in each kind of home |
| `check_capability` | Whether one specific feature is supported (`s3.bucket versioning`, `aks.cluster`), with its limitations |
| `get_code_snippet` | A ready-to-run CLI, Python, JavaScript or curl call for one operation, aimed at your simulator's endpoint |
| `get_sdk_settings` | The exact environment variables, SDK client settings and Terraform provider block, plus the gotchas |
| `get_scan_rules` | The search rules that find cloud SDK, CLI and Terraform usage in a project — your agent runs them locally |
| `summarize_scan_hits` | What those matches mean: per service, whether Vyomi emulates it, where it is used, what to watch out for |
| `propose_env_file` | The exact `.env.vyomi` contents for your project (you apply it) |
| `propose_agents_md_section` | A short "Local cloud: Vyomi" section for `AGENTS.md`, so every agent that opens the repo runs against Vyomi |

Every tool is **read-only**: `readOnlyHint: true`, `destructiveHint: false`, no writer in the set. Your agent does
the local steps with its own tools, and writes a file only after you say yes.

## Try it

- "Which AWS services does Vyomi emulate?"
- "Does Vyomi support S3 bucket versioning?"
- "Show me how to call SQS on Vyomi from Python."
- "What environment variables point the Azure SDK for Python at a Vyomi mesh?"
- "Set this project up to run against Vyomi."

## What the server can and cannot do

The server is hosted by Vyomi, so it **cannot see your machine**. It never reaches `127.0.0.1`, never reads or
writes a file, makes no outbound network connection of its own, and never connects to an endpoint named in a
request. It answers from knowledge compiled into it. It asks for no credentials and returns none: the values in
its answers are the simulator's fixed dummy credentials, the same ones the local tools use.

Your simulator stays on your machine. Where the server needs to know which kind of home you are on, you pass
`home=nano`, `mesh` or `offline` — a kind, not an address. If your code reaches a Nano tab through the **cloud
relay**, you pass `nano_access=relay` and the answer comes back with the placeholder `${VYOMI_RELAY_URL}`, which
your agent substitutes locally from the footer of your Nano tab. **Never send that URL to the server** — anyone
holding it can drive your tab, and the server has no input that takes it.

## What each call receives, and what is kept

| Input | Sent by | Kept |
|---|---|---|
| Tool arguments (cloud, language, home, the feature you searched for) | every call | Not stored. Request logs keep the method, the tool name, the status and the latency for 30 days — **no arguments and no IP addresses** |
| Scan hits: rule ids, file paths, line numbers, and the matched service name (e.g. `s3`) | `summarize_scan_hits` | Not stored, and not logged. **No source lines and no file contents**: the server accepts only an identifier (`^[A-Za-z0-9_.\-/]{1,64}$`) per hit, and a hit for an endpoint override it already found carries `file:line` with no text at all |
| The current text of your `AGENTS.md` and Claude memory file | `propose_agents_md_section` | Not stored, and not logged. These files are meant to be committed and shared; paste them only if that is true for you |
| Credentials, tokens, relay URLs | **never** | There is no input that can carry one |

File paths and line numbers do reach the server when you scan a repo. If that is not acceptable for a project,
use the local `vyomi` plugin instead, which scans on your machine and sends nothing.

Privacy policy: https://vyomi.cloud/privacy · Terms: https://vyomi.cloud/terms · Support:
support@vyomi.cloud · Security policy: [SECURITY.md](../../SECURITY.md)

## Install

Claude Code:

```
/plugin marketplace add vyomi-cloud/claude-plugins
/plugin install vyomi-cloud@vyomi
```

Codex:

```
codex plugin marketplace add vyomi-cloud/claude-plugins
codex plugin add vyomi-cloud@vyomi
```

GitHub Copilot CLI:

```
copilot plugin marketplace add vyomi-cloud/claude-plugins
copilot plugin install vyomi-cloud@vyomi
```

Cursor: teams can import the [plugin repository](https://github.com/vyomi-cloud/claude-plugins) as a team
marketplace and install `vyomi-cloud` from it. Everyone else can add the server to `~/.cursor/mcp.json`:

```
{ "mcpServers": { "vyomi": { "type": "streamable-http", "url": "https://vyomi.cloud/mcp" } } }
```

## Or add the server by hand

Claude Code:

```sh
claude mcp add --transport http vyomi https://vyomi.cloud/mcp
```

Any MCP client that speaks Streamable HTTP: point it at `https://vyomi.cloud/mcp`. There is no sign-in. The
server is stateless, so `GET` returns `405` (there is no event stream) and every call is one `POST`.

## Licence

MIT — see [LICENSE](./LICENSE).
