/* Foundry > Fine-tuning: Azure OpenAI fine-tuning jobs (list, create, detail, try-it) on the data-plane wire (/openai/fine_tuning/jobs, /openai/files).
 * A job on a TRAINABLE base (the embedding model or vyomi.head.*) really trains a small head and carries `vyomiTraining`; every other base is metadata only. */
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Field, Input, MessageBar, MessageBarBody, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea } from "@fluentui/react-components";
import { restJson, sendRaw, WIRE_BASE } from "../../../common/wire.js";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { HeldOutBars, ScoreBars, TrainingChart, TrainingProgress } from "../../../common/TrainingViz.jsx";
import { CAPS, HONEST, KEEP_TAB_OPEN, NON_TRAINABLE, TASKS, TRAINABLE_BASES, isActive, isNano, isTrainableBase, pct, trainingOf, validateJsonl } from "../../../common/training.js";
import { AI_CHAT } from "../../../common/aiModels.js";

const V = "2024-10-21", q = { "api-version": V };
const e = encodeURIComponent;
export const listJobs = () => restJson("GET", "/openai/fine_tuning/jobs", { query: q }).then((r) => r.data || []);
export const getJob = (id) => restJson("GET", `/openai/fine_tuning/jobs/${e(id)}`, { query: q });
export const cancelJob = (id) => restJson("POST", `/openai/fine_tuning/jobs/${e(id)}/cancel`, { query: q });
export const createJob = (body) => restJson("POST", "/openai/fine_tuning/jobs", { query: q, body });
export const listFiles = () => restJson("GET", "/openai/files", { query: { ...q, purpose: "fine-tune" } }).then((r) => r.data || []);
export const fileContent = (id) => sendRaw("GET", `/openai/files/${e(id)}/content`, { query: q });
/** Multipart upload exactly like the OpenAI/Azure SDKs: file + purpose=fine-tune. */
export async function uploadFile(name, text) {
  const fd = new FormData(); fd.append("purpose", "fine-tune"); fd.append("file", new Blob([text], { type: "application/jsonl" }), name);
  const res = await fetch(`${WIRE_BASE}/openai/files?api-version=${V}`, { method: "POST", body: fd });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(j.error?.message || `HTTP ${res.status}`);
  return j;
}
/** Chat-completions on a deployment: the last user message is classified and the label comes back as the assistant content (Vyomi extension). */
export const chat = (dep, content) => restJson("POST", `/openai/deployments/${e(dep)}/chat/completions`, { query: q, body: { messages: [{ role: "user", content }] } });

const stat = (j) => trainingOf(j)?.status || ({ succeeded: "Completed", running: "Training", pending: "Queued", validating_files: "Queued", queued: "Queued", failed: "Failed", cancelled: "Stopped" }[j.status] || j.status);
const color = (s) => (s === "Completed" ? "success" : s === "Failed" ? "danger" : s === "Stopped" ? "subtle" : "informative");
const StatusBadge = ({ j }) => <Badge appearance="tint" color={color(stat(j))}>{stat(j)}</Badge>;
const ts = (v) => (v ? new Date(typeof v === "number" ? v * 1000 : v).toLocaleString() : "-");
const Bar = ({ intent = "info", children, testid }) => <MessageBar intent={intent} data-testid={testid}><MessageBarBody>{children}</MessageBarBody></MessageBar>;
const Card = ({ title, sub, children }) => <section style={{ border: "1px solid var(--colorNeutralStroke2, #ddd)", borderRadius: 4, padding: 16, display: "grid", gap: 8 }}><div><h3 style={{ margin: 0 }}>{title}</h3>{sub && <div style={{ fontSize: 12, opacity: 0.7 }}>{sub}</div>}</div>{children}</section>;
const Kv = ({ rows }) => <dl style={{ display: "grid", gridTemplateColumns: "190px 1fr", gap: "6px 12px", margin: 0 }}>{rows.map(([k, v, id]) => <div key={k} style={{ display: "contents" }}><dt style={{ opacity: 0.7 }}>{k}</dt><dd style={{ margin: 0, wordBreak: "break-word" }} data-testid={id}>{v ?? "-"}</dd></div>)}</dl>;

function Create({ onDone, onCancel }) {
  const [base, setBase] = useState(TRAINABLE_BASES[0].id), [task, setTask] = useState("classifier"), [suffix, setSuffix] = useState(""), [epochs, setEpochs] = useState("8");
  const files = useAsync(() => listFiles().catch(() => []), []);
  const [fileId, setFileId] = useState(""), [local, setLocal] = useState(null), [chk, setChk] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const trainable = isTrainableBase(base);
  const check = (text, size) => setChk(validateJsonl(text, task, size));
  useEffect(() => {   // validate the chosen existing file (or re-validate the local one when the task type changes)
    let dead = false;
    if (local) { check(local.text, local.size); return undefined; }
    if (!fileId || !trainable) { setChk(null); return undefined; }
    fileContent(fileId).then((r) => { if (!dead) check(r.text, r.text.length); }).catch((x) => !dead && setChk({ ok: false, errors: [`Could not read ${fileId}: ${x.message}`] }));
    return () => { dead = true; };
  }, [fileId, task, local, trainable]);   // eslint-disable-line react-hooks/exhaustive-deps
  const pickLocal = async (ev) => { const f = ev.target.files?.[0]; if (!f) return; setFileId(""); setLocal({ name: f.name, size: f.size, text: f.size > CAPS.bytes ? null : await f.text() }); };
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      const id = local ? (await uploadFile(local.name, local.text)).id : fileId;
      const r = await createJob({ model: base, training_file: id, suffix: suffix || undefined, hyperparameters: { n_epochs: Number(epochs) || 1, ...(trainable ? { taskType: task } : {}) } });
      onDone(r, trainable);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const can = (local || fileId) && (!trainable || chk?.ok);
  return (
    <Card title="Create fine-tuning job" sub="Azure OpenAI fine-tuning: /openai/fine_tuning/jobs">
      {err && <Bar intent="error">{err.message}</Bar>}
      {trainable ? <Bar testid="create-honest">{HONEST}{isNano() ? ` ${KEEP_TAB_OPEN}` : ""}</Bar> : <Bar intent="warning" testid="create-meta-only">{NON_TRAINABLE} The job completes with a fine-tuned model record only.</Bar>}
      <Field label="Base model"><Select aria-label="Base model" value={base} onChange={(_, d) => setBase(d.value)}>
        <optgroup label="Trainable in this simulator">{TRAINABLE_BASES.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</optgroup>
        <optgroup label="Metadata only">{AI_CHAT.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}</optgroup></Select></Field>
      {trainable && <Field label="Task type" hint={TASKS.find((x) => x.id === task)?.help}><Select aria-label="Task type" value={task} onChange={(_, d) => setTask(d.value)}>{TASKS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</Select></Field>}
      <Field label="Training file" hint={`JSONL. Limits: ${CAPS.rows} rows, ${CAPS.bytes / 1048576} MB, ${CAPS.labels} labels.`}>
        <div style={{ display: "grid", gap: 8 }}>
          <Select aria-label="Uploaded training file" value={fileId} onChange={(_, d) => { setLocal(null); setFileId(d.value); }}><option value="">Choose an uploaded file</option>{(files.data || []).map((f) => <option key={f.id} value={f.id}>{f.filename} ({f.id})</option>)}</Select>
          <input type="file" accept=".jsonl,.json" aria-label="Upload training file" onChange={pickLocal} />
        </div>
      </Field>
      {local && local.text == null && <Bar intent="error" testid="data-errors">The file is {(local.size / 1048576).toFixed(1)} MB; the limit is {CAPS.bytes / 1048576} MB.</Bar>}
      {trainable && chk && !chk.ok && <Bar intent="error" testid="data-errors">{chk.errors.map((x) => <div key={x}>{x}</div>)}</Bar>}
      {trainable && chk?.ok && <Bar intent="success" testid="data-ok">{chk.rows} rows, {(chk.bytes / 1024).toFixed(1)} KB{chk.labels.length ? `, ${chk.labels.length} labels` : ""}. Within the limits.</Bar>}
      <Field label="Model name suffix"><Input aria-label="Model name suffix" value={suffix} onChange={(_, d) => setSuffix(d.value)} /></Field>
      <Field label="Epochs"><Input aria-label="Epochs" type="number" value={epochs} onChange={(_, d) => setEpochs(d.value)} /></Field>
      <div style={{ display: "flex", gap: 8 }}><Button appearance="primary" disabled={busy || !can} onClick={go}>Start fine-tuning</Button><Button onClick={onCancel}>Cancel</Button></div>
    </Card>
  );
}

export function FineTuningList() {
  const jobs = useAsync(() => listJobs(), []);
  const [creating, setCreating] = useState(false);
  const rows = jobs.data || [];
  const pending = rows.some((j) => isActive(trainingOf(j)?.status) || ["pending", "running", "queued"].includes(j.status));
  useEffect(() => { if (!pending) return undefined; const t = setInterval(jobs.refresh, 2000); return () => clearInterval(t); }, [pending, jobs.refresh]);
  if (creating) return <div className="vy-page"><Create onCancel={() => setCreating(false)} onDone={(r, tr) => { setCreating(false); if (tr) navigate("foundry", "finetuning", r.id); else jobs.reload(); }} /></div>;
  return (
    <div className="vy-page" data-testid="finetune-list" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 8 }}><Button appearance="primary" onClick={() => setCreating(true)}>Fine-tune model</Button><Button onClick={jobs.reload}>Refresh</Button></div>
      <Bar>Fine-tune on your data. On the embedding model a job really trains a small classifier or reranker head; on every other base model it is metadata only.</Bar>
      {jobs.error && <Bar intent="error">{jobs.error.message}</Bar>}
      {jobs.loading && !rows.length ? <Spinner /> : (
        <Table aria-label="Fine-tuning jobs"><TableHeader><TableRow>{["Job ID", "Status", "Base model", "Type", "Progress", "Created"].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
          <TableBody>{rows.length ? rows.map((j) => { const t = trainingOf(j); return (
            <TableRow key={j.id}>
              <TableCell>{isTrainableBase(j.model) ? <a href={`#/foundry/finetuning/${e(j.id)}`}>{j.id}</a> : j.id}</TableCell><TableCell><StatusBadge j={j} /></TableCell>
              <TableCell>{j.model}</TableCell><TableCell>{t ? "Trained head" : "Metadata only"}</TableCell><TableCell>{t ? pct(t.progress) : "-"}</TableCell><TableCell>{ts(j.created_at)}</TableCell>
            </TableRow>); }) : <TableRow><TableCell colSpan={6}>No fine-tuning jobs yet.</TableCell></TableRow>}</TableBody></Table>)}
    </div>
  );
}

function TryIt({ job, t }) {
  const [dep, setDep] = useState(job.fine_tuned_model || ""), [text, setText] = useState(""), [doc, setDoc] = useState(""), [out, setOut] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const rerank = t.taskType === "reranker";
  const run = async () => {
    setBusy(true); setErr(null); setOut(null);
    try { setOut(await chat(dep, rerank ? JSON.stringify({ query: text, document: doc }) : text)); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const content = out?.choices?.[0]?.message?.content, scores = out?.vyomi?.scores || out?.scores;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <Bar intent="warning">Vyomi extension: Azure has no classification API, so the last user message is classified by the trained head and the label comes back as the assistant message. It is not a language model.</Bar>
      <Field label="Deployment (the fine-tuned model name)"><Input aria-label="Deployment" value={dep} onChange={(_, d) => setDep(d.value)} /></Field>
      <Field label={rerank ? "Query" : "Text to classify"}><Textarea aria-label={rerank ? "Query" : "Text to classify"} value={text} onChange={(_, d) => setText(d.value)} /></Field>
      {rerank && <Field label="Document"><Textarea aria-label="Document" value={doc} onChange={(_, d) => setDoc(d.value)} /></Field>}
      <div><Button appearance="primary" disabled={busy || !dep || !text || (rerank && !doc)} onClick={run}>Run</Button></div>
      {err && <Bar intent="error">{err.message}</Bar>}
      {out && <div data-testid="try-result" style={{ display: "grid", gap: 8 }}>
        <div data-testid={rerank ? "try-score" : "try-label"}><b>{rerank ? "Relevance score" : "Predicted label"}:</b> {content}</div>
        {scores && <ScoreBars scores={scores} />}
        {out.vyomiTrained && <div style={{ fontSize: 12, opacity: 0.7 }}>vyomiTrained: true. Produced by the small head trained in this simulator, not by a language model.</div>}</div>}
    </div>
  );
}

export function FineTuningDetail({ id }) {
  const [job, setJob] = useState(null), [err, setErr] = useState(null), timer = useRef();
  const load = async () => { try { const j = await getJob(id); setJob(j); setErr(null); return j; } catch (x) { setErr(x); return null; } };
  useEffect(() => {
    let dead = false;
    const loop = async () => { const j = await load(); if (dead) return; const t = trainingOf(j); if (!j || isActive(t?.status) || ["pending", "running", "queued"].includes(j.status)) timer.current = setTimeout(loop, 1500); };
    loop(); return () => { dead = true; clearTimeout(timer.current); };
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!job) return <div className="vy-page">{err ? <Bar intent="error">{err.message}</Bar> : <Spinner />}</div>;
  const t = trainingOf(job), running = t ? isActive(t.status) : ["pending", "running", "queued"].includes(job.status);
  return (
    <div className="vy-page" data-testid="finetune-detail" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}><a href="#/foundry/finetuning">Fine-tuning</a><h2 style={{ margin: 0 }}>{job.id}</h2>
        <Button disabled={!running} onClick={async () => { try { await cancelJob(id); } catch (x) { setErr(x); } load(); }}>Cancel job</Button><Button onClick={load}>Refresh</Button></div>
      {err && <Bar intent="error">{err.message}</Bar>}
      <Bar testid="honest-note">{t ? HONEST : NON_TRAINABLE}</Bar>
      {t && running && isNano() && <Bar intent="warning" testid="keep-open">{KEEP_TAB_OPEN}</Bar>}
      <Card title="Job details">
        <Kv rows={[["Status", <StatusBadge j={job} />, "job-status"], ["Base model", job.model], ["Task type", t ? TASKS.find((x) => x.id === t.taskType)?.label : "Metadata only"], ["Engine", t?.engine, "job-engine"], ["Training file", job.training_file],
          ["Training rows", t?.rows || ""], ["Fine-tuned model", job.fine_tuned_model], ["Created", ts(job.created_at)], ["Finished", ts(t?.endedAt || job.finished_at)]]} />
        {t && <TrainingProgress value={t.progress} status={t.status} label={`${t.status}${t.epochs ? `, epoch ${t.epoch} of ${t.epochs}` : ""}`} />}
        {t?.note && <div data-testid="job-note" style={{ opacity: 0.8 }}>{t.note}</div>}
        {job.error?.message && <Bar intent="error">{job.error.message}</Bar>}
      </Card>
      {t && <Card title="Training metrics" sub="Loss and training accuracy for each epoch"><TrainingChart metrics={t.metrics} epochs={t.epochs} /></Card>}
      {t && <Card title="Held-out accuracy vs baseline" sub="Accuracy on rows the head never trained on"><HeldOutBars heldOut={t.heldOut} /></Card>}
      {t && <Card title="Output"><Kv rows={[["Trained head artifact", t.artifact ? <code>{t.artifact}</code> : "Available when training completes", "job-artifact"], ["Held-out accuracy", t.heldOut ? pct(t.heldOut.accuracy) : ""]]} /></Card>}
      {t && <Card title="Try it" sub="POST /openai/deployments/{deployment}/chat/completions">{t.status === "Completed" ? <TryIt job={job} t={t} /> : <div data-testid="try-disabled" style={{ opacity: 0.7 }}>Available once training completes.</div>}</Card>}
    </div>
  );
}
