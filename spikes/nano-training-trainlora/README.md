# T2 spike (lane trainlora): LoRA on SmolLM2-135M-Instruct, served by wllama

Throwaway, reproducible. Needs python3.13 venv (torch transformers peft gguf), npm `@wllama/wllama@3.13.0`, a sparse
llama.cpp checkout (`conversion/ gguf-py/` + convert_*.py), Playwright (headless Chromium).

1. `python make_data.py` -> train.json (100 rows) + heldout.json (30 rows); task: ticket triage to `category=X; priority=PN`.
2. `python train_lora.py <hf-dir> <adapter-dir> 8` -> CPU LoRA (r=8, q/k/v/o), prints loss per epoch + JSON of time/RSS/adapter size.
3. `python eval_hf.py <hf-dir> [adapter-dir]` -> exact match on held-out.
4. `convert_hf_to_gguf.py <hf-dir> --outtype f16` and `convert_lora_to_gguf.py --base <hf-dir> <adapter-dir>` -> base-f16.gguf, adapter.gguf.
5. `node serve.mjs <web-root> 8765` (COOP/COEP) with serve_test.html + models/ + heldout.json, then
   `node run_browser.cjs http://localhost:8765/serve_test.html[?lora=1]`.

wllama detail: `loadModel([baseBlob, adapterBlob], {lora_adapters:[{path:'models/model-00002-of-00002.gguf'}]})`. Every blob handed to
loadModel is mounted as a numbered shard file; the adapter rides in as the "second shard" and is referenced by that mounted path
(worked unmodified in 3.13.0, but it is a trick, not a documented API; README still lists LoRA as TODO).
