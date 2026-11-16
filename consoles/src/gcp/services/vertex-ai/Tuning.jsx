/* Vertex AI > Tuning: tuning jobs list + create + detail + try-it. A job on a TRAINABLE base (the embedding model or vyomi.head.*) really trains a
 * small head and carries `vyomiTraining`; on any other base it stays metadata-only and says so. Native wire: tuningJobs + the endpoint :predict. */
import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, MenuItem, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { restJson, sendRaw } from "../../../common/wire.js";
import { HeldOutBars, ScoreBars, TrainingChart, TrainingProgress } from "../../../common/TrainingViz.jsx";
import { CAPS, HONEST, KEEP_TAB_OPEN, NON_TRAINABLE, TASKS, TRAINABLE_BASES, isActive, isNano, isTrainableBase, pct, splitUri, trainingOf, validateJsonl } from "../../../common/training.js";
import { AI_CHAT, DEFAULT_CHAT } from "../../../common/aiModels.js";
import { getProject, useProject } from "../../project.js";
import { PageHeader, Section, KeyValue, ErrorAlert, fmtDate } from "../../kit/common.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { Link } from "../../link.jsx";
import * as gcs from "../storage/api.js";
import * as api from "./api.js";

const status = (j) => trainingOf(j)?.status || api.stateText(j.state);
const chipColor = (s) => (/Completed|Succeeded/.test(s) ? "success" : /Failed/.test(s) ? "error" : /Stopped|Cancel/.test(s) ? "default" : "info");
const StatusChip = ({ j }) => <Chip size="small" variant="outlined" color={chipColor(status(j))} label={status(j)} />;
export const createTuningJob = (loc, body) => restJson("POST", `/v1/projects/${encodeURIComponent(getProject())}/locations/${loc}/tuningJobs`, { body });
export const predict = (endpoint, instances) => restJson("POST", `/v1/${endpoint}:predict`, { body: { instances } });

function DataPicker({ task, uri, setUri, onCheck }) {
  const buckets = useAsync(() => gcs.listBuckets(), []);
  const [bucket, setBucket] = useState(""), [objs, setObjs] = useState([]), [res, setRes] = useState(null);
  useEffect(() => { if (bucket) gcs.listLevel(bucket, "").then((r) => setObjs(r.objects.filter((o) => /\.jsonl?$/i.test(o.name)))).catch(() => setObjs([])); }, [bucket]);
  const m = splitUri(uri);
  useEffect(() => {
    let dead = false; setRes(null); onCheck(null);
    if (!m?.key) return undefined;
    (async () => {
      const meta = await gcs.getObject(m.bucket, m.key).catch(() => null);
      if (meta && Number(meta.size) > CAPS.bytes) return validateJsonl(null, task, Number(meta.size));
      const r = await sendRaw("GET", `/storage/v1/b/${encodeURIComponent(m.bucket)}/o/${encodeURIComponent(m.key)}`, { query: { alt: "media" } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return validateJsonl(r.text, task, meta ? Number(meta.size) : undefined);
    })().then((v) => { if (!dead) { setRes(v); onCheck(v); } }).catch((e) => { if (!dead) { const v = { ok: false, errors: [`Could not read ${uri}: ${e.message}`] }; setRes(v); onCheck(v); } });
    return () => { dead = true; };
  }, [uri, task]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1}>
        <TextField select size="small" label="Training bucket" value={bucket || m?.bucket || ""} sx={{ flex: 1 }} onChange={(e) => { setBucket(e.target.value); setUri(`gs://${e.target.value}/`); }} inputProps={{ "aria-label": "Training bucket" }}>
          {(buckets.data || []).map((b) => <MenuItem key={b.name} value={b.name}>{b.name}</MenuItem>)}</TextField>
        <TextField select size="small" label="Training object (.jsonl)" value={m?.key || ""} sx={{ flex: 1 }} disabled={!bucket && !m} onChange={(e) => setUri(`gs://${bucket || m.bucket}/${e.target.value}`)} inputProps={{ "aria-label": "Training object" }}>
          {objs.length ? objs.map((o) => <MenuItem key={o.name} value={o.name}>{o.name}</MenuItem>) : <MenuItem disabled value="">No .jsonl objects</MenuItem>}</TextField>
      </Stack>
      <Typography variant="caption" color="text.secondary">Limits: {CAPS.rows} rows, {CAPS.bytes / 1048576} MB, {CAPS.labels} labels.</Typography>
      {res && !res.ok && <Alert severity="error" data-testid="data-errors">{res.errors.map((e) => <div key={e}>{e}</div>)}</Alert>}
      {res?.ok && <Alert severity="success" data-testid="data-ok">{res.rows} rows, {(res.bytes / 1024).toFixed(1)} KB{res.labels.length ? `, ${res.labels.length} labels` : ""}. Within the limits.</Alert>}
    </Stack>
  );
}

function CreateDialog({ open, onClose }) {
  const notify = useNotify();
  const [name, setName] = useState(""), [loc, setLoc] = useState("us-central1"), [base, setBase] = useState(TRAINABLE_BASES[0].id), [task, setTask] = useState("classifier"), [uri, setUri] = useState("gs://"), [epochs, setEpochs] = useState("8");
  const [chk, setChk] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const trainable = isTrainableBase(base);
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await createTuningJob(loc, { tunedModelDisplayName: name, baseModel: base, supervisedTuningSpec: { trainingDatasetUri: uri, hyperParameters: { epochCount: String(epochs), ...(trainable ? { taskType: task } : {}) } } });
      notify.success(`Tuning job "${name}" started`); onClose(true, r);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={() => onClose(false)} fullWidth maxWidth="sm" aria-label="Create tuned model">
      <DialogTitle>Create tuned model</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {err && <Alert severity="error">{err.message}</Alert>}
          {trainable ? <Alert severity="info" data-testid="create-honest">{HONEST}{isNano() ? ` ${KEEP_TAB_OPEN}` : ""}</Alert>
            : <Alert severity="warning" data-testid="create-meta-only">{NON_TRAINABLE} The job completes with a tuned-model record only.</Alert>}
          <TextField size="small" label="Tuned model name" value={name} onChange={(e) => setName(e.target.value)} inputProps={{ "aria-label": "Tuned model name" }} />
          <TextField select size="small" label="Region" value={loc} onChange={(e) => setLoc(e.target.value)}>{api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}</TextField>
          <TextField select size="small" label="Base model" value={base} onChange={(e) => setBase(e.target.value)} inputProps={{ "aria-label": "Base model" }}>
            {TRAINABLE_BASES.map((b) => <MenuItem key={b.id} value={b.id}>{b.name} (trainable here)</MenuItem>)}
            {AI_CHAT.map((m) => <MenuItem key={m.id} value={m.id}>{m.id} (metadata only)</MenuItem>)}</TextField>
          {trainable && <TextField select size="small" label="Task type" value={task} onChange={(e) => setTask(e.target.value)} helperText={TASKS.find((x) => x.id === task)?.help} inputProps={{ "aria-label": "Task type" }}>{TASKS.map((x) => <MenuItem key={x.id} value={x.id}>{x.label}</MenuItem>)}</TextField>}
          {trainable ? <DataPicker task={task} uri={uri} setUri={setUri} onCheck={setChk} />
            : <TextField size="small" label="Training dataset (gs://)" value={uri} onChange={(e) => setUri(e.target.value)} />}
          <TextField size="small" label="Epochs" type="number" value={epochs} onChange={(e) => setEpochs(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={() => onClose(false)}>Cancel</Button><Button variant="contained" disabled={busy || !name || uri.length < 6 || (trainable && !chk?.ok)} onClick={go}>Start tuning</Button></DialogActions>
    </Dialog>
  );
}

export function TuningJobs() {
  const project = useProject();
  const jobs = useAsync(() => api.list("tuningJobs", { loc: "-" }), [project]);
  const [open, setOpen] = useState(false);
  const rows = jobs.data || [];
  const pending = rows.some((j) => isActive(trainingOf(j)?.status) || /_(PENDING|RUNNING)$/.test(j.state || ""));
  useEffect(() => { if (!pending) return undefined; const t = setInterval(jobs.refresh, 2000); return () => clearInterval(t); }, [pending, jobs.refresh]);
  return (
    <>
      <PageHeader title="Tuning" />
      <Stack spacing={1.5}>
        <Typography variant="body2" color="text.secondary">Tune models on your own data. On the embedding model a job really trains a small classifier or reranker head; on every other base model it is metadata only.</Typography>
        <Stack direction="row" spacing={1}><Button variant="contained" startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create tuned model</Button><Button startIcon={<RefreshIcon />} onClick={jobs.reload}>Refresh</Button></Stack>
        <ResourceTable resourceName="Tuning jobs" items={rows} rowKey={(i) => i.name} loading={jobs.loading} error={jobs.error} onRetry={jobs.reload} filterPlaceholder="Filter"
          empty={<Typography variant="body2" color="text.secondary">No tuning jobs in this project</Typography>}
          columns={[
            { id: "name", header: "Name", sortValue: (j) => j.tunedModelDisplayName || j.name, cell: (j) => { const p = api.pname(j.name); return <Link href={`#/vertex-ai/tuning/${p.location}/${p.id}`}>{j.tunedModelDisplayName || j.displayName || p.id}</Link>; } },
            { id: "state", header: "Status", cell: (j) => <StatusChip j={j} /> },
            { id: "base", header: "Base model", cell: (j) => api.shortId(j.baseModel) },
            { id: "kind", header: "Type", cell: (j) => (trainingOf(j) ? "Trained head" : "Metadata only") },
            { id: "prog", header: "Progress", cell: (j) => { const t = trainingOf(j); return t ? <Box sx={{ minWidth: 90 }}><LinearProgress variant="determinate" value={t.progress * 100} /></Box> : "—"; } },
            { id: "created", header: "Created", cell: (j) => fmtDate(j.createTime) },
          ]} />
      </Stack>
      <CreateDialog open={open} onClose={(ok, r) => { setOpen(false); if (ok) { jobs.reload(); const p = api.pname(r?.name || ""); if (p.id && isTrainableBase(r?.baseModel)) location.hash = `#/vertex-ai/tuning/${p.location}/${p.id}`; } }} />
    </>
  );
}

function TryIt({ job, t }) {
  const [text, setText] = useState(""), [doc, setDoc] = useState(""), [out, setOut] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const rerank = t.taskType === "reranker";
  const endpoint = job.tunedModel?.endpoint || job.tunedModel?.model;
  const run = async () => {
    setBusy(true); setErr(null); setOut(null);
    try { setOut(await predict(endpoint, [rerank ? { query: text, document: doc } : { text }])); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const p = out?.predictions?.[0];
  return (
    <Stack spacing={1.5}>
      {!endpoint && <Alert severity="warning">This job has no tuned-model endpoint yet.</Alert>}
      <TextField multiline minRows={2} size="small" label={rerank ? "Query" : "Text to classify"} value={text} onChange={(e) => setText(e.target.value)} inputProps={{ "aria-label": rerank ? "Query" : "Text to classify" }} />
      {rerank && <TextField multiline minRows={2} size="small" label="Document" value={doc} onChange={(e) => setDoc(e.target.value)} inputProps={{ "aria-label": "Document" }} />}
      <div><Button variant="contained" disabled={busy || !endpoint || !text || (rerank && !doc)} onClick={run}>Predict</Button></div>
      <ErrorAlert error={err} title="Predict failed" />
      {p && <Stack spacing={1} data-testid="try-result">
        {p.label != null && <Typography variant="h6" data-testid="try-label">Predicted label: {p.label}</Typography>}
        {p.score != null && <Typography variant="h6" data-testid="try-score">Relevance score: {Number(p.score).toFixed(4)}</Typography>}
        {p.scores && <ScoreBars scores={p.scores} />}
        {(out.vyomiTrained || p.vyomiTrained) && <Typography variant="caption" color="text.secondary">vyomiTrained: true. Produced by the small head trained in this simulator, not by a language model.</Typography>}
      </Stack>}
    </Stack>
  );
}

export function TuningDetail({ params }) {
  const project = useProject();
  const name = `projects/${project}/locations/${params.location}/tuningJobs/${params.id}`;
  const [job, setJob] = useState(null), [err, setErr] = useState(null), timer = useRef();
  const load = async () => { try { const j = await api.get(name); setJob(j); setErr(null); return j; } catch (e) { setErr(e); return null; } };
  useEffect(() => {
    let dead = false;
    const loop = async () => { const j = await load(); if (dead) return; const t = trainingOf(j); if (!j || isActive(t?.status) || /_(PENDING|RUNNING)$/.test(j.state || "")) timer.current = setTimeout(loop, 1500); };
    loop(); return () => { dead = true; clearTimeout(timer.current); };
  }, [name]);   // eslint-disable-line react-hooks/exhaustive-deps
  const t = trainingOf(job);
  const running = job && (t ? isActive(t.status) : /_(PENDING|RUNNING)$/.test(job.state || ""));
  const stop = async () => { try { await api.verb(name, "cancel"); } catch (e) { setErr(e); } load(); };
  return (
    <>
      <PageHeader title={job?.tunedModelDisplayName || params.id} back={<Button href="#/vertex-ai/tuning">Tuning</Button>}
        actions={job && <><Button disabled={!running} onClick={stop}>Stop job</Button><Button onClick={load}>Refresh</Button></>} />
      <ErrorAlert error={err} title="Failed to load tuning job" />
      {job && <Stack spacing={3}>
        <Alert severity="info" data-testid="honest-note">{t ? HONEST : NON_TRAINABLE}</Alert>
        {t && running && isNano() && <Alert severity="warning" data-testid="keep-open">{KEEP_TAB_OPEN}</Alert>}
        <Section title="Details">
          <Stack spacing={2}>
            <KeyValue items={[["Status", <span data-testid="job-status"><StatusChip j={job} /></span>], ["Base model", api.shortId(job.baseModel)], ["Task type", t ? TASKS.find((x) => x.id === t.taskType)?.label : "Metadata only"], ["Engine", <span data-testid="job-engine">{t?.engine}</span>],
              ["Training dataset", job.supervisedTuningSpec?.trainingDatasetUri], ["Training rows", t?.rows || ""], ["Tuned model", job.tunedModel?.model], ["Tuned model endpoint", job.tunedModel?.endpoint],
              ["Created", fmtDate(job.createTime)], ["Ended", fmtDate(t?.endedAt || job.endTime)]]} />
            {t && <TrainingProgress value={t.progress} status={t.status} label={`${t.status}${t.epochs ? `, epoch ${t.epoch} of ${t.epochs}` : ""}`} />}
            {t?.note && <Typography variant="body2" color="text.secondary" data-testid="job-note">{t.note}</Typography>}
            {job.error?.message && <Alert severity="error">{job.error.message}</Alert>}
          </Stack>
        </Section>
        {t && <Section title="Training metrics" description="Loss and training accuracy for each epoch"><TrainingChart metrics={t.metrics} epochs={t.epochs} /></Section>}
        {t && <Section title="Held-out accuracy vs baseline" description="Accuracy on rows the head never trained on"><HeldOutBars heldOut={t.heldOut} /></Section>}
        {t && <Section title="Output"><KeyValue items={[["Trained head artifact", <span data-testid="job-artifact">{t.artifact ? <code>{t.artifact}</code> : "Available when training completes"}</span>], ["Held-out accuracy", t.heldOut ? pct(t.heldOut.accuracy) : ""]]} /></Section>}
        {t && <Section title="Try it" description="Calls :predict on the tuned model endpoint. The trained head answers; no language model is involved.">
          {t.status === "Completed" ? <TryIt job={job} t={t} /> : <Typography variant="body2" color="text.secondary" data-testid="try-disabled">Available once training completes.</Typography>}</Section>}
      </Stack>}
    </>
  );
}
