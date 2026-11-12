/* EC2 Image Builder console: image pipelines, images (build versions with the real build log), components, image recipes,
 * infrastructure configurations and distribution settings. Every action is a real Image Builder API call. */
import { useEffect, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Multiselect from "@cloudscape-design/components/multiselect";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, useRoute } from "../../../common/router.js";
import * as api from "./api.js";

const tail = (arn) => (arn || "").split(":").pop();
const nameOf = (arn) => tail(arn).split("/")[1];
const stat = (s) => <StatusIndicator type={s === "AVAILABLE" ? "success" : s === "FAILED" ? "error" : s === "CANCELLED" ? "stopped" : "in-progress"}>{s}</StatusIndicator>;
const dl = (route, arn, text) => <Link href={`#/imagebuilder/${route}?arn=${encodeURIComponent(arn)}`} onFollow={follow}>{text}</Link>;
const CAP = <CapabilityBadge id="ec2.image-builder" />;
const lines = (t) => t.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

const SAMPLE = `name: hello-world
description: Writes a marker file
schemaVersion: 1.0
phases:
  - name: build
    steps:
      - name: WriteMarker
        action: ExecuteBash
        inputs:
          commands:
            - echo "built by Image Builder" > /etc/vyomi-image
  - name: validate
    steps:
      - name: CheckMarker
        action: ExecuteBash
        inputs:
          commands:
            - test -s /etc/vyomi-image
`;

/** A create dialog: fields + submit + error surface. */
function CreateModal({ title, visible, onDismiss, onSubmit, children, size = "medium", cta }) {
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (visible) setErr(null); }, [visible]);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={title} size={size}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={async () => { setBusy(true); setErr(null); try { await onSubmit(); } catch (e) { setErr(e); } finally { setBusy(false); } }}>{cta || title}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />{children}</SpaceBetween>
    </Modal>
  );
}
const Field = ({ label, description, children }) => <FormField label={label} description={description}>{children}</FormField>;

function Lister({ name, load, columns, trackBy = "arn", create, onDelete, delType, actionsExtra, deleteDisabledFor, filterPlaceholder, emptyText }) {
  const notify = useNotify();
  const t = useAsync(load, []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [dlg, setDlg] = useState(false);
  return (
    <>
      <ResourceTable resourceName={name} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy={trackBy} selectionType="single"
        selectedItems={sel} onSelectionChange={setSel} filterPlaceholder={filterPlaceholder || `Find ${name.toLowerCase()}`} empty={{ title: `No ${name.toLowerCase()}`, description: emptyText }}
        columns={columns}
        actions={<SpaceBetween direction="horizontal" size="xs">{CAP}{actionsExtra?.(sel, t.reload)}
          {onDelete && <Button disabled={!sel.length || deleteDisabledFor?.(sel[0])} onClick={() => setDel(true)}>Delete</Button>}
          {create && <Button variant="primary" onClick={() => setDlg(true)}>{create.cta}</Button>}</SpaceBetween>} />
      {create && create.render({ visible: dlg, onDismiss: () => setDlg(false), done: (msg) => { notify.success(msg); setDlg(false); t.reload(); } })}
      {onDelete && <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType={delType} names={sel.map((s) => s.name)}
        onConfirm={async () => { await onDelete(sel[0]); notify.success(`Deleted ${delType} "${sel[0].name}".`); setSel([]); t.reload(); }} />}
    </>
  );
}

/* ── Pipelines ─────────────────────────────────────────────────────────────── */
function CreatePipeline({ visible, onDismiss, done }) {
  const recipes = useAsync(() => api.listRecipes(), []);
  const infra = useAsync(() => api.listInfra(), []);
  const dist = useAsync(() => api.listDist(), []);
  const [f, setF] = useState({ name: "", recipe: null, infra: null, dist: null, cron: "", tests: true });
  const opt = (xs) => (xs.data || []).map((x) => ({ value: x.arn, label: x.name + (x.version ? ` (${x.version})` : "") }));
  return (
    <CreateModal title="Create image pipeline" visible={visible} onDismiss={onDismiss} size="large" onSubmit={async () => {
      await api.createPipeline({ name: f.name, imageRecipeArn: f.recipe?.value, infrastructureConfigurationArn: f.infra?.value, ...(f.dist ? { distributionConfigurationArn: f.dist.value } : {}),
        imageTestsConfiguration: { imageTestsEnabled: f.tests, timeoutMinutes: 720 }, ...(f.cron ? { schedule: { scheduleExpression: f.cron, pipelineExecutionStartCondition: "EXPRESSION_MATCH_ONLY" } } : {}) });
      done(`Created image pipeline "${f.name}".`);
    }}>
      <Field label="Pipeline name"><Input ariaLabel="Pipeline name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></Field>
      <Field label="Image recipe"><Select ariaLabel="Image recipe" selectedOption={f.recipe} options={opt(recipes)} onChange={({ detail }) => setF({ ...f, recipe: detail.selectedOption })} placeholder="Choose a recipe" /></Field>
      <Field label="Infrastructure configuration"><Select ariaLabel="Infrastructure configuration" selectedOption={f.infra} options={opt(infra)} onChange={({ detail }) => setF({ ...f, infra: detail.selectedOption })} placeholder="Choose an infrastructure configuration" /></Field>
      <Field label="Distribution settings (optional)"><Select ariaLabel="Distribution settings" selectedOption={f.dist} options={opt(dist)} onChange={({ detail }) => setF({ ...f, dist: detail.selectedOption })} placeholder="Choose distribution settings" /></Field>
      <Field label="Schedule (optional cron)" description="For example cron(0 0 * * ? *). Stored with the pipeline; Vyomi does not fire schedules on its own - use Run pipeline."><Input ariaLabel="Schedule" value={f.cron} onChange={({ detail }) => setF({ ...f, cron: detail.value })} /></Field>
    </CreateModal>
  );
}

export function Pipelines() {
  const notify = useNotify();
  return <Lister name="Image pipelines" load={api.listPipelines} onDelete={(p) => api.deletePipeline(p.arn)} delType="image pipeline"
    columns={[{ id: "n", header: "Pipeline name", isRowHeader: true, sortingField: "name", cell: (p) => dl("pipelines/view", p.arn, p.name) },
      { id: "s", header: "Status", cell: (p) => <StatusIndicator type={p.status === "ENABLED" ? "success" : "stopped"}>{p.status}</StatusIndicator> },
      { id: "r", header: "Image recipe", cell: (p) => nameOf(p.imageRecipeArn) }, { id: "pl", header: "Platform", cell: (p) => p.platform },
      { id: "sch", header: "Schedule", cell: (p) => p.schedule?.scheduleExpression || "Manual" }, { id: "lr", header: "Last run", cell: (p) => fmtDate(p.dateLastRun) }]}
    actionsExtra={(sel, reload) => <Button disabled={!sel.length || sel[0].status !== "ENABLED"} onClick={async () => {
      try { const r = await api.runPipeline(sel[0].arn); notify.success(`Pipeline execution started: ${tail(r.imageBuildVersionArn)}`); reload(); } catch (e) { notify.error(e.message); } }}>Run pipeline</Button>}
    create={{ cta: "Create image pipeline", render: (p) => <CreatePipeline {...p} /> }} />;
}

export function PipelineDetail() {
  const notify = useNotify();
  const { query } = useRoute();
  const p = useAsync(() => api.getPipeline(query.arn), [query.arn]);
  const imgs = useAsync(() => api.pipelineImages(query.arn), [query.arn]);
  const pl = p.data;
  const toggle = async () => { try { await api.updatePipeline({ imagePipelineArn: pl.arn, imageRecipeArn: pl.imageRecipeArn, infrastructureConfigurationArn: pl.infrastructureConfigurationArn, status: pl.status === "ENABLED" ? "DISABLED" : "ENABLED" }); p.reload(); } catch (e) { notify.error(e.message); } };
  const run = async () => { try { const r = await api.runPipeline(pl.arn); notify.success(`Build ${tail(r.imageBuildVersionArn)} finished.`); imgs.reload(); p.reload(); } catch (e) { notify.error(e.message); } };
  if (p.error) return <ErrorAlert error={p.error} />;
  return (
    <ContentLayout header={<Header variant="h1" actions={<SpaceBetween direction="horizontal" size="xs">{CAP}<Button onClick={toggle}>{pl?.status === "ENABLED" ? "Disable pipeline" : "Enable pipeline"}</Button>
      <Button variant="primary" disabled={pl?.status !== "ENABLED"} onClick={run}>Run pipeline</Button></SpaceBetween>}>{pl?.name || "Pipeline"}</Header>}>
      {pl && <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[["ARN", pl.arn], ["Status", pl.status], ["Platform", pl.platform], ["Image recipe", dl("recipes/view", pl.imageRecipeArn, nameOf(pl.imageRecipeArn))],
          ["Infrastructure configuration", nameOf(pl.infrastructureConfigurationArn)], ["Distribution settings", pl.distributionConfigurationArn ? nameOf(pl.distributionConfigurationArn) : "-"],
          ["Schedule", pl.schedule?.scheduleExpression || "Manual"], ["Image tests", pl.imageTestsConfiguration?.imageTestsEnabled ? "Enabled" : "Disabled"], ["Last run", fmtDate(pl.dateLastRun)]]} />
        <ResourceTable resourceName="Output images" items={imgs.data || []} loading={imgs.loading} onRefresh={imgs.reload} trackBy="arn" empty={{ title: "No images yet", description: "Choose Run pipeline to build one." }}
          columns={[{ id: "v", header: "Version", isRowHeader: true, cell: (i) => dl("images/view", i.arn, i.version) }, { id: "s", header: "Status", cell: (i) => stat(i.state.status) },
            { id: "a", header: "AMI", cell: (i) => (i.outputResources?.amis || []).map((a) => a.image).join(", ") || "-" }, { id: "d", header: "Date created", cell: (i) => fmtDate(i.dateCreated) }]} />
      </SpaceBetween>}
    </ContentLayout>
  );
}

/* ── Images ────────────────────────────────────────────────────────────────── */
function BuildImage({ visible, onDismiss, done }) {
  const recipes = useAsync(() => api.listRecipes(), []);
  const infra = useAsync(() => api.listInfra(), []);
  const dist = useAsync(() => api.listDist(), []);
  const [f, setF] = useState({ recipe: null, infra: null, dist: null });
  const opt = (xs) => (xs.data || []).map((x) => ({ value: x.arn, label: x.name }));
  return (
    <CreateModal title="Create image" visible={visible} onDismiss={onDismiss} onSubmit={async () => {
      const r = await api.createImage({ imageRecipeArn: f.recipe?.value, infrastructureConfigurationArn: f.infra?.value, ...(f.dist ? { distributionConfigurationArn: f.dist.value } : {}) });
      done(`Image build ${tail(r.imageBuildVersionArn)} finished - open it for the result.`);
    }}>
      <Field label="Image recipe"><Select ariaLabel="Image recipe" selectedOption={f.recipe} options={opt(recipes)} onChange={({ detail }) => setF({ ...f, recipe: detail.selectedOption })} placeholder="Choose a recipe" /></Field>
      <Field label="Infrastructure configuration"><Select ariaLabel="Infrastructure configuration" selectedOption={f.infra} options={opt(infra)} onChange={({ detail }) => setF({ ...f, infra: detail.selectedOption })} placeholder="Choose an infrastructure configuration" /></Field>
      <Field label="Distribution settings (optional)"><Select ariaLabel="Distribution settings" selectedOption={f.dist} options={opt(dist)} onChange={({ detail }) => setF({ ...f, dist: detail.selectedOption })} placeholder="Choose distribution settings" /></Field>
    </CreateModal>
  );
}

export function Images() {
  return <Lister name="Images" load={api.listImageBuilds} onDelete={(i) => api.deleteImage(i.arn)} delType="image" trackBy="arn"
    columns={[{ id: "n", header: "Image", isRowHeader: true, sortingField: "name", cell: (i) => dl("images/view", i.arn, `${i.name} / ${i.version}`) }, { id: "s", header: "Status", cell: (i) => stat(i.state.status) },
      { id: "r", header: "Reason", cell: (i) => i.state.reason || "-" }, { id: "a", header: "AMI", cell: (i) => (i.outputResources?.amis || []).map((a) => a.image).join(", ") || "-" },
      { id: "d", header: "Date created", sortingField: "dateCreated", cell: (i) => fmtDate(i.dateCreated) }]}
    create={{ cta: "Create image", render: (p) => <BuildImage {...p} /> }} />;
}

export function ImageDetail() {
  const { query } = useRoute();
  const i = useAsync(() => api.getImage(query.arn), [query.arn]);
  const log = useAsync(() => api.getImageLog(query.arn), [query.arn]);
  const img = i.data;
  if (i.error) return <ErrorAlert error={i.error} />;
  return (
    <ContentLayout header={<Header variant="h1" actions={CAP}>{img ? `${img.name} / ${img.version}` : "Image"}</Header>}>
      {img && <SpaceBetween size="l">
        {img.state.status === "FAILED" && <Alert type="error" header="Image build failed">{img.state.reason}</Alert>}
        <KeyValue title="Details" columns={3} items={[["ARN", img.arn], ["Status", stat(img.state.status)], ["Platform", img.platform], ["Date created", fmtDate(img.dateCreated)],
          ["Image recipe", img.imageRecipe ? dl("recipes/view", img.imageRecipe.arn, img.imageRecipe.name) : "-"], ["Infrastructure configuration", img.infrastructureConfiguration?.name]]} />
        <ResourceTable resourceName="Output AMIs" items={img.outputResources?.amis || []} trackBy="image" empty={{ title: "No output AMIs", description: "An AMI is only produced by a successful build." }}
          columns={[{ id: "i", header: "AMI ID", isRowHeader: true, cell: (a) => a.image }, { id: "n", header: "AMI name", cell: (a) => a.name }, { id: "r", header: "Region", cell: (a) => a.region }, { id: "o", header: "Account", cell: (a) => a.accountId }]} />
        <Container header={<Header variant="h2" description="The build log: the Dockerfile compiled from the recipe's components and the container builder's output.">Build log</Header>}>
          <Box variant="code"><pre style={{ margin: 0, maxHeight: 420, overflow: "auto", whiteSpace: "pre-wrap" }}>{(log.data?.log || []).join("\n") || "No log."}</pre></Box>
        </Container>
      </SpaceBetween>}
    </ContentLayout>
  );
}

/* ── Components ────────────────────────────────────────────────────────────── */
function CreateComponent({ visible, onDismiss, done }) {
  const [f, setF] = useState({ name: "", version: "1.0.0", platform: { value: "Linux", label: "Linux" }, data: SAMPLE, desc: "" });
  return (
    <CreateModal title="Create component" visible={visible} onDismiss={onDismiss} size="large" onSubmit={async () => {
      await api.createComponent({ name: f.name, semanticVersion: f.version, platform: f.platform.value, data: f.data, ...(f.desc ? { description: f.desc } : {}) });
      done(`Created component "${f.name}".`);
    }}>
      <Field label="Component name"><Input ariaLabel="Component name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></Field>
      <Field label="Component version" description="major.minor.patch"><Input ariaLabel="Component version" value={f.version} onChange={({ detail }) => setF({ ...f, version: detail.value })} /></Field>
      <Field label="Platform"><Select selectedOption={f.platform} options={["Linux", "Windows"].map((v) => ({ value: v, label: v }))} onChange={({ detail }) => setF({ ...f, platform: detail.selectedOption })} /></Field>
      <Field label="Description (optional)"><Input ariaLabel="Description" value={f.desc} onChange={({ detail }) => setF({ ...f, desc: detail.value })} /></Field>
      <Field label="Definition document" description="YAML component document: phases build / validate / test, each with steps."><Textarea ariaLabel="Definition document" rows={16} value={f.data} onChange={({ detail }) => setF({ ...f, data: detail.value })} spellcheck={false} /></Field>
    </CreateModal>
  );
}
export function Components() {
  const [owner, setOwner] = useState("Self");
  return (
    <SpaceBetween size="m">
      <Tabs activeTabId={owner} onChange={({ detail }) => setOwner(detail.activeTabId)} tabs={[{ id: "Self", label: "Owned by me" }, { id: "Amazon", label: "Quick start (Amazon-managed)" }]} />
      <Lister key={owner} name="Components" load={() => api.listComponents(owner)} onDelete={owner === "Self" ? (c) => api.deleteComponent(`${c.arn}/1`) : undefined} delType="component"
        columns={[{ id: "n", header: "Name", isRowHeader: true, sortingField: "name", cell: (c) => dl("components/view", owner === "Self" ? `${c.arn}/1` : c.arn, c.name) },
          { id: "v", header: "Version", cell: (c) => c.version }, { id: "p", header: "Platform", cell: (c) => c.platform }, { id: "o", header: "Owner", cell: (c) => c.owner },
          { id: "d", header: "Date created", cell: (c) => fmtDate(c.dateCreated) }]}
        create={owner === "Self" ? { cta: "Create component", render: (p) => <CreateComponent {...p} /> } : undefined} />
    </SpaceBetween>
  );
}
export function ComponentDetail() {
  const { query } = useRoute();
  const c = useAsync(() => api.getComponent(query.arn), [query.arn]);
  if (c.error) return <ErrorAlert error={c.error} />;
  const x = c.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={CAP}>{x ? `${x.name} ${x.version}` : "Component"}</Header>}>
      {x && <SpaceBetween size="l"><KeyValue title="Details" columns={3} items={[["ARN", x.arn], ["Platform", x.platform], ["Owner", x.owner], ["Description", x.description], ["Date created", fmtDate(x.dateCreated)]]} />
        <Container header={<Header variant="h2">Definition document</Header>}><Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{x.data}</pre></Box></Container></SpaceBetween>}
    </ContentLayout>
  );
}

/* ── Recipes ───────────────────────────────────────────────────────────────── */
function CreateRecipe({ visible, onDismiss, done }) {
  const comps = useAsync(() => Promise.all([api.listComponents("Self"), api.listComponents("Amazon")]).then(([a, b]) => [...a, ...b]), []);
  const [f, setF] = useState({ name: "", version: "1.0.0", parent: "ubuntu-server-22-lts-x86", picked: [] });
  const options = (comps.data || []).map((c) => ({ value: c.owner === "Self" ? `${c.arn}/1` : c.arn, label: `${c.name} ${c.version}`, description: c.owner === "Self" ? "Owned by me" : "Amazon-managed" }));
  return (
    <CreateModal title="Create image recipe" visible={visible} onDismiss={onDismiss} size="large" onSubmit={async () => {
      await api.createRecipe({ name: f.name, semanticVersion: f.version, parentImage: `arn:aws:imagebuilder:us-east-1:aws:image/${f.parent}/x.x.x`, components: f.picked.map((o) => ({ componentArn: o.value })) });
      done(`Created image recipe "${f.name}".`);
    }}>
      <Field label="Recipe name"><Input ariaLabel="Recipe name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></Field>
      <Field label="Version" description="major.minor.patch"><Input ariaLabel="Recipe version" value={f.version} onChange={({ detail }) => setF({ ...f, version: detail.value })} /></Field>
      <Field label="Base image" description="Mapped to a container base image already present on the appliance (ubuntu, amazon-linux, debian)."><Input ariaLabel="Base image" value={f.parent} onChange={({ detail }) => setF({ ...f, parent: detail.value })} /></Field>
      <Field label="Build components"><Multiselect ariaLabel="Build components" selectedOptions={f.picked} options={options} onChange={({ detail }) => setF({ ...f, picked: detail.selectedOptions })} placeholder="Choose components" /></Field>
    </CreateModal>
  );
}
export function Recipes() {
  return <Lister name="Image recipes" load={api.listRecipes} onDelete={(r) => api.deleteRecipe(r.arn)} delType="image recipe"
    columns={[{ id: "n", header: "Recipe", isRowHeader: true, sortingField: "name", cell: (r) => dl("recipes/view", r.arn, r.name) }, { id: "v", header: "Version", cell: (r) => tail(r.arn).split("/")[2] },
      { id: "p", header: "Platform", cell: (r) => r.platform }, { id: "b", header: "Parent image", cell: (r) => nameOf(r.parentImage) || r.parentImage }, { id: "d", header: "Date created", cell: (r) => fmtDate(r.dateCreated) }]}
    create={{ cta: "Create image recipe", render: (p) => <CreateRecipe {...p} /> }} />;
}
export function RecipeDetail() {
  const { query } = useRoute();
  const r = useAsync(() => api.getRecipe(query.arn), [query.arn]);
  if (r.error) return <ErrorAlert error={r.error} />;
  const x = r.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={CAP}>{x ? `${x.name} ${x.version}` : "Image recipe"}</Header>}>
      {x && <SpaceBetween size="l"><KeyValue title="Details" columns={3} items={[["ARN", x.arn], ["Platform", x.platform], ["Parent image", x.parentImage], ["Date created", fmtDate(x.dateCreated)]]} />
        <ResourceTable resourceName="Components" items={x.components} trackBy="componentArn" columns={[{ id: "c", header: "Component", isRowHeader: true, cell: (c) => c.componentArn },
          { id: "p", header: "Parameters", cell: (c) => (c.parameters || []).map((p) => `${p.name}=${(p.value || []).join(",")}`).join(", ") || "-" }]} /></SpaceBetween>}
    </ContentLayout>
  );
}

/* ── Infrastructure configurations ─────────────────────────────────────────── */
function CreateInfra({ visible, onDismiss, done }) {
  const [f, setF] = useState({ name: "", profile: "EC2InstanceProfileForImageBuilder", types: "t3.medium", subnet: "", sgs: "" });
  return (
    <CreateModal title="Create infrastructure configuration" visible={visible} onDismiss={onDismiss} onSubmit={async () => {
      await api.createInfra({ name: f.name, instanceProfileName: f.profile, instanceTypes: lines(f.types), ...(f.subnet ? { subnetId: f.subnet } : {}), ...(lines(f.sgs).length ? { securityGroupIds: lines(f.sgs) } : {}) });
      done(`Created infrastructure configuration "${f.name}".`);
    }}>
      <Field label="Name"><Input ariaLabel="Configuration name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></Field>
      <Field label="IAM instance profile"><Input ariaLabel="IAM instance profile" value={f.profile} onChange={({ detail }) => setF({ ...f, profile: detail.value })} /></Field>
      <Field label="Instance types" description="Comma separated."><Input ariaLabel="Instance types" value={f.types} onChange={({ detail }) => setF({ ...f, types: detail.value })} /></Field>
      <Field label="Subnet ID (optional)"><Input ariaLabel="Subnet ID" value={f.subnet} onChange={({ detail }) => setF({ ...f, subnet: detail.value })} /></Field>
      <Field label="Security group IDs (optional)"><Input ariaLabel="Security group IDs" value={f.sgs} onChange={({ detail }) => setF({ ...f, sgs: detail.value })} /></Field>
    </CreateModal>
  );
}
export function Infrastructure() {
  return <Lister name="Infrastructure configurations" load={api.listInfra} onDelete={(i) => api.deleteInfra(i.arn)} delType="infrastructure configuration"
    columns={[{ id: "n", header: "Name", isRowHeader: true, sortingField: "name", cell: (i) => i.name }, { id: "p", header: "IAM instance profile", cell: (i) => i.instanceProfileName },
      { id: "t", header: "Instance types", cell: (i) => (i.instanceTypes || []).join(", ") }, { id: "d", header: "Date created", cell: (i) => fmtDate(i.dateCreated) }]}
    create={{ cta: "Create infrastructure configuration", render: (p) => <CreateInfra {...p} /> }} />;
}

/* ── Distribution settings ─────────────────────────────────────────────────── */
function CreateDist({ visible, onDismiss, done }) {
  const [f, setF] = useState({ name: "", region: "us-east-1", ami: "my-image-{{ imagebuilder:buildDate }}", accounts: "" });
  return (
    <CreateModal title="Create distribution settings" visible={visible} onDismiss={onDismiss} onSubmit={async () => {
      await api.createDist({ name: f.name, distributions: [{ region: f.region, amiDistributionConfiguration: { name: f.ami, ...(lines(f.accounts).length ? { launchPermission: { userIds: lines(f.accounts) } } : {}) } }] });
      done(`Created distribution settings "${f.name}".`);
    }}>
      <Field label="Name"><Input ariaLabel="Settings name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></Field>
      <Field label="Region"><Input ariaLabel="Region" value={f.region} onChange={({ detail }) => setF({ ...f, region: detail.value })} /></Field>
      <Field label="Output AMI name"><Input ariaLabel="Output AMI name" value={f.ami} onChange={({ detail }) => setF({ ...f, ami: detail.value })} /></Field>
      <Field label="Launch permission account IDs (optional)"><Input ariaLabel="Launch permission accounts" value={f.accounts} onChange={({ detail }) => setF({ ...f, accounts: detail.value })} /></Field>
    </CreateModal>
  );
}
export function Distributions() {
  return <Lister name="Distribution settings" load={api.listDist} onDelete={(d) => api.deleteDist(d.arn)} delType="distribution settings"
    columns={[{ id: "n", header: "Name", isRowHeader: true, sortingField: "name", cell: (d) => d.name }, { id: "r", header: "Regions", cell: (d) => (d.regions || []).join(", ") },
      { id: "d", header: "Date created", cell: (d) => fmtDate(d.dateCreated) }]}
    create={{ cta: "Create distribution settings", render: (p) => <CreateDist {...p} /> }} />;
}
