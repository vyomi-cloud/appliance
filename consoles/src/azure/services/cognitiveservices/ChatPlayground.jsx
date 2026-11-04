/* Azure OpenAI "Chat playground": multi-turn chat against a model deployment on this account via the native data plane
 * POST /openai/deployments/{deployment}/chat/completions (core/ai_models_core.azure_openai_dispatch over core/llm_core).
 * The answer comes from whatever local model the appliance runs - a <1 GB model, for exercising code paths, not quality. */
import { useState } from "react";
import { Button, Field, Input, Select, Slider, Textarea } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { ErrorBar, InfoBar } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ChatPlayground({ a }) {
  const deps = useAsync(() => api.listDeployments(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [dep, setDep] = useState("");
  const [system, setSystem] = useState("You are an AI assistant that helps people find information.");
  const [temp, setTemp] = useState(0.7);
  const [maxTok, setMaxTok] = useState("256");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [usage, setUsage] = useState(null);
  const chatDeps = (deps.data || []).filter((d) => !/embedding/i.test(d.properties?.model?.name || ""));
  const send = async () => {
    const text = input.trim(); const d = dep || chatDeps[0]?.name;
    if (!text || !d) return;
    const next = [...msgs, { role: "user", content: text }];
    setMsgs(next); setInput(""); setBusy(true); setErr(null);
    try {
      const r = await restJson("POST", `/openai/deployments/${encodeURIComponent(d)}/chat/completions`, {
        query: { "api-version": "2024-10-21" }, headers: { "api-key": "vyomi-playground" },
        body: { messages: [{ role: "system", content: system }, ...next], temperature: temp, max_tokens: Number(maxTok) || 256 },
      });
      setMsgs([...next, { role: "assistant", content: r.choices?.[0]?.message?.content ?? "" }]); setUsage(r.usage);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Chat playground</div>
      {!api.MODEL_KINDS.includes(a.kind) && <ErrorBar error={{ code: "Unsupported", message: `The playground needs an Azure OpenAI or Azure AI services account, not '${a.kind}'.` }} title="Not available" />}
      <InfoBar title="Local model">Answers are produced by the small local model the appliance runs (core/llm_core). It exercises your prompting, token accounting and error handling; it is not the GPT model named on the deployment.</InfoBar>
      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 24, marginTop: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Deployment"><Select value={dep || chatDeps[0]?.name || ""} onChange={(_, d) => setDep(d.value)} aria-label="Deployment">
            {chatDeps.length === 0 && <option value="">No chat deployments</option>}{chatDeps.map((d) => <option key={d.name} value={d.name}>{d.name} ({d.properties?.model?.name})</option>)}</Select></Field>
          <Field label="Give the model instructions and context"><Textarea rows={5} value={system} onChange={(_, d) => setSystem(d.value)} aria-label="System message" /></Field>
          <Field label={`Temperature: ${temp}`}><Slider min={0} max={2} step={0.1} value={temp} onChange={(_, d) => setTemp(d.value)} aria-label="Temperature" /></Field>
          <Field label="Max response (tokens)"><Input value={maxTok} onChange={(_, d) => setMaxTok(d.value)} aria-label="Max tokens" /></Field>
          {usage && <div style={{ fontSize: 12 }} data-testid="chat-usage">Tokens: {usage.prompt_tokens} in, {usage.completion_tokens} out, {usage.total_tokens} total</div>}
        </div>
        <div>
          <div style={{ minHeight: 220, border: "1px solid var(--colorNeutralStroke2)", padding: 12, display: "flex", flexDirection: "column", gap: 8 }} data-testid="chat-log">
            {msgs.length === 0 && <span className="vy-muted">Start chatting: type a message below.</span>}
            {msgs.map((m, i) => <div key={i}><b>{m.role === "user" ? "User" : "Assistant"}:</b> {m.content}</div>)}
          </div>
          <ErrorBar error={err} title="The model could not answer" />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <div style={{ flex: 1 }}><Input value={input} aria-label="Type user query here" placeholder="Type user query here" onChange={(_, d) => setInput(d.value)} onKeyDown={(e) => e.key === "Enter" && send()} /></div>
            <Button appearance="primary" disabled={busy || !input.trim()} onClick={send}>Send</Button>
            <Button onClick={() => { setMsgs([]); setUsage(null); setErr(null); }}>Clear chat</Button>
          </div>
        </div>
      </div>
    </>
  );
}
