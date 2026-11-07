# Sample run: real model, all three drivers

Recorded 2026-11-07 with `./run_demo.sh --run --runs 3` (3 drivers x 3 scenarios x 3 runs = 27 runs per pass). Nothing is faked: the SDKs
(boto3 `bedrock-runtime`, google-genai `vertexai=True`, `openai.AzureOpenAI`) talk over real HTTP to `core.wire_ingress`, which talks to a real
**Ollama** serving **qwen2.5:3b** (Q4_K_M, 1.9 GB) for chat and **nomic-embed-text** (274 MB) for embeddings. Database: local JSON file, reset before each run.

Host: Apple-silicon MacBook, 16 GB RAM. That is **not** a booster (2 vCPU / 8 GB), so two passes were made:

* **Pass A, laptop GPU (Metal):** the default Ollama configuration. Shows the best case.
* **Pass B, CPU-only, 2 threads:** a derived model with `num_gpu 0` / `num_thread 2`. A closer proxy for a booster, but still an
  optimistic one: Apple performance cores are much faster than a shared cloud vCPU, so real boosters will be slower still.

## Result

| Driver | Pass A: runs OK | Pass B: runs OK | Pass B step 1 (call the tool) median / max | Pass B step 2 (final answer) median / max | Pass B total per question median / max |
|---|---|---|---|---|---|
| `agent_aws.py` (Converse) | 9/9 | 9/9 | 3.4 s / 23.5 s* | 12.2 s / 17.2 s | 16.4 s / 35.3 s* |
| `agent_gcp.py` (Vertex) | 9/9 | 9/9 | 3.6 s / 7.7 s | 12.4 s / 18.1 s | 17.5 s / 23.4 s |
| `agent_azure.py` (AzureOpenAI) | 9/9 | 9/9 | 3.3 s / 6.9 s | 13.2 s / 14.0 s | 16.9 s / 18.4 s |

\* the very first request of the pass includes loading the model into memory.
Pass A medians: step 1 1.3-2.1 s, step 2 2.4-3.7 s, 4.4-6.5 s per question.

"OK" means: the expected tool was called (`order-status` -> `get_order_status`, `kb-search` -> `search_kb`, `damaged-ticket` -> `create_ticket`) and the
final answer contains a fact from the tool result (the carrier/status, the reset steps, the ticket). **54/54 runs passed.**

**What did not happen (read this before trusting the table):** no malformed tool call, no skipped tool, no wrong tool, no retry that we could see,
no timeout. Every run was exactly 2 steps (one tool call, one answer). So the table says "a 3B model reliably handles three clearly-worded, single-tool
questions through all three cloud wires", not "3B models are reliable agents". We did not instrument whether the seam's prompt-translation / retry
path fired (Ollama advertises native tool support for this model, so the native path was most likely used throughout); harder prompts (two tools in
one question, ambiguous order ids, nested arguments) were not tried and are where small models are expected to fail. In the unit tests with a fake
backend the seam's fallback is covered (`tests/conformance/test_ai_sdk_tools.py`, `test_local_llm_seam.py`), not here.

Wall-clock is dominated by step 2 on CPU (the model re-reads system prompt + tool schemas + the call + the result before writing the answer), matching the
5-30 s per step expectation in the audit; step 1 is cheaper because the generated output is short.

## Transcripts (Pass B, CPU-only, via `agent_azure.py`; the other drivers produce the same tool calls)

**order-status** - "Where is my order A1001?"
```
step 1  4.6s  tool call: get_order_status {"order_id": "A1001"}
tool result:  {"order_id": "A1001", "status": "shipped", "carrier": "UPS", "tracking": "1Z999AA10123456784", "eta": "2026-11-12", "items": ["USB-C dock"]}
step 2 13.4s  answer: Your order A1001 has been shipped. It's being transported by UPS with tracking number 1Z999AA10123456784.
              It is expected to arrive on November 12, 2026. Your order includes a USB-C dock.
```

**kb-search** - "How do I reset my password?"
```
step 1  3.3s  tool call: search_kb {"query": "reset password"}
tool result:  method=vector-search; top hit "Reset your password" score 0.803, next "Invoices and receipts" 0.46 (nomic-embed-text embeddings, cosine)
step 2 13.4s  answer: To reset your password, open Settings, choose Security and click 'Forgot password'. A reset link is emailed and expires in 30 minutes. ...
```

**damaged-ticket** - "My order A1002 arrived damaged, please open a support ticket for it."
```
step 1  6.9s  tool call: create_ticket {"priority": "high", "order_id": "A1002", "summary": "Damaged order A1002"}
tool result:  {"ticket_id": "T-207CB2", "summary": "Damaged order A1002", "priority": "high", "order_id": "A1002", ...}   (appended to the JSON db)
step 2 10.3s  answer: I have opened a support ticket T-207CB2 for your damaged order A1002. A human agent will be in touch with you shortly ...
```

Same questions on the other wires (Pass B): Bedrock Converse produced `toolUse` blocks with `stopReason: tool_use` and finished with `end_turn`; Vertex returned
`functionCall` parts and accepted `functionResponse`; Azure returned `finish_reason: tool_calls` with `tool_calls[0].function.arguments` JSON. Identical arguments
on all three in all runs shown above (temperature 0); wording of the final answer varied slightly between runs.

Full per-step traces (tool results included) are written by `./run_demo.sh --run --runs 3 --out DIR` as `aws.json`, `gcp.json`, `azure.json`.

## Caveats

* One machine, one model, one day, easy scenarios. Re-measure on a real booster before promising latency.
* Titan/Vertex/Azure embeddings were all served by nomic-embed-text (768-d, truncated by the seam to the requested 512 for Titan); `search_kb` reported `vector-search`, not the keyword fallback.
* The CI test (`tests/conformance/test_example_agent_workflow.py`) uses a scripted fake model and says so; it is not evidence about model quality.
