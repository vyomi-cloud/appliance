# ai-azureui

Owner: AI session (round 2 gap lane). Base: local `v4/ai-integration` (61433968b). Branch: `v4/ai-azureui`.

## Purpose
Match the Azure portal "Microsoft Foundry" AI hub (captures: `console-captures/azure/live/B-view-microsoft-azure-projectoxford-cognitiveserviceshub-menuview`, 001-013) in the v4 Azure console. Before: no Foundry hub; only the Azure AI services account blade.

## What was built (consoles/src/azure/services/foundry, registered in services/registry.js)
- Hub blade `#/foundry[/<page>]`: title `Microsoft Foundry | <page>`, chip row (Browse all resources / outages / Filter by region; ML has "Get workload templates for ML workspaces"), left menu Overview, All resources, collapsed groups All models agents & tools, Single-capability, Earlier-generation, Help.
- Overview tab (hero, model tiles, Discover capabilities cards) and Dashboard tab (Refresh, "No AI resources found", Alerts / Active resources by cost / Accumulated costs "No data to display").
- List pages (All resources, Foundry, Azure OpenAI, AI Search, ML, Speech, Language, Translator, Content safety, Computer vision, Anomaly detector) use the existing BrowseGrid over real ARM lists: Microsoft.CognitiveServices/accounts filtered by kind, Microsoft.Search/searchServices. Names link to the existing account blade.
- Shared kit: `ResourceBlade` got an additive `groupsClosed` prop (groups collapsed unless active).
- Thin adapter only; no backend changes (thumb rule: engines azure_cognitiveservices_core / azure_search_core already exist).

## Captures vs ours
The real captures are all the "Welcome to Azure! Don't have a subscription" empty state (the captured tenant had no subscription), so the spec is chrome + menu + titles + chips + Overview/Dashboard. Ours shows real resources because the simulator has a subscription.
Closely matches: hub chrome/title/chips, left menu (top level), Overview, Dashboard.
Approximate: sub-menu group membership (capture never expanded groups; inferred), hero/capability card illustrations (plain blocks, no Microsoft art), Help group contents, list pages (capture has none to compare).
No capture to verify against (kept as is, not invented): Foundry project pages (model catalog, deployments, playground, evaluations, prompt flow, agents), any RAG page, Machine Learning workspaces (not simulated; page says so).

## Verification
Playwright against `consoles/dev_server.py` (OUR screenshots: scratchpad/shots-azureui/*.png): overview, dashboard, all, openai, search, ml, speech, safety, anomaly render, seeded OpenAI account and AI Search service listed, zero page errors. `wasm/v4/azure` bundle not committed.

## Open
Foundry project-level pages need captures; ML workspace backend; real group membership.
