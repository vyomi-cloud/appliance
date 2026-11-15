# v4/ai-refapp: Facilities reference application + e2e

Owner: AI session (lane refapp). Base: origin/v4-on-main. Purpose: the application the owner can SEE, written against real boto3, covering the 13 components.
Code: `examples/enterprise-facilities-agent/` (README there). Run: `python examples/enterprise-facilities-agent/run_e2e.py`.

| need | chosen OSS / approach | substrate | why |
| --- | --- | --- | --- |
| agent framework | LangGraph (MIT, pure Python, ~50 MB with deps) | app code, not a backend | brief: no custom framework; Strands pulls more deps |
| tools | boto3 Lambdas + DynamoDB | any | real SDK, runs unchanged on AWS |
| MCP client | stdlib urllib + botocore SigV4 | any | gateway speaks JSON-RPC over HTTP |
| report | static HTML generated from JSON | any | no build step |

Tests: the e2e itself (`run_e2e.py`), 13 components, about 60 steps. Results recorded in the branch report (trunk vs all lanes merged locally).
Declared limits: see README. Open: S3 event to Lambda delivery, InvokeAgentRuntime of a real container, model-backed steps (no model reachable), KMS wrong-context decrypt accepted, ListFoundationModels lacks Anthropic/Titan ids.
