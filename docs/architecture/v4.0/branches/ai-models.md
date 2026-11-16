# Branch v4/ai-models

- **Owner:** AI session (enterprise agentic AI reference app, round 2 gap lane `models`)
- **Base:** `v4/ai-integration` @ 5cb53ee00 (not pushed to trunk; merge via the integration branch)
- **Purpose:** refapp components 10 (foundation models) and 11 (response generation) were failing/blocked: `ListFoundationModels`
  returned only `vyomi.*` ids and no model was reachable, so Converse / tool use / RetrieveAndGenerate could not run.

## What changed
1. **Standard Bedrock ids listed as aliases** (`core/ai_models_core.py`, mirrored to `wasm/core/`): `BEDROCK_ALIASES` (19 ids:
   anthropic.claude-*, amazon.titan-text/embed, amazon.nova-*, meta.llama3-*, cohere.command/embed) are returned by
   `ListFoundationModels` (filters byProvider/byOutputModality work), `GetFoundationModel`, and cross-Region system-defined
   `ListInferenceProfiles`/`GetInferenceProfile` (`us.<id>`). Resolution reuses the catalogue's alias map plus `_EXTRA_ALIASES`
   (titan-text, cohere.command). The ten native `vyomi.*` models stay listed.
2. **Honest metadata:** TEXT-only modalities (no vision claimed), real provider/display name, `modelLifecycle: ACTIVE`, and a
   `vyomiBackedBy` object (`catalogModelId`, `localModel`, `availability`, `note`: "answered by the local open model, not the
   original vendor model"). boto3 drops unknown fields; raw HTTP/console readers see it. Converse responses already carry
   `x-vyomi-local-model`.
3. **Deterministic test stub LLM** `tools/llm_stub/stub_llm_server.py` (stdlib only, OpenAI-compatible, `VYOMI_LLM_ENDPOINT`):
   `/v1/models`, `/v1/chat/completions` (stream + non-stream, `tools`/`tool_calls`, forced tool_choice, json_schema), `/v1/embeddings`.
   Rule-based: picks the tool by name/description overlap, fills args from the text (ids like `B-12`), answers a tool-result turn,
   routes the facilities supervisor prompt, extracts the first context line for grounded answers. Model name is
   `vyomi-stub-llm (deterministic test stub)`. **It is not a model and proves plumbing, not quality.**
4. `examples/enterprise-facilities-agent/run_e2e.py --llm-stub` starts the stub and labels the report "STUB-BACKED PASS".

## Replacing the stub with the real model (no code change)
The seam `core/llm_core.py` is the only consumer. **Mesh:** boot the AI pack (llama.cpp, Qwen2.5-3B Q4) and leave
`VYOMI_LLM_ENDPOINT` at its default `http://vyomi-llm:8080`; native tool calls are used when the server supports them, otherwise
the seam's prompt-translated, grammar-constrained, validated tool envelope (existing). **Nano:** WebLLM registered through
`llm.set_async_backend` (prompt-translated tools, async path). Quality of tool selection with a 3B model is the open risk; the
seam validates calls against the tool schema and retries.

## OSS table (thumb rule)
| Piece | Choice | Licence | Substrate | Why / limit |
|---|---|---|---|---|
| Local LLM | llama.cpp + Qwen2.5-3B Q4 (existing seam) | MIT / Apache-2.0 | Mesh container | ~2 GB RAM; already integrated, 3B limits tool-use reliability |
| In-browser LLM | WebLLM (existing seam) | Apache-2.0 | Nano | needs WebGPU; small models only |
| Test stub | hand-built (stdlib `http.server`) | n/a | CI / dev only | no OSS fake gives deterministic tool_calls with zero download; ~150 lines, test-only |
| Alias wire adapter | thin code on existing `ai_models_core` | n/a | both | glue only |

## Tests
- `tests/conformance/test_bedrock_models_alias.py` (28 checks: listing, metadata, profiles, Converse all families, tool_use round trip,
  ConverseStream, InvokeModel, real boto3 incl. `converse_stream`). Stub-backed model output.
- Updated `test_ai_model_catalog.py` (listing now = ten + aliases; GetFoundationModel of a listed alias is 200). Also green:
  `test_ai_model_catalog_web`, `test_bedrock_agents_core`, `test_local_llm_seam`.
- Facilities e2e `--llm-stub` (fresh state): 10 PASS, 2 BLOCKED (3 agentcore, 12 knowledge), 1 FAIL (13 KMS encryption-context; other lanes).
  Component 10 PASS 4/4 and 11 PASS 4/4, **both stub-backed**. Without `--llm-stub` (no model) they stay BLOCKED/FAIL by design.

## Declared limits / open
- No real model was run here (no model installed, disk tight): real Qwen2.5-3B tool-use fidelity is untested.
- Aliases do not imply Claude/Nova/Titan behaviour; image/document inputs are rejected as the local model is text-only.
- Inference profiles are alias listings only (us. prefix; eu./apac. resolve for invoke but are not listed).
- Untouched shared files: none beyond `core/ai_models_core.py` (+ wasm mirror via `wasm/build_cores.py`).
