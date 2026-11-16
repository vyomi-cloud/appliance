/* Shared logic for the three "import a chat model" pages (Bedrock Custom model import, Vertex Model Registry import, Foundry custom model).
 * UI-free: the lens components (Cloudscape / MUI / Fluent) render it. The engine is core/import_core.py (validation, registry, object-store persistence)
 * and, on Nano, wasm/wllama-bridge.js (base GGUF from Hugging Face cached in OPFS + your LoRA adapter, llama.cpp WASM). See docs/architecture/v4.0/branches/ai-nanoimport.md.
 *
 * Honest framing every page shows: the result is a small open base model plus YOUR LoRA adapter (trained on Mesh or your machine), not a vendor model. */
import { useEffect, useState } from "react";

export const ADAPTER_MAX = 50 * 1024 * 1024;
export const ADAPTER_FILE = "adapter.gguf", META_FILE = "adapter_meta.json";
export const ID_PREFIX = "vyomi.import.";

/** Bases Nano can serve (mirror of core/import_core.BASES; the engine rejects anything else with its own message). */
export const IMPORT_BASES = [
  { id: "smollm2-135m-instruct", name: "SmolLM2 135M Instruct", quants: { Q8_0: 145, Q4_K_M: 105 }, defaultQuant: "Q8_0" },
  { id: "smollm2-360m-instruct", name: "SmolLM2 360M Instruct", quants: { Q4_K_M: 271, Q8_0: 386 }, defaultQuant: "Q4_K_M" },
];

export const FRAMING = "The imported model is a small open base model (SmolLM2) plus your LoRA adapter, served in this browser tab with wllama. It is not a vendor model, and quality is whatever your own held-out check says.";
export const TRAIN_HINT = "Train the adapter on Mesh (a LoRA fine-tuning job on a SmolLM2 or Qwen2.5 base) or on your own machine with llama.cpp convert_lora_to_gguf.py, then bring adapter.gguf (and adapter_meta.json) here.";
export const NANO_ONLY = "Serving needs the Nano console tab: it downloads the base GGUF from Hugging Face on first use (105 to 386 MB, cached in your browser) and runs it on CPU. Mesh and offline appliances store the import but cannot serve it yet.";
export const META_HELP = 'adapter_meta.json: {"base_model": "smollm2-135m-instruct", "rank": 8, "alpha": 16}. Rank and alpha must match the adapter file.';

export const isNanoSubstrate = () => typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano";

/** adapter_meta.json text from the form fields (when the user did not bring a meta file). */
export const buildMeta = ({ base, rank, alpha, quant }) => JSON.stringify({ base_model: base, rank: Number(rank), alpha: Number(alpha), ...(quant ? { base_quant: quant } : {}) });

export const randomSuffix = () => Math.random().toString(36).slice(2, 8);

/** Client-side pre-check so the user sees the reason before the cloud's own validation error. GGUF magic only; the engine parses the rest. */
export async function checkAdapterFile(file) {
  if (!file) return { ok: false, error: "Choose the adapter.gguf file." };
  if (file.size > ADAPTER_MAX) return { ok: false, error: `The adapter is ${(file.size / 1048576).toFixed(1)} MB; the limit is 50 MB.` };
  const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
  if (String.fromCharCode(...head) !== "GGUF") return { ok: false, error: "This file is not a GGUF (it does not start with GGUF). Convert the LoRA adapter with llama.cpp convert_lora_to_gguf.py." };
  return { ok: true };
}

/** The meta file the user picked (text) or the one built from the form fields; empty string when the fields are incomplete. */
export async function resolveMeta({ metaFile, base, rank, alpha, quant }) {
  if (metaFile) return metaFile.text();
  if (!base || !rank || !alpha) return "";
  return buildMeta({ base, rank, alpha, quant });
}

/* ── browser-side serving status (wasm/wllama-bridge.js publishes it on globalThis.vyomiWllamaStatus() + a "vyomi-wllama" event) ── */
export const wllamaNow = () => (typeof globalThis.vyomiWllamaStatus === "function" ? globalThis.vyomiWllamaStatus() : null);

export function useWllama() {
  const [st, setSt] = useState(wllamaNow);
  useEffect(() => {
    const on = (e) => setSt({ ...e.detail });
    addEventListener("vyomi-wllama", on);
    const t = setInterval(() => setSt(wllamaNow()), 1500);   // the bridge is installed a moment after the page boots
    return () => { removeEventListener("vyomi-wllama", on); clearInterval(t); };
  }, []);
  return st;
}

const MB = (n) => `${(n / 1e6).toFixed(0)} MB`;
/** {phase, label, pct|null, busy, done, error} for a progress bar from a wllama status. */
export function servingState(st) {
  if (!st) return { phase: "none", label: "The in-browser engine is not installed (Nano only).", pct: null, busy: false, done: false };
  const p = st.phase;
  if (st.error) return { phase: p, label: `Failed: ${st.error}`, pct: null, busy: false, done: false, error: true };
  if (p === "downloading") return { phase: p, label: `Downloading the base model: ${MB(st.bytes)} of ${MB(st.total)}`, pct: st.total ? Math.min(100, Math.round((100 * st.bytes) / st.total)) : null, busy: true, done: false };
  if (p === "loading") return { phase: p, label: "Loading the base model and adapter into the engine", pct: null, busy: true, done: false };
  if (p === "generating") return { phase: p, label: "Generating", pct: null, busy: true, done: false };
  if (p === "ready" || p === "loaded" || (st.loaded && p !== "idle")) return { phase: p, label: `Ready: ${st.loaded || st.model || "model"} loaded${st.loadMs ? ` in ${(st.loadMs / 1000).toFixed(1)} s` : ""}`, pct: 100, busy: false, done: true };
  return { phase: p, label: st.loaded ? `Idle (last loaded: ${st.loaded})` : "Idle: the base model downloads on the first request to an imported model.", pct: null, busy: false, done: !!st.loaded };
}

/** Pull the base into the tab and load model + adapter by making one tiny real request through the cloud's own wire. `ask` = () => Promise. */
export async function warmUp(ask) {
  try { await ask(); return { ok: true }; } catch (e) { return { ok: false, error: e }; }
}

export const fmtBytes = (n) => (n == null ? "-" : n > 1048576 ? `${(n / 1048576).toFixed(2)} MB` : `${(n / 1024).toFixed(1)} KB`);
