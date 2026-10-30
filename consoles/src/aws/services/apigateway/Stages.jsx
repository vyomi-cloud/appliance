/* Stages — split view: stage list on the left, selected stage's tabbed detail on the
 * right (Stage details, Logs and tracing, Stage variables, Deployment history, Canary,
 * Tags), matching the native console's REST API "Stages" nav item. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Grid from "@cloudscape-design/components/grid";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateStageModal({ apiId, visible, onDismiss, onDone, deployments }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [dep, setDep] = useState(deployments[0] ? { value: deployments[0].id, label: deployments[0].id } : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createStage(apiId, { stageName: name, deploymentId: dep?.value }); notify.success(`Stage "${name}" created.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create stage"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name || !dep} onClick={submit}>Create stage</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Stage name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Stage name" /></FormField>
        <FormField label="Deployment"><Select selectedOption={dep} onChange={({ detail }) => setDep(detail.selectedOption)} options={deployments.map((d) => ({ value: d.id, label: d.id }))} /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

function StageTabs({ apiId, stage, reload }) {
  const notify = useNotify();
  const [vars, setVars] = useState(null);
  const saveVars = async () => {
    const ops = Object.entries(vars).map(([k, v]) => ({ op: "replace", path: `/variables/${k}`, value: v }));
    await api.updateStage(apiId, stage.stageName, ops);
    notify.success("Stage variables updated."); setVars(null); reload();
  };
  const toggleTracing = async () => { await api.updateStage(apiId, stage.stageName, [{ op: "replace", path: "/tracingEnabled", value: !stage.tracingEnabled }]); reload(); };
  const deployments = useAsync(() => api.listDeployments(apiId), [apiId]);
  return (
    <Tabs tabs={[
      { id: "details", label: "Stage details", content: (
        <KeyValue title="Stage details" columns={3} actions={<Button onClick={() => {}}>Edit</Button>} items={[
          ["Stage name", stage.stageName], ["Invoke URL", stage.invokeUrl], ["Deployment", stage.deploymentId],
          ["Rate", stage.throttleSettings?.rateLimit], ["Burst", stage.throttleSettings?.burstLimit],
          ["Cache cluster", stage.cacheClusterEnabled ? "Enabled" : "Disabled"],
          ["Default method-level caching", stage.cacheClusterEnabled ? "Enabled" : "Disabled"],
          ["Active deployment", stage.deploymentId], ["Created", fmtDate(stage.createdDate)], ["Last updated", fmtDate(stage.lastUpdatedDate)],
        ]} />
      ) },
      { id: "logs", label: "Logs and tracing", content: (
        <KeyValue title="Logs and tracing" columns={2} actions={<Button onClick={toggleTracing}>Edit</Button>} items={[
          ["CloudWatch logs", stage.accessLogSettings ? "Enabled" : "Disabled"], ["Detailed metrics", "Disabled"],
          ["Data tracing", "Disabled"], ["X-Ray tracing", stage.tracingEnabled ? "Enabled" : "Disabled"],
          ["Custom access logging", stage.accessLogSettings?.destinationArn || "Disabled"],
        ]} />
      ) },
      { id: "vars", label: "Stage variables", content: (
        <Container header={<Header variant="h2" actions={<Button onClick={() => setVars({ ...stage.variables })}>Manage variables</Button>}>Stage variables</Header>}>
          <Table variant="embedded" items={Object.entries(stage.variables || {}).map(([k, v]) => ({ k, v }))}
            columnDefinitions={[{ id: "n", header: "Name", cell: (x) => x.k }, { id: "v", header: "Value", cell: (x) => x.v }]}
            empty={<Box textAlign="center" color="inherit">No stage variables</Box>} />
          <Modal visible={!!vars} onDismiss={() => setVars(null)} header="Manage stage variables"
            footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setVars(null)}>Cancel</Button><Button variant="primary" onClick={saveVars}>Save changes</Button></SpaceBetween></Box>}>
            {vars && <SpaceBetween size="s">
              {Object.entries(vars).map(([k, v]) => (
                <SpaceBetween key={k} direction="horizontal" size="xs">
                  <Input value={k} disabled ariaLabel="Variable name" />
                  <Input value={v} onChange={({ detail }) => setVars({ ...vars, [k]: detail.value })} ariaLabel="Variable value" />
                </SpaceBetween>
              ))}
              <SpaceBetween direction="horizontal" size="xs">
                <Input placeholder="new-variable" id="newvar" ariaLabel="New variable name" onChange={({ detail }) => setVars({ ...vars, __new: detail.value })} />
                <Button onClick={() => { const k = vars.__new; if (k) { const { __new, ...rest } = vars; setVars({ ...rest, [k]: "" }); } }}>Add</Button>
              </SpaceBetween>
            </SpaceBetween>}
          </Modal>
        </Container>
      ) },
      { id: "history", label: "Deployment history", content: (
        <Table variant="container" header={<Header variant="h2" counter={`(${(deployments.data || []).length})`}>Deployment history</Header>}
          items={deployments.data || []} loading={deployments.loading}
          columnDefinitions={[{ id: "id", header: "Deployment ID", cell: (x) => x.id }, { id: "d", header: "Description", cell: (x) => x.description || "-" }, { id: "c", header: "Created", cell: (x) => fmtDate(x.createdDate) }]}
          empty={<Box textAlign="center" color="inherit">No deployments</Box>} />
      ) },
      { id: "canary", label: "Canary", content: <NotSimulatedContainer title="Canary" note="Canary release deployments (splitting traffic between two deployments on one stage) aren't modeled by Vyomi." /> },
      { id: "tags", label: "Tags", content: (
        <Table variant="container" header={<Header variant="h2" counter={`(${Object.keys(stage.tags || {}).length})`} actions={<Button>Manage tags</Button>}>Tags</Header>}
          items={Object.entries(stage.tags || {}).map(([k, v]) => ({ k, v }))}
          columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.k }, { id: "v", header: "Value", cell: (x) => x.v }]}
          empty={<Box textAlign="center" color="inherit">No tags</Box>} />
      ) },
    ]} />
  );
}

export default function Stages({ params }) {
  const notify = useNotify();
  const t = useAsync(async () => {
    const a = await api.resolveRestApi(params.id);
    const [stages, deployments] = await Promise.all([api.listStages(a.id), api.listDeployments(a.id)]);
    return { apiId: a.id, stages, deployments };
  }, [params.id]);
  const [selected, setSelected] = useState(params.stage || null);
  const [createOpen, setCreateOpen] = useState(false);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const { apiId, stages, deployments } = t.data;
  const stage = stages.find((s) => s.stageName === selected) || stages[0];

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!stage} onClick={async () => { await api.deleteStage(apiId, stage.stageName); notify.success("Stage deleted."); setSelected(null); t.reload(); }}>Delete</Button>
        <Button variant="primary" onClick={() => setCreateOpen(true)}>Create stage</Button>
      </SpaceBetween>
    }>Stages</Header>}>
      <Grid gridDefinition={[{ colspan: 3 }, { colspan: 9 }]}>
        <Container header={<Header variant="h2">Stages</Header>}>
          <SpaceBetween size="xs">
            {stages.map((s) => <Button key={s.stageName} variant={stage?.stageName === s.stageName ? "primary" : "link"} onClick={() => setSelected(s.stageName)}>{s.stageName}</Button>)}
            {!stages.length && <Box color="text-body-secondary">No stages</Box>}
          </SpaceBetween>
        </Container>
        {stage ? <StageTabs apiId={apiId} stage={stage} reload={t.reload} /> : <Box color="text-body-secondary">Choose a stage to view its details.</Box>}
      </Grid>
      <CreateStageModal apiId={apiId} visible={createOpen} onDismiss={() => setCreateOpen(false)} onDone={t.reload} deployments={deployments} />
    </ContentLayout>
  );
}
