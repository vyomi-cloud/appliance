# Layer 9: Agent Gateway

_One governed gateway with a tool catalogue and a read-only policy_

**What you build:** Put one governed door in front of the tools: a tool catalogue, a policy check on every call and a rate limit.

## Code, in order

### 1. Install the libraries

Chapter 4 puts one governed door in front of the tools: Azure API Management (APIM). The tool catalogue is an API with one operation per tool; policies add a rate limit and a rule that keeps the write tool behind an approval; an MCP server API exposes the same tools as `tools/list` and `tools/call`. It fronts the Function App from chapter 7. Honest scope note: Azure has no Cedar-style agent policy engine (AWS AgentCore Gateway and Vertex AI have one), so the policy here is APIM policy expressions (`choose`/`when`), which is what Azure teams actually use.

- File: [`install4.sh`](./install4.sh)

### 2. Write the gateway helpers

The APIM data plane is served at `https://<service>.azure-api.net/<api path>` on Azure; the simulator serves it at `/azure-data/apim/<service>/<api path>`. `headers()` carries the subscription key (read from APIM through ARM, as `az apim` does) and, from chapter 1 on, the bearer token. `mcp()` sends a JSON-RPC 2.0 message to the MCP API.

- File: [`gw.py`](./gw.py)

### 3. Create the gateway, the tool catalogue and the subscription

In order: the APIM service `facilities-apim`; an API `tools` whose backend is your Function App; three operations (`kb-search`, `asset-status`, `create-work-order`, the write tool); an API-level policy that adds the function's host key to every backend call (so callers never see it) and rate-limits each subscription to 60 calls a minute; and a subscription `agent-sub` that covers every API. Callers now need a subscription key, never the function key.

- File: [`create_gateway.py`](./create_gateway.py)
- Run: `python create_gateway.py` (or `./run_all.sh 9` from the project root)
- You should see: `catalogue: ['asset-status', 'create-work-order', 'kb-search']`

### 4. Call a read-only tool through the gateway

The same asset-status call as chapter 7, but now through the front door: the gateway checks the subscription key, rate-limits, adds the function key and forwards. Without the key it answers 401.

- File: [`call_gateway.py`](./call_gateway.py)
- Run: `python call_gateway.py` (or `./run_all.sh 9` from the project root)
- You should see: `with the subscription key: 200 | B-12 status: RUNNING`

### 5. Add an operation policy and the approval rule

Two operation-level policies. The first, a `rate-limit` of 1000 calls a minute on `asset-status`, shows the usual per-operation throttle. The second is the Azure substitute for an agent policy engine: a `choose`/`when` *policy expression* on the write tool that returns 403 unless the request carries an `x-approval-id` header. The check shows both sides: without the header the call never reaches the function; with it, it does (and the function, which has no approved ledger row for that id, still refuses: defence in depth, you will build the ledger in chapter 5).

- File: [`policies.py`](./policies.py)
- Run: `python policies.py` (or `./run_all.sh 9` from the project root)
- You should see: `write tool without x-approval-id: 403`

### 6. Expose the tools as an MCP server

MCP (Model Context Protocol) is how agent frameworks discover tools. APIM can publish an existing REST API as an MCP server: create a second API of type `mcp` whose source is `tools`, and its operations become MCP tools. Then speak plain JSON-RPC 2.0 to it: `tools/list` to discover, `tools/call` to run one.

- File: [`mcp_server.py`](./mcp_server.py)
- Run: `python mcp_server.py` (or `./run_all.sh 9` from the project root)
- You should see: `| status: RUNNING`

## It works when

- catalogue lists the operations
- read tool reaches the function
- write tool denied without an approval id
- tools/list and tools/call work
