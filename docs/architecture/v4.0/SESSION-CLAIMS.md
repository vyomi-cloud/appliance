# v4 session claims

One row per active topic. Add your row BEFORE editing; remove it when the branch merges into the trunk. Before editing a path outside
your own claim, read this file and ask the owner if it is claimed. Claims older than 7 days without a push are stale.
Rule: docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md (section 5.2).

| Session | Branch | Repo | Paths claimed | Since |
|---|---|---|---|---|
| claude (MCP follow-ups 3) | v4/mcp-followups-3 | appliance | tools/mcp-eval/prerelease-it.sh, packaging/tunnel/**, integrations/claude-plugins/**, scripts/gen_nano_docs.py, scripts/gen_mcp_matrix.py, wasm/docs/aws/*.json, core/azure_tls_front.py, tests/mesh/test_azure_tls_front_wanted.py | 2026-11-20 |
| claude (agent plugins) | v4/agent-plugins | appliance | integrations/claude-plugins/**, packaging/tunnel/**, cmd/vyomi/{mcp_agents_md*.go,mcp_tunnel_sync*.go,mcp.go,mcp_tools.go,mcp_test.go,mcp_guardrails_test.go,README.md}, wasm/relay/{mcp-launch,mesh-cli,test-mcp-launch}.mjs, tools/guardrails/run.sh, tools/npx-smoke/**, scripts/{check_agent_plugins,check_server_json,sync_claude_plugins}.py, .github/workflows/{tunnel-release,tunnel-npx-smoke,tunnel-mcp-checks}.yml, README.md (MCP section) | 2026-11-22 |
| claude (directory fixes) | v4/directory-fixes | appliance | integrations/claude-plugins/**, scripts/{check_agent_plugins,sync_claude_plugins}.py, .github/workflows/tunnel-release.yml (plugin-sync step), HUMAN-GATES.md, docs/architecture/v4.0/AGENT-DISTRIBUTION-NOW.md | 2026-11-22 |
| claude (F2: retire v1 session tokens) | v4/mesh-session-v1-retire | appliance | core/mesh_session.py, core/mesh_llm.py, wasm/relay/{mesh-session.mjs,test-mesh-session-derived.mjs,test-mesh-link.mjs,test-mesh-shell.mjs,test-mesh-shell-ui.mjs,test-mesh-ssh.mjs,test-tunnel-k3s.mjs,test-fixtures/**}, tests/{mesh_testkey.py,test_mcp_guardrails_server.py,conformance/test_mesh_{session,session_tier,shell,remote_llm,runner_pool,llm}.py}, tools/mcp-eval/{prerelease-it.sh,it-trust-test-key/**}, .github/workflows/{guardrails.yml,tunnel-mcp-checks.yml} (test deps/paths only), docs/architecture/v4.0/{MESH-SESSION-ED25519.md,MCP-GUARDRAILS-INCIDENT-DESIGN.md} | 2026-11-22 |
| claude (hosted MCP PR 1: transport + knowledge tools) | v4/hosted-mcp-transport | appliance | cmd/vyomi/{mcp.go,mcp_http.go,mcp_hosted_tools.go,mcp_homes.go,mcp_ratelimit.go,mcp_log.go,mcp_tools.go,mcp_hosted_test.go,mcp_http_test.go}, tools/mcp-hosted-smoke.sh, tools/guardrails/run.sh (hosted rows only), docs/architecture/v4.0/branches/hosted-mcp-transport.md | 2026-11-22 |
