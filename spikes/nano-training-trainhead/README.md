# Spike T1: train task heads on frozen MiniLM embeddings in the browser (throwaway)

Reproduce: `python3 gen_data.py && node run.mjs [js tfjs-wasm tfjs-cpu sklearn]` (needs network for CDN + HF model, and Playwright;
set `PW=` to a playwright install). Writes `results.json`. Headless Chromium, CPU/WASM only, no WebGPU.
Files: `worker.js` (all candidates, runs in a Web Worker), `harness.html`, `run.mjs` (driver: network/RSS accounting, reload test in a
new browser context sharing the profile), `data/` (template intent data, 1000 train / 200 held-out, 100 KB).
