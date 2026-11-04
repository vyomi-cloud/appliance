/* REST API detail — resources tree, methods + integrations, Enable CORS, and the
 * Deploy API modal (CreateDeployment). The Resource tree / Resource details / Methods
 * layout matches the native console's "Resources" page (the default landing tab for a
 * REST API). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Grid from "@cloudscape-design/components/grid";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import * as api from "./api.js";

function Tree({ nodes, byParent, selected, onSelect, depth = 0 }) {
  return (
    <SpaceBetween size="xs">
      {nodes.map((n) => (
        <div key={n.id}>
          <Button variant={selected === n.id ? "primary" : "link"} onClick={() => onSelect(n.id)}>
            {"— ".repeat(depth)}{n.path === "/" ? "/" : n.pathPart}
          </Button>
          {byParent[n.id]?.length > 0 && <Box padding={{ left: "l" }}><Tree nodes={byParent[n.id]} byParent={byParent} selected={selected} onSelect={onSelect} depth={depth + 1} /></Box>}
        </div>
      ))}
    </SpaceBetween>
  );
}

function DeployModal({ apiId, visible, onDismiss, onDone, stages }) {
  const notify = useNotify();
  const NEW = { value: "__new__", label: "*New stage*" };
  const [stage, setStage] = useState(NEW);
  const [stageName, setStageName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const options = [NEW, ...stages.map((s) => ({ value: s.stageName, label: s.stageName }))];
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const name = stage.value === "__new__" ? stageName : stage.value;
      await api.createDeployment(apiId, { stageName: name, description });
      notify.success(`Deployed to stage "${name}".`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Deploy API"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={stage.value === "__new__" && !stageName} onClick={submit}>Deploy</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Stage"><Select selectedOption={stage} onChange={({ detail }) => setStage(detail.selectedOption)} options={options} /></FormField>
        {stage.value === "__new__" && <FormField label="Stage name"><Input value={stageName} onChange={({ detail }) => setStageName(detail.value)} ariaLabel="Stage name" /></FormField>}
        <FormField label="Deployment description"><Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Deployment description" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

function MethodsSection({ apiId, resource, reload }) {
  const notify = useNotify();
  const methods = useAsync(() => Promise.all(Object.keys(resource.resourceMethods || {})
    .map((m) => api.getMethod(apiId, resource.id, m))), [apiId, resource.id, JSON.stringify(resource.resourceMethods)]);
  const [sel, setSel] = useState([]);
  return (
    <Container header={<Header variant="h2" counter={`(${(methods.data || []).length})`} actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => { for (const m of sel) await api.deleteMethod(apiId, resource.id, m.httpMethod); notify.success("Method(s) deleted."); setSel([]); methods.reload(); reload(); }}>Delete</Button>
        <Button variant="primary" onClick={() => navigate("apigateway", "apis", apiId, "create-method", resource.id)}>Create method</Button>
      </SpaceBetween>
    }>Methods</Header>}>
      <Table variant="embedded" items={methods.data || []} loading={methods.loading} trackBy="httpMethod"
        selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "method", header: "Method type", cell: (m) => m.httpMethod },
          { id: "integ", header: "Integration type", cell: (m) => m.methodIntegration?.type || "-" },
          { id: "auth", header: "Authorization", cell: (m) => m.authorizationType },
          { id: "key", header: "API key", cell: (m) => (m.apiKeyRequired ? "Required" : "Not required") },
        ]}
        empty={<Box textAlign="center" color="inherit">No methods on this resource</Box>} />
    </Container>
  );
}

export default function RestApiDetail({ params }) {
  const notify = useNotify();
  const d = useAsync(async () => {
    const a = await api.resolveRestApi(params.id);
    const [resources, stages] = await Promise.all([api.listResources(a.id), api.listStages(a.id)]);
    return { a, resources, stages };
  }, [params.id]);
  const [selected, setSelected] = useState(null);
  const [deployOpen, setDeployOpen] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const { a, resources, stages } = d.data;
  const apiId = a.id;
  const byParent = {};
  resources.forEach((r) => { if (r.parentId) (byParent[r.parentId] = byParent[r.parentId] || []).push(r); });
  const root = resources.find((r) => r.path === "/");
  const selId = selected || root?.id;
  const current = resources.find((r) => r.id === selId) || root;

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <ButtonDropdown items={[{ id: "delete", text: "Delete API" }]} onItemClick={async ({ detail }) => {
          if (detail.id === "delete") { await api.deleteRestApi(apiId); notify.success("API deleted."); navigate("apigateway", "apis"); }
        }}>API actions</ButtonDropdown>
        <Button variant="primary" onClick={() => setDeployOpen(true)}>Deploy API</Button>
      </SpaceBetween>
    }>{a.name}</Header>}>
      <SpaceBetween size="l">
        <Grid gridDefinition={[{ colspan: 4 }, { colspan: 8 }]}>
          <Container header={<Header variant="h2" actions={<Button onClick={() => navigate("apigateway", "apis", apiId, "create-resource", selId)}>Create resource</Button>}>Resources</Header>}>
            <Box variant="small" color="text-body-secondary" padding={{ bottom: "xs" }}>Resource tree</Box>
            {root ? <Tree nodes={[root]} byParent={byParent} selected={selId} onSelect={setSelected} /> : <Box color="text-body-secondary">No resources</Box>}
          </Container>
          <SpaceBetween size="l">
            {current && (
              <Container header={<Header variant="h2" actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button disabled={current.path === "/"} onClick={async () => { await api.deleteResource(apiId, current.id); notify.success("Resource deleted."); setSelected(root.id); d.reload(); }}>Delete</Button>
                  <Button onClick={() => notify.info("Resource documentation isn't modeled by Vyomi.")}>Update documentation</Button>
                  <Button onClick={async () => { await api.enableCors(apiId, current.id); notify.success("CORS enabled on this resource."); d.reload(); }}>Enable CORS</Button>
                </SpaceBetween>
              }>Resource details</Header>}>
                <SpaceBetween size="s">
                  <div><Box variant="awsui-key-label">Path</Box><div>{current.path}</div></div>
                  <div><Box variant="awsui-key-label">Resource ID</Box><div>{current.id}</div></div>
                </SpaceBetween>
              </Container>
            )}
            {current && <MethodsSection apiId={apiId} resource={current} reload={d.reload} />}
          </SpaceBetween>
        </Grid>
      </SpaceBetween>
      <DeployModal apiId={apiId} visible={deployOpen} onDismiss={() => setDeployOpen(false)} onDone={d.reload} stages={stages} />
    </ContentLayout>
  );
}
