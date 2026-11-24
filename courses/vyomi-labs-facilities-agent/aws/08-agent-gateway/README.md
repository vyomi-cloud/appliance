# Layer 8: Agent Gateway

_One governed gateway with a tool catalogue and a read-only policy_

**What you build:** Put one governed door in front of the tools: a tool catalogue, a policy check on every call and a rate limit.

## Code, in order

### 1. Create the gateway and register the tools

AgentCore Gateway turns Lambda functions into an MCP tool catalog behind IAM authorization. One target per tool, each with an inline tool schema. Needs the two read-only Lambda tools from chapters 7 and 6. The script waits for the gateway and each target to reach READY.

- File: [`gateway.py`](./gateway.py)
- Run: `python gateway.py` (or `./run_all.sh 8` from the project root)
- You should see: `2 targets ['READY', 'READY']`

### 2. List the tools over MCP

The data plane speaks MCP (JSON-RPC over HTTP). `tools/list` returns the catalog an agent can discover; this uses the SigV4 client you saved in chapter 3.

- File: [`mcp_list.py`](./mcp_list.py)
- Run: `python mcp_list.py` (or `./run_all.sh 8` from the project root)
- You should see: `MCP tools/list:`

### 3. Call a tool through the gateway

`tools/call` invokes the Lambda behind the tool and returns its output as MCP content.

- File: [`mcp_call.py`](./mcp_call.py)
- Run: `python mcp_call.py` (or `./run_all.sh 8` from the project root)
- You should see: `found: True | status: RUNNING | isError: False`

### 4. Restrict tool use with a Cedar policy

A policy engine evaluates Cedar policies on every tool call. This one permits only the read-only `asset_status` tool; anything not permitted is denied by default, so the write path stays out of the gateway.

- File: [`cedar_policy.py`](./cedar_policy.py)
- Run: `python cedar_policy.py` (or `./run_all.sh 8` from the project root)
- You should see: `with a Cedar permit policy`

### 5. Ask the agent again, now through the gateway

Same helper and same question as chapter 3, new session. The agent now discovers the gateway and its tool calls report `agentcore-gateway` instead of `unavailable`.

- File: [`agent_via_gateway.py`](./agent_via_gateway.py)
- Run: `python agent_via_gateway.py` (or `./run_all.sh 8` from the project root)
- You should see: `tools reached through the gateway: True`

## It works when

- gateway READY
- tools/list shows the tools
- tools/call returns a result
- a Cedar policy exists
