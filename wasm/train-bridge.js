/* Nano training bridge: core/training_core.py (Pyodide) <-> train-worker.js (Web Worker).
 * Python hands a validated job (rows already parsed + capped) to vyomiTrainHead(jobId, specJson). This module embeds every unique text with the page's
 * MiniLM (globalThis.vyomiEmbed, batches of 64, cancellable), then hands the vectors to a dedicated Web Worker that trains the head with typed arrays and
 * posts per-epoch events; each event is forwarded to training_core.on_event (which publishes head.json into the simulated object store).
 * Limits (declared): the tab must stay open while embedding (about 12 ms/text); only contexts that own the embedder install this (the console page, not the
 * relay shared worker), so SDK/CLI jobs that arrive through a relay context fail fast with an honest message. */
export function installTrainBridge(py) {
  if (globalThis.__nano_train_bridge) return globalThis.__nano_train_bridge;
  py.runPython(`
import json
def _train_bridge_start(job_id, spec_json):
    import js
    js.globalThis.vyomiTrainHead(job_id, spec_json)
def _train_bridge_cancel(job_id):
    import js
    js.globalThis.vyomiTrainCancel(job_id)
def _train_event(ev_json):
    from core import training_core as tc
    tc.on_event(ev_json)
def _train_bridge_set(on):
    from core import training_core as tc
    tc.set_bridge(_train_bridge_start if on else None, _train_bridge_cancel if on else None)
`);
  const onEvent = py.globals.get("_train_event");
  const emit = (ev) => { try { onEvent(JSON.stringify(ev)); } catch (e) { console.warn("[nano] training event dropped:", e); } };
  let worker = null; const cancelled = new Set();
  const getWorker = () => {
    if (worker) return worker;
    worker = new Worker(new URL("./train-worker.js", import.meta.url));
    worker.onmessage = (e) => { const m = e.data || {}; if (m.id) emit(m); };
    worker.onerror = (e) => { console.warn("[nano] train worker error:", e.message); };
    return worker;
  };
  globalThis.vyomiTrainCancel = (id) => { cancelled.add(id); if (worker) worker.postMessage({ cmd: "cancel", id }); };
  globalThis.vyomiTrainHead = (id, specJson) => {
    (async () => {
      try {
        const spec = JSON.parse(specJson);
        const texts = [...new Set(spec.rows.flatMap((r) => spec.task === "reranker" ? [r.query, r.positive, r.negative] : [r.text]))];
        emit({ id, status: "Embedding", progress: 0 });
        const D0 = 384, vecs = new Float32Array(texts.length * D0);
        for (let i = 0; i < texts.length; i += 64) {
          if (cancelled.has(id)) { cancelled.delete(id); return; }
          const batch = JSON.parse(await globalThis.vyomiEmbed(JSON.stringify(texts.slice(i, i + 64))));
          batch.forEach((v, k) => vecs.set(v, (i + k) * D0));
          emit({ id, progress: +(0.2 * Math.min(1, (i + 64) / texts.length)).toFixed(3) });
        }
        if (cancelled.has(id)) { cancelled.delete(id); return; }
        getWorker().postMessage({ cmd: "train", id, task: spec.task, labels: spec.labels, rows: spec.rows, epochs: spec.epochs, lr: spec.lr, bs: spec.bs, seed: spec.seed,
                                  texts, vecs, D: D0, embedder: "all-minilm-l6-v2" }, [vecs.buffer]);
      } catch (e) { emit({ id, error: "Embedding failed: " + ((e && e.message) || e) }); }
    })();
  };
  py.runPython("_train_bridge_set(True)");
  globalThis.__nano_train_bridge = { emit };
  return globalThis.__nano_train_bridge;
}
