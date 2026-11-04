/* EventBridge integration pages: Pipes, Connections, API destinations, Global endpoints, Sandbox.
 * All five run over the native wire (AWSEvents.* JSON and the /v1/pipes REST API). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import Alert from "@cloudscape-design/components/alert";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import MetricGraphs from "../../kit/MetricGraphs.jsx";
import { ErrorAlert, KeyValue, Status, fmtDate } from "../../kit/common.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

const q = (k) => new URLSearchParams((location.hash.split("?")[1]) || "").get(k) || "";
const tail = (arn) => (arn || "").split(/[:/]/).pop();
const stateOk = (s) => ["RUNNING", "AUTHORIZED", "ACTIVE"].includes(s);

function Page({ title, description, children, actions }) {
  return (
    <ContentLayout header={<Header variant="h1" description={description} actions={actions}>{title}</Header>}>
      <SpaceBetween size="l">{children}</SpaceBetween>
    </ContentLayout>
  );
}

function FormPage({ title, backTo, error, busy, onSubmit, submitLabel, children }) {
  return (
    <Page title={title}>
      {error && <ErrorAlert error={error} />}
      <Container>
        <SpaceBetween size="l">
          {children}
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate("eventbridge", backTo)}>Cancel</Button>
            <Button variant="primary" loading={busy} onClick={onSubmit}>{submitLabel}</Button>
          </SpaceBetween>
        </SpaceBetween>
      </Container>
    </Page>
  );
}

function useSubmit(fn, done, okMsg) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async () => {
    setBusy(true); setError(null);
    try { await fn(); notify.success(okMsg); navigate("eventbridge", done); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return { busy, error, run };
}

// ── Pipes ───────────────────────────────────────────────────────────────────
export function Pipes() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listPipes());
  const act = async (fn, msg) => { try { await fn(sel[0].Name); notify.success(msg); reload(); } catch (e) { notify.error(e); } };
  return (
    <>
      <ResourceTable resourceName="Pipes" description={<CapabilityBadge id="eventbridge.pipes.crud" />} items={data} loading={loading} error={error} onRefresh={reload}
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} trackBy="Name" filterPlaceholder="Find pipes"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (p) => <Link href={`${href("eventbridge", "pipes", p.Name)}`} onFollow={follow}>{p.Name}</Link> },
          { id: "status", header: "Status", cell: (p) => <Status ok={p.CurrentState === "RUNNING"}>{p.CurrentState}</Status> },
          { id: "source", header: "Source", cell: (p) => tail(p.Source) },
          { id: "enrichment", header: "Enrichment", cell: (p) => (p.Enrichment ? tail(p.Enrichment) : "-") },
          { id: "target", header: "Target", cell: (p) => tail(p.Target) },
          { id: "created", header: "Creation time", cell: (p) => fmtDate(p.CreationTime) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1 || sel[0].CurrentState === "RUNNING"} onClick={() => act(api.startPipe, `Started pipe ${sel[0].Name}.`)}>Start</Button>
            <Button disabled={sel.length !== 1 || sel[0].CurrentState !== "RUNNING"} onClick={() => act(api.stopPipe, `Stopped pipe ${sel[0].Name}.`)}>Stop</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" href={href("eventbridge", "create-pipe")} onFollow={follow}>Create pipe</Button>
          </SpaceBetween>}
        empty={{ title: "No pipes", subtitle: "No pipes to display", action: <Button href={href("eventbridge", "create-pipe")} onFollow={follow}>Create pipe</Button> }}
      />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="pipe" names={sel.map((p) => p.Name)}
        onConfirm={async () => { await Promise.all(sel.map((p) => api.deletePipe(p.Name))); notify.success("Deleted pipe."); setSel([]); setDel(false); reload(); }} />
    </>
  );
}

export function CreatePipe() {
  const { data: queues = [] } = useAsync(() => api.listQueueTargets());
  const { data: targets = [] } = useAsync(() => api.listAllTargets());
  const [name, setName] = useState(""); const [source, setSource] = useState(null); const [target, setTarget] = useState(null);
  const [desc, setDesc] = useState(""); const [state, setState] = useState({ value: "RUNNING", label: "Running" });
  const s = useSubmit(() => api.createPipe(name, { Source: source.value, Target: target.value, Description: desc, DesiredState: state.value, RoleArn: "arn:aws:iam::000000000000:role/vyomi-pipes" }), "pipes", `Pipe ${name} was created.`);
  return (
    <FormPage title="Create pipe" backTo="pipes" {...s} onSubmit={s.run} submitLabel="Create pipe">
      <FormField label="Pipe name" constraintText="Letters, numbers, hyphens and underscores"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Pipe name" /></FormField>
      <FormField label="Description - optional"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} ariaLabel="Description" /></FormField>
      <FormField label="Source" description="An SQS queue. Messages sent to it are forwarded to the target the moment they land."><Select placeholder="Select a source" selectedOption={source} onChange={({ detail }) => setSource(detail.selectedOption)} options={queues.map((o) => ({ value: o.arn, label: o.label }))} ariaLabel="Source" /></FormField>
      <FormField label="Target"><Select placeholder="Select a target" selectedOption={target} onChange={({ detail }) => setTarget(detail.selectedOption)} options={targets.map((o) => ({ value: o.arn, label: o.label }))} ariaLabel="Target" /></FormField>
      <FormField label="Desired state"><Select selectedOption={state} onChange={({ detail }) => setState(detail.selectedOption)} options={[{ value: "RUNNING", label: "Running" }, { value: "STOPPED", label: "Stopped" }]} ariaLabel="Desired state" /></FormField>
      <Alert type="info"><CapabilityBadge id="eventbridge.pipes.crud" /> Enrichment and filtering are not applied; the message body is forwarded as-is.</Alert>
    </FormPage>
  );
}

export function PipeDetail({ params }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const { data: p, loading, error, reload } = useAsync(() => api.describePipe(params.name), [params.name]);
  if (error) return <Page title={params.name}><ErrorAlert error={error} /></Page>;
  if (loading || !p) return <Page title={params.name}><Box>Loading</Box></Page>;
  const act = async (fn, msg) => { try { await fn(p.Name); notify.success(msg); reload(); } catch (e) { notify.error(e); } };
  return (
    <>
      <Page title={p.Name} actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={p.CurrentState === "RUNNING"} onClick={() => act(api.startPipe, `Started pipe ${p.Name}.`)}>Start</Button>
        <Button disabled={p.CurrentState !== "RUNNING"} onClick={() => act(api.stopPipe, `Stopped pipe ${p.Name}.`)}>Stop</Button>
        <Button onClick={() => setDel(true)}>Delete</Button></SpaceBetween>}>
        <KeyValue title="Pipe details" items={[["Status", <Status ok={p.CurrentState === "RUNNING"}>{p.CurrentState}</Status>], ["ARN", p.Arn], ["Source", p.Source], ["Target", p.Target], ["Enrichment", p.Enrichment], ["Description", p.Description], ["Created", fmtDate(p.CreationTime)], ["Last modified", fmtDate(p.LastModifiedTime)]]} />
        <Tabs tabs={[{ id: "monitoring", label: "Monitoring", content: <CapabilityContainer id="eventbridge.pipes.metrics" title="Metrics"><MetricGraphs bare graphs={["Execution", "ExecutionSucceeded", "ExecutionFailed", "Duration"].map((n) => ({ title: n, namespace: "AWS/EventBridge/Pipes", name: n, dimensions: [{ Name: "PipeName", Value: p.Name }], unit: n === "Duration" ? "Milliseconds" : "Count", stat: n === "Duration" ? "Average" : "Sum" }))} /></CapabilityContainer> }]} />
      </Page>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="pipe" names={[p.Name]}
        onConfirm={async () => { await api.deletePipe(p.Name); notify.success(`Deleted pipe ${p.Name}.`); navigate("eventbridge", "pipes"); }} />
    </>
  );
}

// ── Connections ──────────────────────────────────────────────────────────────
const AUTH = [{ value: "API_KEY", label: "API key" }, { value: "BASIC", label: "Basic (username/password)" }, { value: "OAUTH_CLIENT_CREDENTIALS", label: "OAuth client credentials" }];

export function Connections() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listConnections());
  return (
    <>
      <ResourceTable resourceName="Connections" description={<CapabilityBadge id="eventbridge.connections" />} items={data} loading={loading} error={error} onRefresh={reload}
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} trackBy="Name" filterPlaceholder="Find connections"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (c) => c.Name },
          { id: "status", header: "Status", cell: (c) => <Status ok={stateOk(c.ConnectionState)}>{c.ConnectionState}</Status> },
          { id: "auth", header: "Authorization type", cell: (c) => c.AuthorizationType },
          { id: "arn", header: "ARN", cell: (c) => c.ConnectionArn },
          { id: "created", header: "Creation time", cell: (c) => fmtDate(c.CreationTime) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1 || sel[0].ConnectionState !== "AUTHORIZED"} onClick={async () => { try { await api.deauthorizeConnection(sel[0].Name); notify.success("Connection deauthorized."); setSel([]); reload(); } catch (e) { notify.error(e); } }}>Deauthorize</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" href={href("eventbridge", "create-connection")} onFollow={follow}>Create connection</Button>
          </SpaceBetween>}
        empty={{ title: "No connections", subtitle: "No connections to display", action: <Button href={href("eventbridge", "create-connection")} onFollow={follow}>Create connection</Button> }}
      />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="connection" names={sel.map((c) => c.Name)}
        onConfirm={async () => { try { await api.deleteConnection(sel[0].Name); notify.success("Deleted connection."); setSel([]); reload(); } catch (e) { notify.error(e); } setDel(false); }} />
    </>
  );
}

export function CreateConnection() {
  const [name, setName] = useState(""); const [desc, setDesc] = useState(""); const [auth, setAuth] = useState(AUTH[0]);
  const [f, setF] = useState({ keyName: "", keyValue: "", user: "", pass: "", endpoint: "", method: "POST", cid: "", csecret: "" });
  const set = (k) => ({ detail }) => setF((x) => ({ ...x, [k]: detail.value }));
  const params = () => auth.value === "API_KEY" ? { ApiKeyAuthParameters: { ApiKeyName: f.keyName, ApiKeyValue: f.keyValue } }
    : auth.value === "BASIC" ? { BasicAuthParameters: { Username: f.user, Password: f.pass } }
    : { OAuthParameters: { AuthorizationEndpoint: f.endpoint, HttpMethod: f.method, ClientParameters: { ClientID: f.cid, ClientSecret: f.csecret } } };
  const s = useSubmit(() => api.createConnection({ Name: name, Description: desc, AuthorizationType: auth.value, AuthParameters: params() }), "connections", `Connection ${name} was created.`);
  return (
    <FormPage title="Create connection" backTo="connections" {...s} onSubmit={s.run} submitLabel="Create">
      <FormField label="Connection name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Connection name" /></FormField>
      <FormField label="Description - optional"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} ariaLabel="Description" /></FormField>
      <FormField label="Authorization type"><Select selectedOption={auth} onChange={({ detail }) => setAuth(detail.selectedOption)} options={AUTH} ariaLabel="Authorization type" /></FormField>
      {auth.value === "API_KEY" && <><FormField label="API key name"><Input value={f.keyName} onChange={set("keyName")} ariaLabel="API key name" /></FormField><FormField label="Value"><Input type="password" value={f.keyValue} onChange={set("keyValue")} ariaLabel="API key value" /></FormField></>}
      {auth.value === "BASIC" && <><FormField label="Username"><Input value={f.user} onChange={set("user")} ariaLabel="Username" /></FormField><FormField label="Password"><Input type="password" value={f.pass} onChange={set("pass")} ariaLabel="Password" /></FormField></>}
      {auth.value === "OAUTH_CLIENT_CREDENTIALS" && <><FormField label="Authorization endpoint"><Input value={f.endpoint} onChange={set("endpoint")} ariaLabel="Authorization endpoint" /></FormField><FormField label="Client ID"><Input value={f.cid} onChange={set("cid")} ariaLabel="Client ID" /></FormField><FormField label="Client secret"><Input type="password" value={f.csecret} onChange={set("csecret")} ariaLabel="Client secret" /></FormField></>}
    </FormPage>
  );
}

// ── API destinations ─────────────────────────────────────────────────────────
export function ApiDestinations() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listApiDestinations());
  return (
    <>
      <ResourceTable resourceName="API destinations" description={<CapabilityBadge id="eventbridge.api-destinations" />} items={data} loading={loading} error={error} onRefresh={reload}
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} trackBy="Name" filterPlaceholder="Find API destinations"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (d) => d.Name },
          { id: "status", header: "Status", cell: (d) => <Status ok={d.ApiDestinationState === "ACTIVE"}>{d.ApiDestinationState}</Status> },
          { id: "conn", header: "Connection", cell: (d) => tail(d.ConnectionArn) },
          { id: "endpoint", header: "Invocation endpoint", cell: (d) => d.InvocationEndpoint },
          { id: "method", header: "HTTP method", cell: (d) => d.HttpMethod },
          { id: "rate", header: "Rate limit (per second)", cell: (d) => d.InvocationRateLimitPerSecond },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" href={href("eventbridge", "create-api-destination")} onFollow={follow}>Create API destination</Button>
          </SpaceBetween>}
        empty={{ title: "No API destinations", subtitle: "No API destinations to display", action: <Button href={href("eventbridge", "create-api-destination")} onFollow={follow}>Create API destination</Button> }}
      />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="API destination" names={sel.map((d) => d.Name)}
        onConfirm={async () => { await api.deleteApiDestination(sel[0].Name); notify.success("Deleted API destination."); setSel([]); setDel(false); reload(); }} />
    </>
  );
}

export function CreateApiDestination() {
  const { data: conns = [] } = useAsync(() => api.listConnections());
  const [name, setName] = useState(""); const [desc, setDesc] = useState(""); const [url, setUrl] = useState("");
  const [method, setMethod] = useState({ value: "POST", label: "POST" }); const [conn, setConn] = useState(null); const [rate, setRate] = useState("300");
  const s = useSubmit(() => api.createApiDestination({ Name: name, Description: desc, ConnectionArn: conn?.value, InvocationEndpoint: url, HttpMethod: method.value, InvocationRateLimitPerSecond: Number(rate) }), "api-destinations", `API destination ${name} was created.`);
  return (
    <FormPage title="Create API destination" backTo="api-destinations" {...s} onSubmit={s.run} submitLabel="Create">
      <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
      <FormField label="Description - optional"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} ariaLabel="Description" /></FormField>
      <FormField label="API destination endpoint" description="An http(s) URL that receives the event."><Input value={url} onChange={({ detail }) => setUrl(detail.value)} ariaLabel="API destination endpoint" placeholder="https://example.com/webhook" /></FormField>
      <FormField label="HTTP method"><Select selectedOption={method} onChange={({ detail }) => setMethod(detail.selectedOption)} options={["POST", "GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].map((m) => ({ value: m, label: m }))} ariaLabel="HTTP method" /></FormField>
      <FormField label="Invocation rate limit per second"><Input type="number" value={rate} onChange={({ detail }) => setRate(detail.value)} ariaLabel="Invocation rate limit" /></FormField>
      <FormField label="Connection"><Select placeholder="Choose a connection" selectedOption={conn} onChange={({ detail }) => setConn(detail.selectedOption)} options={conns.map((c) => ({ value: c.ConnectionArn, label: c.Name }))} ariaLabel="Connection" /></FormField>
      <Alert type="info"><CapabilityBadge id="eventbridge.api-destinations" /> Use the API destination ARN as a rule target.</Alert>
    </FormPage>
  );
}

// ── Global endpoints ─────────────────────────────────────────────────────────
export function GlobalEndpoints() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listEndpoints());
  return (
    <>
      <ResourceTable resourceName="Global endpoints" description={<CapabilityBadge id="eventbridge.global-endpoints" />} items={data} loading={loading} error={error} onRefresh={reload}
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} trackBy="Name" filterPlaceholder="Find global endpoints"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (e) => e.Name },
          { id: "status", header: "Status", cell: (e) => <Status ok={e.State === "ACTIVE"}>{e.State}</Status> },
          { id: "home", header: "Home", cell: (e) => tail(e.EventBuses?.[0]) },
          { id: "id", header: "Endpoint Id", cell: (e) => e.EndpointId },
          { id: "url", header: "Endpoint URL", cell: (e) => e.EndpointUrl },
          { id: "repl", header: "Event replication", cell: (e) => e.ReplicationConfig?.State },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" href={href("eventbridge", "create-global-endpoint")} onFollow={follow}>Create global endpoint</Button>
          </SpaceBetween>}
        empty={{ title: "No global endpoints", subtitle: "No global endpoints to display", action: <Button href={href("eventbridge", "create-global-endpoint")} onFollow={follow}>Create global endpoint</Button> }}
      />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="global endpoint" names={sel.map((e) => e.Name)}
        onConfirm={async () => { await api.deleteEndpoint(sel[0].Name); notify.success("Deleted global endpoint."); setSel([]); setDel(false); reload(); }} />
    </>
  );
}

export function CreateGlobalEndpoint() {
  const [name, setName] = useState(""); const [hc, setHc] = useState("arn:aws:route53:::healthcheck/vyomi");
  const [primary, setPrimary] = useState("arn:aws:events:us-east-1:000000000000:event-bus/default"); const [secondary, setSecondary] = useState("arn:aws:events:us-west-2:000000000000:event-bus/default");
  const [region, setRegion] = useState("us-west-2"); const [repl, setRepl] = useState({ value: "ENABLED", label: "Enabled" });
  const s = useSubmit(() => api.createEndpoint({ Name: name, RoutingConfig: { FailoverConfig: { Primary: { HealthCheck: hc }, Secondary: { Route: region } } },
    ReplicationConfig: { State: repl.value }, EventBuses: [{ EventBusArn: primary }, { EventBusArn: secondary }].map((b) => b.EventBusArn) }), "global-endpoints", `Global endpoint ${name} was created.`);
  return (
    <FormPage title="Create global endpoint" backTo="global-endpoints" {...s} onSubmit={s.run} submitLabel="Create">
      <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
      <FormField label="Primary event bus ARN"><Input value={primary} onChange={({ detail }) => setPrimary(detail.value)} ariaLabel="Primary event bus ARN" /></FormField>
      <FormField label="Secondary event bus ARN"><Input value={secondary} onChange={({ detail }) => setSecondary(detail.value)} ariaLabel="Secondary event bus ARN" /></FormField>
      <FormField label="Secondary Region"><Input value={region} onChange={({ detail }) => setRegion(detail.value)} ariaLabel="Secondary Region" /></FormField>
      <FormField label="Route 53 health check ARN"><Input value={hc} onChange={({ detail }) => setHc(detail.value)} ariaLabel="Health check" /></FormField>
      <FormField label="Event replication"><Select selectedOption={repl} onChange={({ detail }) => setRepl(detail.selectedOption)} options={[{ value: "ENABLED", label: "Enabled" }, { value: "DISABLED", label: "Disabled" }]} ariaLabel="Event replication" /></FormField>
      <Alert type="info"><CapabilityBadge id="eventbridge.global-endpoints" /></Alert>
    </FormPage>
  );
}

// ── Sandbox: TestEventPattern ────────────────────────────────────────────────
const SAMPLE_EVENT = JSON.stringify({ version: "0", id: "6a7e8feb-b491-4cf7-a9f1-bf3703467718", "detail-type": "EC2 Instance State-change Notification", source: "aws.ec2", account: "000000000000", time: "2026-01-01T12:00:00Z", region: "us-east-1", resources: [], detail: { "instance-id": "i-0123456789abcdef0", state: "running" } }, null, 2);
const SAMPLE_PATTERN = JSON.stringify({ source: ["aws.ec2"], detail: { state: ["running", "stopped"] } }, null, 2);

export function Sandbox() {
  const [event, setEvent] = useState(SAMPLE_EVENT);
  const [pattern, setPattern] = useState(SAMPLE_PATTERN);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const test = async () => { setErr(null); setRes(null); try { setRes((await api.testEventPattern(pattern, event)).Result); } catch (e) { setErr(e); } };
  return (
    <Page title="Sandbox" description="Test an event pattern against a sample event using the same matcher rules use.">
      <CapabilityBadge id="eventbridge.sandbox" />
      <Container header={<Header variant="h2">Event pattern</Header>}>
        <SpaceBetween size="l">
          <FormField label="Sample event"><Textarea rows={12} value={event} onChange={({ detail }) => setEvent(detail.value)} ariaLabel="Sample event" /></FormField>
          <FormField label="Event pattern"><Textarea rows={8} value={pattern} onChange={({ detail }) => setPattern(detail.value)} ariaLabel="Event pattern" /></FormField>
          <Button variant="primary" onClick={test}>Test pattern</Button>
          {err && <ErrorAlert error={err} />}
          {res !== null && <Alert type={res ? "success" : "warning"} header={res ? "Matched" : "Did not match"} data-testid="sandbox-result">{res ? "The event matches this pattern." : "The event does not match this pattern."}</Alert>}
        </SpaceBetween>
      </Container>
    </Page>
  );
}
