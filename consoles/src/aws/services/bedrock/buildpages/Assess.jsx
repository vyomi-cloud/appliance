/* Bedrock Assess + Configure: model evaluation jobs, model access, settings (invocation logging), prompt optimization.
 * Evaluations score the local model with simple metrics (core/bedrock_build_core); settings/access/optimize are the real control-plane ops. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Multiselect from "@cloudscape-design/components/multiselect";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue, fmtDate } from "../../../kit/common.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { follow, href, navigate } from "../../../../common/router.js";
import { CreateModal, Field, ModelSelect, Page, jobStatus, providerOf, useModelOptions, when } from "../inferTune/Shared.jsx";
import * as base from "../api.js";
import * as api from "./api.js";

const METRICS = [{ label: "Accuracy (token F1 vs reference)", value: "Builtin.Accuracy" }, { label: "Robustness (answer stability under prompt perturbation)", value: "Builtin.Robustness" }, { label: "Toxicity (share of answers hitting the guardrail lexicon)", value: "Builtin.Toxicity" }];
const TASKS = ["QuestionAndAnswer", "Summarization", "Classification", "Generation", "Custom"].map((v) => ({ label: v, value: v }));

export function Evaluations() {
  const t = useAsync(() => api.listEvaluations(), []);
  const models = useModelOptions();
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [del, setDel] = useState(false);
  const [name, setName] = useState(""), [model, setModel] = useState(null), [task, setTask] = useState(TASKS[0]), [ds, setDs] = useState("s3://"), [out, setOut] = useState("s3://"), [mets, setMets] = useState([METRICS[0]]);
  const New = <Button variant="primary" onClick={() => setOpen(true)}>Create</Button>;
  return (
    <Page title="Model evaluations" description="Evaluate foundation models with a custom prompt dataset and automatic metrics. Jobs run on the local model and write per-record scores to S3.">
      <Alert type="info">Automated model evaluation only. The scorers are simple open metrics (token F1, perturbation consistency, a guardrail lexicon), not the managed BERTScore or real-world-knowledge scorers. Human, RAG and LLM-as-a-judge evaluations are not simulated.</Alert>
      <ResourceTable variant="container" resourceName="Evaluation jobs" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="jobArn" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        filterPlaceholder="Find evaluation jobs" empty={{ title: "No evaluation jobs", action: New }}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>{New}</SpaceBetween>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "jobName", cell: (j) => <Link href={href("bedrock", "evaluations", api.tail(j.jobArn))} onFollow={follow}>{j.jobName}</Link> },
          { id: "status", header: "Status", sortingField: "status", cell: (j) => jobStatus(j.status) },
          { id: "model", header: "Model", cell: (j) => j.modelIdentifiers?.join(", ") },
          { id: "task", header: "Task type", cell: (j) => j.evaluationTaskTypes?.join(", ") },
          { id: "created", header: "Creation time", sortingField: "creationTime", cell: (j) => when(j.creationTime) },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Create automatic evaluation" size="large" disabled={!name || !model || ds.length < 6 || out.length < 6 || !mets.length}
        onSubmit={async () => {
          const r = await api.createEvaluation({ jobName: name, evaluationConfig: { automated: { datasetMetricConfigs: [{ taskType: task.value, dataset: { name: "custom-dataset", datasetLocation: { s3Uri: ds } }, metricNames: mets.map((m) => m.value) }] } },
            inferenceConfig: { models: [{ bedrockModel: { modelIdentifier: model, inferenceParams: JSON.stringify({ temperature: 0 }) } }] }, outputDataConfig: { s3Uri: out } });
          notify.success(`Evaluation job "${name}" submitted.`); t.reload(); navigate("bedrock", "evaluations", api.tail(r.jobArn));
        }}>
        <Field label="Evaluation name" value={name} onChange={setName} />
        <FormField label="Model"><ModelSelect value={model} onChange={setModel} {...models} /></FormField>
        <FormField label="Task type"><Select selectedOption={task} options={TASKS} onChange={({ detail }) => setTask(detail.selectedOption)} ariaLabel="Task type" /></FormField>
        <FormField label="Metrics"><Multiselect selectedOptions={mets} options={METRICS} onChange={({ detail }) => setMets(detail.selectedOptions)} ariaLabel="Metrics" /></FormField>
        <Field label="Prompt dataset (S3 JSONL)" description='One JSON per line: {"prompt": "...", "referenceResponse": "...", "category": "..."}; at most 25 records are scored.' placeholder="s3://my-bucket/dataset.jsonl" value={ds} onChange={setDs} />
        <Field label="Evaluation results (S3 location)" placeholder="s3://my-bucket/results/" value={out} onChange={setOut} />
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="evaluation job" names={sel.map((j) => j.jobName)}
        onConfirm={async () => { await api.deleteEvaluation(api.tail(sel[0].jobArn)); notify.success("Evaluation job deleted."); setSel([]); t.reload(); }} />
    </Page>
  );
}

export function EvaluationDetail({ params }) {
  const id = params.id;
  const j = useAsync(() => api.getEvaluation(id), [id]);
  const d = j.data;
  const rep = d?.vyomiReport;
  const names = rep ? [...new Set(rep.datasets.flatMap((x) => Object.keys(x.metrics)))] : [];
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={j.reload}>Refresh</Button>}>{d?.jobName || id}</Header>}>
      <SpaceBetween size="l">
        {j.error && <ErrorAlert error={j.error} />}
        {d && <KeyValue title="Evaluation summary" items={[["Status", jobStatus(d.status)], ["Job type", `${d.jobType} model evaluation`], ["Model", d.inferenceConfig.models.map((m) => m.bedrockModel.modelIdentifier).join(", ")], ["Output", d.outputDataConfig.s3Uri],
          ["Created", when(d.creationTime)], ["Last modified", when(d.lastModifiedTime)]]} />}
        {d?.failureMessages?.length ? <Alert type="error" header="Job failed">{d.failureMessages.join("; ")}</Alert> : null}
        {rep && <Table variant="container" header={<Header variant="h2" description={`Scorer: ${rep.scorer}`}>Metric summary</Header>} items={rep.datasets} trackBy="name"
          columnDefinitions={[{ id: "d", header: "Dataset", isRowHeader: true, cell: (x) => x.name }, { id: "n", header: "Records", cell: (x) => x.records },
            ...names.map((m) => ({ id: m, header: m.replace("Builtin.", ""), cell: (x) => (x.metrics[m] ?? "-") })), { id: "o", header: "Per-record results", cell: (x) => x.output }]} />}
      </SpaceBetween>
    </ContentLayout>
  );
}

// ── Model access ──
export function ModelAccess() {
  const t = useAsync(async () => {
    const ms = await base.listModels();
    return Promise.all(ms.map(async (m) => ({ ...m, access: await api.modelAvailability(m.modelId).catch(() => null) })));
  }, []);
  return (
    <Page title="Model access" description="Models served by this Vyomi space. Access is granted automatically: the models are local open models, so there is no end-user agreement or entitlement request.">
      <Alert type="info">Standard Bedrock ids (anthropic.*, amazon.*, meta.*, cohere.*) are aliases answered by a local open model; the Backed by column names it.</Alert>
      <ResourceTable variant="container" resourceName="Models" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="modelId" filterPlaceholder="Find models"
        empty={{ title: "No models" }}
        columns={[
          { id: "name", header: "Model", isRowHeader: true, sortingField: "modelName", cell: (m) => m.modelName },
          { id: "id", header: "Model ID", cell: (m) => m.modelId },
          { id: "prov", header: "Provider", sortingField: "providerName", cell: (m) => m.providerName || providerOf(m.modelId) },
          { id: "access", header: "Access status", cell: (m) => (m.access ? <StatusIndicator type="success">{m.access.authorizationStatus === "AUTHORIZED" ? "Access granted" : m.access.authorizationStatus}</StatusIndicator> : <StatusIndicator type="error">Unknown</StatusIndicator>) },
          { id: "mod", header: "Output", cell: (m) => (m.outputModalities || []).join(", ") },
          { id: "back", header: "Backed by", cell: (m) => m.vyomiBackedBy?.localModel || "native local model" },
        ]} />
    </Page>
  );
}

// ── Settings: model invocation logging ──
export function Settings() {
  const t = useAsync(() => api.getLogging(), []);
  const notify = useNotify();
  const c = t.data;
  const [f, setF] = useState(null);
  const form = f || { s3: !!c?.s3Config, bucket: c?.s3Config?.bucketName || "", prefix: c?.s3Config?.keyPrefix || "", cw: !!c?.cloudWatchConfig, group: c?.cloudWatchConfig?.logGroupName || "/aws/bedrock/modelinvocations", role: c?.cloudWatchConfig?.roleArn || base.roleArn(), text: c?.textDataDeliveryEnabled ?? true };
  const set = (k, v) => setF({ ...form, [k]: v });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.putLogging({ ...(form.s3 ? { s3Config: { bucketName: form.bucket, ...(form.prefix ? { keyPrefix: form.prefix } : {}) } } : {}), ...(form.cw ? { cloudWatchConfig: { logGroupName: form.group, roleArn: form.role } } : {}),
        textDataDeliveryEnabled: form.text, imageDataDeliveryEnabled: false, embeddingDataDeliveryEnabled: false });
      notify.success("Model invocation logging saved."); setF(null); t.reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Page title="Settings" description="Model invocation logging collects invocation logs, model input data and model output data for all invocations in this account.">
      <Container header={<Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!c} onClick={async () => { try { await api.deleteLogging(); notify.success("Logging configuration deleted."); setF(null); t.reload(); } catch (e) { notify.error(e); } }}>Delete configuration</Button><Button variant="primary" loading={busy} disabled={!form.s3 && !form.cw} onClick={save}>Save settings</Button></SpaceBetween>}>Model invocation logging</Header>}>
        <SpaceBetween size="m">
          {t.error && <ErrorAlert error={t.error} />}
          <Alert type="info">After saving, every successful InvokeModel and Converse call writes a record to the selected destinations (S3 as gzip JSON under AWSLogs/.../BedrockModelInvocationLogs, CloudWatch Logs as one JSON event). Image, video and embedding payload delivery is not produced.</Alert>
          <StatusIndicator type={c ? "success" : "stopped"}>{c ? "Logging is on" : "Logging is off"}</StatusIndicator>
          <Checkbox checked={form.text} onChange={({ detail }) => set("text", detail.checked)}>Include text data in logs</Checkbox>
          <Checkbox checked={form.s3} onChange={({ detail }) => set("s3", detail.checked)}>Amazon S3</Checkbox>
          {form.s3 && <SpaceBetween size="xs"><Field label="S3 bucket name" value={form.bucket} onChange={(v) => set("bucket", v)} /><Field label="Key prefix (optional)" value={form.prefix} onChange={(v) => set("prefix", v)} /></SpaceBetween>}
          <Checkbox checked={form.cw} onChange={({ detail }) => set("cw", detail.checked)}>Amazon CloudWatch Logs</Checkbox>
          {form.cw && <SpaceBetween size="xs"><Field label="Log group name" value={form.group} onChange={(v) => set("group", v)} /><Field label="Service role ARN" value={form.role} onChange={(v) => set("role", v)} /></SpaceBetween>}
        </SpaceBetween>
      </Container>
    </Page>
  );
}

// ── Advanced prompt optimization ──
export function PromptOptimization() {
  const models = useModelOptions();
  const [model, setModel] = useState(null);
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); setErr(null); setRes(null); try { setRes(await api.optimizePrompt(text, model)); } catch (e) { setErr(e); } finally { setBusy(false); } };
  return (
    <Page title="Advanced prompt optimization" description="Rewrite a prompt for a target model with OptimizePrompt.">
      <Alert type="info">Optimization is a meta-prompt run by the local model. It tidies role, task and output format and keeps {"{{variables}}"}; it is not Bedrock's managed optimizer and quality is that of the local model. Dataset-driven optimization jobs are not simulated.</Alert>
      <Container header={<Header variant="h2">Optimize a prompt</Header>}>
        <SpaceBetween size="s">
          <FormField label="Target model"><ModelSelect value={model} onChange={setModel} {...models} /></FormField>
          <FormField label="Prompt"><Textarea value={text} rows={5} onChange={({ detail }) => setText(detail.value)} ariaLabel="Prompt to optimize" placeholder="Write the prompt to improve" /></FormField>
          <Box><Button variant="primary" loading={busy} disabled={!text || !model} onClick={go}>Optimize</Button></Box>
          {err && <ErrorAlert error={err} header="Optimization failed" />}
          {res !== null && <FormField label="Optimized prompt"><Box data-testid="optimized" variant="p"><span style={{ whiteSpace: "pre-wrap" }}>{res}</span></Box></FormField>}
        </SpaceBetween>
      </Container>
    </Page>
  );
}
