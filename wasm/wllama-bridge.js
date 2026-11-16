/* Nano imported-chat-model bridge: core/import_core.py + core/llm_core.py (Pyodide) <-> wllama (llama.cpp WASM, CPU) in the console tab.
 *
 * An IMPORTED custom model is base GGUF + LoRA adapter GGUF. Base models keep using WebLLM; only ids that import_core registered come here.
 *   - base GGUF (SmolLM2 135M/360M Q4_K_M from Hugging Face, 105/271 MB) is downloaded on first use and cached in OPFS (resumable: no; a
 *     half-written file has no ".ok" marker and is fetched again). Progress is published on globalThis.vyomiWllamaStatus() + a "vyomi-wllama" event.
 *   - the adapter bytes come from the simulated object store through Python (base64) and are cached in OPFS content-addressed (adapter-<sha256>.gguf),
 *     so they survive reloads even if the object store is rebuilt.
 *   - wllama 3.13.0 (pinned; llama.cpp is version-locked to the wasm) loads [base, adapter] with the adapter-as-second-shard trick: every blob given to
 *     loadModel is mounted as a numbered shard and the adapter is referenced by that mounted path (an undocumented but working path in 3.13.0).
 *   - ONE model is resident at a time; switching imported model reloads (about 1 s once the base is cached).
 * Threads: wllama multi-thread needs SharedArrayBuffer = cross-origin isolation (COOP same-origin + COEP). The portal does NOT send these headers for
 * /nano, so the wasm runs single-thread (wllama falls back by itself). status().multiThread says which one is in use; nothing is faked.
 * Limits (declared): main-thread OPFS createWritable (Chromium, Firefox 111+); model + adapter live in tab memory (about 2x the base GGUF while loading);
 * only the console page owns the engine (relay shared worker calls fail fast with an honest message). */
const VER = "3.13.0";
export function installWllamaBridge(py) {
  if (globalThis.vyomiWllama) return globalThis.vyomiWllama;
  const CDN = () => (globalThis.VYOMI_WLLAMA_CDN || `https://cdn.jsdelivr.net/npm/@wllama/wllama@${VER}/esm`);
  const st = { phase: "idle", model: null, base: null, loaded: null, bytes: 0, total: 0, multiThread: null, crossOriginIsolated: !!globalThis.crossOriginIsolated,
               threads: null, note: "", error: null, loadMs: null, version: VER };
  const emit = (patch) => { Object.assign(st, patch); try { dispatchEvent(new CustomEvent("vyomi-wllama", { detail: { ...st } })); } catch (_) {} };
  let lib = null, wl = null, queue = Promise.resolve();

  async function opfs() {
    if (!navigator.storage || !navigator.storage.getDirectory) throw new Error("OPFS is not available in this browser (needed to cache the base model).");
    const root = await navigator.storage.getDirectory();
    return root.getDirectoryHandle("vyomi-wllama", { create: true });
  }
  async function has(dir, name) { try { await dir.getFileHandle(name); return true; } catch (_) { return false; } }
  async function put(dir, name, bytes) {
    const fh = await dir.getFileHandle(name, { create: true }); const w = await fh.createWritable(); await w.write(bytes); await w.close();
  }
  async function ensureBase(dir, spec) {
    if (await has(dir, spec.file + ".ok")) return;
    emit({ phase: "downloading", base: spec.base, bytes: 0, total: spec.size, note: `Downloading ${spec.file} (${(spec.size / 1e6).toFixed(0)} MB) from Hugging Face; cached in OPFS for next time.`, error: null });
    const r = await fetch(spec.url);
    if (!r.ok || !r.body) throw new Error(`Base model download failed: HTTP ${r.status} from ${new URL(spec.url).host}.`);
    const total = +r.headers.get("content-length") || spec.size;
    const fh = await dir.getFileHandle(spec.file, { create: true }); const w = await fh.createWritable();
    const rd = r.body.getReader(); let got = 0, lastEmit = 0;
    try {
      for (;;) {
        const { done, value } = await rd.read(); if (done) break;
        await w.write(value); got += value.length;
        if (Date.now() - lastEmit > 250) { lastEmit = Date.now(); emit({ bytes: got, total }); }
      }
      await w.close();
    } catch (e) { try { await w.abort(); } catch (_) {} throw e; }
    if (got < total * 0.99) throw new Error(`Base model download was cut short (${got} of ${total} bytes); try again.`);
    await put(dir, spec.file + ".ok", new TextEncoder().encode(String(got)));
    emit({ bytes: got, total });
  }
  async function adapterBlob(dir, modelId, spec) {
    const name = `adapter-${spec.adapterSha256}.gguf`;
    if (!(await has(dir, name))) {
      const b64 = py.globals.get("_import_adapter_b64")(modelId);
      if (!b64) throw new Error(`Adapter for ${modelId} is not in the simulated object store.`);
      const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      await put(dir, name, bin);
    }
    return (await (await dir.getFileHandle(name)).getFile());
  }
  async function ensureLoaded(modelId, spec) {
    const key = `${spec.file}|${spec.noAdapter ? "base-only" : spec.adapterSha256}`;
    if (wl && st.loaded === key) return;
    if (!lib) lib = await import(/* webpackIgnore: true */ `${CDN()}/index.js`);
    const dir = await opfs();
    await ensureBase(dir, spec);
    emit({ phase: "loading", model: modelId, note: "Loading base + LoRA adapter into llama.cpp (WASM)." });
    if (wl) { try { await wl.exit(); } catch (_) {} wl = null; st.loaded = null; }
    const baseFile = await (await dir.getFileHandle(spec.file)).getFile();
    const adFile = spec.noAdapter ? null : await adapterBlob(dir, modelId, spec);     // noAdapter: measurement hook (the untuned base, same GGUF)
    const w = new lib.Wllama({ default: `${CDN()}/wasm/wllama.wasm` }, { suppressNativeLog: true });
    const t0 = performance.now();
    // wllama itself falls back to 1 thread when SharedArrayBuffer is unavailable (page not cross-origin isolated).
    await w.loadModel(adFile ? [baseFile, adFile] : [baseFile], { n_ctx: 2048, n_threads: Math.max(2, Math.min(4, (navigator.hardwareConcurrency || 4) - 1)), n_gpu_layers: 0,
                                            ...(adFile ? { lora_adapters: [{ path: "models/model-00002-of-00002.gguf", scale: 1.0 }] } : {}) });
    wl = w;
    const multi = !!w.isMultithread(), threads = multi ? w.getNumThreads() : 1;
    emit({ phase: "ready", loaded: key, model: modelId, loadMs: Math.round(performance.now() - t0), threads, multiThread: multi,
           note: multi ? `llama.cpp WASM, ${threads} threads.` : "llama.cpp WASM, single thread (this page is not cross-origin isolated, so SharedArrayBuffer threads are unavailable)." });
  }

  async function chat(reqJson) {
    const q = JSON.parse(reqJson);
    emit({ busy: true });
    try { return await chat1(q); } finally { emit({ busy: false }); }
  }
  async function chat1(q) {
    try {
      await ensureLoaded(q.model, q.spec);
    } catch (e) { emit({ phase: "error", error: String((e && e.message) || e) }); throw e; }
    const t0 = performance.now();
    const msgs = q.messages.map((m) => ({ role: m.role, content: String(m.content ?? "") }));
    const body = { messages: msgs, max_tokens: q.max_tokens || 256, temperature: q.temperature ?? 0 };
    if (q.stop && q.stop.length) body.stop = q.stop;
    const r = await wl.createChatCompletion(body);
    const c = r.choices[0];
    const ms = performance.now() - t0, ntok = (r.usage && r.usage.completion_tokens) || 0;
    emit({ lastTokS: ntok ? +(ntok / (ms / 1000)).toFixed(1) : null });
    return JSON.stringify({ text: c.message.content || "", input_tokens: r.usage && r.usage.prompt_tokens, output_tokens: r.usage && r.usage.completion_tokens,
                            finish_reason: c.finish_reason === "length" ? "length" : "stop", backend: "wllama" });
  }
  const api = {
    // One generation at a time (single wasm instance); concurrent requests queue.
    chat: (reqJson) => { const p = queue.then(() => chat(reqJson)); queue = p.catch(() => {}); return p; },
    status: () => ({ ...st }),
    unload: async () => { if (wl) { try { await wl.exit(); } catch (_) {} wl = null; emit({ phase: "idle", loaded: null }); } },
    async cachedBases() { const d = await opfs(); const out = []; for await (const [n] of d.entries()) if (n.endsWith(".ok")) out.push(n.slice(0, -3)); return out; },
    async clearCache() { const root = await navigator.storage.getDirectory(); await root.removeEntry("vyomi-wllama", { recursive: true }); },
  };
  globalThis.vyomiWllama = api;
  globalThis.vyomiWllamaStatus = api.status;
  py.runPython(`
import json, builtins
def _import_adapter_b64(mid):
    from core import import_core as ic
    return ic.adapter_b64(mid)
async def _import_chat(model, msgs, system, max_tokens, temperature, stop):
    import js
    from core import import_core as ic
    spec = ic.base_spec(model)
    if spec is None:
        raise RuntimeError("imported model " + model + " is not registered")
    eng = getattr(js.globalThis, "vyomiWllama", None)
    if eng is None:
        raise RuntimeError("the wllama engine only runs in the console page, not in this context; open the console tab")
    r = await eng.chat(json.dumps({"model": model, "spec": spec, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature, "stop": stop}))
    return json.loads(str(r))
def _import_bridge_set(on):
    from core import llm_core, import_core as ic
    llm_core.set_custom_backend((lambda m: ic.is_import_id(m) and ic.has_model(m)) if on else None, _import_chat if on else None)
builtins._import_adapter_b64 = _import_adapter_b64
builtins._import_bridge_set = _import_bridge_set
`);
  py.runPython("_import_bridge_set(True)");
  return api;
}
