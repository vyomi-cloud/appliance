# Branch v4/ai-limagents - Bedrock Agents + Foundry Assistants limits (Round 8)

Owner: AI session, lane `limagents`. Base: local `v4/ai-integration` (5feeae0e6). Purpose: close the limits declared in `ai-capagents.md`.

## Closed (all proven with real boto3 / openai SDK clients, `tests/conformance/test_bedrock_agents_limits.py`, 57 checks)
| Limit | Status | What now works |
|---|---|---|
| Multi-agent collaboration | closed (sequential) | `agentCollaboration` DISABLED/SUPERVISOR/SUPERVISOR_ROUTER on Create/UpdateAgent; Associate/Get/List/Update/DisassociateAgentCollaborator (alias ARN, unique name, cycle + self rejection, depth 3); supervisor gets one tool per collaborator; collaborator traces relayed with `collaboratorName` + `callerChain`; router = model classifier -> `routingClassifierTrace`, relays the collaborator answer. Collaborator sessions are deterministic per supervisor session. |
| AMAZON.UserInput | closed | built-in group; question returned as reply, trace ASK_USER, next InvokeAgent continues the session. |
| AMAZON.CodeInterpreter | closed (restricted sandbox) | real execution via `core/code_sandbox_core.py`; `sessionState.files` (BYTE_CONTENT / S3, CODE_INTERPRETER) in, `files` event out; `codeInterpreterInvocationInput/Output` trace; os.system / sockets / host files blocked and reported as `executionError`. |
| requireConfirmation | closed | `functionSchema.functions[].requireConfirmation` and OpenAPI `x-requireConfirmation`; returnControl `actionInvocationType: CONFIRM`; Lambda runs only after `confirmationState: CONFIRM`; DENY tells the model; missing state -> ValidationException. |
| Custom prompts / parser Lambdas | closed except KB prompt | validated `promptOverrideConfiguration`; ORCHESTRATION template + `inferenceConfiguration`; PRE/POST_PROCESSING, MEMORY_SUMMARIZATION, ROUTING_CLASSIFIER templates; `overrideLambda` gets the real OUTPUT_PARSER event for PRE, ORCHESTRATION (FINISH / ASK_USER / ACTION_GROUP, reprompt) and POST. `KNOWLEDGE_BASE_RESPONSE_GENERATION` is accepted, stored, **not applied**. |
| apiSchema from S3 | closed | `apiSchema.s3` read from the simulated S3 at create and at invoke; missing object -> ValidationException. |
| Session summary on idle timeout | closed (lazy) | sessions untouched past `idleSessionTTLInSeconds` are summarised into memory (when SESSION_SUMMARY on) and removed on the next request that touches the agent or `GetAgentMemory` (no background clock exists on Nano). |
| InvokeInlineAgent | closed (no nested inline collaborators) | `POST /agents/{sessionId}` with instruction, action groups (incl. built-ins), knowledge bases, guardrail, prompts, `collaboratorConfigurations`; same loop and trace. Inline `collaborators` and memory: rejected / not supported. |
| Console Agents page | closed | `bedrock/Agents.jsx`: action groups (Lambda function / OpenAPI inline / OpenAPI from S3 / return control / built-ins) add + delete, collaboration mode + collaborator editor, advanced prompt JSON, aliases (existing), test panel with trace toggle + trace viewer, confirm / return-control prompt, output-file list. Playwright smoke `consoles/tests/smoke-limagents.mjs` (6 PASS + honest model error; the trace viewer itself was NOT exercised in a browser because headless has no local model). |
| Foundry Assistants code_interpreter | closed (restricted sandbox) | tool accepted; the model's Python runs in the same sandbox; input files from `tool_resources` / `attachments`; logs in run steps (`runs/steps` now listed); output files saved to `/files` with `file_path` annotations + message attachments. |
| Foundry Assistants file_search | closed | `/vector_stores` (create/list/get/delete, files, file_batches); chunk (knowledge_core parsers: txt/md/csv/json/html/PDF/DOCX/XLSX/PPTX) + embed (llm_core embedder) + cosine; top passages given to the model, `file_citation` annotations returned; unsupported file -> `status: failed`, `last_error`. |

## OSS / backend choices (thumb rule)
| Piece | Choice | Substrate | Why |
|---|---|---|---|
| Code execution | CPython itself: `python -I` child with rlimits + `sys.addaudithook` (Mesh); AST gate + builtins/import allow-list + `settrace` guard (Nano) | Mesh subprocess; Nano in-process | no new dependency; RestrictedPython/Pyodide-in-Pyodide add MBs for weaker guarantees. Hand-written part is the ~250-line wrapper. |
| Vector store | existing `llm_core.embed` + `knowledge_core` parsers/splitter, in-memory cosine | both | reuses the embedder and parsers; no new store |
| Collaboration, confirmation, parsers, summaries | thin orchestration inside the existing Agents loop; Lambda engine for parsers | both | no OSS equivalent for Bedrock's wire semantics |
No new downloads; pure Python, stdlib only.

## Declared limits (also in `core/capabilities/aws/bedrock.json`, `azure/cognitiveservices.json`, scopeHelp)
- Sandbox is restricted execution, not a VM: Mesh has no network namespace (blocking is by audit hook, native code is not capped), Nano cannot interrupt one long C call and has only the stdlib allow-list (no numpy/pandas/matplotlib); variables do not persist between calls, files do; no image/plot outputs.
- Collaborators run sequentially (depth 3), no parallel calls; no nested inline collaborators; inline agents have no memory.
- Router and tool choice quality is the small local model's, not measured against a real model here (tests use a scripted fake).
- Not applied: `KNOWLEDGE_BASE_RESPONSE_GENERATION` prompt; non-text chat inputs (`useCase: CHAT` rejected); parser `KNOWLEDGE_BASE` invocation.
- Azure: Responses-API built-in tools still rejected; no vector-store expiry, ranking_options, custom chunking; assistants run replay on Nano's async WebLLM path (pre-existing) was not exercised for the new tool loop - pure Python but NOT run under Pyodide in this lane. The Azure Foundry console page has no code_interpreter / file_search toggles yet (backend only).
- Idle-timeout summaries are lazy (next request), not timer-driven.

## Shared-file edits
`core/aws_wire_router.py`: one regex token (`vector_stores`) so `/openai/vector_stores` reaches the Azure OpenAI dispatcher. `wasm/build_cores.py` + `wasm/nano-boot.js`: `code_sandbox_core.py` added to the core lists. `tests/conformance/test_ai_agent_lanes.py`: the old "code_interpreter rejected" check now asserts an unsupported tool (`computer_use`) is rejected.

## Tests
`test_bedrock_agents_limits.py` 57 passed; `test_bedrock_agents_capabilities` 33, `test_bedrock_agents_core`, `test_agentcore_facilities` 25, `test_azure_openai_inference` 15, `test_ai_agent_lanes` 47 (one timing-sensitive streaming check failed once, passed on rerun).
