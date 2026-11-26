# labs-integration

Integrates the Vyomi Labs work for the two editions of the course, cut from `origin/v4-on-main`.
- `v4/labs-enterprise-content`: enterprise content (real assertions, IAM Enforce, failure labs, Ship-it capstone), schema 2 with `edition` per block, `<cloud>.json` = Mesh and `<cloud>-nano.json` = Nano subset.
- `v4/labs-nano-edition`: free in-browser runtime (Deploy runs what can run, runner body fix, urllib, model picker for the four WebLLMs, Lambda SDK sandbox, AgentCore boto3/langgraph).
- `v4/nano-cognito-waf`: Cognito, WAFv2 and authorizers on Nano (`core/identity_native.py`).
- This branch adds: edition selection in `wasm/labs/labs.js` (Nano page without a runner or Mesh loads `<cloud>-nano.json`; `?edition=nano|mesh` forces one) and a Terraform exporter fix (real-cloud mode replaces the simulator account id inside `jsonencode` policies).

Design decision: one content source, two generated data sets, so the editions cannot drift.
Open issues: GCP and Azure cannot run on Nano (browser SDK missing; see docs/labs/nano-matrix-*.md); Azure/GCP have no IAM Enforce lab; hosted agents need PyPI once for langgraph; ch4 `event_driven` and ch7 `memory_events` count expectations; Nano checks that only match printed substrings pass for every model.

## Final reconcile (v4/labs-integration-final)
Merged origin/v4-on-main (chapter 14 "Design the RAG", `rag_design_src.py`, RAG Studio consoles) into this branch. Hand-merged: labs_{aws,azure,gcp}.py (trunk's rag_design readers in ch 10/12/6/11 kept, our `vymodels` rename, real assertions and `_ent` blocks kept; rerank assertion generalised for topN 1), wasm/labs/labs.js (trunk nLayers/nWord helpers + our edition logic), wasm/nano-boot.js (core list: trunk `iam_events_core.py` + our `identity_native.py`). Regenerated, not merged: courses/**, wasm/labs/data|project, wasm/v4, wasm/core, MCP files. Numbers and evidence: docs/labs/nano-edition-verified.md.
Open: cedar_enforce.py in the in-process run; GCP add_policy.py (pre-existing); Azure call_container_app.py.
