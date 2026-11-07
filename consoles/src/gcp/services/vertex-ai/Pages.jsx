/* Vertex AI pages. Each is a handful of ResourceList / Tabbed blocks over the native aiplatform wire. */
import { useState } from "react";
import { Alert, Box, Button, Card, CardActions, CardContent, Chip, Grid, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { useProject } from "../../project.js";
import { PageHeader, Section, KeyValue, ErrorAlert } from "../../kit/common.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { Link } from "../../link.jsx";
import ResourceList, { StateChip, Tabbed } from "./ResourceList.jsx";
import { DeployModelDialog, DeployIndexDialog, UpsertDialog, QueryDialog } from "./Dialogs.jsx";
import * as api from "./api.js";

const nameField = { key: "displayName", label: "Name" };
const lastSeg = (s) => api.shortId(s);

/* ── Dashboard ── */
export function Dashboard() {
  const project = useProject();
  const counts = useAsync(() => Promise.all(api.COLLECTIONS.map(async ([c]) => { try { return (await api.list(c)).length; } catch { return 0; } })), [project]);
  const jobs = useAsync(async () => (await Promise.all(["trainingPipelines", "customJobs", "batchPredictionJobs", "pipelineJobs"].map((c) => api.list(c).catch(() => [])))).flat()
    .sort((a, b) => String(b.createTime).localeCompare(String(a.createTime))).slice(0, 6), [project]);
  return (
    <>
      <PageHeader title="Vertex AI dashboard" />
      <Stack spacing={3}>
        <Section title="Get started" description="Build, deploy and manage ML and generative AI applications.">
          <Stack direction="row" spacing={1.5} useFlexGap sx={{ flexWrap: "wrap" }}>
            <Button variant="contained" href="#/vertex-ai/studio">Open Vertex AI Studio</Button>
            <Button variant="outlined" href="#/vertex-ai/model-garden">Explore Model Garden</Button>
            <Button variant="outlined" href="#/vertex-ai/endpoints">Create endpoint</Button>
            <Button variant="outlined" href="#/vertex-ai/training">Train a model</Button>
          </Stack>
        </Section>
        <Section title="Resources in this project">
          <Grid container spacing={2}>
            {api.COLLECTIONS.map(([c, label, href], i) => (
              <Grid item xs={6} md={3} key={c}>
                <Card variant="outlined" component="a" href={`#/vertex-ai/${href}`} data-testid={`count-${c}`} sx={{ display: "block", textDecoration: "none", color: "inherit" }}>
                  <CardContent><Typography variant="h2" component="div">{counts.data ? counts.data[i] : "…"}</Typography><Typography variant="body2" color="text.secondary">{label}</Typography></CardContent>
                </Card>
              </Grid>))}
          </Grid>
        </Section>
        <Section title="Recent jobs">
          <ErrorAlert error={jobs.error} />
          {jobs.data?.length ? (
            <ResourceTable resourceName="jobs" columns={[{ id: "n", header: "Name", cell: (j) => j.displayName }, { id: "t", header: "Type", cell: (j) => api.pname(j.name).coll }, { id: "s", header: "Status", cell: (j) => <StateChip s={j.state} /> }, { id: "c", header: "Created", cell: (j) => api.when(j.createTime) }]}
              items={jobs.data} rowKey={(j) => j.name} />
          ) : <Typography variant="body2" color="text.secondary">No jobs yet. Start one from Training, Pipelines or Batch predictions.</Typography>}
        </Section>
      </Stack>
    </>
  );
}

/* ── Model Garden ── */
export function ModelGarden() {
  const notify = useNotify();
  const [q, setQ] = useState("");
  const [pub, setPub] = useState("");
  const [deploy, setDeploy] = useState(null);
  const [info, setInfo] = useState(null);
  const { data = [], loading, error } = useAsync(() => api.listModelGarden(), []);
  const pubs = [...new Set(data.map((m) => m.name.split("/")[1]))];
  const shown = data.filter((m) => (!pub || m.name.split("/")[1] === pub) && (!q || `${m.displayName} ${m.description} ${m.name}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <>
      <PageHeader title="Model Garden" actions={<CapabilityBadge id="gcp.vertex-ai.model-garden" host="[data-vyomi-header]" />} />
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }} alignItems="center">
          <TextField size="small" label="Search models" value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 280 }} />
          <Chip label="All" color={pub ? "default" : "primary"} onClick={() => setPub("")} />
          {pubs.map((p) => <Chip key={p} label={p} color={pub === p ? "primary" : "default"} onClick={() => setPub(p)} />)}
        </Stack>
        <ErrorAlert error={error} />
        {loading && <Typography variant="body2">Loading…</Typography>}
        <Grid container spacing={2}>
          {shown.map((m) => {
            const id = lastSeg(m.name);
            return (
              <Grid item xs={12} md={4} key={m.name}>
                <Card variant="outlined" data-testid="garden-card" sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
                  <CardContent sx={{ flex: 1 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{m.displayName}</Typography>
                    <Typography variant="caption" color="text.secondary">{m.name.split("/")[1]} · {m.openSourceCategory === "PROPRIETARY" ? "Proprietary" : "Open"} · {m.launchStage}</Typography>
                    <Typography variant="body2" sx={{ mt: 1 }}>{m.description}</Typography>
                  </CardContent>
                  <CardActions>
                    {m.servedByVyomi && <Button size="small" href="#/vertex-ai/studio">Open in Studio</Button>}
                    {m.supportedActions?.deploy && <Button size="small" onClick={() => setDeploy(m)}>Deploy</Button>}
                    <Button size="small" onClick={() => setInfo(m)}>View details</Button>
                  </CardActions>
                </Card>
              </Grid>);
          })}
        </Grid>
        {!loading && !shown.length && <Typography variant="body2" color="text.secondary">No models match.</Typography>}
      </Stack>
      {deploy && <FormDialog open title={`Deploy ${deploy.displayName}`} submitLabel="Deploy" onClose={() => setDeploy(null)}
        fields={[{ key: "displayName", label: "Model name", default: lastSeg(deploy.name) }, { key: "region", label: "Region", options: api.REGIONS, default: "us-central1" }]}
        onSubmit={async (v) => { await api.deployToNewEndpoint({ displayName: v.displayName, artifactUri: `gs://vertex-model-garden/${lastSeg(deploy.name)}`, imageUri: deploy.supportedActions.deploy.containerSpec.imageUri, loc: v.region }); notify.success(`Deployed ${v.displayName} to a new endpoint`); }} />}
      {info && <FormDialog open title={info.displayName} submitLabel="Close" fields={[{ key: "json", label: "Publisher model", multiline: true, default: JSON.stringify(info, null, 2) }]} onClose={() => setInfo(null)} onSubmit={async () => {}} />}
    </>
  );
}

/* ── Endpoints ── */
export function Endpoints() {
  return (
    <>
      <PageHeader title="Online prediction: Endpoints" actions={<CapabilityBadge id="gcp.vertex-ai.endpoints" host="[data-vyomi-header]" />} />
      <ResourceList coll="endpoints" title="Endpoints" singular="endpoint"
        fields={[nameField, { key: "description", label: "Description" }]}
        build={(v) => ({ body: { displayName: v.displayName, description: v.description }, idKey: "endpointId" })}
        href={(i) => `#/vertex-ai/endpoints/${api.pname(i.name).location}/${lastSeg(i.name)}`}
        columns={[{ id: "models", header: "Models", cell: (i) => (i.deployedModels || []).length }, { id: "traffic", header: "Traffic split", cell: (i) => Object.values(i.trafficSplit || {}).map((x) => `${x}%`).join(" / ") || "—" }]}
        actions={[{ label: "Deploy model", dialog: ({ item, onClose }) => <DeployModelDialog endpoint={item} onClose={onClose} /> }]} />
    </>
  );
}

export function EndpointDetail({ params }) {
  const notify = useNotify();
  const name = `projects/${useProject()}/locations/${params.location}/endpoints/${params.id}`;
  const ep = useAsync(() => api.get(name), [name]);
  const [dep, setDep] = useState(false);
  const e = ep.data;
  return (
    <>
      <PageHeader title={e ? e.displayName : params.id} back={<Button href="#/vertex-ai/endpoints">Endpoints</Button>}
        actions={<>{e && <><Button onClick={() => setDep(true)}>Deploy model</Button><Button onClick={ep.reload}>Refresh</Button></>}<CapabilityBadge id="gcp.vertex-ai.endpoints" host="[data-vyomi-header]" /></>} />
      <ErrorAlert error={ep.error} title="Failed to load endpoint" />
      {e && <Stack spacing={3}>
        <Section title="Details"><KeyValue items={[["Endpoint ID", params.id], ["Region", params.location], ["Resource name", e.name], ["Description", e.description || "—"], ["Created", api.when(e.createTime)]]} /></Section>
        <CapabilityContainer noBadge id="gcp.vertex-ai.endpoints" title="Deployed models" description="Models serving traffic on this endpoint.">
          {e.deployedModels?.length ? (
            <ResourceTable resourceName="deployed models" items={e.deployedModels} rowKey={(d) => d.id}
              columns={[{ id: "n", header: "Model", cell: (d) => d.displayName || lastSeg(d.model) }, { id: "id", header: "Deployed model ID", cell: (d) => d.id },
                { id: "t", header: "Traffic split", cell: (d) => `${(e.trafficSplit || {})[d.id] ?? 0}%` },
                { id: "m", header: "Machine type", cell: (d) => d.dedicatedResources?.machineSpec?.machineType || "—" },
                { id: "a", header: "Actions", cell: (d) => <Button size="small" onClick={async () => { try { await api.verb(e.name, "undeployModel", { deployedModelId: d.id }); notify.success("Model undeployed"); ep.reload(); } catch (x) { notify.error(x); } }}>Undeploy</Button> }]} />
          ) : <Typography variant="body2" color="text.secondary">No models deployed. Use Deploy model.</Typography>}
        </CapabilityContainer>
      </Stack>}
      {dep && e && <DeployModelDialog endpoint={e} onClose={(ok) => { setDep(false); if (ok) ep.reload(); }} />}
    </>
  );
}

/* ── Model Registry ── */
export function Models() {
  return (
    <>
      <PageHeader title="Model Registry" actions={<CapabilityBadge id="gcp.vertex-ai.models" host="[data-vyomi-header]" />} />
      <ResourceList coll="models" title="Models" singular="model" createLabel="Import model"
        fields={[nameField, { key: "artifactUri", label: "Model artifact location", default: "gs://my-bucket/model/" }, { key: "image", label: "Serving container image", default: "us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest" }]}
        build={(v) => ({ body: { model: { displayName: v.displayName, artifactUri: v.artifactUri, containerSpec: { imageUri: v.image } } }, upload: true })}
        columns={[{ id: "ver", header: "Version", cell: (i) => i.versionId || "1" }, { id: "dep", header: "Deployed to", cell: (i) => (i.deployedModels || []).map((d) => lastSeg(d.endpoint)).join(", ") || "—" }]}
        actions={[{ label: "Deploy to endpoint", dialog: ({ item, onClose }) => <DeployModelDialog model={item} onClose={onClose} /> }]} />
    </>
  );
}

/* ── Datasets ── */
const DS = { Image: "image_1.0.0", Text: "text_1.0.0", Tabular: "tabular_1.0.0", Video: "video_1.0.0" };
export function Datasets() {
  return (
    <>
      <PageHeader title="Datasets" actions={<CapabilityBadge id="gcp.vertex-ai.datasets" host="[data-vyomi-header]" />} />
      <ResourceList coll="datasets" title="Datasets" singular="dataset"
        fields={[nameField, { key: "type", label: "Data type", options: Object.keys(DS), default: "Image" }]}
        build={(v) => ({ body: { displayName: v.displayName, metadataSchemaUri: `gs://google-cloud-aiplatform/schema/dataset/metadata/${DS[v.type]}.yaml`, labels: { type: v.type.toLowerCase() } } })}
        columns={[{ id: "type", header: "Data type", cell: (i) => i.labels?.type || (i.metadataSchemaUri || "").split("/").pop().split("_")[0] }, { id: "n", header: "Items", cell: (i) => i.dataItemCount || "0" }]} />
    </>
  );
}

/* ── Training ── */
const cancel = { label: "Cancel", when: (i) => !/(SUCCEEDED|CANCELLED|FAILED)$/.test(i.state || ""), run: (i) => api.verb(i.name, "cancel") };
const stateCol = { id: "state", header: "Status", sortValue: (i) => i.state, cell: (i) => <StateChip s={i.state} /> };
const dur = (i) => (i.startTime && i.endTime ? `${Math.max(1, Math.round((new Date(i.endTime) - new Date(i.startTime)) / 1000))} s` : "—");
const IMG = "us-docker.pkg.dev/vertex-ai/training/scikit-learn-cpu.1-0:latest";
export function Training({ query }) {
  const jobPool = (v) => [{ machineSpec: { machineType: v.machine }, replicaCount: String(+v.replicas || 1), containerSpec: { imageUri: v.image } }];
  return (
    <>
      <PageHeader title="Training" actions={<CapabilityBadge id="gcp.vertex-ai.jobs" host="[data-vyomi-header]" />} />
      <Tabbed query={query} tabs={[
        { id: "pipelines", label: "Training pipelines", render: () => (
          <ResourceList coll="trainingPipelines" title="Training pipelines" singular="training pipeline" poll
            fields={[nameField, { key: "model", label: "Output model name" }, { key: "image", label: "Training container image", default: IMG }]}
            build={(v) => ({ body: { displayName: v.displayName, trainingTaskDefinition: "gs://google-cloud-aiplatform/schema/trainingjob/definition/custom_task_1.0.0.yaml", trainingTaskInputs: { workerPoolSpecs: jobPool({ machine: "n1-standard-4", replicas: 1, image: v.image }) }, modelToUpload: { displayName: v.model || `${v.displayName}-model` } } })}
            columns={[stateCol, { id: "dur", header: "Elapsed", cell: dur }, { id: "model", header: "Model", cell: (i) => (i.modelToUpload?.name ? lastSeg(i.modelToUpload.name) : "—") }]} actions={[cancel]} />) },
        { id: "custom", label: "Custom jobs", render: () => (
          <ResourceList coll="customJobs" title="Custom jobs" singular="custom job" poll
            fields={[nameField, { key: "machine", label: "Machine type", options: ["n1-standard-4", "n1-standard-8", "n1-highmem-8", "a2-highgpu-1g"], default: "n1-standard-4" }, { key: "replicas", label: "Replica count", default: "1" }, { key: "image", label: "Container image", default: IMG }]}
            build={(v) => ({ body: { displayName: v.displayName, jobSpec: { workerPoolSpecs: jobPool(v) } } })}
            columns={[stateCol, { id: "dur", header: "Elapsed", cell: dur }, { id: "m", header: "Machine", cell: (i) => i.jobSpec?.workerPoolSpecs?.[0]?.machineSpec?.machineType }]} actions={[cancel]} />) },
        { id: "hpt", label: "Hyperparameter tuning", render: () => (
          <ResourceList coll="hyperparameterTuningJobs" title="Hyperparameter tuning jobs" singular="tuning job" poll
            fields={[nameField, { key: "metric", label: "Metric ID", default: "accuracy" }, { key: "goal", label: "Goal", options: ["MAXIMIZE", "MINIMIZE"], default: "MAXIMIZE" }, { key: "trials", label: "Max trial count", default: "4" }, { key: "image", label: "Container image", default: IMG }]}
            build={(v) => ({ body: { displayName: v.displayName, maxTrialCount: +v.trials || 4, parallelTrialCount: 1, studySpec: { metrics: [{ metricId: v.metric, goal: v.goal }], parameters: [{ parameterId: "learning_rate", doubleValueSpec: { minValue: 0.001, maxValue: 0.1 } }] }, trialJobSpec: { workerPoolSpecs: jobPool({ machine: "n1-standard-4", replicas: 1, image: v.image }) } } })}
            columns={[stateCol, { id: "t", header: "Max trials", cell: (i) => i.maxTrialCount }]} actions={[cancel]} />) },
        { id: "tuning", label: "Model tuning", render: () => (
          <ResourceList coll="tuningJobs" title="Tuning jobs" singular="tuning job" poll
            fields={[nameField, { key: "base", label: "Base model", options: ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"], default: "gemini-2.0-flash" }, { key: "data", label: "Training dataset (gs://)", default: "gs://my-bucket/train.jsonl" }]}
            build={(v) => ({ body: { displayName: v.displayName, baseModel: v.base, supervisedTuningSpec: { trainingDatasetUri: v.data } } })}
            columns={[stateCol, { id: "b", header: "Base model", cell: (i) => i.baseModel }]} actions={[cancel]} />) },
      ]} />
    </>
  );
}

/* ── Pipelines ── */
export function Pipelines() {
  return (
    <>
      <PageHeader title="Pipelines" actions={<CapabilityBadge id="gcp.vertex-ai.jobs" host="[data-vyomi-header]" />} />
      <ResourceList coll="pipelineJobs" title="Pipeline runs" singular="pipeline run" createLabel="Create run" poll
        fields={[nameField, { key: "template", label: "Pipeline template (gs:// or Artifact Registry URI)", default: "gs://my-bucket/pipeline.json" }, { key: "root", label: "Pipeline root", default: "gs://my-bucket/pipeline-root" }]}
        build={(v) => ({ body: { displayName: v.displayName, templateUri: v.template, runtimeConfig: { gcsOutputDirectory: v.root } } })}
        columns={[stateCol, { id: "dur", header: "Duration", cell: dur }, { id: "t", header: "Template", cell: (i) => i.templateUri || "—" }]} actions={[cancel]} />
    </>
  );
}

/* ── Batch predictions ── */
export function Batch() {
  const models = useAsync(() => api.list("models"), []);
  return (
    <>
      <PageHeader title="Batch predictions" actions={<CapabilityBadge id="gcp.vertex-ai.jobs" host="[data-vyomi-header]" />} />
      <ResourceList coll="batchPredictionJobs" title="Batch predictions" singular="batch prediction" poll
        fields={[nameField, { key: "model", label: "Model", options: (models.data || []).map((m) => ({ value: m.name, label: m.displayName })) }, { key: "input", label: "Input (gs://)", default: "gs://my-bucket/input.jsonl" }, { key: "output", label: "Output prefix (gs://)", default: "gs://my-bucket/output" }]}
        build={(v) => ({ body: { displayName: v.displayName, model: v.model, inputConfig: { instancesFormat: "jsonl", gcsSource: { uris: [v.input] } }, outputConfig: { predictionsFormat: "jsonl", gcsDestination: { outputUriPrefix: v.output } } } })}
        columns={[stateCol, { id: "m", header: "Model", cell: (i) => lastSeg(i.model || "") || "—" }, { id: "o", header: "Output", cell: (i) => i.outputInfo?.gcsOutputDirectory || "—" }]} actions={[cancel]} />
    </>
  );
}

/* ── Workbench / Colab ── */
const power = [
  { label: "Start", when: (i) => i.state === "STOPPED" || i.runtimeState === "STOPPED", run: (i) => api.verb(i.name, "start", {}, i.name.includes("/instances/")) },
  { label: "Stop", when: (i) => i.state === "ACTIVE" || i.runtimeState === "RUNNING", run: (i) => api.verb(i.name, "stop", {}, i.name.includes("/instances/")) },
];
export function Workbench({ query }) {
  return (
    <>
      <PageHeader title="Workbench" actions={<CapabilityBadge id="gcp.vertex-ai.notebooks" host="[data-vyomi-header]" />} />
      <Tabbed query={query} tabs={[
        { id: "instances", label: "Instances", render: () => (
          <ResourceList coll="instances" v2 title="Instances" singular="notebook instance"
            fields={[{ key: "id", label: "Instance name", helper: "Lowercase letters, numbers and hyphens" }, { key: "machine", label: "Machine type", options: ["e2-standard-4", "n1-standard-4", "n1-standard-8", "g2-standard-4"], default: "n1-standard-4" }]}
            build={(v) => ({ body: { gceSetup: { machineType: v.machine } }, idKey: "instanceId", id: v.id })}
            nameOf={(i) => api.shortId(i.name)} hideId
            columns={[{ id: "state", header: "Status", cell: (i) => <StateChip s={i.state} /> }, { id: "m", header: "Machine type", cell: (i) => i.gceSetup?.machineType }, { id: "jl", header: "JupyterLab", cell: (i) => (i.state === "ACTIVE" ? <Link href={`https://${i.proxyUri}`} target="_blank">Open JupyterLab</Link> : "—") }]}
            actions={power} />) },
        { id: "runtimes", label: "Colab runtimes", render: () => (
          <ResourceList coll="notebookRuntimes" title="Runtimes" singular="runtime"
            fields={[nameField, { key: "template", label: "Runtime template", default: "" }]}
            build={(v) => ({ body: { displayName: v.displayName, notebookRuntimeTemplateRef: v.template ? { notebookRuntimeTemplate: v.template } : undefined } })}
            columns={[{ id: "state", header: "Status", cell: (i) => <StateChip s={i.runtimeState} /> }]} actions={power} />) },
        { id: "templates", label: "Runtime templates", render: () => (
          <ResourceList coll="notebookRuntimeTemplates" title="Runtime templates" singular="runtime template"
            fields={[nameField, { key: "machine", label: "Machine type", options: ["e2-standard-4", "n1-standard-4", "n1-standard-8"], default: "e2-standard-4" }]}
            build={(v) => ({ body: { displayName: v.displayName, machineSpec: { machineType: v.machine } } })}
            columns={[{ id: "m", header: "Machine type", cell: (i) => i.machineSpec?.machineType }]} />) },
      ]} />
    </>
  );
}

/* ── Vector Search ── */
export function VectorSearch({ query }) {
  return (
    <>
      <PageHeader title="Vector Search" actions={<CapabilityBadge id="gcp.vertex-ai.vector-search" host="[data-vyomi-header]" />} />
      <Tabbed query={query} tabs={[
        { id: "indexes", label: "Indexes", render: () => (
          <ResourceList coll="indexes" title="Indexes" singular="index"
            fields={[nameField, { key: "dims", label: "Dimensions", default: "128" }, { key: "dist", label: "Distance measure", options: ["COSINE_DISTANCE", "DOT_PRODUCT_DISTANCE", "SQUARED_L2_DISTANCE", "L1_DISTANCE"], default: "COSINE_DISTANCE" }]}
            build={(v) => ({ body: { displayName: v.displayName, indexUpdateMethod: "STREAM_UPDATE", metadata: { config: { dimensions: +v.dims, distanceMeasureType: v.dist, approximateNeighborsCount: 10, algorithmConfig: { treeAhConfig: {} } } } } })}
            columns={[{ id: "dim", header: "Dimensions", cell: (i) => i.metadata?.config?.dimensions }, { id: "vc", header: "Vectors", cell: (i) => i.indexStats?.vectorsCount || "0" }, { id: "dist", header: "Distance", cell: (i) => i.metadata?.config?.distanceMeasureType }, { id: "dep", header: "Deployed", cell: (i) => (i.deployedIndexes || []).length }]}
            actions={[{ label: "Upsert datapoints", dialog: ({ item, onClose }) => <UpsertDialog index={item} onClose={onClose} /> },
              { label: "Remove datapoint…", dialog: ({ item, onClose }) => <FormDialog open title="Remove datapoints" submitLabel="Remove" fields={[{ key: "ids", label: "Datapoint IDs (comma separated)" }]} onClose={onClose} onSubmit={(v) => api.verb(item.name, "removeDatapoints", { datapointIds: v.ids.split(",").map((s) => s.trim()).filter(Boolean) })} /> }]} />) },
        { id: "endpoints", label: "Index endpoints", render: () => (
          <ResourceList coll="indexEndpoints" title="Index endpoints" singular="index endpoint"
            fields={[nameField]} build={(v) => ({ body: { displayName: v.displayName, publicEndpointEnabled: true } })}
            columns={[{ id: "dep", header: "Deployed indexes", cell: (i) => (i.deployedIndexes || []).map((d) => d.id).join(", ") || "—" }]}
            actions={[{ label: "Deploy index", dialog: ({ item, onClose }) => <DeployIndexDialog endpoint={item} onClose={onClose} /> },
              { label: "Query index", dialog: ({ item, onClose }) => <QueryDialog endpoint={item} onClose={onClose} /> }]} />) },
      ]} />
    </>
  );
}

/* ── Feature Store ── */
export function FeatureStore({ query }) {
  return (
    <>
      <PageHeader title="Feature Store" actions={<CapabilityBadge id="gcp.vertex-ai.feature-store" host="[data-vyomi-header]" />} />
      <Tabbed query={query} tabs={[
        { id: "groups", label: "Feature groups", render: () => (
          <ResourceList coll="featureGroups" title="Feature groups" singular="feature group" hideId
            fields={[{ key: "id", label: "Feature group ID" }, { key: "table", label: "BigQuery source", default: "bq://my-project.my_dataset.my_table" }]}
            build={(v) => ({ body: { bigQuery: { bigQuerySource: { inputUri: v.table } } }, idKey: "featureGroupId", id: v.id })}
            nameOf={(i) => api.shortId(i.name)} columns={[{ id: "src", header: "Source", cell: (i) => i.bigQuery?.bigQuerySource?.inputUri }]} />) },
        { id: "features", label: "Features", render: () => (
          <ResourceList coll="features" title="Features" singular="feature" parentColl="featureGroups" parentLabel="Feature group" noRegion hideId
            fields={[{ key: "id", label: "Feature ID" }, { key: "description", label: "Description" }]}
            build={(v) => ({ body: { description: v.description }, idKey: "featureId", id: v.id })} nameOf={(i) => api.shortId(i.name)} />) },
        { id: "stores", label: "Online stores", render: () => (
          <ResourceList coll="featureOnlineStores" title="Online stores" singular="online store" hideId
            fields={[{ key: "id", label: "Online store ID" }]} build={(v) => ({ body: { optimized: {} }, idKey: "featureOnlineStoreId", id: v.id })}
            nameOf={(i) => api.shortId(i.name)} columns={[{ id: "type", header: "Type", cell: (i) => (i.optimized ? "Optimized" : "Bigtable") }]} />) },
        { id: "views", label: "Feature views", render: () => (
          <ResourceList coll="featureViews" title="Feature views" singular="feature view" parentColl="featureOnlineStores" parentLabel="Online store" noRegion hideId
            fields={[{ key: "id", label: "Feature view ID" }, { key: "group", label: "Feature group (optional)" }]}
            build={(v) => ({ body: v.group ? { featureRegistrySource: { featureGroups: [{ featureGroupId: v.group, featureIds: [] }] } } : {}, idKey: "featureViewId", id: v.id })} nameOf={(i) => api.shortId(i.name)} />) },
      ]} />
    </>
  );
}

/* ── Experiments, metadata, TensorBoard ── */
const mstore = (region, project) => `projects/${project}/locations/${region}/metadataStores/default`;
export function Experiments({ query }) {
  return (
    <>
      <PageHeader title="Experiments" actions={<CapabilityBadge id="gcp.vertex-ai.experiments" host="[data-vyomi-header]" />} />
      <Tabbed query={query} tabs={[
        { id: "experiments", label: "Experiments", render: () => (
          <ResourceList coll="contexts" title="Experiments" singular="experiment" fixedParent={mstore} noRegion hideId
            query={{ filter: 'schema_title="system.Experiment"' }}
            fields={[{ key: "id", label: "Experiment name", helper: "Lowercase letters, numbers and hyphens" }, { key: "description", label: "Description" }]}
            build={(v) => ({ body: { displayName: v.id, description: v.description, schemaTitle: "system.Experiment" }, idKey: "contextId", id: v.id })}
            nameOf={(i) => i.displayName || api.shortId(i.name)} columns={[{ id: "d", header: "Description", cell: (i) => i.description || "—" }]} />) },
        { id: "artifacts", label: "Artifacts", render: () => (
          <ResourceList coll="artifacts" title="Artifacts" singular="artifact" fixedParent={mstore} noRegion
            fields={[nameField, { key: "uri", label: "URI", default: "gs://my-bucket/artifact" }, { key: "type", label: "Schema", options: ["system.Artifact", "system.Dataset", "system.Model", "system.Metrics"], default: "system.Artifact" }]}
            build={(v) => ({ body: { displayName: v.displayName, uri: v.uri, schemaTitle: v.type } })}
            columns={[{ id: "t", header: "Type", cell: (i) => i.schemaTitle }, { id: "u", header: "URI", cell: (i) => i.uri || "—" }]} />) },
        { id: "executions", label: "Executions", render: () => (
          <ResourceList coll="executions" title="Executions" singular="execution" fixedParent={mstore} noRegion
            fields={[nameField, { key: "state", label: "State", options: ["COMPLETE", "RUNNING", "FAILED", "CACHED"], default: "COMPLETE" }]}
            build={(v) => ({ body: { displayName: v.displayName, state: v.state, schemaTitle: "system.ContainerExecution" } })}
            columns={[{ id: "s", header: "State", cell: (i) => <StateChip s={i.state} /> }]} />) },
        { id: "tensorboards", label: "TensorBoard", render: () => (
          <ResourceList coll="tensorboards" title="TensorBoard instances" singular="TensorBoard instance"
            fields={[nameField]} build={(v) => ({ body: { displayName: v.displayName } })} />) },
      ]} />
    </>
  );
}
