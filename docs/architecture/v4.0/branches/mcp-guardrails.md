# v4/mcp-guardrails

**Why:** the MCP must not become an admin channel into the simulator (config, DB, signed code, image). Pin that in a test.

**Changes:** `vyomi_write_env` (the only writing tool) now carries `destructiveHint=true`; `cmd/vyomi/mcp_guardrails_test.go` pins the tool list (7 read-only + 1 writer) and the wire annotations.

**Design:** the one write is a single `.env.vyomi*` file in the user's own project (existing guards: plain name, no overwrite unless asked, no symlink, explicit approval). The probes are HTTP GET only.

**Open:** Claude's own shell tools are outside the MCP and not covered by these guardrails.
