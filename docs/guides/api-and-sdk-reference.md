# API reference and SDK and CLI usage (Nano and the offline appliance)

Every cloud console has two generated views, backed by `wasm/docs/` (rendered by `wasm/nano-docs.js`):

- **API reference** - each service, every operation that really answers on the simulator, wire request, parameters, response example, and copy-paste snippets for the cloud's own CLI and SDKs (boto3 / `aws`, google-api-python-client / `gcloud` / `google-genai`, azure-mgmt / `az`), pointed at your endpoint.
- **SDK and CLI usage** - one card per service with CLI, Python, JavaScript and curl.

Regenerate after adding or changing a service:

```
pip install botocore google-api-python-client
python3 scripts/gen_nano_docs.py                 # rewrites wasm/docs/** (deterministic)
python3 scripts/gen_nano_docs.py --verify-extras # sends every hand-authored op to the Nano router
```

How a service gets documented:

| Cloud | Source of operations | Where to add a new service |
| --- | --- | --- |
| AWS | botocore models, each op probed against `core/aws_wire_router.py` | `AWS_MAP` in `scripts/gen_nano_docs.py` (unmapped wired APIs appear automatically as `api-<service>`) |
| GCP | Google discovery documents, each method probed | `GCP_MAP` (+ `GCP_EXTRA_SERVICES` for services without a console page) |
| Azure | ARM resource types probed for list/get/put/delete | `AZ_MAP`, `AZ_SDK`, `AZ_EXTRA_SERVICES` |
| Anything without a discovery/botocore model | hand-authored ops with their own snippets | `scripts/nano_docs_extras.py` (`EXTRAS`) |

## Services added in v4 and where they are documented

AWS: Redshift (cluster API + Redshift Data API), X-Ray, EC2 Instance Connect, CloudFront (under S3), Glue and DMS (under RDS), SSM, EventBridge v2, IAM toolbox, Lambda core / web / microvms, Bedrock (Guardrails, converse-stream and the agent/runtime APIs).

GCP: Vertex AI (v1 and v1beta1), Binary Authorization, BigQuery, Cloud Functions (v1 and v2), Cloud DNS, Security Command Center, Cloud Trace, Compute, and the Gemini Developer API alias.

Azure: Defender for Cloud (workflow automations, pricings), Monitor (action groups, activity-log alerts, autoscale, scheduled-query rules, DCRs, workbooks, Grafana), Activity-log export (subscription diagnostic settings), Log Analytics data export and purge, Resource Graph query, Azure OpenAI Responses and Assistants, Stream Analytics, network firewall policies / DDoS / Network Watcher, locks, App Service certificates, Cache for Redis, AI Search, Logic Apps.

## Runnable examples for the AI services

Operations that call a model need the local LLM (`vyomi llm start` on the offline appliance); they answer 503 until it runs. Everything else answers immediately.

```python
# Gemini Developer API alias (API-key auth) - same seam as Vertex AI
from google import genai
from google.genai import types
client = genai.Client(api_key="test", http_options=types.HttpOptions(base_url="http://127.0.0.1:8090"))
print([m.name for m in client.models.list()])
print(client.models.generate_content(model="gemini-2.0-flash", contents="Say hello").text)
```

```python
# Azure OpenAI Responses + Assistants (a deployment must exist on an OpenAI account)
from openai import AzureOpenAI
client = AzureOpenAI(azure_endpoint="http://127.0.0.1:8090", api_key="test", api_version="2025-03-01-preview")
print(client.responses.create(model="gpt4o", input="Say hello").output_text)
```

```bash
# Defender automation / activity-log export / Resource Graph, via az rest
az rest --skip-authorization-header --headers "Authorization=Bearer dev" --method post \
  --url "http://127.0.0.1:8090/subscriptions/00000000-0000-0000-0000-cloudlearn01/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01" \
  --body '{"query":"Resources | project name, type | limit 5"}'
```

Notes: Resource Graph supports a KQL subset (where, project, limit, order by, count; no joins or summarize). Calls that need a model are flagged in the console with the `vyomi llm start` hint.
