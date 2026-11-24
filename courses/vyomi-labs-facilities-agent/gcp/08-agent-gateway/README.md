# Layer 8: Agent Gateway

_One governed gateway with a tool catalogue and a read-only policy_

**What you build:** Put one governed door in front of the tools: a tool catalogue, a policy check on every call and a rate limit.

## Code, in order

### 1. Install the libraries

Chapter 4 puts one governed door in front of the tools. It relies on gcp.py (chapter 10), functions.py and the Firestore tools (chapter 7) and the kb-search tool and knowledge base (chapters 6 and 12). Google publishes no client library for Agent Platform gateways, MCP servers or agent policies, so these calls use the documented REST resources through google-auth's AuthorizedSession, the way Google documents it for APIs without a library.

- File: [`install_4.sh`](./install_4.sh)

### 2. Write the MCP tool server

MCP (Model Context Protocol) is the open standard the gateway speaks to tools. This Cloud Run function is a tiny MCP server over streamable HTTP (JSON-RPC 2.0) that publishes exactly two read-only tools, kb_search and asset_status. The write tool is deliberately not in the catalogue: write actions go through the approval flow in chapter 5.

- File: [`mcp_server_fn.py`](./mcp_server_fn.py)

### 3. Write the gateway helpers

A small module with the two things every later step needs: the REST path prefix for Agent Platform resources and a function that sends one MCP JSON-RPC request to a URL.

- File: [`gateway.py`](./gateway.py)

### 4. Deploy the tool server and register it

Deploys the MCP server function and registers it in the agent registry as the MCP server facilities-tools, so the gateway knows where the tools live.

- File: [`register_tools.py`](./register_tools.py)
- Run: `python register_tools.py` (or `./run_all.sh 8` from the project root)
- You should see: `registered: projects/`

### 5. Create the gateway and attach the tools

Creates the agent gateway facilities-gateway, waits until it is ACTIVE (it has an MCP endpoint then) and attaches the MCP server. From now on agents talk to the gateway, never to the functions.

- File: [`create_gateway.py`](./create_gateway.py)
- Run: `python create_gateway.py` (or `./run_all.sh 8` from the project root)
- You should see: `attached: ['facilities-tools']`

### 6. List and call the tools through the gateway

The tool catalogue and a tool call, both through the gateway's MCP endpoint: tools/list returns the catalogue (each tool name is prefixed with the MCP server name), tools/call runs asset_status for boiler B-12.

- File: [`use_gateway.py`](./use_gateway.py)
- Run: `python use_gateway.py` (or `./run_all.sh 8` from the project root)
- You should see: `asset_status via gateway: B-12 RUNNING`

### 7. Add a policy: read-only tools only

A policy on every call. Agent policies are written in Cedar: this one permits the two read tools and, because Cedar denies by default, the write tool create_work_order is refused. The policy is attached to the gateway in ENFORCE mode and tested with the simulator's policy test endpoint, which evaluates a principal and a tool against the policy.

- File: [`add_policy.py`](./add_policy.py)
- Run: `python add_policy.py` (or `./run_all.sh 8` from the project root)
- You should see: `policy attached to facilities-gateway`

## It works when

- gateway ACTIVE
- tools/list shows tools
- tools/call works
- write tool is denied by policy
