/* Console Home — the widget dashboard of the native console, on live Vyomi data only:
 * every number and status comes from a real call (native wire or Vyomi's event log);
 * the layout (which widgets show) is a per-browser preference. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import Grid from "@cloudscape-design/components/grid";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Modal from "@cloudscape-design/components/modal";
import Checkbox from "@cloudscape-design/components/checkbox";
import Table from "@cloudscape-design/components/table";
import { byId, SERVICES } from "../services/registry.js";
import { follow } from "../../common/router.js";
import { awsJson, awsQuery, asList, getRegion, s3, WIRE_BASE } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { fmtDate } from "../kit/common.jsx";

const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(`vyomi.v4.${k}`)) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(`vyomi.v4.${k}`, JSON.stringify(v)); } catch {} },
};

export function recordVisit(id) {
  const recent = store.get("recent", []).filter((x) => x !== id);
  store.set("recent", [id, ...recent].slice(0, 12));
}

// One real, cheap native call per service: proves it is up AND counts its resources.
const PROBES = {
  s3: async () => asList((await s3("GET", "/")).ListAllMyBucketsResult?.Buckets?.Bucket).length,
  dynamodb: async () => (await awsJson("dynamodb", "DynamoDB_20120810.ListTables", {})).TableNames?.length || 0,
  sqs: async () => (await awsJson("sqs", "AmazonSQS.ListQueues", {})).QueueUrls?.length || 0,
  sns: async () => asList((await awsQuery("sns", "ListTopics", {}, { version: "2010-03-31" })).ListTopicsResponse?.ListTopicsResult?.Topics?.member).length,
  kms: async () => (await awsJson("kms", "TrentService.ListKeys", {}, { version: "1.1" })).Keys?.length || 0,
  secretsmanager: async () => (await awsJson("secretsmanager", "secretsmanager.ListSecrets", {}, { version: "1.1" })).SecretList?.length || 0,
  iam: async () => asList((await awsQuery("iam", "ListRoles", {}, { version: "2010-05-08" })).ListRolesResponse?.ListRolesResult?.Roles?.member).length,
};
const RESOURCE_NOUN = { s3: "buckets", dynamodb: "tables", sqs: "queues", sns: "topics", kms: "keys", secretsmanager: "secrets", iam: "roles" };

function useProbes() {
  return useAsync(async () => {
    const out = await Promise.all(Object.entries(PROBES).map(async ([id, fn]) => {
      const t = performance.now();
      try { return { id, ok: true, count: await fn(), ms: Math.round(performance.now() - t) }; }
      catch (e) { return { id, ok: false, error: e.code || e.message, ms: Math.round(performance.now() - t) }; }
    }));
    return out;
  }, []);
}

const WIDGETS = [
  { id: "recent", title: "Recently visited" },
  { id: "welcome", title: "Welcome to Vyomi" },
  { id: "health", title: "Vyomi health" },
  { id: "resources", title: "Resources" },
  { id: "activity", title: "Recent activity" },
  { id: "connect", title: "Connect your SDK or CLI" },
];
const DEFAULT_LAYOUT = WIDGETS.map((w) => w.id);

function Widget({ title, info, actions, footer, children }) {
  return (
    <Container fitHeight header={<Header variant="h2" info={info} actions={actions}>{title}</Header>} footer={footer}>
      {children}
    </Container>
  );
}

function Recent() {
  const recent = store.get("recent", []).map((id) => byId[id]).filter(Boolean);
  return (
    <Widget title="Recently visited" actions={<Button href="#/services" onFollow={follow}>All services</Button>}>
      {recent.length ? (
        <ColumnLayout columns={2} variant="text-grid">
          {recent.map((s) => <Link key={s.id} href={`#/${s.id}`} onFollow={follow}>{s.title}</Link>)}
        </ColumnLayout>
      ) : <Box color="text-body-secondary">No recently visited services. Explore one of the services below to get started.</Box>}
    </Widget>
  );
}

function Welcome() {
  return (
    <Widget title="Welcome to Vyomi">
      <SpaceBetween size="s">
        <Box variant="p">Everything here runs against your local Vyomi simulator — the same native APIs your SDKs and CLI use.</Box>
        <Link href="#/s3/create" onFollow={follow}>Create an S3 bucket</Link>
        <Link href="#/dynamodb/create-table" onFollow={follow}>Create a DynamoDB table</Link>
        <Link href="#/services" onFollow={follow}>Browse all services</Link>
      </SpaceBetween>
    </Widget>
  );
}

function Health({ probes }) {
  const rows = probes.data || [];
  const up = rows.filter((r) => r.ok).length;
  return (
    <Widget title="Vyomi health" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={probes.reload} />}
      footer={<Box textAlign="center" color="text-body-secondary" variant="small">Each status is a live API call to the service in region {getRegion()}.</Box>}>
      {probes.loading ? <StatusIndicator type="loading">Checking services</StatusIndicator> : (
        <SpaceBetween size="xs">
          <Box><Box variant="awsui-key-label">Services responding</Box><Box fontSize="display-l" fontWeight="bold">{up}/{rows.length}</Box></Box>
          {rows.filter((r) => !r.ok).map((r) => <StatusIndicator key={r.id} type="error">{byId[r.id]?.title || r.id}: {r.error}</StatusIndicator>)}
          {up === rows.length && <StatusIndicator type="success">All probed services are operational</StatusIndicator>}
        </SpaceBetween>
      )}
    </Widget>
  );
}

function Resources({ probes }) {
  return (
    <Widget title="Resources" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={probes.reload} />}>
      <Table variant="embedded" loading={probes.loading} items={(probes.data || []).filter((r) => r.ok)}
        columnDefinitions={[
          { id: "svc", header: "Service", cell: (r) => <Link href={`#/${r.id}`} onFollow={follow}>{byId[r.id]?.title || r.id}</Link> },
          { id: "n", header: "Resources", cell: (r) => `${r.count} ${RESOURCE_NOUN[r.id]}` },
          { id: "ms", header: "Latency", cell: (r) => `${r.ms} ms` },
        ]}
        empty={<Box textAlign="center">No services responded</Box>} />
    </Widget>
  );
}

function Activity() {
  // Vyomi's own event log (appliance: {events:[{at,event,detail}]}; Nano: {events:[{ts,service,action,resource}]}).
  const ev = useAsync(async () => {
    const base = WIRE_BASE.replace(/\/_wire$/, "");
    const r = await fetch(`${base}/api/cloudsim/events?limit=8`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    return (d.events || []).slice(0, 8).map((e) => ({
      when: e.at || e.ts,
      what: e.event || [e.provider, e.service, e.action].filter(Boolean).join("."),
      resource: e.detail?.name || e.resource || e.detail?.resource_id || "",
    }));
  }, []);
  return (
    <Widget title="Recent activity" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={ev.reload} />}>
      <Table variant="embedded" loading={ev.loading} items={ev.data || []}
        columnDefinitions={[
          { id: "w", header: "Time", cell: (e) => fmtDate(e.when) },
          { id: "a", header: "Event", cell: (e) => e.what },
          { id: "r", header: "Resource", cell: (e) => e.resource || "-" },
        ]}
        empty={<Box textAlign="center" color="inherit">{ev.error ? `Event log unavailable (${ev.error.message})` : "No activity yet"}</Box>} />
    </Widget>
  );
}

function Connect() {
  const endpoint = location.origin + (WIRE_BASE.startsWith("/nano") ? " (via the Nano relay: vyomi-tunnel)" : "");
  return (
    <Widget title="Connect your SDK or CLI">
      <SpaceBetween size="xs">
        <Box variant="awsui-key-label">Endpoint</Box><Box variant="code">{endpoint}</Box>
        <Box variant="awsui-key-label">Region</Box><Box variant="code">{getRegion()}</Box>
        <Box variant="awsui-key-label">Example</Box>
        <Box variant="code">aws --endpoint-url {location.origin} s3 ls</Box>
      </SpaceBetween>
    </Widget>
  );
}

export default function Home() {
  const [layout, setLayout] = useState(store.get("home.layout", DEFAULT_LAYOUT));
  const [picking, setPicking] = useState(null);
  const probes = useProbes();
  const save = (l) => { setLayout(l); store.set("home.layout", l); };
  const render = {
    recent: <Recent />, welcome: <Welcome />, health: <Health probes={probes} />,
    resources: <Resources probes={probes} />, activity: <Activity />, connect: <Connect />,
  };
  const shown = layout.filter((id) => render[id]);
  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => save(DEFAULT_LAYOUT)}>Reset to default layout</Button>
          <Button variant="primary" iconName="add-plus" onClick={() => setPicking([...layout])}>Add widgets</Button>
        </SpaceBetween>
      }>Console Home</Header>
    }>
      <Grid gridDefinition={shown.map((id) => ({ colspan: { default: 12, m: id === "recent" || id === "resources" || id === "activity" ? 6 : 6, l: id === "recent" ? 6 : id === "resources" || id === "activity" ? 6 : 3 } }))}>
        {shown.map((id) => <div key={id} style={{ height: "100%" }}>{render[id]}</div>)}
      </Grid>
      <Modal visible={!!picking} onDismiss={() => setPicking(null)} header="Add widgets"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setPicking(null)}>Cancel</Button>
          <Button variant="primary" onClick={() => { save(DEFAULT_LAYOUT.filter((id) => picking.includes(id))); setPicking(null); }}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="xs">
          {picking && WIDGETS.map((w) => (
            <Checkbox key={w.id} checked={picking.includes(w.id)}
              onChange={({ detail }) => setPicking(detail.checked ? [...picking, w.id] : picking.filter((x) => x !== w.id))}>{w.title}</Checkbox>
          ))}
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}

/** #/services — every service by category (the console's "All services" view). */
export function AllServices() {
  const cats = [...new Set(SERVICES.map((s) => s.category))];
  return (
    <ContentLayout header={<Header variant="h1">All services</Header>}>
      <SpaceBetween size="l">
        {cats.map((cat) => (
          <Container key={cat} header={<Header variant="h2">{cat}</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              {SERVICES.filter((s) => s.category === cat).map((s) => (
                <div key={s.id}>
                  <Link href={`#/${s.id}`} onFollow={follow} fontSize="heading-s">{s.title}</Link>
                  <Box variant="small" display="block" color="text-body-secondary" margin={{ top: "xxxs" }}>{s.description}{!s.load ? " · classic console" : ""}</Box>
                </div>
              ))}
            </ColumnLayout>
          </Container>
        ))}
      </SpaceBetween>
    </ContentLayout>
  );
}
