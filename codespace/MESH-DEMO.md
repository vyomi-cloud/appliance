# Facilities agent demo (Vyomi Mesh, Beta)

A reference app written against the real AWS SDK (boto3) that exercises all 13 components of the "Agentic AI on AWS Bedrock"
architecture (Cognito, API Gateway + WAF, AgentCore runtime/gateway/memory, Bedrock KB + guardrails, Step Functions approval,
X-Ray, KMS/CloudTrail) on your Mesh. Sources: `examples/enterprise-facilities-agent/`.

## Run

```bash
bash .devcontainer/mesh/vyomi-agent-demo          # or: vyomi-agent-demo, once the Mesh is ready
bash .devcontainer/mesh/vyomi-agent-demo -- --only 5,6   # a subset
```

First run creates a Python venv and installs boto3, langgraph, fastapi, uvicorn (about a minute, needs PyPI). It finds your Mesh
simulator itself and sets `AWS_ENDPOINT_URL`; any dummy credentials work. Use `--endpoint URL` to target another endpoint
(for example a vyomi-tunnel forward from your laptop).

## What to expect

A step-by-step transcript, then a table of the 13 components (PASS / BLOCKED / FAIL) and the agent's cited answer. Results are written to
`examples/enterprise-facilities-agent/results/` (`report.html`). Exit code 0 only if all 13 PASS.

## Beta limits

- Small model (Qwen3-4B on llama.cpp, CPU). Routing and answers are modest; model quality is not what is being tested. The first
  run waits for the model download; if the model is not ready, model-dependent steps show BLOCKED, not PASS.
- Dev Simplified: IAM and policy enforcement are simplified, not production-faithful.
- 16 GB class machine: the model, the simulator and your instances share it; a run takes several minutes.
