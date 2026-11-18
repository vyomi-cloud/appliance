# Branch `v4/fix-aws-prompt-optimization`

Base: `origin/v4-on-main` (4.0.8). Not merged; not released.

## Symptom (owner)
AWS console, Bedrock > Advanced prompt optimization: "optimised prompt is not getting displayed. It is displaying `{{input}}{{output}}` continuously."

## Root cause
`core/bedrock_build_core.py` / `wasm/core/bedrock_build_core.py` `_optimize` (OptimizePrompt) sent the local model a meta-prompt that contained the literal
token `{{variable}}` ("keep every {{variable}} placeholder unchanged"). The default local models are <1 GB (SmolLM2 360M, Qwen2.5 0.5B, ...). A model that
small parrots placeholders it was never given and loops until `max_tokens` (400): `{{input}}{{output}}{{input}}{{output}}...`. The core returned the raw
reply as `optimizedPrompt`, and the page (`buildpages/Assess.jsx` `PromptOptimization`) rendered it. Nothing validated the reply.
Affects both substrates (identical core in `core/` and `wasm/core/`); in practice seen on Nano with a loaded in-browser model.
Without a loaded model the page already shows an honest 424 ("No local LLM backend is available").

## Fix
- Meta-prompt no longer contains a literal `{{variable}}`; it lists only the placeholders the user typed ("Keep these placeholders exactly as written and add no others: ...").
- `max_tokens` scales with the prompt (96..400) instead of a flat 400.
- Reply validation (`_usable`): rejects empty output, a user variable that was dropped, any placeholder the user did not type, placeholder-only text (< 3 words), and
  loops (token uniqueness < 35% over >= 12 tokens).
- An unusable reply falls back to a deterministic, labelled rule-based rewrite (`_rule_rewrite`: role + the user's own prompt + format line; user `{{variables}}` untouched).
  The `analyzePromptEvent` message says the model reply was unusable; the page shows it as a warning. It is never presented as model output.
- The 424 "no backend" error now carries the substrate's own message (on Nano: how to load an in-browser model).
- `api.optimizePrompt` returns `{text, note, fallback}`; the page shows `res.text` and a warning when `fallback`.
- Bundle `wasm/v4/aws/main.js` + `index.html` rebuilt with `node consoles/build.mjs --cloud aws` (content-hash cache-buster updated by the build).

## Verification
- `tests/test_bedrock_optimize_prompt.py` (10 tests): 7 fail on v4-on-main's core, all 10 pass on the fix. Covers the owner symptom, invented placeholders, user-typed `{{input}}` kept, good replies pass through, dropped variable, loops, empty reply, meta-prompt content/token cap, honest 424.
- `consoles/tests/smoke-aws-uiaws.mjs`: usable reply shown as-is; looping `{{input}}{{output}}` reply never shown, user's `{{topic}}` kept, warning note visible.
- Real Chrome on the Nano preview (`consoles/nano_preview.mjs`).

## Known limits
Quality of a model-written rewrite is that of the local model; a tiny model will often trigger the rule-based fallback. GCP/Azure have no equivalent page.
