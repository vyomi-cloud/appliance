# ai-uiazure (Round 7): finish the Azure AI "Coming soon" pages

Owner: AI session (uiazure lane). Base: local `v4/ai-integration` (1e7125dcd). Branch: `v4/ai-uiazure`.

## Finding
The Azure AI account blade was already wired (alerts, metrics, diagnostic settings, logs, tasks, resource health, support all use the shared kit
components; `NS_NOTES` was a dead fallback). The real gaps were: Foundry AI Search rows (name not clickable, no blade), Foundry Machine Learning
(bare not-simulated), no Agents / Content filters / Evaluations / Prompt flow pages, and two Locks scope dialogs (Subscription, Resource group) plus Feedback.

## Page -> built on
| Page | Result | Built on |
|---|---|---|
| AI Search blade (`#/aisearch`, Foundry > AI Search) | built | `core/azure_search_core.py` over ARM (indexes, docs, indexers, data sources, keys) |
| Foundry > Agents | built | `core/azure_openai_agents_core.py` (Assistants API: assistants, threads, runs) |
| Foundry > Content filters | built, enforced | raiPolicies in `azure_cognitiveservices_core.py`; enforcement in `ai_models_core.py` mapped onto `bedrock_guardrails_core.evaluate` |
| Cognitive Services > Locks (Subscription, Resource group) | built | `Microsoft.Authorization/locks` at each scope; list shows every applicable lock |
| Cognitive Services > Feedback | reworded | no Microsoft inbox; points to the Vyomi feedback widget |
| Foundry > Evaluations, Prompt flow, Machine Learning | not in scope | explicit panel with reason and "Use instead" |
| Alerts, Metrics, Diagnostic settings, Logs, Tasks, Resource health, Support | already real | shared kit components (verified: no Coming soon) |

## OSS choices (thumb rule)
No new backend. Everything reuses existing engines. Content filter enforcement is a ~40 line adapter (policy mapping + error shapes) onto the existing
guardrails content engine (keyword lists + local embedding model). Not hand-built: no evaluator (azure-ai-evaluation / promptfoo are the pointers).

## Tests
- `tests/conformance/test_azure_content_filters.py` (8 PASS): prompt block 400 content_filter + ResponsibleAIPolicyViolation, jailbreak, completion filter, unguarded deployment unaffected.
- `consoles/tests/smoke-uiazure.mjs` (16 PASS on Nano preview with a stand-in model): AI Search create/index/upload/search/keys, Agents chat, Content filter create/assign/enforce, three not-in-scope panels, no Coming soon on 11 account panels, resource-group lock.
- Regression: test_azure_openai_inference, test_azure_cognitiveservices_core.

## Declared limits
Content filters: Hate/Sexual/Violence/Jailbreak only (no Self-harm, protected material, blocklists, annotate mode); keyword + embedding matching, not a safety guarantee; Microsoft default policies do not block.
AI Search: TF-IDF ranking, no semantic/vector/hybrid, no skillsets; Cosmos and SQL indexers report failure. Agents: no code interpreter or file search sandbox.
Shared-file edits: `core/ai_models_core.py` (additive, mirrored to `wasm/core`), `consoles/src/azure/services/registry.js` (one entry), `consoles/src/common/scopeHelp.js`.
