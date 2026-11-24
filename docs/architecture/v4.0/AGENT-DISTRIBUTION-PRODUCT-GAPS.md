# Vyomi on coding agents: what we have and what is missing

Status: analysis, 2026-11-22 · Owner: Rohith · Exported from the Claude doc of the same name · Execution plan for the "Now" items:
`AGENT-DISTRIBUTION-NOW.md`

Vyomi already has the hard part: a guarded MCP server, three skills and a simulator that runs in a browser tab, a Mesh or Docker.
What it lacks is the packaging around them. Agents struggle to find Vyomi, it takes more than one command to install, cloud agents
cannot reach it, and the agent cannot see what its calls did in the simulator.

## The building blocks dev tools use

The pattern peers have settled on has three parts. An MCP server lets the agent act, skills and instruction files teach it when and
how, and a one-command installer puts both into whatever agent the user runs. Everything else in this table helps people find the
tool or makes it reachable from more places.

| Building block | What it is | What it does for the user | Peer example |
| --- | --- | --- | --- |
| MCP server (local) | A process the agent starts over stdio; it exposes tools | The agent can query and act on your product | [LocalStack MCP](https://docs.localstack.cloud/aws/tooling/mcp-server/) via `npx` |
| MCP server (remote) | The same, over HTTP, usually with OAuth | Works in web and cloud agents with no install | Neon's hosted `mcp.neon.tech` |
| Skills | Folders of instructions the agent loads when a task matches | The agent knows the right workflow, not just the API | AWS and Neon ship skills next to their MCP servers |
| Plugin / extension bundle | One package: MCP config + skills (+ hooks), per agent or in the shared Agent Plugins format | One install gives the agent everything | [Agent Toolkit for AWS](https://aws.amazon.com/products/developer-tools/agent-toolkit-for-aws/) plugins for Claude Code, Cursor, Codex, Kiro, Devin |
| Instruction files | `AGENTS.md`, `CLAUDE.md`, Cursor rules, committed in the user's repo | Every agent that opens the repo follows the project's conventions | Encore generates `AGENTS.md` / rules for its local stack |
| Installer CLI (`init`) | One command that detects installed agents and writes their configs | Setup is one step, not one per agent | `npx neonctl init`, `npx @localstack/localstack-mcp-server init` |
| One-click links | `cursor://` and VS Code install links on docs pages | Install from the docs page with one click | Neon and LocalStack "Add to Cursor" buttons |
| Registries and marketplaces | Official MCP Registry, Claude plugin directory, Cursor Marketplace, Codex directory | Agents and users find you without knowing your URL | LocalStack listed as `io.github.localstack/localstack-mcp-server` |
| Agent-readable docs | `llms.txt`, Markdown copies of pages, a docs MCP, an "AI agents" page | Agents answer questions about your product correctly | Neon links `llms.txt` from every docs page |
| Cloud-agent environments | `copilot-setup-steps.yml`, `.cursor/environment.json`, Codex setup scripts | Agents that run in the cloud can use your tool too | Copilot's setup job accepts `services:` containers |
| CI action | A GitHub Action that boots the tool for tests | The same checks run in CI that the agent ran locally | `setup-localstack` |
| Editor extension | A VS Code / Cursor extension with UI | People browse state next to the code | Neon Local Connect, installed by `neon init` |

## What Vyomi has today

From `v4-on-main` at `0df22d4e` and vyomi.cloud, 22 Nov 2026. Strong at the core, thin at the edges.

| Surface | State | Notes |
| --- | --- | --- |
| MCP server (`vyomi-tunnel mcp`) | Shipped, tunnel 1.3.3 | Local stdio only. 7 read-only tools + `vyomi_write_env`, pinned by the guardrail gate. Finds the simulator, scans the repo, gives exact env per place it runs. Never starts or changes the simulator, by design |
| Claude Code plugin | Shipped, 4.1.2 | MCP + 3 skills (setup, nano, mesh), own marketplace repo `vyomi-cloud/claude-plugins`. Not in Claude's official directory |
| Codex, Cursor, VS Code, Copilot | Manual MCP config only | Tunnel README has per-editor snippets. No skills, no plugin, no one-click link |
| Gemini CLI, Windsurf, others | Not documented | The generic `mcpServers` snippet works |
| Where the simulator runs | Nano (browser, Free), Mesh (local or Codespace, Pro/Max), Docker appliance (`vyomi/appliance`, Free tier and up) | The MCP knows all three. Only Docker runs headless without a browser |
| GitHub Action `setup-vyomi` | Scaffold inside the repo | v2-era docs (`version: 2.2.2`), not published to the Marketplace, not mentioned for agents |
| Devcontainers | For the Codespace Mesh | Not offered as a template for users' own repos or cloud agents |
| Docs site | Strong on coverage and comparisons | No AI-agents section, no MCP setup page, `llms.txt` not reachable, no Markdown copies of pages |
| MCP Registry / directories | Not listed | No `server.json`; `vyomi-tunnel` on npm has no `mcpName` |
| AGENTS.md support | Planned | Read-only `vyomi_agents_md` passes the gate (branch `v4/agent-plugins`) |
| Usage signal | None for agents | No count of installs or first runs per agent |

## Where users drop off

Work is the strong stage: the skills and MCP set an agent up well once it is installed. Discover, install and share are where users
fall away, and those are also the cheapest stages to fix.

| Stage | Today | Missing |
| --- | --- | --- |
| Discover | Plugin repo, docs site | MCP Registry, agent directories, AI docs page, install links |
| Install | Claude plugin; manual MCP elsewhere | `init` command, multi-agent package |
| Connect | Nano, Mesh, Docker image; `vyomi_status` | Cloud-agent recipes, Docker-free runtime |
| Work | 3 skills, repo scan, `.env.vyomi` | Skills outside Claude Code |
| Verify | The user's own tests via `.env.vyomi` | Request log and resources for the agent |
| Share | Codespace Mesh (Pro/Max) | `AGENTS.md`, usage signal per agent |

## Gaps

Ten gaps, sorted by priority. P0 blocks adoption from agents now; P1 is needed to compete with LocalStack; P2 can wait. Effort: S is
days, M is 1 to 2 weeks, L is longer.

| # | Gap | Why it matters to users | What peers do | Fix | Effort | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Full plugin only in Claude Code | Codex, Cursor and Copilot users get the MCP by hand and never get the skills | AWS ships one plugin per agent; the shared Agent Plugins format covers most | Multi-agent package (`v4/agent-plugins`) | S | P0 |
| 2 | No one-command setup | Today: install tunnel, save key, configure each agent, start Nano. Each step loses users | LocalStack `init` checks Docker, reads the token, detects agents, writes configs. Neon `init` covers 15 agents | `vyomi-tunnel init`: detect agents, install plugin or MCP + skills, save the key, offer AGENTS.md, print next step | M | P0 |
| 3 | Cloud agents cannot use Vyomi | Copilot cloud agent, Cursor cloud agents and Codex cloud run in their own VMs; Nano in the user's tab and `localhost` are out of reach | Copilot setup job takes `services:` containers; Cursor reads `.cursor/environment.json`; Codex runs a setup script | Ready recipes per agent built on the `vyomi/appliance` image; `init --cloud` writes them; `setup-vyomi` updated to v4 and published | M | P0 |
| 4 | No Docker-free headless mode | Codex cloud containers typically lack Docker, so even recipe 3 fails there | LocalStack also needs Docker; this is a chance to lead | Decide: a pip-installable core, or headless Nano driven by the tunnel | L | P1 |
| 5 | The agent cannot see what its calls did | The MCP only knows config. After a failing test the agent cannot ask Vyomi which calls failed or what exists | LocalStack's agent reproduces a bug from App Inspector traces and proves the fix | Read-only inspection tools: recent requests and errors, resources in a space. Fits the guardrail (read-only) | M | P1 |
| 6 | Hard to discover | Not in the official MCP Registry or any agent directory; no install buttons | LocalStack is in the Registry; Neon and LocalStack have Cursor buttons | `server.json` + `mcpName`, publish from CI; directory submissions; Cursor and VS Code install links on docs and Nano | S | P1 |
| 7 | Docs are not agent-ready | Agents asked "how do I use Vyomi with X" find nothing and guess | Neon: `llms.txt` and `.md` pages; LocalStack: an AI-workflows page and an `agents.md` | "Vyomi for AI agents" page, Markdown copies of pages, `llms.txt`. Markdown and MCP matter more than `llms.txt` itself | S | P1 |
| 8 | No usage signal per agent | You cannot tell which agents bring users or where setup fails | Common practice: client-level analytics | Opt-in count of MCP client name and first successful `vyomi_status`; installs per marketplace | S | P1 |
| 9 | MCP needs a global install | Config breaks if `vyomi-tunnel` is not on PATH (GUI editors) | LocalStack config is `npx -y @localstack/localstack-mcp-server` | Configs use `npx -y vyomi-tunnel mcp`, handing over to an installed tunnel (`v4/agent-plugins`) | S | P2 |
| 10 | No hosted knowledge MCP | Web agents (claude.ai, ChatGPT) cannot ask what Vyomi supports | Neon and others host remote MCP servers | Read-only remote MCP at `mcp.vyomi.cloud`: capabilities and snippets, no simulator access | M | P2 |

Not listed as a gap: a VS Code extension. Nano's console already gives people a UI; revisit if users ask.

## Recommended order

Start with what is nearly built and cheap: it puts Vyomi in every agent within two weeks. Then make setup one command and reach
cloud agents. The deeper product work comes last.

**Now: the next 2 weeks** (executed via `AGENT-DISTRIBUTION-NOW.md`)

1. Ship the multi-agent package and the read-only AGENTS.md tool: gap 1.
2. List in the MCP Registry and submit to the Claude directory (Cursor and OpenAI paused): gap 6.
3. Publish a "Vyomi for AI agents" docs page with install buttons per agent, plus `llms.txt` and Markdown pages: gaps 6 and 7.
4. Switch the plugin and config snippets to `npx -y vyomi-tunnel mcp`: gap 9.

**Next: the following month**

1. `vyomi-tunnel init`: one command from zero to a working agent: gap 2.
2. Cloud-agent recipes for Copilot, Cursor and Codex on the Docker image, with `setup-vyomi` updated for v4 and published: gap 3.
3. Opt-in usage signal per agent, so the next priorities come from data: gap 8.

**Later: once the above shows which agents matter**

1. Read-only inspection tools for the agent's verify loop: gap 5, needs a guardrail review.
2. A Docker-free headless runtime: gap 4.
3. A hosted read-only knowledge MCP: gap 10.

## Decisions only you can make

- [ ] Which agents come first? Without usage data, Claude Code, Cursor and Codex are the safest bet: every peer supports them first.
- [ ] Should the MCP stay knowledge-only, or gain read-only inspection (gap 5)? The second closes the agent's verify loop. It needs a guardrail review, but no new write path.
- [ ] Cloud agents and CI on the Free tier: can the Docker appliance run headless in an agent's VM or CI without a key, and how is that counted? This decides whether gap 3 is a growth channel or a paid feature.
- [ ] Docker-free runtime (gap 4): a pip-installable core, or headless Nano driven by the tunnel? It sets the cost of reaching Codex cloud.
- [ ] Brand: one command, `vyomi-tunnel init`, or a new `npx vyomi init` entry point that people remember?

## Sources

- [LocalStack MCP Server docs](https://docs.localstack.cloud/aws/tooling/mcp-server/), [Give Your Coding Agent a Real Cloud to Break](https://blog.localstack.cloud/give-your-coding-agent-a-real-cloud-to-break/), [LocalStack AI & Agent Workflows](https://docs.localstack.cloud/aws/getting-started/ai-workflows/)
- [Agent Toolkit for AWS](https://aws.amazon.com/products/developer-tools/agent-toolkit-for-aws/)
- [Neon: get started with your AI agent](https://neon.com/docs/get-started/with-an-agent), [Neon MCP server](https://neon.com/docs/ai/neon-mcp-server.md), [neon mcp command](https://neon.com/docs/cli/mcp.md)
- [GitHub: Copilot coding agent customization](https://learn.microsoft.com/en-us/training/modules/github-copilot-code-agent/4-customize-extend-validate-copilot-code-agent), [MCP and Copilot coding agent](https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/coding-agent/mcp-and-coding-agent)
- [Cursor cloud environment setup](https://cursor.com/docs/cloud-agents/setup), [Codex cloud environments](https://developers.openai.com/codex/cloud/environments)
- [MCP Registry quickstart](https://modelcontextprotocol.io/registry/quickstart)
- [Redocly: llms.txt is still overhyped](https://redocly.com/blog/llms-txt-still-overhyped)
- [Encore: local setup for AI coding agents](https://encore.dev/articles/best-local-development-setup-ai-coding-agents)
- Vyomi: `vyomi-cloud/appliance` at `0df22d4e` (README, `.github/actions/setup-vyomi`, `docs/DOCKERHUB.md`, `packaging/tunnel/README.md`), [vyomi.cloud/docs](https://vyomi.cloud/docs)
