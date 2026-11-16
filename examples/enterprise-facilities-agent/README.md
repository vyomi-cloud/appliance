# Enterprise Facilities agent: reference application and end-to-end test

A facilities-management agent written the way a customer would write it, against the **real AWS SDK (boto3)** only. The same code runs on
real AWS by changing the endpoint and credentials. It exercises all 13 components of the "Agentic AI on AWS Bedrock" reference architecture
on a Vyomi simulator (Mesh appliance, or the in-process server used here).

```
user -> Cognito sign-in (JWT) -> API Gateway (Cognito authorizer) + WAF -> AgentCore Runtime
        supervisor + Facilities / Maintenance / Analytics sub-agents (LangGraph) + AgentCore Memory
     -> AgentCore Gateway (MCP tool catalog, Cedar policy) -> Lambda tools
          read-only: kb-search (Bedrock KB over OpenSearch), asset-status (DynamoDB)
          write: create-work-order behind Step Functions human approval (waitForTaskToken, SNS->SQS approver inbox, DynamoDB ledger)
     -> Bedrock Guardrails in/out + grounded, cited answer -> X-Ray/CloudWatch traces -> KMS + CloudTrail
```

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt      # boto3, langgraph, fastapi, uvicorn
# in-process simulator (needs the repo checkout; clean state every run, nothing else to start):
.venv/bin/python examples/enterprise-facilities-agent/run_e2e.py
# or against a running simulator / Mesh:
.venv/bin/python examples/enterprise-facilities-agent/run_e2e.py --endpoint http://localhost:8099
# against another checkout of the simulator code (e.g. an integration branch):
VYOMI_REPO=/path/to/checkout .venv/bin/python examples/enterprise-facilities-agent/run_e2e.py
```

Outputs `results/e2e-result.json` and `results/report.html` (open it in a browser; static, no build step). `python report.py results/e2e-result.json > r.html`
re-renders it. Exit code is 0 only if all 13 components PASS. `--only 5,6` runs a subset (it does not re-run dependencies).

## What you see

A transcript with every SDK-level step, a PASS / BLOCKED / FAIL line each, the agent run (route, tools, cited answer, work order created after approval), and a
summary table of the 13 components. **BLOCKED** = the simulator lacks a capability that another lane is building (the lane is named); **FAIL** = a real
discrepancy. Nothing is mocked and nothing blocked is reported as a pass.

## Layout

| path | what |
| --- | --- |
| `facilities/components/cNN_*.py` | one module per architecture component, plain boto3 calls |
| `facilities/agents.py` | supervisor + 3 sub-agents as a LangGraph StateGraph; tools are boto3-backed functions; model via Bedrock Converse |
| `facilities/lambdas/*.py` | the Lambda tool code (zipped and deployed with CreateFunction) |
| `facilities/mcp.py` | MCP-over-HTTP client for the AgentCore Gateway (SigV4, `bedrock-agentcore`) |
| `fixtures/` | SOP/manual documents, assets, work orders |
| `run_e2e.py`, `report.py`, `facilities/server.py` | harness, HTML report, in-process simulator launcher |

Resource names follow the cross-lane contract (`facilities-users`, `facilities-kb`, `facilities-gateway`, `work-order-approval`, `approval-ledger`, `approver-inbox`,
`facilities-guardrail`). AgentCore runtime and memory names use underscores (`facilities_supervisor`, `facilities_memory`) because the real API rejects hyphens there.

## Notes and honest limits

- With no reachable model (`VYOMI_LLM_ENDPOINT`, Mesh AI pack or Nano WebLLM) the supervisor routes with keyword rules and the answer is extractive; the report says so.
  Converse, tool-use and RetrieveAndGenerate steps are BLOCKED until a model is reachable. Model quality is a non-goal.
- Only one S3 bucket can be created on the default plan, so documents, audit objects and the CloudTrail prefix share `facilities-docs`.
- The gateway data plane is addressed on the simulator endpoint; on AWS use the `gatewayUrl` (see `facilities/mcp.py`).
- The Lambdas find the simulator through the standard `AWS_ENDPOINT_URL` environment variable set on the function.
