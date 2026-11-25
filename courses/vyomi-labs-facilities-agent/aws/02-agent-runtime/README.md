# Layer 2: Agent Runtime

_A supervisor agent and three sub-agents answering in isolated sessions_

**What you build:** Host a supervisor agent that routes work to Facilities, Maintenance and Analytics sub-agents, one isolated session at a time.

## Code, in order

### 1. Install the one dependency

The agent graph uses LangGraph; everything else is boto3, which you already have from chapter 10. On real AWS the dependency must also be vendored into the deployment zip (`pip install -t package langgraph`); the simulator's runtime host already has it from this install.

- File: [`install.sh`](./install.sh)

### 2. Write the gateway client

A tiny MCP-over-HTTP client for the AgentCore Gateway (chapter 4). The agent uses it when the gateway exists and falls back to calling the Lambda tools directly. The gateway authorizes with AWS_IAM, so requests are SigV4-signed for the `bedrock-agentcore` service.

- File: [`mcp_client.py`](./mcp_client.py)

### 3. Write the supervisor and the three sub-agents

One LangGraph StateGraph: the supervisor plans a route, then the Facilities agent (knowledge search), Maintenance agent (asset lookup and, for write requests, a human-approval workflow) and Analytics agent (work-order statistics) run in order, and the supervisor synthesises a cited answer. Tools come from the gateway when it exists, otherwise from the Lambda functions, otherwise the agent reports the tool as unavailable instead of failing. That is why you can deploy and test this chapter before the tools exist: chapters 7, 6, 4 and 5 light the tools up one by one.

- File: [`agents.py`](./agents.py)

### 4. Write the AgentCore entrypoint

The AgentCore Runtime contract is an HTTP agent: `POST /invocations` with the caller's payload, `GET /ping`. The runtime host wraps a plain `handler(payload, context)` function in that contract (with the bedrock-agentcore SDK you would write `@app.entrypoint` instead; the body is identical). The agent finds the simulator through the standard `AWS_ENDPOINT_URL` environment variable.

- File: [`agent_main.py`](./agent_main.py)

### 5. Package the agent and create the runtime

Zips the entrypoint (renamed main.py) with the agent modules, uploads the zip to S3, and calls CreateAgentRuntime with a code configuration (S3 zip + entry point). Then it polls GetAgentRuntime until the runtime is READY. Runtime names use underscores; the API rejects hyphens.

- File: [`deploy_runtime.py`](./deploy_runtime.py)
- Run: `python deploy_runtime.py` (or `./run_all.sh 2` from the project root)
- You should see: `runtime status READY`

### 6. Write a small helper to call the agent

Every later chapter talks to the agent through this helper: it looks the runtime up by name and wraps InvokeAgentRuntime. Keep the file; chapters 4, 5, 11 and 8 import it.

- File: [`ask_agent.py`](./ask_agent.py)

### 7. Invoke the hosted supervisor from two sessions

InvokeAgentRuntime sends the question to the agent running inside the runtime (a process of its own, not yours). Each runtimeSessionId (at least 33 characters) gets its own agent process, reused for later calls in the same session. At this point the tools do not exist yet, so the spans show the supervisor routing to all three sub-agents while the tool calls report `unavailable`; you will re-run this after chapters 7, 6 and 4.

- File: [`invoke_agent.py`](./invoke_agent.py)
- Run: `python invoke_agent.py` (or `./run_all.sh 2` from the project root)
- You should see: `the same session reuses its process: True`

### 8. Stop a session

StopRuntimeSession ends that session's agent process immediately (otherwise it idles out). The next call with that session id starts a fresh process.

- File: [`stop_session.py`](./stop_session.py)
- Run: `python stop_session.py` (or `./run_all.sh 2` from the project root)
- You should see: `runtime still READY`

### 9. Failure lab: a runaway agent hits its step budget

An agent that loops, or a question engineered to make it call every tool, must stop. The step limit is an environment variable of the runtime (so a caller cannot raise it). The block lowers the budget to two steps, asks the full question in a fresh session, and asserts the run stops with `step_budget`, does not start an approval or reach any tool it had no budget for, and says so in plain language; then it restores the limit and asserts the same question completes normally.

- File: [`runaway.py`](./runaway.py)
- Run: `python runaway.py` (or `./run_all.sh 2` from the project root)
- You should see: `runaway protection verified`

### 10. Least privilege for the agent's role

The runtime role is the agent's whole blast radius. Settle it from the audit log by running what the agent really does as that identity: call the model, retrieve from the knowledge base, ask the approval workflow, and check it may run the two read tools (a dry-run invoke, so nothing executes). Then assert the dangerous neighbours are refused: the write tool, deleting a work order, reading the approval ledger directly, and calling the approval API as the approver.

- File: [`iam_runtime.py`](./iam_runtime.py)
- Run: `python iam_runtime.py` (or `./run_all.sh 2` from the project root)
- You should see: `agent role verified`

## It works when

- facilities-supervisor exists and is READY
- InvokeAgentRuntime answers
- two session ids are isolated
