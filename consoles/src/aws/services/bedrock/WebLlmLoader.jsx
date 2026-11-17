import { useEffect, useState } from "react";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";

/* Nano only: loads an in-browser WebLLM model (window.vyomiEnableWebLLM, provided by nano-boot.js). Renders nothing where the bridge does not exist
 * (offline appliance / Mesh), so the Playground stays unchanged there. `hint` = the model label picked in the Playground, used to preselect. */
export default function WebLlmLoader({ hint = "", onLoaded }) {
  const [can, setCan] = useState(typeof window !== "undefined" && typeof window.vyomiEnableWebLLM === "function");
  useEffect(() => {
    if (can) return undefined;
    const t = setInterval(() => { if (typeof window.vyomiEnableWebLLM === "function") setCan(true); }, 1000);
    return () => clearInterval(t);
  }, [can]);
  const models = (typeof window !== "undefined" && window.vyomiWebLLMModels) || [];
  const guess = models.find((m) => hint && String(hint).toLowerCase().includes(m.name.toLowerCase()));
  const [pick, setPick] = useState("");
  const [st, setSt] = useState(null);
  if (!can) return null;
  const sel = pick || (guess && guess.id) || (models[0] && models[0].id) || "";
  const load = async () => {
    setSt({ msg: "Loading the in-browser model..." });
    try {
      const id = await window.vyomiEnableWebLLM(sel || undefined, (p) => setSt({ msg: p.text || "Loading..." }));
      setSt({ ok: true, msg: `WebLLM model ${id} is loaded. Run your prompt again.` });
      if (onLoaded) onLoaded(id);
    } catch (e) { setSt({ ok: false, msg: String(e.message || e) }); }
  };
  return (
    <SpaceBetween direction="horizontal" size="xs" alignItems="center">
      {models.length > 0 && <select data-testid="playground-webllm-model" value={sel} onChange={(e) => setPick(e.target.value)} style={{ padding: "4px 6px" }}>
        {models.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.size})</option>)}</select>}
      <Button data-testid="playground-load-webllm" iconName="download" onClick={load} loading={st && st.ok === undefined}>Load in-browser model (WebLLM)</Button>
      {st && (st.ok === false ? <StatusIndicator type="warning">{st.msg}</StatusIndicator> : <StatusIndicator type={st.ok ? "success" : "in-progress"}>{st.msg}</StatusIndicator>)}
    </SpaceBetween>
  );
}
