/* Bedrock Data Automation: projects, blueprints and a run panel over the real wire (core/bedrock_bda_core.py).
 * Quality is that of a small open vision model (Mesh only for images); the page says so. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtDate } from "../../../kit/common.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { awsRest, awsJson, s3 } from "../../../../common/wire.js";
import { CreateModal, Field, Page } from "../inferTune/Shared.jsx";

const D = (m, p, o) => awsRest("bedrock", m, p, o);
const PROFILE = "arn:aws:bedrock:us-east-1:123456789012:data-automation-profile/us.data-automation-v1";
const SAMPLE = JSON.stringify({ class: "invoice", description: "An invoice", type: "object", properties: {
  invoice_number: { type: "string", inferenceType: "explicit", instruction: "The invoice number" },
  vendor: { type: "string", inferenceType: "explicit", instruction: "Vendor name" },
  total_due: { type: "number", inferenceType: "explicit", instruction: "Total amount due" } } }, null, 2);
const tail = (a) => String(a || "").split("/").pop();

const api = {
  blueprints: () => D("POST", "/blueprints/", { body: {} }).then((r) => r.blueprints || []),
  createBlueprint: (b) => D("PUT", "/blueprints/", { body: b }).then((r) => r.blueprint),
  deleteBlueprint: (arn) => D("DELETE", `/blueprints/${encodeURIComponent(arn)}/`),
  projects: () => D("POST", "/data-automation-projects/", { body: {} }).then((r) => r.projects || []),
  createProject: (b) => D("PUT", "/data-automation-projects/", { body: b }),
  deleteProject: (arn) => D("DELETE", `/data-automation-projects/${encodeURIComponent(arn)}/`),
  invoke: (b) => awsJson("bedrock", "AmazonBedrockKeystoneRuntimeService.InvokeDataAutomationAsync", b, { version: "1.1" }),
  status: (arn) => awsJson("bedrock", "AmazonBedrockKeystoneRuntimeService.GetDataAutomationStatus", { invocationArn: arn }, { version: "1.1" }),
};

function Blueprints() {
  const t = useAsync(() => api.blueprints(), []);
  const notify = useNotify();
  const [sel, setSel] = useState([]), [open, setOpen] = useState(false), [del, setDel] = useState(false);
  const [name, setName] = useState(""), [type, setType] = useState("IMAGE"), [schema, setSchema] = useState(SAMPLE);
  const New = <Button variant="primary" onClick={() => setOpen(true)}>Create blueprint</Button>;
  return (
    <>
      <ResourceTable variant="container" resourceName="Blueprints" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="blueprintArn" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        filterPlaceholder="Find blueprints" empty={{ title: "No blueprints", action: New }}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>{New}</SpaceBetween>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "blueprintName", cell: (b) => b.blueprintName },
          { id: "stage", header: "Stage", cell: (b) => b.blueprintStage },
          { id: "id", header: "Blueprint ID", cell: (b) => tail(b.blueprintArn) },
          { id: "mod", header: "Last modified", cell: (b) => fmtDate(b.lastModifiedTime) },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Create blueprint" submitLabel="Create blueprint" disabled={!name || !schema} size="large"
        onSubmit={async () => { await api.createBlueprint({ blueprintName: name, type, schema }); notify.success(`Blueprint "${name}" created.`); t.reload(); }}>
        <Field label="Blueprint name" constraint="Letters, numbers, hyphens and underscores" value={name} onChange={setName} />
        <FormField label="Type"><Select selectedOption={{ label: type, value: type }} onChange={({ detail }) => setType(detail.selectedOption.value)} options={["IMAGE", "DOCUMENT"].map((v) => ({ label: v, value: v }))} /></FormField>
        <FormField label="Blueprint schema (JSON)" description="Each property: type, inferenceType (explicit | inferred) and an instruction the model follows."><Textarea value={schema} rows={14} onChange={({ detail }) => setSchema(detail.value)} ariaLabel="Blueprint schema" /></FormField>
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="blueprint" names={sel.map((b) => b.blueprintName)}
        onConfirm={async () => { await api.deleteBlueprint(sel[0].blueprintArn); notify.success("Blueprint deleted."); setSel([]); t.reload(); }} />
    </>
  );
}

function Projects() {
  const t = useAsync(() => api.projects(), []);
  const bps = useAsync(() => api.blueprints(), []);
  const notify = useNotify();
  const [sel, setSel] = useState([]), [open, setOpen] = useState(false), [del, setDel] = useState(false);
  const [name, setName] = useState(""), [bp, setBp] = useState(null);
  const New = <Button variant="primary" onClick={() => setOpen(true)}>Create project</Button>;
  return (
    <>
      <ResourceTable variant="container" resourceName="Projects" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="projectArn" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        filterPlaceholder="Find projects" empty={{ title: "No projects", action: New }}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>{New}</SpaceBetween>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "projectName", cell: (p) => p.projectName },
          { id: "stage", header: "Stage", cell: (p) => p.projectStage },
          { id: "status", header: "Status", cell: (p) => <StatusIndicator type={p.status === "COMPLETED" ? "success" : "in-progress"}>{p.status}</StatusIndicator> },
          { id: "arn", header: "Project ARN", cell: (p) => p.projectArn },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Create project" submitLabel="Create project" disabled={!name}
        onSubmit={async () => {
          await api.createProject({ projectName: name, standardOutputConfiguration: { image: { extraction: { category: { state: "ENABLED", types: ["TEXT_DETECTION"] }, boundingBox: { state: "DISABLED" } } } },
            ...(bp ? { customOutputConfiguration: { blueprints: [{ blueprintArn: bp, blueprintStage: "DEVELOPMENT" }] } } : {}) });
          notify.success(`Project "${name}" created.`); t.reload();
        }}>
        <Field label="Project name" constraint="Letters, numbers, hyphens and underscores" value={name} onChange={setName} />
        <FormField label="Custom output blueprint (optional)"><Select selectedOption={bp ? { label: ((bps.data || []).find((b) => b.blueprintArn === bp) || {}).blueprintName || tail(bp), value: bp } : null} placeholder="Choose a blueprint" onChange={({ detail }) => setBp(detail.selectedOption.value)}
          options={(bps.data || []).map((b) => ({ label: b.blueprintName, value: b.blueprintArn, description: tail(b.blueprintArn) }))} /></FormField>
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="project" names={sel.map((p) => p.projectName)}
        onConfirm={async () => { await api.deleteProject(sel[0].projectArn); notify.success("Project deleted."); setSel([]); t.reload(); }} />
    </>
  );
}

function Run() {
  const projects = useAsync(() => api.projects(), []);
  const [proj, setProj] = useState(null), [inUri, setIn] = useState("s3://bda-in/scans/invoice.png"), [outUri, setOut] = useState("s3://bda-out/results");
  const [state, setState] = useState(null), [result, setResult] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr(null); setResult(null); setState(null);
    try {
      const { invocationArn } = await api.invoke({ inputConfiguration: { s3Uri: inUri }, outputConfiguration: { s3Uri: outUri }, dataAutomationConfiguration: { dataAutomationProjectArn: proj, stage: "DEVELOPMENT" }, dataAutomationProfileArn: PROFILE });
      let st;
      for (let i = 0; i < 600; i++) { st = await api.status(invocationArn); setState(st); if (!["Created", "InProgress"].includes(st.status)) break; await new Promise((r) => setTimeout(r, 1000)); }
      if (st.status === "Success") {
        const m = String(st.outputConfiguration.s3Uri).replace("s3://", ""); const bucket = m.split("/")[0], key = m.slice(bucket.length + 1);
        const meta = JSON.parse((await s3("GET", `/${bucket}/${key}`, { raw: true })).text);
        const seg = meta.output_metadata[0].segment_metadata[0];
        const out = {};
        for (const k of ["custom_output_path", "standard_output_path"]) if (seg[k]) { const p = seg[k].replace("s3://", ""); const b = p.split("/")[0]; out[k] = JSON.parse((await s3("GET", `/${b}/${p.slice(b.length + 1)}`, { raw: true })).text); }
        setResult(out);
      }
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2" description="Runs InvokeDataAutomationAsync, polls GetDataAutomationStatus and reads the result.json files from your output bucket.">Run a project on an S3 object</Header>}>
      <SpaceBetween size="m">
        <FormField label="Project"><Select selectedOption={proj ? { label: ((projects.data || []).find((p) => p.projectArn === proj) || {}).projectName || tail(proj), value: proj } : null} placeholder="Choose a project" onChange={({ detail }) => setProj(detail.selectedOption.value)}
          options={(projects.data || []).map((p) => ({ label: p.projectName, value: p.projectArn, description: p.projectStage }))} /></FormField>
        <Field label="Input S3 URI" description="png / jpeg / gif / webp, or a pdf / docx / xlsx / pptx / csv / html / md / txt document." value={inUri} onChange={setIn} />
        <Field label="Output S3 URI" value={outUri} onChange={setOut} />
        <Button variant="primary" loading={busy} disabled={!proj || !inUri || !outUri} onClick={run}>Run</Button>
        {err && <ErrorAlert error={err} header="Request failed" />}
        {state && <Box data-testid="bda-status"><StatusIndicator type={state.status === "Success" ? "success" : /Error/.test(state.status) ? "error" : "in-progress"}>{state.status}</StatusIndicator>{state.errorMessage ? ` ${state.errorMessage}` : ""}</Box>}
        {result && <Textarea readOnly rows={18} value={JSON.stringify(result, null, 2)} ariaLabel="Result" data-testid="bda-result" />}
      </SpaceBetween>
    </Container>
  );
}

export default function DataAutomation() {
  return (
    <Page title="Data Automation" description="Extract insights from documents and images with blueprints and projects.">
      <Alert type="info" header="Small open models, not the managed service">
        Images are read by a small open vision model (SmolVLM, Mesh only) and fields are extracted with constrained JSON; text documents are parsed without a model.
        There are no confidence scores, bounding boxes or layout elements, scanned PDFs have no OCR, and audio and video are not supported. Check extracted values before relying on them.
      </Alert>
      <Tabs tabs={[{ id: "projects", label: "Projects", content: <Projects /> }, { id: "blueprints", label: "Blueprints", content: <Blueprints /> }, { id: "run", label: "Run", content: <Run /> }]} />
    </Page>
  );
}
