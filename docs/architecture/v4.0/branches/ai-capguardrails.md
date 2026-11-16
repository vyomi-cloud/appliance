# Branch: v4/ai-capguardrails

Owner: AI session (capguardrails lane). Base: `v4/ai-integration` (20c01eaa3). Purpose: close the "Dev Simplified" limitations of `bedrock.guardrails`
(`core/bedrock_guardrails_core.py`, mirrored to `wasm/core/`). PII/regex/word/topic behaviour is untouched.

## What changed
| Limitation | Now |
|---|---|
| ConverseStream / InvokeModel check input only | Converse, ConverseStream, InvokeModel, InvokeModelWithResponseStream judge input and output. Invoke takes the real `X-Amzn-Bedrock-Guardrail{Identifier,Version}` / `-Trace` headers (boto3 `guardrailIdentifier`, `guardrailVersion`, `trace`) and returns `amazon-bedrock-guardrailAction` (+ `amazon-bedrock-trace`). |
| stream output not re-checked | `guard_events()` wraps the seam event stream: `streamProcessingMode=sync` (default) holds each ~1000-char window until judged (replace with blocked messaging, mask ANONYMIZE, end with `guardrail_intervened`); `async` streams at once and only reports in the metadata trace. |
| contextual grounding rejected | (already present from the approvals lane) GROUNDING/RELEVANCE with threshold+score in ApplyGuardrail; new: Converse `guardContent` blocks with `grounding_source`/`query`/`guard_content` qualifiers drive grounding on the model output. |
| strength levels | LOW/MEDIUM/HIGH honoured against a confidence (keyword hits; plus embedding-prototype score when a real embedder answers). |
| process-local state | State is in `store.account["bedrock_guardrails"]` (space-scoped persisted account bag, same mechanism as Bedrock Agents); the wire router binds the store on every Bedrock call. |

## OSS choices
| Need | Chosen | Substrate | Why / limit |
|---|---|---|---|
| Content classifier | the embedding model the seam already serves (MiniLM via transformers.js on Nano, nomic-embed via llama.cpp on Mesh), zero-shot cosine against 3 prototype sentences per category | Nano and Mesh (pure Python, no download) | Toxicity models (toxic-bert, detoxify) need torch or 250+ MB ONNX; not Nano-safe. Thresholds (0.58/0.68/0.78) are conservative defaults and NOT calibrated; a discriminative margin guards against a degenerate embedder; off when only the hash fallback exists or `VYOMI_GUARDRAIL_SEMANTIC=0`. |
| Grounding / relevance | word coverage + number check + embedding cosine through `llm_core.embed` | both | scorer, not Bedrock's trained model |
Nothing hand-built beyond the wire adapter and the window logic.

## Tests
`tests/conformance/test_bedrock_guardrails_caps.py` (real boto3 `bedrock` + `bedrock-runtime` over HTTP, fake model server, deterministic bag-of-words embedder): 29 checks.
Also green: `test_ai_agent_lanes.py` (47).

## Declared limits
- Stream windows are judged independently: a violation split across two windows can be missed; grounding on streams is judged per window.
- Embedding-prototype classifier quality is NOT measured (no real embedder or labelled set available in this lane); the plumbing is tested with a fake embedder.
- Automated reasoning, image content, cross-Region config remain rejected.
- Restart persistence is proved by account-bag round-trip; the appliance's own DB flush of that bag is the existing mechanism, not re-tested here.
