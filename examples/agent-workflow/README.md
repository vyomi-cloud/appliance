# Sample agent workflow: support triage on Vyomi

A small tool-calling agent you can copy. It answers customer messages with three plain-Python tools and is written against the
**native cloud SDKs, unchanged** - only the endpoint differs from production.

| File | What it is |
|---|---|
| `triage_tools.py` | the shared part: `get_order_status`, `search_kb` (embeddings + cosine search), `create_ticket`, a JSON "database" (local file, or an S3 object), the system prompt, 3 scenarios, a CLI |
| `agent_aws.py` | boto3 `bedrock-runtime` **Converse** tool loop (`toolUse` / `toolResult`), Titan embeddings (primary) |
| `agent_aws_guardrails.py` | boto3 Guardrails (CreateGuardrail / ApplyGuardrail / Converse `guardrailConfig`) + real `InvokeModelWithResponseStream` token streaming (Dev Simplified filters) |
| `agent_gcp.py` | `google-genai` with `vertexai=True`, manual function-calling loop, `text-embedding-005` |
| `agent_azure.py` | `openai.AzureOpenAI` `tools=` loop, embeddings deployment |
| `run_demo.py` / `run_demo.sh` | starts the local Vyomi AI wire server (`core.wire_ingress`) in front of a real local model and can run all three agents |
| `SAMPLE-RUN.md` | real transcripts, timings and failure rates from running these on a real model |

The tools: `get_order_status(order_id)`, `search_kb(query)` (the knowledge-base articles are embedded once, vectors cached in the
database, query ranked by cosine similarity - a tiny local vector search), `create_ticket(summary, priority, order_id)`.
Database: `./triage_db.json` (or `$TRIAGE_DB_FILE`); set `TRIAGE_DB_S3_BUCKET` to keep it in an S3 object in the simulator instead.

The loop in every driver is the standard one: send messages + tool specs, if the model returns a tool call run it and send the result
back, stop when it answers in text (max 6 steps). Bad tool names/arguments are returned to the model as an error result instead of
crashing, which is what lets a small model recover.

## Run it

```bash
pip install -r requirements.txt boto3 google-genai openai      # from the repo root
ollama serve &                                                  # any OpenAI-compatible local server works (llama.cpp: llama-server --jinja)
ollama pull qwen2.5:3b && ollama pull nomic-embed-text
cd examples/agent-workflow
./run_demo.sh --run --runs 3          # starts the wire server on a free port, runs 3 drivers x 3 scenarios x 3 runs, prints transcripts
./run_demo.sh                         # or: just serve, and print the endpoint to export
```

`run_demo.py` serves the same `core.wire_ingress` router the offline appliance serves (see `tests/conformance/test_ai_sdk_tools.py`, which
does the same with a fake model), points the seam (`core/llm_core.py`) at your local model, and registers `nomic-embed-text` as the
embedding model (otherwise the seam would reuse the chat model for embeddings). It also creates an Azure OpenAI account with `chat` and
`embed` deployments.

### Against the offline appliance
Boot the appliance with the AI pack enabled (the `vyomi-llm` container, `VYOMI_LLM_ENDPOINT`), then:
```bash
export VYOMI_ENDPOINT=http://localhost:<appliance port>
python agent_aws.py "Where is my order A1001?"     # also agent_gcp.py / agent_azure.py; no argument = the 3 built-in scenarios
```
Azure: create an Azure OpenAI account and a chat deployment (name it `chat`, or set `AZURE_OPENAI_DEPLOYMENT`) and an embeddings
deployment (`embed`, or `AZURE_OPENAI_EMBED_DEPLOYMENT`). If the account advertises its own endpoint (`/azure-data/openai/<account>`),
set `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY`.

### Against the Nano tunnel
Nano's AI engines run in your browser tab; local SDK calls reach them through `vyomi-tunnel` (the tab registers on
`ws://127.0.0.1:8090/register`, the tunnel forwards your SDK's HTTP calls to the tab). Start the tunnel, keep the Nano tab open and set
`VYOMI_ENDPOINT` to the URL the tunnel prints. NOT verified by this sample: the Nano tab has no 3B-class model today, so expect the
plumbing to work and the model to be far weaker than below. See the Nano docs for the tunnel's current port and limitations.

### Against a booster
A booster is a 2-core / 8 GB compute+AI appliance (Codespaces `basicLinux32gb`-class host, only the booster services). It binds the same
endpoints on its own port; export `VYOMI_ENDPOINT` to the booster URL (local `<id>.local.vyomi.cloud` -> 127.0.0.1, or the relay URL).
Nothing in the example changes. NOT verified here either: this sample was run on a laptop, not a booster.

## Model recommendations (from `docs/architecture/v4.0/AI-PACK-AUDIT.md` section 3)

| Role | Model | Notes |
|---|---|---|
| **Default tool-calling agent** | **Qwen2.5-3B-Instruct Q4_K_M** (~2 GB) | what this sample is run with; est. 4-7 tok/s on 2 vCPU |
| Smoke tests | Qwen2.5-1.5B or Llama-3.2-1B Q4 | faster, tool calls flakier |
| Higher fidelity (opt-in) | Qwen2.5-7B Q4 (~4.7 GB) | does not fit comfortably on 8 GB next to compute; minutes per agent loop |
| Embeddings | nomic-embed-text v1.5 (274 MB) or bge-small-en-v1.5 (~130 MB) | replaces the labelled hash fallback |

**The 8 GB / Qwen2.5-3B-Q4 decision:** the booster host has 8 GB; the AI share of the capped budget has to leave room for the compute
engines (the booster docs budget ~5 GB for compute containers). A 3B model at Q4 is ~2 GB of weights plus KV cache at `-c 4096-8192`,
so it fits with an embedding model loaded beside it, while a 7B Q4 does not. CPU speed, not RAM, is the constraint.

## Honest expectations

- **Speed.** On a 2-core CPU expect roughly 5-30 s per agent step with a 3B model (prompt processing dominates: every step re-sends the
  system prompt, the tool schemas and the history). A typical triage question is 2 steps (tool call, then answer). `SAMPLE-RUN.md` has
  measured numbers: a laptop GPU is several times faster than a booster; the CPU-limited pass is the closer proxy.
- **Flakiness.** 1-3B models sometimes skip the tool and answer from imagination, print the call as text, emit malformed JSON, pick the wrong
  tool or invent argument values. Parallel tool calls and nested schemas fail more often. This is a good way to test that *your* loop handles
  tool_use/toolResult, retries and error results; it is not a way to measure agent quality.
- **What the seam does about it** (`core/llm_core.py`): it uses the backend's native tool calling first; if the backend rejects tools, or
  returns a call to an unknown tool / arguments that fail the JSON schema, it falls back to *prompt translation* - a JSON "tool envelope"
  produced under **constrained decoding** (`response_format` json_schema, which llama.cpp turns into a grammar) - validates the result
  against your schema, and re-asks up to `MAX_RETRIES = 2` times with the rejection reason. A model that prints the call as plain text
  is recovered by parsing it. If it still cannot produce a valid call you get the cloud's real error (Bedrock `ModelErrorException`,
  Vertex `INTERNAL`, Azure 500 `model_error`) - never a canned answer - so put a retry / fallback in your driver for production-style code.
  It cannot fix a model that chooses the *wrong* tool or wrong values with a perfectly valid call.
- Temperature is 0 in the drivers; runs are still not guaranteed identical.

## Tests

`tests/conformance/test_example_agent_workflow.py` imports and runs all three drivers end to end through the wire server. **Its model is a
scripted fake** (CI cannot run a 3B model); it proves the example code and wire plumbing only. Real-model results: `SAMPLE-RUN.md`.

## More agent lanes (Dev Simplified, same seam)
- **Gemini Developer API**: `genai.Client(api_key="x", http_options=types.HttpOptions(base_url=ENDPOINT))` - generateContent, streaming, function calling, embeddings, `models.list/get`.
- **Azure OpenAI Responses + Assistants**: `AzureOpenAI(...).responses.create(...)` (tools, `previous_response_id`, streaming) and `client.beta.assistants/threads/runs` (function tools, `submit_tool_outputs`).
- Limits are listed per lane in `core/capabilities/*` and proven by `tests/conformance/test_ai_agent_lanes.py`.
- **Hosted agents (Bedrock AgentCore Runtime + Vertex AI Agent Engine)**: `agent_hosted_spec.py` runs one *Vyomi agent spec* (JSON instructions + declarative tools, executed in-process over the local model) through boto3 `bedrock-agentcore-control`/`bedrock-agentcore` `invoke_agent_runtime` and the `reasoningEngines` `:query`/`:streamQuery` REST/gapic API. Containers and pickled classes are not run; proven by `tests/conformance/test_ai_agent_runtimes.py`.
