/* Bedrock AgentCore: runtimes (control plane), gateways + Lambda targets (a real MCP endpoint that invokes the Lambdas). */
import { useEffect, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { WIRE_BASE } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";
import { stat } from "./Common.jsx";

const SAMPLE_TOOLS = JSON.stringify([{ name: "add", description: "Add two numbers", inputSchema: { type: "object", properties: { a: { type: "number" }, b: { type: "number" } }, required: ["a", "b"] } }], null, 2);

export function CreateTargetModal({ visible, onDismiss, gateways, gatewayId, onDone }) {
  const notify = useNotify();
  const fns = useAsync(() => api.listLambdas(), []);
  const [gw, setGw] = useState(null);
  const [name, setName] = useState("");
  const [fn, setFn] = useState(null);
  const [tools, setTools] = useState(SAMPLE_TOOLS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const gwSel = gatewayId ? { value: gatewayId, label: gatewayId } : gw;
  const go = async () => {
    setBusy(true); setError(null);
    try {
      let parsed; try { parsed = JSON.parse(tools); } catch { throw new Error("Tool schema must be valid JSON"); }
      await api.createLambdaTarget(gwSel.value, name, fn.value, parsed);
      notify.success(`Target "${name}" created.`); setName(""); onDone?.(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create gateway target" size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!gwSel || !name || !fn} onClick={go}>Create target</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} header="Couldn't create target" />}
        {!gatewayId && <FormField label="Gateway"><Select selectedOption={gw} onChange={({ detail }) => setGw(detail.selectedOption)} options={(gateways || []).map((g) => ({ label: g.name, value: g.gatewayId }))} placeholder="Choose a gateway" ariaLabel="Gateway" /></FormField>}
        <FormField label="Target name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Target name" /></FormField>
        <FormField label="Lambda function" description="Its tools are exposed through the gateway's MCP endpoint."><Select selectedOption={fn} onChange={({ detail }) => setFn(detail.selectedOption)} options={(fns.data || []).map((f) => ({ label: f.name, value: f.arn }))} statusType={fns.loading ? "loading" : "finished"} placeholder="Choose a function" ariaLabel="Lambda function" empty="No Lambda functions" /></FormField>
        <FormField label="Tool schema (inline)"><Textarea value={tools} rows={10} onChange={({ detail }) => setTools(detail.value)} ariaLabel="Tool schema" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

function CreateSimple({ visible, onDismiss, header, fields, onSubmit, submitLabel }) {
  const [vals, setVals] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => { setBusy(true); setError(null); try { await onSubmit(vals); setVals({}); onDismiss(); } catch (e) { setError(e); } finally { setBusy(false); } };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={header}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={fields.some((f) => !(vals[f.key] ?? f.def))} onClick={go}>{submitLabel}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} header="Request failed" />}
        {fields.map((f) => <FormField key={f.key} label={f.label} description={f.desc}><Input value={vals[f.key] ?? f.def ?? ""} onChange={({ detail }) => setVals({ ...vals, [f.key]: detail.value })} ariaLabel={f.label} placeholder={f.ph} /></FormField>)}
      </SpaceBetween>
    </Modal>
  );
}

export function Runtimes() {
  const t = useAsync(() => api.listRuntimes(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  return (
    <CapabilityContainer id="bedrock.agentcore.runtime" title="Agent runtime">
      <ResourceTable variant="embedded" resourceName="Agent runtimes" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="agentRuntimeId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        empty={{ title: "No agent runtimes", action: <Button onClick={() => setCreate(true)}>Host agent</Button> }}
        columns={[{ id: "n", header: "Name", isRowHeader: true, cell: (r) => r.agentRuntimeName }, { id: "id", header: "Runtime ID", cell: (r) => r.agentRuntimeId }, { id: "v", header: "Version", cell: (r) => r.agentRuntimeVersion }, { id: "s", header: "Status", cell: (r) => stat(r.status) }, { id: "u", header: "Updated", cell: (r) => r.lastUpdatedAt }]}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button><Button variant="primary" onClick={() => setCreate(true)}>Host agent</Button></SpaceBetween>} />
      <CreateSimple visible={create} onDismiss={() => { setCreate(false); t.reload(); }} header="Host agent" submitLabel="Create runtime"
        fields={[{ key: "name", label: "Agent name", ph: "my_agent", desc: "Letters, numbers and underscores; starts with a letter" }, { key: "uri", label: "Container image URI", def: `${api.ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/my-agent:latest` }]}
        onSubmit={(v) => api.createRuntime(v.name, v.uri ?? `${api.ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/my-agent:latest`)} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="agent runtime" names={sel.map((r) => r.agentRuntimeName)} onConfirm={async () => { await api.deleteRuntime(sel[0].agentRuntimeId); setSel([]); t.reload(); }} />
    </CapabilityContainer>
  );
}

export function Gateways() {
  const t = useAsync(() => api.listGateways(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  return (
    <CapabilityContainer id="bedrock.agentcore.gateway" title="Gateways">
      <ResourceTable variant="embedded" resourceName="Gateways" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="gatewayId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        empty={{ title: "No gateways", action: <Button onClick={() => setCreate(true)}>Create gateway</Button> }}
        columns={[{ id: "n", header: "Name", isRowHeader: true, cell: (g) => <Link href={href("bedrock", "agentcore", "gateways", g.gatewayId)} onFollow={follow}>{g.name}</Link> }, { id: "id", header: "Gateway ID", cell: (g) => g.gatewayId }, { id: "a", header: "Inbound auth", cell: (g) => g.authorizerType }, { id: "s", header: "Status", cell: (g) => stat(g.status) }]}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button><Button variant="primary" onClick={() => setCreate(true)}>Create gateway</Button></SpaceBetween>} />
      <CreateSimple visible={create} onDismiss={() => { setCreate(false); t.reload(); }} header="Create gateway" submitLabel="Create gateway" fields={[{ key: "name", label: "Gateway name", ph: "my-gateway" }]}
        onSubmit={async (v) => { const g = await api.createGateway(v.name, "NONE"); navigate("bedrock", "agentcore", "gateways", g.gatewayId); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="gateway" names={sel.map((g) => g.name)} onConfirm={async () => { await api.deleteGateway(sel[0].gatewayId); setSel([]); t.reload(); }} />
    </CapabilityContainer>
  );
}

export function AgentCore() {
  return (
    <ContentLayout header={<Header variant="h1" description="Host agents, and give them tools through MCP gateways.">Amazon Bedrock AgentCore</Header>}>
      <SpaceBetween size="l"><Gateways /><Runtimes /></SpaceBetween>
    </ContentLayout>
  );
}

export function GatewayDetail({ params }) {
  const id = params.id;
  const notify = useNotify();
  const gw = useAsync(() => api.getGateway(id), [id]);
  const tg = useAsync(() => api.listTargets(id), [id]);
  const tools = useAsync(async () => { try { return (await api.mcp(id, "tools/list")).result?.tools || []; } catch { return []; } }, [id, (tg.data || []).length, gw.data?.status]);
  const [create, setCreate] = useState(false);
  const [call, setCall] = useState(null);
  const [args, setArgs] = useState("{}");
  const [out, setOut] = useState(null);
  const g = gw.data;
  // gateways and targets are CREATING for a moment (like the real service): poll until READY
  useEffect(() => {
    if (!g || (g.status === "READY" && (tg.data || []).every((x) => x.status === "READY"))) return undefined;
    const t = setTimeout(() => { gw.reload(); tg.reload(); }, 1200);
    return () => clearTimeout(t);
  });
  const runTool = async () => {
    try { setOut((await api.mcp(id, "tools/call", { name: call.name, arguments: JSON.parse(args || "{}") }))); } catch (e) { notify.error(e); }
  };
  return (
    <ContentLayout header={<Header variant="h1">{g?.name || id}</Header>}>
      <SpaceBetween size="l">
        {gw.error && <ErrorAlert error={gw.error} />}
        {g && <Container header={<Header variant="h2">Gateway details</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <div><Box variant="awsui-key-label">Status</Box>{stat(g.status)}</div>
            <div><Box variant="awsui-key-label">Gateway ID</Box>{g.gatewayId}</div>
            <div><Box variant="awsui-key-label">Inbound auth</Box>{g.authorizerType}</div>
            <div><Box variant="awsui-key-label">MCP endpoint (this appliance)</Box><span data-testid="mcp-url">{`${location.origin}${WIRE_BASE}/gateways/${g.gatewayId}/mcp`}</span></div>
            <div><Box variant="awsui-key-label">ARN</Box>{g.gatewayArn}</div>
          </ColumnLayout></Container>}
        <CapabilityContainer id="bedrock.agentcore.gateway" title="Targets" actions={<Button variant="primary" onClick={() => setCreate(true)}>Add target</Button>}>
          <Table variant="embedded" items={tg.data || []} loading={tg.loading} trackBy="targetId" empty={<Box textAlign="center">No targets</Box>}
            columnDefinitions={[{ id: "n", header: "Name", cell: (t) => t.name, isRowHeader: true }, { id: "i", header: "Target ID", cell: (t) => t.targetId }, { id: "s", header: "Status", cell: (t) => stat(t.status) },
              { id: "x", header: "", cell: (t) => <Button variant="inline-link" onClick={async () => { try { await api.deleteTarget(id, t.targetId); tg.reload(); } catch (e) { notify.error(e); } }}>Delete</Button> }]} />
        </CapabilityContainer>
        <Container header={<Header variant="h2" description="tools/list over the gateway's MCP endpoint.">Tools</Header>}>
          <Table variant="embedded" items={tools.data || []} loading={tools.loading} trackBy="name" empty={<Box textAlign="center">No tools yet - add a Lambda target</Box>}
            columnDefinitions={[{ id: "n", header: "Tool", cell: (t) => t.name, isRowHeader: true }, { id: "d", header: "Description", cell: (t) => t.description }, { id: "c", header: "", cell: (t) => <Button variant="inline-link" onClick={() => { setCall(t); setOut(null); setArgs("{}"); }}>Call tool</Button> }]} />
        </Container>
      </SpaceBetween>
      <CreateTargetModal visible={create} onDismiss={() => setCreate(false)} gatewayId={id} onDone={tg.reload} />
      <Modal visible={!!call} onDismiss={() => setCall(null)} header={`Call ${call?.name}`} size="medium" footer={<Box float="right"><Button variant="primary" onClick={runTool}>Call</Button></Box>}>
        <SpaceBetween size="s">
          <FormField label="Arguments (JSON)"><Textarea value={args} rows={4} onChange={({ detail }) => setArgs(detail.value)} ariaLabel="Arguments" /></FormField>
          {out && <Alert type={out.result?.isError || out.error ? "error" : "success"} header="Result"><span data-testid="tool-result">{out.error ? out.error.message : out.result.content.map((c) => c.text).join("")}</span></Alert>}
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}

/** API Gateway console "AgentCore targets": every gateway target across gateways, with create/delete. */
export function AgentCoreTargets() {
  const notify = useNotify();
  const gws = useAsync(() => api.listGateways(), []);
  const t = useAsync(async () => {
    const out = [];
    for (const g of await api.listGateways()) for (const x of await api.listTargets(g.gatewayId)) out.push({ ...x, gatewayId: g.gatewayId, gatewayName: g.name });
    return out;
  }, []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  return (
    <Box padding="l">
      <CapabilityContainer id="apigateway.agentcore-targets" title="AgentCore targets" description="MCP targets that AgentCore gateways expose to agents.">
        <ResourceTable variant="embedded" resourceName="AgentCore targets" items={t.data || []} loading={t.loading} error={t.error} onRefresh={() => { t.reload(); gws.reload(); }} trackBy="targetId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
          empty={{ title: "No AgentCore targets", action: <Button onClick={() => setCreate(true)}>Create target</Button> }}
          columns={[{ id: "n", header: "Target", isRowHeader: true, cell: (x) => x.name }, { id: "g", header: "Gateway", cell: (x) => <Link href={href("bedrock", "agentcore", "gateways", x.gatewayId)} onFollow={follow}>{x.gatewayName}</Link> }, { id: "s", header: "Status", cell: (x) => stat(x.status) }, { id: "c", header: "Created", cell: (x) => x.createdAt }]}
          actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={async () => { try { await api.deleteTarget(sel[0].gatewayId, sel[0].targetId); notify.success("Target deleted."); setSel([]); t.reload(); } catch (e) { notify.error(e); } }}>Delete</Button><Button variant="primary" onClick={() => setCreate(true)}>Create target</Button></SpaceBetween>} />
      </CapabilityContainer>
      <CreateTargetModal visible={create} onDismiss={() => setCreate(false)} gateways={gws.data} onDone={t.reload} />
    </Box>
  );
}
