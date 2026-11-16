/* Foundry Evaluations (Azure OpenAI Evals API: /openai/evals, runs, output_items) and Prompt flow (flow.dag.yaml DAG, run on the shared flow runner).
 * Backend: core/azure_openai_agents_core.py (evals_dispatch, pf_dispatch) -> core/bedrock_build_core scorers + _Run. Prompt flow endpoints are a Vyomi extension. */
import { useEffect, useMemo, useState } from "react";
import { ReactFlow, Background, Controls, Handle, MarkerType, Position } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular, Play20Regular } from "@fluentui/react-icons";
import { restJson } from "../../../common/wire.js";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, InfoBar, Loading } from "../../kit/common.jsx";
import { listDeployments, MODEL_KINDS } from "../cognitiveservices/api.js";
import * as hub from "./api.js";

const AV = "2025-04-01-preview";
const H = { "api-key": "console" };
const oai = (m, path, body, query = {}) => restJson(m, `/openai${path}`, { query: { "api-version": AV, ...query }, body, headers: H });
const j = (v) => (typeof v === "string" ? v : JSON.stringify(v));

function useDeployments() {
  const q = useAsync(async () => {
    const accts = (await hub.listAccounts()).filter((a) => MODEL_KINDS.includes(a.kind));
    const out = [];
    for (const a of accts) (await listDeployments(a.resourceGroup, a.name).catch(() => [])).forEach((d) => out.push(d.name));
    return [...new Set(out)];
  }, []);
  return q.data || [];
}

// ── Evaluations ──────────────────────────────────────────────────────────────
const SAMPLE = '{"q": "Capital of France?", "a": "Paris"}\n{"q": "Capital of Spain?", "a": "Madrid"}';
export function EvaluationsPage() {
  const notify = useNotify();
  const deps = useDeployments();
  const evs = useAsync(() => oai("GET", "/evals").then((r) => r.data || []), []);
  const [open, setOpen] = useState(null);       // eval being inspected
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", model: "", rows: SAMPLE, system: "Answer with one word.", crit: "string_check", judge: true });
  const [err, setErr] = useState(null);
  const create = async () => {
    setErr(null);
    try {
      const rows = f.rows.split("\n").filter((x) => x.trim()).map((x) => JSON.parse(x));
      const keys = Object.keys(rows[0] || {});
      const first = keys[0], ref = keys[1] || keys[0];
      const prop = Object.fromEntries(keys.map((k) => [k, { type: "string" }]));
      const crit = [];
      if (f.crit === "string_check") crit.push({ type: "string_check", name: "exact match", input: "{{sample.output_text}}", operation: "ilike", reference: `{{item.${ref}}}` });
      if (f.crit === "text_similarity") crit.push({ type: "text_similarity", name: "rouge-l", input: "{{sample.output_text}}", reference: `{{item.${ref}}}`, evaluation_metric: "rouge_l", pass_threshold: 0.6 });
      if (f.judge && f.model) crit.push({ type: "label_model", name: "judge", model: f.model, input: [{ role: "user", content: `Question: {{item.${first}}}\nReference: {{item.${ref}}}\nAnswer: {{sample.output_text}}\nIs the answer correct?` }], labels: ["correct", "incorrect"], passing_labels: ["correct"] });
      const ev = await oai("POST", "/evals", { name: f.name, data_source_config: { type: "custom", item_schema: { type: "object", properties: prop, required: keys }, include_sample_schema: true }, testing_criteria: crit });
      await oai("POST", `/evals/${ev.id}/runs`, { name: `${f.name} run`, data_source: { type: "completions", model: f.model, input_messages: { type: "template", template: [{ role: "developer", content: f.system }, { role: "user", content: `{{item.${first}}}` }] }, source: { type: "file_content", content: rows.map((item) => ({ item })) } } });
      notify.success(`Evaluation '${f.name}' created and run started.`, "Create succeeded"); setAdding(false); evs.reload(); setOpen(ev);
    } catch (x) { setErr(x); }
  };
  return (
    <div className="vy-page" data-testid="foundry-evals">
      <div className="vy-cmdbar" role="toolbar" aria-label="Evaluation commands">
        <Button appearance="primary" icon={<Add20Regular />} onClick={() => { setF({ ...f, model: f.model || deps[0] || "" }); setAdding(true); }}>New evaluation</Button>
        <Button appearance="subtle" icon={<ArrowClockwise20Regular />} onClick={evs.reload}>Refresh</Button>
      </div>
      <ErrorBar error={evs.error} />
      <Table size="small" aria-label="Evaluations"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>ID</TableHeaderCell><TableHeaderCell>Graders</TableHeaderCell><TableHeaderCell style={{ width: 60 }} /></TableRow></TableHeader>
        <TableBody>{(evs.data || []).map((e) => (
          <TableRow key={e.id}><TableCell><Button appearance="transparent" onClick={() => setOpen(e)}>{e.name}</Button></TableCell><TableCell>{e.id}</TableCell><TableCell>{(e.testing_criteria || []).map((c) => c.name || c.type).join(", ")}</TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${e.name}`} onClick={async () => { await oai("DELETE", `/evals/${e.id}`); if (open?.id === e.id) setOpen(null); evs.reload(); }} /></TableCell></TableRow>))}
          {!evs.loading && !(evs.data || []).length && <TableRow><TableCell colSpan={4}>No evaluations yet. An evaluation grades model answers over a dataset with string, similarity and model-judge graders.</TableCell></TableRow>}</TableBody></Table>
      {open && <EvalDetail key={open.id} ev={open} />}
      <InfoBar>Evaluations use the Azure OpenAI Evals API (the openai SDK's client.evals works against this endpoint). Graders: string_check, text_similarity (fuzzy_match, bleu, rouge, cosine), label_model and score_model. The judge is the small local model, so judged scores are indicative only; python graders and logs data sources are not supported. Up to 1000 rows per run, graded in batches.</InfoBar>
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="New evaluation"><DialogBody><DialogTitle>New evaluation</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Field label="Evaluation name" required><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Evaluation name" /></Field>
            <Field label="Model deployment" required><Select value={f.model} onChange={(_, d) => setF({ ...f, model: d.value })} aria-label="Model deployment">{deps.length ? deps.map((n) => <option key={n}>{n}</option>) : <option value="">Deploy a model first</option>}</Select></Field>
            <Field label="System prompt"><Input value={f.system} onChange={(_, d) => setF({ ...f, system: d.value })} aria-label="System prompt" /></Field>
            <Field label="Dataset (JSON lines: first field = question, second = expected answer)"><Textarea rows={5} value={f.rows} onChange={(_, d) => setF({ ...f, rows: d.value })} aria-label="Dataset" /></Field>
            <Field label="Grader"><Select value={f.crit} onChange={(_, d) => setF({ ...f, crit: d.value })} aria-label="Grader"><option value="string_check">String check (contains the expected answer)</option><option value="text_similarity">Text similarity (ROUGE-L)</option><option value="none">None (judge only)</option></Select></Field>
            <label><input type="checkbox" checked={f.judge} onChange={(e) => setF({ ...f, judge: e.target.checked })} /> Add a model judge (label_model, local model)</label>
            <ErrorBar error={err} title="Failed to create the evaluation" /></div></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!f.name || !f.model} onClick={create}>Create and run</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </div>
  );
}

function EvalDetail({ ev }) {
  const runs = useAsync(() => oai("GET", `/evals/${ev.id}/runs`).then((r) => r.data || []), [ev.id]);
  useEffect(() => { if (!(runs.data || []).some((r) => r.status === "in_progress")) return undefined; const h = setInterval(runs.reload, 2500); return () => clearInterval(h); }, [runs.data]);   // eslint-disable-line react-hooks/exhaustive-deps
  const [sel, setSel] = useState(null);
  const items = useAsync(() => (sel ? oai("GET", `/evals/${ev.id}/runs/${sel}/output_items`, undefined, { limit: 100 }).then((r) => r.data || []) : Promise.resolve([])), [sel, (runs.data || []).find((r) => r.id === sel)?.status]);
  return (
    <section style={{ marginTop: 16 }} data-testid="eval-detail">
      <h3>{ev.name}: runs</h3>
      <Table size="small" aria-label="Runs"><TableHeader><TableRow><TableHeaderCell>Run</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Progress</TableHeaderCell><TableHeaderCell>Passed / failed / errored</TableHeaderCell><TableHeaderCell>Per grader (passed/failed)</TableHeaderCell></TableRow></TableHeader>
        <TableBody>{(runs.data || []).map((r) => (
          <TableRow key={r.id}><TableCell><Button appearance="transparent" onClick={() => setSel(r.id)}>{r.name}</Button></TableCell><TableCell data-testid="run-status">{r.status}</TableCell>
            <TableCell>{r.vyomiProgress ? `${r.vyomiProgress.processedItems}/${r.vyomiProgress.totalItems}` : "-"}</TableCell><TableCell>{r.result_counts.passed} / {r.result_counts.failed} / {r.result_counts.errored}</TableCell>
            <TableCell>{(r.per_testing_criteria_results || []).map((c) => `${c.testing_criteria}: ${c.passed}/${c.failed}`).join(", ")}</TableCell></TableRow>))}</TableBody></Table>
      {(runs.data || []).find((r) => r.error) && <ErrorBar error={new Error(j((runs.data || []).find((r) => r.error).error.message))} title="Run failed" />}
      {sel && (<Table size="small" aria-label="Output items" style={{ marginTop: 12 }}><TableHeader><TableRow><TableHeaderCell>Item</TableHeaderCell><TableHeaderCell>Model output</TableHeaderCell><TableHeaderCell>Result</TableHeaderCell><TableHeaderCell>Grader results</TableHeaderCell></TableRow></TableHeader>
        <TableBody>{(items.data || []).map((i) => (
          <TableRow key={i.id}><TableCell>{j(i.datasource_item)}</TableCell><TableCell>{i.sample?.output_text}</TableCell><TableCell>{i.status}</TableCell>
            <TableCell>{(i.results || []).map((r) => `${r.name}: ${r.score == null ? "unscored" : r.score}${r.passed ? " pass" : " fail"}`).join("; ")}</TableCell></TableRow>))}</TableBody></Table>)}
    </section>
  );
}

// ── Prompt flow ──────────────────────────────────────────────────────────────
const STARTER = (dep) => ({
  inputs: { question: { type: "string", default: "What is Azure?" } },
  outputs: { answer: { type: "string", reference: "${chat.output}" } },
  nodes: [{ name: "chat", type: "llm", source: { type: "code", path: "chat.jinja2" }, inputs: { deployment_name: dep, temperature: 0.2, question: "${inputs.question}" }, api: "chat", connection: "vyomi" }],
  files: { "chat.jinja2": "system:\nYou are a concise assistant.\n\nuser:\n{{question}}\n" },
});
const REF = /^\$\{([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}$/;
function FlowNode({ data }) {
  const col = data.kind === "inputs" ? "#107c10" : data.kind === "llm" ? "#0078d4" : data.kind === "prompt" ? "#8764b8" : "#a4262c";
  return (<div data-testid={`pfnode-${data.label}`} style={{ minWidth: 150, background: "#fff", color: "#201f1e", border: `2px solid ${data.sel ? "#000" : col}`, borderRadius: 6, fontSize: 12 }}>
    <Handle type="target" position={Position.Left} />
    <div style={{ background: col, color: "#fff", padding: "3px 8px", fontWeight: 600 }}>{data.label} <span style={{ opacity: 0.8, fontWeight: 400 }}>{data.kind}</span></div>
    <div style={{ padding: "4px 8px" }}>{data.sub}</div><Handle type="source" position={Position.Right} /></div>);
}
const nodeTypes = { pf: FlowNode };
function graph(flow, sel) {
  const nodes = [{ id: "inputs", type: "pf", position: { x: 0, y: 80 }, data: { label: "inputs", kind: "inputs", sub: Object.keys(flow.inputs || {}).join(", "), sel: sel === "inputs" } }];
  const edges = [];
  (flow.nodes || []).forEach((n, i) => {
    nodes.push({ id: n.name, type: "pf", position: { x: 230 * (i + 1), y: 20 + (i % 2) * 110 }, data: { label: n.name, kind: n.type, sub: n.type === "llm" ? n.inputs?.deployment_name : "template", sel: sel === n.name } });
    Object.values(n.inputs || {}).forEach((v) => { const m = REF.exec(String(v)); if (m) edges.push({ id: `${m[1]}-${n.name}-${edges.length}`, source: m[1], target: n.name, markerEnd: { type: MarkerType.ArrowClosed } }); });
  });
  const ox = 230 * ((flow.nodes || []).length + 1);
  Object.entries(flow.outputs || {}).forEach(([k, o], i) => { nodes.push({ id: `out_${k}`, type: "pf", position: { x: ox, y: 20 + i * 90 }, data: { label: k, kind: "output", sub: o.reference } }); const m = REF.exec(String(o.reference)); if (m) edges.push({ id: `o-${k}`, source: m[1], target: `out_${k}`, markerEnd: { type: MarkerType.ArrowClosed } }); });
  return { nodes, edges };
}

export function PromptFlowPage() {
  const notify = useNotify();
  const deps = useDeployments();
  const list = useAsync(() => oai("GET", "/vyomi/promptflow/flows").then((r) => r.data || []), []);
  const [cur, setCur] = useState(null);          // {name, flow}
  const [sel, setSel] = useState(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [dep, setDep] = useState("");
  const [inputs, setInputs] = useState("{}");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState("");
  const open = async (n) => { const f = await oai("GET", `/vyomi/promptflow/flows/${n}`); setCur({ name: f.name, flow: f.flow }); setSel(null); setRes(null); setInputs(JSON.stringify(Object.fromEntries(Object.entries(f.flow.inputs || {}).map(([k, v]) => [k, v.default ?? ""])), null, 1)); };
  const g = useMemo(() => (cur ? graph(cur.flow, sel) : { nodes: [], edges: [] }), [cur, sel]);
  const node = cur?.flow.nodes.find((n) => n.name === sel);
  const edit = (fn) => setCur({ ...cur, flow: fn(JSON.parse(JSON.stringify(cur.flow))) });
  const run = async (fn) => { setErr(null); setBusy("x"); try { await fn(); } catch (x) { setErr(x); } finally { setBusy(""); } };
  const create = () => run(async () => { await oai("POST", "/vyomi/promptflow/flows", { name, flow: STARTER(dep || deps[0] || "") }); setAdding(false); setName(""); list.reload(); await open(name); notify.success(`Flow '${name}' was created.`, "Create succeeded"); });
  const save = () => run(async () => { await oai("PUT", `/vyomi/promptflow/flows/${cur.name}`, { flow: cur.flow }); notify.success("Flow saved.", "Save succeeded"); list.reload(); });
  const test = () => run(async () => { setRes(await oai("POST", `/vyomi/promptflow/flows/${cur.name}/test`, { inputs: JSON.parse(inputs) })); });
  const addNode = (type) => edit((fl) => {
    const nm = `${type}_${fl.nodes.length + 1}`;
    fl.files[`${nm}.jinja2`] = type === "llm" ? "system:\nYou are a helpful assistant.\n\nuser:\n{{input}}\n" : "{{input}}";
    fl.nodes.push({ name: nm, type, source: { type: "code", path: `${nm}.jinja2` }, inputs: type === "llm" ? { deployment_name: deps[0] || "", temperature: 0.2, input: "${inputs." + (Object.keys(fl.inputs)[0] || "question") + "}" } : { input: "${inputs." + (Object.keys(fl.inputs)[0] || "question") + "}" }, ...(type === "llm" ? { api: "chat", connection: "vyomi" } : {}) });
    return fl;
  });
  const setSetting = (k, v) => edit((fl) => { fl.nodes.find((n) => n.name === sel).inputs[k] = v; return fl; });
  const setTemplate = (v) => edit((fl) => { fl.files[node.source.path] = v; return fl; });
  return (
    <div className="vy-page" data-testid="foundry-promptflow">
      <div className="vy-cmdbar" role="toolbar" aria-label="Prompt flow commands">
        <Button appearance="primary" icon={<Add20Regular />} onClick={() => setAdding(true)}>Create flow</Button>
        <Button appearance="subtle" icon={<ArrowClockwise20Regular />} onClick={list.reload}>Refresh</Button>
      </div>
      <ErrorBar error={list.error} />
      <Table size="small" aria-label="Flows"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Inputs</TableHeaderCell><TableHeaderCell>Outputs</TableHeaderCell><TableHeaderCell>Nodes</TableHeaderCell><TableHeaderCell style={{ width: 60 }} /></TableRow></TableHeader>
        <TableBody>{(list.data || []).map((f) => (
          <TableRow key={f.name}><TableCell><Button appearance="transparent" onClick={() => open(f.name)}>{f.name}</Button></TableCell><TableCell>{f.inputs.join(", ")}</TableCell><TableCell>{f.outputs.join(", ")}</TableCell><TableCell>{f.nodes}</TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${f.name}`} onClick={async () => { await oai("DELETE", `/vyomi/promptflow/flows/${f.name}`); if (cur?.name === f.name) setCur(null); list.reload(); }} /></TableCell></TableRow>))}
          {!list.loading && !(list.data || []).length && <TableRow><TableCell colSpan={5}>No flows yet. A prompt flow chains prompt and LLM nodes into a DAG with named inputs and outputs.</TableCell></TableRow>}</TableBody></Table>
      {cur && (
        <section style={{ marginTop: 16 }} data-testid="pf-editor">
          <div className="vy-cmdbar"><b style={{ marginRight: 12 }}>{cur.name}</b><Button size="small" onClick={() => addNode("llm")}>+ LLM node</Button><Button size="small" onClick={() => addNode("prompt")}>+ Prompt node</Button><Button appearance="primary" size="small" onClick={save}>Save</Button></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 12 }}>
            <div style={{ height: 320, border: "1px solid #c8c6c4" }} data-testid="pf-canvas"><ReactFlow nodes={g.nodes} edges={g.edges} nodeTypes={nodeTypes} onNodeClick={(_, n) => setSel(n.id)} fitView nodesConnectable={false} proOptions={{ hideAttribution: true }}><Background /><Controls showInteractive={false} /></ReactFlow></div>
            <div data-testid="pf-node-panel">{node ? (<div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <b>{node.name} ({node.type})</b>
              {node.type === "llm" && <Field label="Deployment"><Select value={node.inputs.deployment_name || ""} onChange={(_, d) => setSetting("deployment_name", d.value)} aria-label="Deployment">{[...new Set([node.inputs.deployment_name, ...deps].filter(Boolean))].map((n) => <option key={n}>{n}</option>)}</Select></Field>}
              {node.type === "llm" && <Field label="Temperature"><Input type="number" value={String(node.inputs.temperature ?? 0.2)} onChange={(_, d) => setSetting("temperature", Number(d.value))} aria-label="Temperature" /></Field>}
              <Field label={node.type === "llm" ? "Prompt (system: / user: sections, {{variables}})" : "Template ({{variables}})"}><Textarea rows={7} value={cur.flow.files[node.source.path] || ""} onChange={(_, d) => setTemplate(d.value)} aria-label="Template" /></Field>
              <Field label="Input wiring (JSON, ${node.output} references)"><Textarea rows={3} value={JSON.stringify(Object.fromEntries(Object.entries(node.inputs).filter(([k]) => !["deployment_name", "temperature"].includes(k))))} onChange={(_, d) => { try { const v = JSON.parse(d.value); edit((fl) => { const nn = fl.nodes.find((x) => x.name === sel); nn.inputs = { ...Object.fromEntries(Object.entries(nn.inputs).filter(([k]) => ["deployment_name", "temperature"].includes(k))), ...v }; return fl; }); } catch { /* typing */ } }} aria-label="Input wiring" /></Field>
            </div>) : <InfoBar>Select a node to edit its prompt, deployment and input wiring. Edges follow the ${"{node.output}"} references.</InfoBar>}</div>
          </div>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8, maxWidth: 640 }}>
            <Field label="Test inputs (JSON)"><Textarea rows={3} value={inputs} onChange={(_, d) => setInputs(d.value)} aria-label="Test inputs" /></Field>
            <div><Button appearance="primary" icon={<Play20Regular />} disabled={!!busy} onClick={test}>Run</Button></div>
            <ErrorBar error={err} title="Flow failed" />
            {res && (<div data-testid="pf-result"><b>Outputs</b><pre style={{ margin: 0 }}>{JSON.stringify(res.outputs, null, 1)}</pre>
              <b>Trace</b><ul>{res.trace.map((t, i) => <li key={i}>{t.node} {t.event}: {j(t.fields)}</li>)}</ul>
              <div>Deployed endpoint contract: <code>POST /openai/vyomi/promptflow/flows/{cur.name}/score</code> with the inputs JSON returns the outputs object.</div></div>)}
          </div>
        </section>)}
      <InfoBar>Flows use the flow.dag.yaml shape (inputs, outputs, llm and prompt nodes) and run on the same graph runner as Bedrock Flows, calling your Azure OpenAI deployments. Python tool nodes are not supported (they would run arbitrary code). Prompt flow management endpoints are a Vyomi extension; state is held in memory and cleared on restart.</InfoBar>
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Create flow"><DialogBody><DialogTitle>Create flow</DialogTitle>
          <DialogContent><Field label="Flow name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Flow name" /></Field>
            <Field label="Model deployment" required><Select value={dep || deps[0] || ""} onChange={(_, d) => setDep(d.value)} aria-label="Flow deployment">{deps.length ? deps.map((n) => <option key={n}>{n}</option>) : <option value="">Deploy a model first</option>}</Select></Field><ErrorBar error={err} title="Failed to create the flow" /></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!name || !(dep || deps[0])} onClick={create}>Create</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </div>
  );
}
