"""Hand-authored operations for scripts/gen_nano_docs.py (EXTRAS).

Operations whose wire is not derivable from botocore / discovery docs / ARM CRUD probing: the Gemini Developer API alias,
Azure OpenAI Responses + Assistants, Resource Graph, Activity-log export, Log Analytics export/purge, Defender automations.

Each op carries its own runnable snippets ("s": [[label, code], ...]); "{EP}" is replaced with the console endpoint at
render time (wasm/nano-docs.js).  "llm": true marks calls that need the local model (`vyomi llm start`); every other wire
here answers on the Nano router (checked by `gen_nano_docs.py --verify-extras`).
"""
import json

SUB = "00000000-0000-0000-0000-cloudlearn01"
SCOPE = "/subscriptions/" + SUB
RG = SCOPE + "/resourceGroups/my-rg"
STORE = RG + "/providers/Microsoft.Storage/storageAccounts/mystorage"
WS = RG + "/providers/Microsoft.OperationalInsights/workspaces/my-workspace"
ARM_PY_CRED = ("from azure.core.credentials import AccessToken\n\nclass DevCredential:   # the simulator accepts any token\n"
               "    def get_token(self, *scopes, **kw):\n        return AccessToken(\"dev\", 4102444800)\n")


def _j(b):
    return json.dumps(b, separators=(",", ":"))


def az_op(n, method, url, d, body=None, out=None, extra=None):
    rest = 'az rest --skip-authorization-header --headers "Authorization=Bearer dev" --method %s \\\n  --url "{EP}%s"' % (method.lower(), url)
    curl = 'curl -s -X %s "{EP}%s" \\\n  -H "Authorization: Bearer dev"' % (method, url)
    py = 'import requests\n\nr = requests.%s("{EP}%s",\n    headers={"Authorization": "Bearer dev"}%s)\nprint(r.status_code, r.json() if r.content else "")' % (
        method.lower(), url, (",\n    json=" + json.dumps(body)) if body is not None else "")
    if body is not None:
        rest += " \\\n  --body '%s'" % _j(body)
        curl += " \\\n  -H 'Content-Type: application/json' \\\n  -d '%s'" % _j(body)
    return {"n": n, "m": method, "u": url, "w": "%s %s" % (method, url), "d": d, "in": body, "out": out or {}, "p": [],
            "s": [["Azure CLI (az rest)", rest]] + (extra or []) + [["Python (requests)", py], ["curl (ARM REST)", curl]], "llm": False}


def aoai(path, name, method, d, body, out, py, llm=False, ver="2025-03-01-preview"):
    url = path + "?api-version=" + ver
    sdk = 'from openai import AzureOpenAI\n\nclient = AzureOpenAI(azure_endpoint="{EP}", api_key="test", api_version="%s")\n%s' % (ver, py)
    curl = 'curl -s -X %s "{EP}%s" \\\n  -H "api-key: test" -H "Content-Type: application/json"' % (method, url)
    if body is not None:
        curl += " \\\n  -d '%s'" % _j(body)
    js = ('import { AzureOpenAI } from "openai";\n\nconst client = new AzureOpenAI({ endpoint: "{EP}", apiKey: "test", apiVersion: "%s" });\n// REST: %s %s' % (ver, method, url))
    return {"n": name, "m": method, "u": url, "w": "%s %s" % (method, url), "d": d, "in": body, "out": out, "p": [], "llm": llm,
            "s": [["Python (openai SDK)", sdk], ["JavaScript (openai)", js], ["curl (wire)", curl]]}


GEM_PY = ('from google import genai\nfrom google.genai import types\n\nclient = genai.Client(api_key="test",\n'
          '    http_options=types.HttpOptions(base_url="{EP}"))   # Gemini Developer API alias of the Vertex seam\n')


def gem(name, method, path, d, body, out, py, llm=False):
    curl = 'curl -s -X %s "{EP}%s" \\\n  -H "x-goog-api-key: test"' % (method, path)
    if body is not None:
        curl += " \\\n  -H 'Content-Type: application/json' \\\n  -d '%s'" % _j(body)
    js = 'import { GoogleGenAI } from "@google/genai";\n\nconst ai = new GoogleGenAI({ apiKey: "test", httpOptions: { baseUrl: "{EP}" } });\n// REST: %s %s' % (method, path)
    return {"n": name, "m": method, "u": path, "w": "%s %s" % (method, path), "ex": path, "d": d, "in": body, "out": out, "p": [], "llm": llm,
            "s": [["Python (google-genai)", GEM_PY + py], ["JavaScript (@google/genai)", js], ["curl (REST)", curl]]}


M = "gemini-2.0-flash"
GEMINI_OPS = [
    gem("models.list", "GET", "/v1beta/models", "List the Gemini and embedding models served by the local-model seam.", None,
        {"models": [{"name": "models/" + M}]}, "for m in client.models.list():\n    print(m.name)"),
    gem("models.get", "GET", "/v1beta/models/" + M, "Get one model.", None, {"name": "models/" + M},
        'print(client.models.get(model="%s"))' % M),
    gem("models.generateContent", "POST", "/v1beta/models/%s:generateContent" % M, "Generate a response (needs the local LLM: `vyomi llm start`).",
        {"contents": [{"parts": [{"text": "Say hello"}]}]}, {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]},
        'resp = client.models.generate_content(model="%s", contents="Say hello")\nprint(resp.text)' % M, llm=True),
    gem("models.streamGenerateContent", "POST", "/v1beta/models/%s:streamGenerateContent?alt=sse" % M, "Streamed generation (SSE).",
        {"contents": [{"parts": [{"text": "Count to 3"}]}]}, {"candidates": []},
        'for chunk in client.models.generate_content_stream(model="%s", contents="Count to 3"):\n    print(chunk.text, end="")' % M, llm=True),
    gem("models.countTokens", "POST", "/v1beta/models/%s:countTokens" % M, "Count tokens for a prompt.",
        {"contents": [{"parts": [{"text": "Say hello"}]}]}, {"totalTokens": 3},
        'print(client.models.count_tokens(model="%s", contents="Say hello"))' % M, llm=True),
    gem("models.embedContent", "POST", "/v1beta/models/text-embedding-004:embedContent", "Embed one text.",
        {"content": {"parts": [{"text": "hello"}]}}, {"embedding": {"values": [0.1]}},
        'print(client.models.embed_content(model="text-embedding-004", contents="hello"))', llm=True),
    gem("models.batchEmbedContents", "POST", "/v1beta/models/text-embedding-004:batchEmbedContents", "Embed several texts.",
        {"requests": [{"content": {"parts": [{"text": "a"}]}}, {"content": {"parts": [{"text": "b"}]}}]}, {"embeddings": [{"values": [0.1]}]},
        'print(client.models.embed_content(model="text-embedding-004", contents=["a", "b"]))', llm=True),
]

AOAI_OPS = [
    aoai("/openai/responses", "Responses: create", "POST", "Create a response (needs the local LLM: `vyomi llm start`).",
         {"model": "gpt4o", "input": "Say hello"}, {"id": "resp_...", "object": "response", "output": []},
         'resp = client.responses.create(model="gpt4o", input="Say hello")\nprint(resp.output_text)', llm=True),
    aoai("/openai/responses/{response_id}", "Responses: get / delete", "GET", "Retrieve (GET) or delete (DELETE) a stored response.",
         None, {"id": "resp_..."}, 'print(client.responses.retrieve("resp_..."))'),
    aoai("/openai/assistants", "Assistants: create", "POST", "Create an assistant bound to a deployment (the model is the deployment name).",
         {"model": "gpt4o", "name": "helper", "instructions": "Be brief."}, {"id": "asst_...", "object": "assistant"},
         'a = client.beta.assistants.create(model="gpt4o", name="helper", instructions="Be brief.")\nprint(a.id)', ver="2024-05-01-preview"),
    aoai("/openai/threads", "Threads: create", "POST", "Create a conversation thread.", {}, {"id": "thread_...", "object": "thread"},
         't = client.beta.threads.create()\nprint(t.id)', ver="2024-05-01-preview"),
    aoai("/openai/threads/{thread_id}/runs", "Runs: create", "POST", "Run an assistant on a thread (needs the local LLM).",
         {"assistant_id": "asst_..."}, {"id": "run_...", "status": "queued"},
         'run = client.beta.threads.runs.create_and_poll(thread_id="thread_...", assistant_id="asst_...")\nprint(run.status)', llm=True, ver="2024-05-01-preview"),
]

_AUTO_BODY = {"location": "eastus", "properties": {
    "isEnabled": True, "scopes": [{"description": "sub", "scopePath": SCOPE}], "sources": [{"eventSource": "Alerts", "ruleSets": []}],
    "actions": [{"actionType": "LogicApp", "logicAppResourceId": RG + "/providers/Microsoft.Logic/workflows/wf1", "uri": "https://example.logic.azure.com/x"}]}}

# (cloud, console service id) -> {"title","category" (new service only), "api": {...}}
EXTRAS = {
    ("gcp", "gemini"): {"title": "Gemini Developer API", "category": "AI and Machine Learning", "api": {
        "id": "generativelanguage", "version": "v1beta", "title": "Gemini Developer API (generativelanguage.googleapis.com alias)", "ops": GEMINI_OPS}},
    ("azure", "cognitiveservices"): {"api": {
        "id": "azure-openai-dev", "title": "Azure OpenAI data plane: Responses + Assistants (needs a deployment on an OpenAI account)", "ops": AOAI_OPS}},
    ("azure", "eventgrid"): {"api": {"id": "resource-graph", "title": "Azure Resource Graph (Microsoft.ResourceGraph/resources)", "ops": [
        az_op("Resources: query", "POST", SCOPE + "/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01",
              "Run a KQL-subset query (Resources / ResourceContainers; where, project, limit, order by, count) over the ARM store.",
              {"query": "Resources | where type =~ 'microsoft.eventgrid/topics' | project name, location | limit 5"},
              {"totalRecords": 1, "count": 1, "data": {"columns": [], "rows": []}},
              extra=[["Azure CLI (graph extension)", 'az extension add -n resource-graph\naz graph query -q "Resources | project name, type | limit 5"   # after `az cloud set` to this environment']]),
    ]}},
    ("azure", "monitor"): {"api": {"id": "activity-log-export", "title": "Activity-log export (subscription diagnostic settings)", "ops": [
        az_op("Diagnostic settings: create (activity-log export)", "PUT", SCOPE + "/providers/Microsoft.Insights/diagnosticSettings/actlog?api-version=2021-05-01-preview",
              "Export the subscription Activity Log to a storage account in this environment (the destination must exist).",
              {"properties": {"storageAccountId": STORE, "logs": [{"category": "Administrative", "enabled": True}, {"category": "Security", "enabled": True}]}},
              {"name": "actlog", "type": "Microsoft.Insights/diagnosticSettings"},
              extra=[["Azure CLI (native)", "az monitor diagnostic-settings subscription create --name actlog --location global \\\n  --storage-account " + STORE + " \\\n  --logs '[{\"category\":\"Administrative\",\"enabled\":true}]'"]]),
        az_op("Diagnostic settings: list", "GET", SCOPE + "/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview",
              "List the subscription's activity-log export settings.", None, {"value": []}),
    ]}},
    ("azure", "loganalytics"): {"api": {"id": "law-export-purge", "title": "Log Analytics data export + purge", "ops": [
        az_op("Data exports: create", "PUT", WS + "/dataExports/my-export?api-version=2020-08-01", "Continuously export tables to a storage account.",
              {"properties": {"destination": {"resourceId": STORE}, "tableNames": ["Heartbeat"], "enable": True}}, {"name": "my-export"},
              extra=[["Azure CLI (native)", "az monitor log-analytics workspace data-export create -g my-rg --workspace-name my-workspace -n my-export \\\n  --tables Heartbeat --destination " + STORE]]),
        az_op("Purge", "POST", WS + "/purge?api-version=2020-08-01", "Delete rows matching filters (async: returns an operationId).",
              {"table": "Heartbeat", "filters": [{"column": "TimeGenerated", "operator": "<", "value": "2026-01-01T00:00:00Z"}]}, {"operationId": "purge-..."}),
    ]}},
    ("azure", "defender"): {"api": {"id": "defender-automations", "title": "Defender for Cloud workflow automations (Microsoft.Security/automations)", "ops": [
        az_op("Automations: create or update", "PUT", RG + "/providers/Microsoft.Security/automations/my-automation?api-version=2023-12-01-preview",
              "Trigger a Logic App when Defender alerts are raised (matches on the alerts the detector emits).", _AUTO_BODY,
              {"name": "my-automation", "type": "Microsoft.Security/automations"},
              extra=[["Python (azure-mgmt-security)", "from azure.mgmt.security import SecurityCenter\n" + ARM_PY_CRED + "\nclient = SecurityCenter(DevCredential(), \"" + SUB + "\", base_url=\"{EP}\",\n    credential_scopes=[\"https://management.azure.com/.default\"])\nfor a in client.automations.list_by_resource_group(\"my-rg\"):\n    print(a.name)   # create: client.automations.create_or_update(\"my-rg\", \"my-automation\", {...})"]]),
        az_op("Automations: list", "GET", SCOPE + "/providers/Microsoft.Security/automations?api-version=2023-12-01-preview", "List automations in the subscription.", None, {"value": []}),
    ]}},
}

# wire checks used by --verify-extras: (method, path-with-query, body, headers, ok-statuses)
VERIFY_SETUP = [
    ("PUT", RG + "?api-version=2021-04-01", {"location": "eastus"}),
    ("PUT", STORE + "?api-version=2023-05-01", {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}),
    ("PUT", WS + "?api-version=2022-10-01", {"location": "eastus", "properties": {}}),
    ("PUT", RG + "/providers/Microsoft.CognitiveServices/accounts/oai1?api-version=2023-05-01", {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {}}),
    ("PUT", RG + "/providers/Microsoft.CognitiveServices/accounts/oai1/deployments/gpt4o?api-version=2023-05-01",
     {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-05-13"}}}),
]
