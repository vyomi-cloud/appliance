# ai-helppanes: "Scope and limits" in the right-hand help pane

- Owner: AI session (2026-11-16). Branch `v4/ai-helppanes`, base local `v4/ai-integration` (530527267). Not merged; no `wasm/v4` bundles committed (the orchestrator rebuilds).
- Ask (owner): show the scope/limits of the section in each console's right-hand doc pane, taken from our docs.

## What was built (consoles only, no backend)
- `consoles/src/common/scopeHelp.js`: plain data entries `{id, title, intro, real[], metadata[], limits[], nano[], mesh[]}` keyed by cloud + route pattern; `scopeFor(cloud, path)` picks the most specific match. Wording is taken from the `ai-*.md` branch docs; nothing the docs do not state is claimed.
- `consoles/src/common/ScopeSection.jsx`: cloud-neutral markup (same approach as `BackendsPanel.jsx`) with the heading "Scope and limits".
- AWS: Bedrock routes get `help: {title, body}` through `withHelp` in `services/bedrock/index.jsx` (covers the Infer/Tune routes too); `aws/App.jsx` now renders `help.body` first, then the existing Backends section, then the generic text only when a page has no entry.
- GCP: the existing top-bar (i) already opens the "How Vyomi runs this service" aside; it now shows the Scope section above Backends. Other products are unchanged (no entry, nothing rendered).
- Azure: the Help + support drawer shows the Scope section above Backends and the generic text.

## Entries
AWS: Bedrock Overview, Quickstart, API keys, Model catalog, Playground, Quotas, Compare models, Tokenizer, Inference profiles, Batch inference, Provisioned Throughput, Custom models (incl. import note), Customization job detail, Prompt routers, Marketplace deployments, Knowledge bases (+detail), RAG Studio, AgentCore (+gateway detail).
GCP Agent Platform: Overview, Studio, Model Garden, Model detail, Tuning (+detail), Agent Garden, Deployments, Endpoints (+detail).
Azure Foundry: Overview, Fine-tuning (+job), Azure OpenAI, AI Search, Machine Learning, and one shared entry for All resources / Foundry / Speech / Language / Translator / Content safety / Vision / Anomaly / Docs.
Not covered (no entry, generic pane): Bedrock Agents pages, other GCP/Azure/AWS products.

## Source docs
ai-nano-training-scope, ai-trainengine, ai-meshlora, ai-nanoimport, ai-trainui, ai-ragstudio, ai-knowledge, ai-nanoembed, ai-models, ai-bedrockui-a/b, ai-gcpui, ai-azureui, ai-agentcore, ai-runtime, ai-identity, ai-observability.

## Tests
`consoles/tests/smoke-help-panes.mjs` (Playwright on `nano_preview.mjs`): opens the pane on 6 AWS, 5 GCP and 4 Azure pages and checks the section and a page-specific phrase; 17/17 PASS, no page errors. Screenshots viewed by eye (AWS custom models, GCP tuning, Azure fine-tuning render correctly in each style).

    node consoles/build.mjs && node consoles/nano_preview.mjs --port 8781 --tier pro &
    BASE=http://127.0.0.1:8781 SHOTS=/tmp/shots node consoles/tests/smoke-help-panes.mjs

## Declared limits / open
- Text is static: if an engine changes (for example Mesh LoRA serving gets verified), update `scopeHelp.js` and the source doc together.
- The training entries are long (heads and chat-LoRA on three substrates); trimming or collapsible sections is a possible follow-up.
- Entries describe the integration-branch backends as documented; claims about pieces not run (real llama-server, Codespace, Docker runtime) are stated as not verified.
- Build gotcha: `consoles/node_modules` was symlinked from the integration worktree and `consoles/rag-overlay` needs its own install (`npm install --no-package-lock --omit=peer`).
