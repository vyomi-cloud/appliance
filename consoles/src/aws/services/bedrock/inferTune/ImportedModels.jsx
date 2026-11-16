/* Custom model import (Bedrock): Imported models / Import jobs, an import wizard (upload adapter.gguf + adapter_meta.json, or point at an S3 prefix),
 * job detail with the validation result, and a model detail page with in-browser serving progress and a try-it chat.
 * Backend: CreateModelImportJob / ListImportedModels ... (core/bedrock_ctl_core.py) over core/import_core.py; serving on Nano = wasm/wllama-bridge.js.
 * Vyomi extension: real Bedrock imports Hugging Face weights; here the S3 prefix holds a LoRA adapter GGUF trained elsewhere. */
import { useEffect, useRef, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { CapabilityBadge } from "../../../kit/Capability.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { ErrorAlert } from "../../../kit/common.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { navigate } from "../../../../common/router.js";
import { s3 as s3call } from "../../../../common/wire.js";
import { FRAMING, IMPORT_BASES, META_HELP, NANO_ONLY, TRAIN_HINT, checkAdapterFile, fmtBytes, isNanoSubstrate, randomSuffix, resolveMeta, servingState, useWllama } from "../../../../common/importModel.js";
import * as s3api from "../../s3/api.js";
import * as api from "./api.js";
import * as base from "../api.js";
import { CreateModal, HowItWorks, Page, jobStatus, when } from "./Shared.jsx";

const idOf = (arn) => String(arn || "").split("/").pop();
const NAME_RE = /^[a-zA-Z0-9](-*[a-zA-Z0-9+\-.])*$/;
const STAGE_BUCKET = "vyomi-models";

/** Progress of the in-browser engine (base download, load, ready), straight from wasm/wllama-bridge.js. */
export function ServingBar() {
  const st = useWllama(), s = servingState(st);
  if (!isNanoSubstrate() && !st) return <Alert type="info" data-testid="serving-nano-only">{NANO_ONLY}</Alert>;
  return (
    <SpaceBetween size="xs">
      <ProgressBar value={s.pct ?? (s.busy ? undefined : 0)} status={s.error ? "error" : s.done ? "success" : "in-progress"} label="In-browser engine" description={s.label} resultText={s.done ? "Ready" : undefined} variant="standalone" data-testid="serving-bar" />
      {st?.note && s.busy && <Box variant="small" color="text-body-secondary">{st.note}</Box>}
      {st && s.done && <Box variant="small" color="text-body-secondary">{st.multiThread ? `${st.threads} threads` : "Single thread"}; {st.base || "base"} cached in this browser (OPFS).</Box>}
    </SpaceBetween>
  );
}

function ImportWizard({ visible, onDismiss, onStarted }) {
  const [mode, setMode] = useState("upload");
  const [jn, setJn] = useState(`import-${randomSuffix()}`), [mn, setMn] = useState(""), [uri, setUri] = useState("s3://");
  const [adapter, setAdapter] = useState(null), [metaFile, setMetaFile] = useState(null), [chk, setChk] = useState(null);
  const [bm, setBm] = useState(IMPORT_BASES[0].id), [rank, setRank] = useState("8"), [alpha, setAlpha] = useState("16"), [quant, setQuant] = useState("");
  const [progress, setProgress] = useState("");
  const bases = IMPORT_BASES.map((b) => ({ label: b.name, value: b.id, description: `Quantisations: ${Object.entries(b.quants).map(([q, mb]) => `${q} ${mb} MB`).join(", ")}` }));
  const quants = Object.keys(IMPORT_BASES.find((b) => b.id === bm).quants).map((q) => ({ label: q, value: q }));
  useEffect(() => { checkAdapterFile(adapter).then((r) => setChk(adapter ? r : null)); }, [adapter]);
  const nameOk = NAME_RE.test(mn) && NAME_RE.test(jn);
  const uriOk = /^s3:\/\/[a-z0-9][a-z0-9.-]{1,61}[a-z0-9](\/.*)?$/.test(uri);
  const ready = nameOk && (mode === "upload" ? chk?.ok && (metaFile || (rank && alpha)) : uriOk);
  const submit = async () => {
    let src = uri;
    if (mode === "upload") {
      const meta = await resolveMeta({ metaFile, base: bm, rank, alpha, quant });
      const prefix = `uploads/${mn}-${randomSuffix()}/`;
      setProgress("Uploading adapter to the simulated S3");
      try { await s3api.createBucket(STAGE_BUCKET); } catch (_) { /* exists */ }
      await s3call("PUT", `/${STAGE_BUCKET}/${prefix}adapter.gguf`, { body: await adapter.arrayBuffer(), headers: { "content-type": "application/octet-stream" } });
      await s3call("PUT", `/${STAGE_BUCKET}/${prefix}adapter_meta.json`, { body: meta, headers: { "content-type": "application/json" } });
      src = `s3://${STAGE_BUCKET}/${prefix}`;
    }
    setProgress("Creating the import job");
    const r = await api.createImportJob(jn, mn, src);
    onStarted(idOf(r.jobArn));
  };
  return (
    <CreateModal visible={visible} onDismiss={onDismiss} header="Import model" submitLabel="Import model" size="large" disabled={!ready} onSubmit={submit}>
      <Alert type="info" data-testid="import-framing">{FRAMING} {TRAIN_HINT}</Alert>
      <FormField label="Imported model name" constraintText="Letters, digits, hyphens, plus and dot."><Input value={mn} onChange={({ detail }) => setMn(detail.value)} ariaLabel="Imported model name" invalid={!!mn && !NAME_RE.test(mn)} /></FormField>
      <FormField label="Job name"><Input value={jn} onChange={({ detail }) => setJn(detail.value)} ariaLabel="Job name" /></FormField>
      <FormField label="Model import source"><RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)} items={[
        { value: "upload", label: "Upload adapter files", description: "adapter.gguf (LoRA adapter, up to 50 MB) and optionally adapter_meta.json" },
        { value: "s3", label: "Amazon S3 prefix", description: "A prefix in the simulated S3 that already holds adapter.gguf and adapter_meta.json" }]} /></FormField>
      {mode === "upload" ? (
        <SpaceBetween size="m">
          <FormField label="Adapter file (adapter.gguf)" description="LoRA adapter converted with llama.cpp convert_lora_to_gguf.py.">
            <input type="file" accept=".gguf" aria-label="Adapter file" data-testid="adapter-input" onChange={(e) => setAdapter(e.target.files?.[0] || null)} />
          </FormField>
          {adapter && chk && !chk.ok && <Alert type="error" data-testid="adapter-error">{chk.error}</Alert>}
          {adapter && chk?.ok && <Alert type="success" data-testid="adapter-ok">{adapter.name}, {fmtBytes(adapter.size)}. GGUF header looks right; the engine checks rank, hidden size and base on import.</Alert>}
          <FormField label="adapter_meta.json (optional)" description={`${META_HELP} Leave empty to use the fields below.`}>
            <input type="file" accept=".json" aria-label="Meta file" data-testid="meta-input" onChange={(e) => setMetaFile(e.target.files?.[0] || null)} />
          </FormField>
          {!metaFile && <ColumnLayout columns={4}>
            <FormField label="Base model"><Select selectedOption={bases.find((b) => b.value === bm)} options={bases} ariaLabel="Base model" onChange={({ detail }) => { setBm(detail.selectedOption.value); setQuant(""); }} /></FormField>
            <FormField label="LoRA rank"><Input type="number" value={rank} onChange={({ detail }) => setRank(detail.value)} ariaLabel="LoRA rank" /></FormField>
            <FormField label="LoRA alpha"><Input type="number" value={alpha} onChange={({ detail }) => setAlpha(detail.value)} ariaLabel="LoRA alpha" /></FormField>
            <FormField label="Base quantisation"><Select selectedOption={quants.find((q) => q.value === quant) || { label: `Default (${IMPORT_BASES.find((b) => b.id === bm).defaultQuant})`, value: "" }} options={[{ label: "Default", value: "" }, ...quants]} ariaLabel="Base quantisation" onChange={({ detail }) => setQuant(detail.selectedOption.value)} /></FormField>
          </ColumnLayout>}
        </SpaceBetween>
      ) : (
        <FormField label="S3 location" description="s3://bucket/prefix/ that holds adapter.gguf and adapter_meta.json"><Input value={uri} onChange={({ detail }) => setUri(detail.value)} ariaLabel="S3 location" invalid={uri.length > 5 && !uriOk} /></FormField>
      )}
      {progress && <Box color="text-status-info" data-testid="import-progress"><Spinner /> {progress}</Box>}
    </CreateModal>
  );
}

export default function ImportedModels() {
  const notify = useNotify();
  const models = useAsync(() => api.listImportedModels(), []), jobs = useAsync(() => api.listImportJobs(), []);
  const [msel, setMsel] = useState([]), [jsel, setJsel] = useState([]), [open, setOpen] = useState(false), [del, setDel] = useState(false);
  const imp = <Button variant="primary" onClick={() => setOpen(true)}>Import model</Button>;
  return (
    <Page title="Imported models" description="Import a customized model, bring your own LoRA adapter, and use it through Converse and InvokeModel on its ARN. Imported models are billed per use; in this simulator they run in your browser for free.">
      <HowItWorks steps={[
        { title: "Train an adapter", body: TRAIN_HINT },
        { title: "Import it", body: "Upload adapter.gguf (and adapter_meta.json). The import job validates the file (GGUF header, rank, hidden size, base model) and registers the model, or fails with the reason." },
        { title: "Use it", body: "Open the model in the playground, or call Converse and InvokeModel on its ARN with any AWS SDK. " + NANO_ONLY },
      ]}><CapabilityBadge id="bedrock.imported-models" /></HowItWorks>
      <Tabs tabs={[
        { id: "models", label: "Models", content: (
          <ResourceTable variant="container" resourceName="Imported models" description="Models you imported. Each is a small open base model plus your LoRA adapter." items={models.data || []} loading={models.loading} error={models.error} onRefresh={models.reload}
            trackBy="modelArn" selectionType="single" selectedItems={msel} onSelectionChange={setMsel} filterPlaceholder="Find imported model"
            empty={{ title: "No imported models", subtitle: "Import a LoRA adapter to create one.", action: imp }}
            actions={<><Button disabled={!msel.length} onClick={() => navigate("bedrock", "playground")}>Open in playground</Button><Button disabled={!msel.length} onClick={() => setDel(true)}>Delete</Button>{imp}</>}
            columns={[
              { id: "name", header: "Model name", isRowHeader: true, sortingField: "modelName", cell: (m) => <Link href={`#/bedrock/imported-models/${encodeURIComponent(idOf(m.modelArn))}`}>{m.modelName}</Link> },
              { id: "arn", header: "Model ARN", cell: (m) => <Box variant="code">{m.modelArn}</Box> },
              { id: "created", header: "Creation time (UTC)", sortingField: "creationTime", cell: (m) => when(m.creationTime) },
            ]} />) },
        { id: "jobs", label: "Jobs", content: (
          <ResourceTable variant="container" resourceName="Import jobs" description="Every import is a job: it validates the adapter and registers the model, or fails with the reason." items={jobs.data || []} loading={jobs.loading} error={jobs.error} onRefresh={jobs.reload}
            trackBy="jobArn" selectionType="single" selectedItems={jsel} onSelectionChange={setJsel} filterPlaceholder="Find jobs" empty={{ title: "No import jobs", subtitle: "There are currently no resources." }} actions={imp}
            columns={[
              { id: "name", header: "Job name", isRowHeader: true, sortingField: "jobName", cell: (j) => <Link href={`#/bedrock/imported-models/jobs/${encodeURIComponent(idOf(j.jobArn))}`}>{j.jobName}</Link> },
              { id: "status", header: "Status", cell: (j) => jobStatus(j.status) },
              { id: "model", header: "Imported model", cell: (j) => j.importedModelName },
              { id: "created", header: "Creation time (UTC)", sortingField: "creationTime", cell: (j) => when(j.creationTime) },
            ]} />) },
      ]} />
      <ImportWizard visible={open} onDismiss={() => setOpen(false)} onStarted={(id) => { notify.success("Import job created."); navigate("bedrock", "imported-models", "jobs", id); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="imported model" names={msel.map((m) => m.modelName)} onConfirm={async () => { await api.deleteImportedModel(idOf(msel[0].modelArn)); setMsel([]); models.reload(); }} />
    </Page>
  );
}

const Kv = ({ label, children, id }) => <div><Box variant="awsui-key-label">{label}</Box><div data-testid={id}>{children ?? "-"}</div></div>;

/** One job: status, the failure reason when validation rejected the adapter, and where it came from. Polls while InProgress. */
export function ImportJobDetail({ params }) {
  const id = decodeURIComponent(params.id);
  const [job, setJob] = useState(null), [err, setErr] = useState(null), timer = useRef();
  useEffect(() => {
    let dead = false;
    const loop = async () => {
      try { const j = await api.getImportJob(id); if (dead) return; setJob(j); setErr(null); if (j.status === "InProgress") timer.current = setTimeout(loop, 1200); } catch (e) { if (!dead) setErr(e); }
    };
    loop(); return () => { dead = true; clearTimeout(timer.current); };
  }, [id]);
  if (!job) return <Page title="Import job">{err ? <ErrorAlert error={err} header="Could not load the job" /> : <Spinner />}</Page>;
  const stages = [["Validate adapter", job.status !== "InProgress" && job.status !== "Failed" ? 100 : job.status === "Failed" ? 0 : 50], ["Register model", job.status === "Completed" ? 100 : 0]];
  return (
    <Page title={job.jobName} description="Model import job">
      {job.status === "Failed" && <Alert type="error" header="Import failed" data-testid="job-failure">{job.failureMessage}</Alert>}
      {job.status === "Completed" && <Alert type="success" data-testid="job-done">The model was imported. <Link href={`#/bedrock/imported-models/${encodeURIComponent(idOf(job.importedModelArn))}`}>Open {job.importedModelName}</Link></Alert>}
      <Container header={<Header variant="h2" actions={<Button onClick={() => navigate("bedrock", "imported-models")}>Back to imported models</Button>}>Job details</Header>}>
        <ColumnLayout columns={3} variant="text-grid">
          <Kv label="Status" id="job-status">{jobStatus(job.status)}</Kv>
          <Kv label="Imported model name">{job.importedModelName}</Kv>
          <Kv label="Creation time (UTC)">{when(job.creationTime)}</Kv>
          <Kv label="Source" id="job-source"><Box variant="code">{job.modelDataSource?.s3DataSource?.s3Uri}</Box></Kv>
          <Kv label="Job ARN"><Box variant="code">{job.jobArn}</Box></Kv>
          <Kv label="Ended">{when(job.endTime)}</Kv>
        </ColumnLayout>
      </Container>
      <Container header={<Header variant="h2">Progress</Header>}>
        <SpaceBetween size="m">{stages.map(([l, v]) => <ProgressBar key={l} value={v} label={l} status={job.status === "Failed" && v === 0 ? "error" : v === 100 ? "success" : "in-progress"} />)}</SpaceBetween>
        {job.vyomiNote && <Box variant="small" color="text-body-secondary" margin={{ top: "s" }}>{job.vyomiNote}</Box>}
      </Container>
    </Page>
  );
}

/** One imported model: details, in-browser serving progress + a "Load into browser" warm-up, and a try-it chat through Converse on the ARN. */
export function ImportedModelDetail({ params }) {
  const id = decodeURIComponent(params.id);
  const m = useAsync(() => api.getImportedModel(id), [id]);
  const [prompt, setPrompt] = useState("Say hello in five words."), [out, setOut] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const arn = m.data?.modelArn;
  const run = async (text, max = 128) => {
    setBusy(true); setErr(null);
    try { const r = await base.converse(arn, text, { maxTokens: max, temperature: 0 }); setOut(r); return r; } catch (e) { setErr(e); return null; } finally { setBusy(false); }
  };
  if (m.loading && !m.data) return <Page title="Imported model"><Spinner /></Page>;
  if (m.error) return <Page title="Imported model"><ErrorAlert error={m.error} header="Could not load the model" /></Page>;
  const d = m.data, vi = d.vyomiImport || {};
  return (
    <Page title={d.modelName} description="Imported model">
      <Alert type="info" data-testid="model-framing">{d.vyomiNote || FRAMING}</Alert>
      <Container header={<Header variant="h2" actions={<Button onClick={() => navigate("bedrock", "playground")}>Open in playground</Button>}>Model details</Header>}>
        <ColumnLayout columns={3} variant="text-grid">
          <Kv label="Model ARN"><Box variant="code">{d.modelArn}</Box></Kv>
          <Kv label="Creation time (UTC)">{when(d.creationTime)}</Kv>
          <Kv label="Import job"><Link href={`#/bedrock/imported-models/jobs/${encodeURIComponent(idOf(d.jobArn))}`}>{d.jobName}</Link></Kv>
          <Kv label="Base model" id="m-base">{vi.base}</Kv>
          <Kv label="LoRA rank / alpha" id="m-rank">{vi.rank} / {vi.alpha}</Kv>
          <Kv label="Adapter size">{fmtBytes(vi.adapterBytes)}</Kv>
          <Kv label="Architecture">{d.modelArchitecture}</Kv>
          <Kv label="Source"><Box variant="code">{d.modelDataSource?.s3DataSource?.s3Uri}</Box></Kv>
          <Kv label="Adapter SHA-256"><Box variant="code">{String(vi.adapterSha256 || "").slice(0, 16)}</Box></Kv>
        </ColumnLayout>
      </Container>
      <Container header={<Header variant="h2" description="The first request downloads the base model and loads it with your adapter. Later requests answer from the loaded model.">In-browser serving</Header>}>
        <SpaceBetween size="m">
          <ServingBar />
          <Button loading={busy} onClick={() => run("Reply with OK.", 4)} data-testid="warm-up">Load into browser</Button>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2" description="Converse on the imported model ARN, exactly what an SDK call does.">Try it</Header>}>
        <SpaceBetween size="m">
          <Textarea value={prompt} onChange={({ detail }) => setPrompt(detail.value)} rows={3} ariaLabel="Prompt" />
          <div><Button variant="primary" loading={busy} disabled={!prompt} onClick={() => run(prompt)} data-testid="try-run">Run</Button></div>
          {err && <Alert type="error" header={err.code === "ModelNotReadyException" ? "The model is not ready" : err.code}>{err.message}</Alert>}
          {out && <Container header={<Header variant="h3">Response</Header>}><div data-testid="try-output" style={{ whiteSpace: "pre-wrap" }}>{out.output.message.content.map((c) => c.text).join("")}</div>
            <Box variant="small" color="text-body-secondary">{out.usage.inputTokens} input tokens, {out.usage.outputTokens} output tokens, {out.metrics.latencyMs} ms</Box></Container>}
        </SpaceBetween>
      </Container>
    </Page>
  );
}
