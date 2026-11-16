# Branch v4/ai-capagents - Bedrock Agents capabilities (Round 6)

Owner: AI session, lane `capagents`. Base: local `v4/ai-integration` (20c01eaa3). Purpose: close the `bedrock.agents` "Dev Simplified" limitations.

## What now works (core/bedrock_agents_core.py, mirrored to wasm/core)
- Action groups are invoked. Function-schema and OpenAPI (JSON, YAML if PyYAML is present) groups with a `lambda` executor call the Lambda engine with the real Bedrock Agents event
  (messageVersion, agent, actionGroup, function / apiPath+httpMethod, parameters, requestBody.content.application/json.properties, sessionAttributes); the response
  (functionResponse / responseBody) is fed back to the model; Lambda sessionAttributes are carried to the next call.
- RETURN_CONTROL (`customControl`): InvokeAgent emits a `returnControl` event (functionInvocationInput / apiInvocationInput); the next InvokeAgent with
  `sessionState.returnControlInvocationResults` + `invocationId` resumes the loop. Wrong invocationId / missing result -> ValidationException.
- Tool selection: `llm_core.chat(tools=...)` (schema-constrained JSON envelope, validation, bounded retries) then the arguments are re-validated against the action schema before anything is invoked.
  Exhausted retries -> "Sorry, I am unable to assist you with this request." + `failureTrace`; the Lambda is not called.
- `enableTrace`: separate `trace` events - preProcessingTrace, orchestrationTrace (modelInvocationInput/Output, rationale, invocationInput ACTION_GROUP|KNOWLEDGE_BASE, observation ACTION_GROUP|KNOWLEDGE_BASE|FINISH),
  postProcessingTrace, guardrailTrace, failureTrace. Pre/post-processing are deterministic steps (labelled so), not model calls.
- `guardrailConfiguration` (validated at Create/UpdateAgent, snapshotted per version) applies core/bedrock_guardrails_core to input (block -> blockedInputMessaging without calling the model; anonymise -> redacted text) and output.
- `memoryConfiguration` SESSION_SUMMARY: `endSession` + `memoryId` stores an LLM session summary (storageDays, maxRecentSessions); later sessions with the same memoryId get it in the prompt;
  `GetAgentMemory` (paged) / `DeleteAgentMemory` (memoryId, sessionId) on `/agents/{id}/agentAliases/{alias}/memories`.
- Also fixed: the action-group control-plane path was `agentactiongroups`; the real SDK uses `/agentversions/{v}/actiongroups/`, so CreateAgentActionGroup never reached the engine through boto3. Added Get/Update/Delete + executor/schema validation.
- Nano replay safety: Lambda results are memoised across the `llm.arun` replay, session state is committed once at the end (verified: 2 model awaits -> 1 Lambda call).

## OSS / backend choices (thumb rule)
| Piece | Choice | Substrate | Why |
|---|---|---|---|
| Tool-call reliability | existing llm_core JSON-schema constrained output (llama.cpp grammar / WebLLM) + own validator | both | already in the seam; no new dependency |
| Tool execution | existing Lambda engine (lambda_core) | both | the real executor contract |
| Guardrails | existing bedrock_guardrails_core | both | reuse |
| Summaries | llm_core.chat | both | no extra model |
| OpenAPI YAML | PyYAML if importable | Mesh yes; Nano only if loaded (JSON always) | stdlib has no YAML; JSON is the default path |
Nothing hand-built beyond wire adapters and the loop.

## Tests
`tests/conformance/test_bedrock_agents_capabilities.py` (33 checks, real boto3 bedrock-agent / bedrock-agent-runtime / lambda / bedrock clients, in-process server, scripted OpenAI-compatible fake model).
Existing: test_bedrock_agents_core, test_ai_agent_lanes (47), test_agentcore_facilities (25) pass. test_local_llm_seam has 1 failure that is identical on the integration base.

## Declared limits (also in core/capabilities/aws/bedrock.json)
Multi-agent collaboration, AMAZON.UserInput / CodeInterpreter groups, apiSchema from S3, requireConfirmation, custom prompts/parsers, non-text inputs, summaries on idle expiry are not implemented.
Tool-choice quality with a <1 GB model is still weak: reliability here means validated + retried, not smart. Not measured against a real small model in this lane (only the scripted fake).
