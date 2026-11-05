/* "Local model" status + enable control for every AI playground (Azure OpenAI, Vertex AI Studio, ...).
 * Nano: the only model that can answer is one the BROWSER runs (WebLLM, needs WebGPU). Nothing loads it by itself, so a
 * playground prompt used to fail with "ModelNotReady". This bar shows the real state and a one-click enable.
 * Offline appliance: the model is llama.cpp in the vyomi-llm container (`vyomi llm start`); the bar says so.
 * Plain React + inline styles so it renders the same inside Cloudscape, MUI and Fluent pages. */
import { useEffect, useState } from "react";
import { isNano } from "./NanoVmPanel.jsx";

const box = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "9px 12px", border: "1px solid #d4d4d8", borderRadius: 8, background: "#fafafa", color: "#18181b", fontSize: 13, margin: "0 0 12px" };
const btn = { padding: "5px 12px", border: "1px solid #18181b", borderRadius: 6, background: "#18181b", color: "#fff", cursor: "pointer", fontSize: 13 };
const dot = (c) => ({ width: 9, height: 9, borderRadius: "50%", background: c, flex: "none" });

export default function LocalModelBar() {
  const nano = isNano();                    // the page declares its substrate; the bridge itself appears once the engine has booted
  const [bridge, setBridge] = useState(typeof window !== "undefined" && typeof window.vyomiEnableWebLLM === "function");
  const [st, setSt] = useState(null);       // llm_core.status() on Nano
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => { try { setSt(window.vyomiLlmStatus ? window.vyomiLlmStatus() : null); } catch (_) { setSt(null); } };
  useEffect(() => {                         // the Nano engine boots after the page renders: wait for the bridge, then read the state
    if (!nano) return undefined;
    const t = setInterval(() => { if (typeof window.vyomiEnableWebLLM === "function") { setBridge(true); refresh(); } }, 1000);
    return () => clearInterval(t);
  }, [nano]);
  if (!nano) {
    return (
      <div style={box} data-testid="local-model-bar">
        <span style={dot("#a1a1aa")} /><span>Prompts are answered by the local model on this appliance (llama.cpp in the <code>vyomi-llm</code> container). If a prompt fails with "model not ready", start it with <code>vyomi llm start</code>.</span>
      </div>
    );
  }
  const ready = !!(st && st.available);
  if (!bridge) return <div style={box} data-testid="local-model-bar"><span style={dot("#f59e0b")} /><span>Starting the in-browser engine...</span></div>;
  const webgpu = typeof navigator !== "undefined" && "gpu" in navigator;
  const enable = async () => {
    setBusy(true); setMsg("Loading the in-browser model (first time downloads a few hundred MB)...");
    try { const id = await window.vyomiEnableWebLLM(undefined, (p) => setMsg((p && p.text) || "Loading...")); setMsg(`Model ${id} is ready.`); }
    catch (e) { setMsg(String((e && e.message) || e)); }
    finally { setBusy(false); refresh(); }
  };
  return (
    <div style={box} data-testid="local-model-bar">
      <span style={dot(ready ? "#16a34a" : busy ? "#f59e0b" : "#a1a1aa")} />
      {ready ? <span>In-browser model ready{st.model ? `: ${st.model}` : ""}. Answers are toy-grade; use them to exercise prompts and token accounting.</span>
        : <span>{webgpu ? "No model is loaded yet, so prompts return \"model not ready\"." : "This browser has no WebGPU, so Nano cannot run a model here. Use a recent Chrome/Edge on desktop."}</span>}
      {!ready && webgpu && <button type="button" style={btn} disabled={busy} onClick={enable}>{busy ? "Loading..." : "Enable in-browser model"}</button>}
      {msg && <span style={{ color: "#52525b" }}>{msg}</span>}
    </div>
  );
}
