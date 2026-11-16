# v4/ai-limflows: overcoming the declared limits (Flows, Evaluations, Foundry)

Branch from `v4/ai-integration`. Runs on both substrates (host and Nano/Pyodide) because it only uses the shared cores.

## What was built

| Area | Change | OSS / thin adapter |
|---|---|---|
| Bedrock Flows runner | Event-driven graph runner in `core/bedrock_build_core.py`: Input, Output, Prompt, Condition (==, !=, contains, numeric, and/or, default), Collector, Iterator (fan-out), Agent, KnowledgeBase, LambdaFunction, Retrieval and Storage (S3), Loop/LoopInput/LoopController. `enableTrace` returns `flowTraceEvent` (nodeInputTrace, nodeOutputTrace, conditionNodeResultTrace). | none (stdlib) |
| Flows canvas | `FlowCanvas.jsx`: drag-and-drop palette, wiring, per-node config panel, auto layout, JSON tab, trace ticks. | `@xyflow/react` 12.12.1 (already bundled for RAG Studio) |
| Bedrock Evaluations | Model-as-judge jobs (local model), RAG retrieve-only and retrieve-and-generate over a KB, human-workflow job recorded as InProgress with no fabricated ratings, custom metrics, dataset cap 1000 with batching (25 per step on host, 3 on Nano), scorers f1, rouge_l, cosine, toxicity heuristic. | stdlib scorers, `core/llm_core` as the judge |
| Azure Foundry Evaluations | Azure OpenAI Evals API (`/openai/evals`, runs, output_items): string_check, text_similarity, label_model, score_model. Works with the `openai` SDK `client.evals`. | same scorers and judge |
| Azure Foundry Prompt flow | flow.dag.yaml shape (inputs, outputs, llm and prompt nodes) converted to the Bedrock runner definition; `/openai/vyomi/promptflow/flows[/{name}[/test|/score]]` (Vyomi extension). Fluent pages with an xyflow canvas. | `@xyflow/react` |

## Tests
- `tests/conformance/test_bedrock_flows.py` (26), `test_bedrock_evals.py` (29), `test_bedrock_build.py` (30), `test_azure_foundry_evals_flows.py` (real `openai` AzureOpenAI client).
- Playwright on the Nano preview: `consoles/tests/smoke-limflows.mjs` (AWS) and `smoke-limflows-azure.mjs`.

## Honest limits
- The judge is a small local model: judged scores are indicative, not benchmark grade. Unparsable verdicts count as unscored, never as a score. No BERTScore.
- Human-workflow jobs stay InProgress; nothing is rated.
- Lex and InlineCode flow nodes are rejected. Loop semantics are Vyomi's reading of the documented node.
- Canvas layout (positions) lives in the browser (localStorage); the definition itself is stored by the API.
- Azure: Prompt flow state is in memory; python tool nodes, python graders, logs/stored_completions sources and gleu/meteor are rejected. Bring-your-own `precomputedInferenceSource` (Bedrock) is unsupported.
- `@xyflow/react` is not in `consoles/package.json`; it resolves from `consoles/rag-overlay`.
