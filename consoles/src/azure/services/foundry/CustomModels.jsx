/* Foundry > Custom models: import a chat model (LoRA adapter), deploy it to an Azure OpenAI / Foundry resource and chat with it.
 * Vyomi extension: POST /openai/vyomi/custom-models (multipart name + adapter.gguf + adapter_meta.json; no real Azure API registers a custom LoRA this way),
 * then a normal ARM deployment (model.format "Vyomi", model.name = the model id) and /openai/deployments/{dep}/chat/completions.
 * Engine: core/import_core.py; serving on Nano: wasm/wllama-bridge.js (base GGUF cached in OPFS + your adapter). A small open model, not a vendor model. */
import { useEffect, useState } from "react";
import { Badge, Button, Field, Input, MessageBar, MessageBarBody, ProgressBar, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea } from "@fluentui/react-components";
import { restJson, WIRE_BASE } from "../../../common/wire.js";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { FRAMING, IMPORT_BASES, META_HELP, NANO_ONLY, TRAIN_HINT, checkAdapterFile, fmtBytes, isNanoSubstrate, randomSuffix, resolveMeta, servingState, useWllama } from "../../../common/importModel.js";
import { MODEL_KINDS, listDeployments, listKeys, putDeployment } from "../cognitiveservices/api.js";
import * as hub from "./api.js";

const V = "2024-10-21", H = { "api-key": "console" }, e = encodeURIComponent;
const api = {
  list: () => restJson("GET", "/openai/vyomi/custom-models", { query: { "api-version": V }, headers: H }).then((r) => r.data || []),
  remove: (id) => restJson("DELETE", `/openai/vyomi/custom-models/${e(id)}`, { query: { "api-version": V }, headers: H }),
  async create(name, adapter, metaText) {
    const fd = new FormData(); fd.append("name", name); fd.append("adapter", adapter, "adapter.gguf"); fd.append("meta", new Blob([metaText], { type: "application/json" }), "adapter_meta.json");
    const res = await fetch(`${WIRE_BASE}/openai/vyomi/custom-models?api-version=${V}`, { method: "POST", headers: H, body: fd });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(j.error?.message || `HTTP ${res.status}`), { code: j.error?.code });
    return j;
  },
  chat: (key, dep, messages, max = 128) => restJson("POST", `/openai/deployments/${e(dep)}/chat/completions`, { query: { "api-version": V }, headers: { "api-key": key }, body: { messages, max_tokens: max, temperature: 0 } }),
};

const Bar = ({ intent = "info", children, testid }) => <MessageBar intent={intent} data-testid={testid}><MessageBarBody>{children}</MessageBarBody></MessageBar>;
const Card = ({ title, children, testid }) => <section data-testid={testid} style={{ border: "1px solid var(--colorNeutralStroke2, #ddd)", borderRadius: 4, padding: 16, display: "grid", gap: 8 }}><h3 style={{ margin: 0 }}>{title}</h3>{children}</section>;
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,63}$/;

export function ServingBar() {
  const st = useWllama(), s = servingState(st);
  if (!isNanoSubstrate() && !st) return <Bar testid="serving-nano-only">{NANO_ONLY}</Bar>;
  return (
    <div data-testid="serving-bar" style={{ display: "grid", gap: 4 }}>
      <b>In-browser engine</b>
      <ProgressBar value={s.pct == null ? undefined : s.pct / 100} max={1} thickness="large" color={s.error ? "error" : s.done ? "success" : "brand"} />
      <span style={{ fontSize: 12, opacity: 0.8 }}>{s.label}</span>
      {st && s.done && <span style={{ fontSize: 12, opacity: 0.7 }}>{st.multiThread ? `${st.threads} threads` : "Single thread"}; {st.base || "base"} cached in this browser (OPFS).</span>}
    </div>
  );
}

function Import({ onDone, onCancel }) {
  const [name, setName] = useState(`facilities-tuned-${randomSuffix()}`), [adapter, setAdapter] = useState(null), [metaFile, setMetaFile] = useState(null), [chk, setChk] = useState(null);
  const [base, setBase] = useState(IMPORT_BASES[0].id), [rank, setRank] = useState("8"), [alpha, setAlpha] = useState("16"), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  useEffect(() => { checkAdapterFile(adapter).then((r) => setChk(adapter ? r : null)); }, [adapter]);
  const ready = NAME_RE.test(name) && chk?.ok && (metaFile || (rank && alpha));
  const go = async () => {
    setBusy(true); setErr(null);
    try { onDone(await api.create(name, adapter, await resolveMeta({ metaFile, base, rank, alpha }))); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Card title="Import custom model" testid="import-form">
      <Bar testid="import-framing">{FRAMING} {TRAIN_HINT}</Bar>
      {err && <Bar intent="error" testid="import-error">{err.message}</Bar>}
      <Field label="Model name" hint="Letters, digits, dot, underscore, tilde and hyphen."><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Model name" /></Field>
      <Field label="Adapter file (adapter.gguf, up to 50 MB)"><input type="file" accept=".gguf" aria-label="Adapter file" data-testid="adapter-input" onChange={(ev) => setAdapter(ev.target.files?.[0] || null)} /></Field>
      {adapter && chk && !chk.ok && <Bar intent="error" testid="adapter-error">{chk.error}</Bar>}
      {adapter && chk?.ok && <Bar intent="success" testid="adapter-ok">{adapter.name}, {fmtBytes(adapter.size)}. GGUF header looks right; the engine checks rank, hidden size and base on import.</Bar>}
      <Field label="adapter_meta.json (optional)" hint={`${META_HELP} Leave empty to use the fields below.`}><input type="file" accept=".json" aria-label="Meta file" data-testid="meta-input" onChange={(ev) => setMetaFile(ev.target.files?.[0] || null)} /></Field>
      {!metaFile && <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 8 }}>
        <Field label="Base model"><Select value={base} onChange={(_, d) => setBase(d.value)} aria-label="Base model">{IMPORT_BASES.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>
        <Field label="LoRA rank"><Input type="number" value={rank} onChange={(_, d) => setRank(d.value)} aria-label="LoRA rank" /></Field>
        <Field label="LoRA alpha"><Input type="number" value={alpha} onChange={(_, d) => setAlpha(d.value)} aria-label="LoRA alpha" /></Field></div>}
      <div style={{ display: "flex", gap: 8 }}><Button appearance="primary" disabled={!ready || busy} onClick={go}>{busy ? "Importing..." : "Import model"}</Button><Button onClick={onCancel}>Cancel</Button></div>
    </Card>
  );
}

function DeployChat({ model }) {
  const notify = useNotify();
  const accts = useAsync(async () => (await hub.listAccounts()).filter((a) => MODEL_KINDS.includes(a.kind)), []);
  const [sel, setSel] = useState(""), [dep, setDep] = useState(`${model.name.toLowerCase().replace(/[^a-z0-9-]/g, "-")}`.slice(0, 40)), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("Say hello in five words."), [hist, setHist] = useState([]), [chatBusy, setChatBusy] = useState(false), [cerr, setCerr] = useState(null), [deployed, setDeployed] = useState(null);
  const list = accts.data || [];
  useEffect(() => { if (!sel && list.length) setSel(`${list[0].resourceGroup}/${list[0].name}`); }, [list.length]);   // eslint-disable-line react-hooks/exhaustive-deps
  const [rg, an] = sel.split("/");
  const existing = useAsync(async () => (an ? (await listDeployments(rg, an)).filter((d) => d.properties?.model?.name === model.id) : []), [rg, an, model.id, deployed]);
  const cur = deployed || existing.data?.[0]?.name || "";
  const deploy = async () => {
    setBusy(true); setErr(null);
    try { await putDeployment(rg, an, dep, { sku: { name: "Standard", capacity: 1 }, properties: { model: { format: "Vyomi", name: model.id, version: "1" } } }); setDeployed(dep); notify.success(`Deployment '${dep}' was created.`, "Deployment succeeded"); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const send = async (text = msg, max = 128) => {
    const next = [...hist, { role: "user", content: text }];
    setChatBusy(true); setCerr(null);
    try {
      const key = (await listKeys(rg, an)).key1;
      const r = await api.chat(key, cur, next, max);
      setHist([...next, { role: "assistant", content: r.choices[0].message.content, usage: r.usage }]); setMsg("");
    } catch (x) { setCerr(x); } finally { setChatBusy(false); }
  };
  return (
    <Card title="Deploy and chat" testid="deploy-chat">
      {!accts.loading && !list.length && <Bar intent="warning">Create an <a href="#/cognitiveservices/create">Azure OpenAI or Foundry resource</a> first: a custom model is deployed on a resource like any other model.</Bar>}
      {!!list.length && <Field label="Resource"><Select value={sel} onChange={(_, d) => setSel(d.value)} aria-label="Resource">{list.map((a) => <option key={a.id} value={`${a.resourceGroup}/${a.name}`}>{a.name}</option>)}</Select></Field>}
      {err && <Bar intent="error" testid="deploy-error">{err.message}</Bar>}
      {!cur && !!list.length && <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
        <Field label="Deployment name"><Input value={dep} onChange={(_, d) => setDep(d.value)} aria-label="Deployment name" /></Field>
        <Button appearance="primary" disabled={!dep || busy} onClick={deploy}>{busy ? "Deploying..." : "Deploy"}</Button></div>}
      {cur && <div data-testid="deployed-as">Deployed as <b>{cur}</b> on {an}. It is also listed under Model deployments and in the Chat playground of that resource: <a href={`#/cognitiveservices/${e(rg)}/${e(an)}/playground`}>Open the chat playground</a>.</div>}
      {cur && <>
        <ServingBar />
        <div data-testid="chat-history" style={{ display: "grid", gap: 6 }}>{hist.map((m, i) => <div key={i} style={{ background: m.role === "user" ? "var(--colorBrandBackground2, #eef)" : "var(--colorNeutralBackground3, #f5f5f5)", padding: 8 }}><b>{m.role === "user" ? "User" : "Assistant"}:</b> <span data-testid={m.role === "assistant" ? "chat-answer" : undefined} style={{ whiteSpace: "pre-wrap" }}>{m.content}</span>{m.usage ? ` (${m.usage.total_tokens} tokens)` : ""}</div>)}</div>
        {cerr && <Bar intent="error" testid="chat-error">{cerr.message}</Bar>}
        <Field label="Message"><Textarea value={msg} onChange={(_, d) => setMsg(d.value)} aria-label="Message" rows={2} /></Field>
        <div style={{ display: "flex", gap: 8 }}><Button appearance="primary" disabled={!msg || chatBusy} onClick={() => send()}>{chatBusy ? "Running..." : "Send"}</Button><Button disabled={chatBusy} onClick={() => send("Reply with OK.", 4)} data-testid="warm-up">Load into browser</Button></div></>}
    </Card>
  );
}

export default function CustomModelsPage() {
  const notify = useNotify();
  const list = useAsync(() => api.list(), []);
  const [creating, setCreating] = useState(false), [open, setOpen] = useState(null), [err, setErr] = useState(null);
  const rows = list.data || [];
  const sel = rows.find((m) => m.id === open);
  return (
    <div className="vy-page" data-testid="foundry-custom-models" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 8 }}><Button appearance="primary" onClick={() => setCreating(true)}>Import custom model</Button><Button onClick={list.reload}>Refresh</Button></div>
      <Bar>Bring a LoRA adapter you trained on Mesh or your own machine. It becomes a custom chat model you can deploy and call through the normal chat completions API. This is a Vyomi extension: Azure has no API that registers a custom LoRA adapter. {NANO_ONLY}</Bar>
      {err && <Bar intent="error">{err.message}</Bar>}
      {creating && <Import onCancel={() => setCreating(false)} onDone={(m) => { setCreating(false); notify.success(`Imported model '${m.name}'.`, "Import succeeded"); list.reload(); setOpen(m.id); }} />}
      {list.loading && !rows.length ? <Spinner /> : (
        <Table aria-label="Custom models"><TableHeader><TableRow>{["Name", "Model id", "Base model", "Rank / alpha", "Adapter", "Status", ""].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
          <TableBody>{rows.length ? rows.map((m) => (
            <TableRow key={m.id}><TableCell><a href="#/foundry/custommodels" onClick={(ev) => { ev.preventDefault(); setOpen(m.id); }}>{m.name}</a></TableCell><TableCell>{m.id}</TableCell><TableCell>{m.base_model}</TableCell>
              <TableCell>{m.vyomiImport?.rank} / {m.vyomiImport?.alpha}</TableCell><TableCell>{fmtBytes(m.vyomiImport?.adapterBytes)}</TableCell><TableCell><Badge appearance="tint" color="success">{m.status}</Badge></TableCell>
              <TableCell><Button size="small" appearance="subtle" aria-label={`Delete ${m.name}`} onClick={async () => { try { await api.remove(m.id); if (open === m.id) setOpen(null); list.reload(); } catch (x) { setErr(x); } }}>Delete</Button></TableCell></TableRow>))
            : <TableRow><TableCell colSpan={7}>No custom models yet. Import a LoRA adapter to create one.</TableCell></TableRow>}</TableBody></Table>)}
      {sel && <><Bar testid="model-framing">{sel.vyomiNote}</Bar><DeployChat key={sel.id} model={sel} /></>}
    </div>
  );
}
