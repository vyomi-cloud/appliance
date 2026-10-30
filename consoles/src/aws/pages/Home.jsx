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
import { vy } from "../../common/VyomiMark.jsx";
import { byId, SERVICES, classicHref } from "../services/registry.js";
import ServiceIcon from "../../common/icons/ServiceIcon.jsx";

/** A service's icon followed by its console link (Console Home lists, All services). */
const SvcLink = ({ s, size = 20, fontSize }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0 }}>
    <ServiceIcon cloud="aws" id={s.icon || s.id} category={s.category} size={size} />
    <Link href={`#/${s.id}`} onFollow={follow} fontSize={fontSize}>{s.title}</Link>
  </span>
);
import { follow } from "../../common/router.js";
import { awsJson, awsQuery, asList, getRegion, s3, WIRE_BASE } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { fmtDate } from "../kit/common.jsx";
import Tabs from "@cloudscape-design/components/tabs";
import CopyToClipboard from "@cloudscape-design/components/copy-to-clipboard";
import { sdkEndpoint } from "../../common/connect.js";

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

// Inside the Board, BoardItem draws the header/footer; a widget body renders only its content.
function Widget({ children }) {
  return <>{children}</>;
}

function RecentWidget() {
  const recent = store.get("recent", []).map((id) => byId[id]).filter(Boolean);
  return (
    <Widget title="Recently visited" actions={<Button href="#/services" onFollow={follow}>All services</Button>}>
      {recent.length ? (
        <ColumnLayout columns={2} variant="text-grid">
          {recent.map((s) => <SvcLink key={s.id} s={s} />)}
        </ColumnLayout>
      ) : <Box color="text-body-secondary">No recently visited services. Explore one of the services below to get started.</Box>}
    </Widget>
  );
}

function WelcomeWidget() {
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

function HealthWidget({ probes }) {
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

function ResourcesWidget({ probes }) {
  return (
    <Widget title="Resources" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={probes.reload} />}>
      <Table variant="embedded" loading={probes.loading} items={(probes.data || []).filter((r) => r.ok)}
        columnDefinitions={[
          { id: "svc", header: "Service", cell: (r) => byId[r.id] ? <SvcLink s={byId[r.id]} size={16} /> : <Link href={`#/${r.id}`} onFollow={follow}>{r.id}</Link> },
          { id: "n", header: "Resources", cell: (r) => `${r.count} ${RESOURCE_NOUN[r.id]}` },
          { id: "ms", header: "Latency", cell: (r) => `${r.ms} ms` },
        ]}
        empty={<Box textAlign="center">No services responded</Box>} />
    </Widget>
  );
}

function ActivityWidget() {
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

function Snippet({ code, label }) {
  return (
    <div style={{ position: "relative" }}>
      <Box variant="code" display="block" padding="s">
        <pre style={{ margin: 0, whiteSpace: "pre", overflowX: "auto", fontSize: 12, lineHeight: 1.5, paddingRight: 28 }}>{code}</pre>
      </Box>
      <div style={{ position: "absolute", top: 4, right: 4 }}>
        <CopyToClipboard variant="icon" textToCopy={code} copyButtonAriaLabel={`Copy ${label}`} copySuccessText="Copied" copyErrorText="Couldn't copy" />
      </div>
    </div>
  );
}

function ConnectWidget() {
  const ep = sdkEndpoint();
  const region = getRegion();
  const cli = [
    "export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test",
    `export AWS_DEFAULT_REGION=${region}`,
    `aws --endpoint-url ${ep.url} s3 ls`,
    `aws --endpoint-url ${ep.url} dynamodb list-tables`,
  ].join("\n");
  const sdk = [
    "import boto3",
    "",
    `session = boto3.Session(aws_access_key_id="test", aws_secret_access_key="test", region_name="${region}")`,
    `s3 = session.client("s3", endpoint_url="${ep.url}")`,
    `ddb = session.client("dynamodb", endpoint_url="${ep.url}")`,
    "",
    'print([b["Name"] for b in s3.list_buckets()["Buckets"]])',
    'print(ddb.list_tables()["TableNames"])',
  ].join("\n");
  return (
    <SpaceBetween size="xs">
      <Tabs variant="default" tabs={[
        { id: "cli", label: "AWS CLI", content: <Snippet code={cli} label="AWS CLI commands" /> },
        { id: "sdk", label: "Python (boto3)", content: <Snippet code={sdk} label="Python snippet" /> },
      ]} />
      {ep.note && <Box variant="small" color="text-body-secondary">{ep.note}</Box>}
    </SpaceBetween>
  );
}


import Board from "@cloudscape-design/board-components/board";
import BoardItem from "@cloudscape-design/board-components/board-item";
import ItemsPalette from "@cloudscape-design/board-components/items-palette";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Alert from "@cloudscape-design/components/alert";

// Widget catalogue (columnSpan of a 4-column board; the board reflows on narrow screens).
const CATALOG = {
  recent: { title: "Recently visited", columnSpan: 2, rowSpan: 3 },
  welcome: { title: "Welcome to Vyomi", columnSpan: 1, rowSpan: 3 },
  health: { title: "Vyomi Health", columnSpan: 1, rowSpan: 3 },
  cost: { title: "Cost and usage", columnSpan: 2, rowSpan: 3 },
  resources: { title: "Resources", columnSpan: 2, rowSpan: 4 },
  activity: { title: "Recent activity", columnSpan: 2, rowSpan: 4 },
  explore: { title: "Explore Vyomi", columnSpan: 1, rowSpan: 3 },
  security: { title: "Security", columnSpan: 1, rowSpan: 3 },
  connect: { title: "Connect your SDK or CLI", columnSpan: 2, rowSpan: 4 },
};
const DEFAULT_ITEMS = ["recent", "welcome", "health", "cost", "resources", "activity", "explore", "security", "connect"]
  .map((id) => ({ id, columnSpan: CATALOG[id].columnSpan, rowSpan: CATALOG[id].rowSpan, data: { id } }));
// Saved layouts from before a widget changed size keep working; bump to re-apply defaults.
const LAYOUT_VERSION = 2;

const boardI18n = {
  liveAnnouncementDndStarted: (op) => (op === "resize" ? "Resizing" : "Dragging"),
  liveAnnouncementDndItemReordered: () => "Item moved.",
  liveAnnouncementDndItemResized: () => "Item resized.",
  liveAnnouncementDndItemInserted: () => "Item inserted.",
  liveAnnouncementDndCommitted: (op) => `${op} committed`,
  liveAnnouncementDndDiscarded: (op) => `${op} discarded`,
  liveAnnouncementItemRemoved: (op) => `Removed item ${op.item.data.id}.`,
  navigationAriaLabel: "Board navigation",
  navigationAriaDescription: "Click on non-empty item to move focus over",
  navigationItemAriaLabel: (item) => (item ? CATALOG[item.data.id]?.title : "Empty"),
};
const itemI18n = {
  dragHandleAriaLabel: "Drag handle",
  dragHandleAriaDescription: "Use Space or Enter to activate drag, arrow keys to move, Space or Enter to submit, or Escape to discard.",
  resizeHandleAriaLabel: "Resize handle",
  resizeHandleAriaDescription: "Use Space or Enter to activate resize, arrow keys to resize, Space or Enter to submit, or Escape to discard.",
};
const paletteI18n = {
  header: "Add widgets",
  headerDescription: "Drag a widget onto the board.",
  liveAnnouncementDndStarted: () => "Dragging",
  liveAnnouncementDndDiscarded: () => "Insertion discarded",
  navigationAriaLabel: "Widgets",
  navigationAriaDescription: "Click on an item to move focus over",
  navigationItemAriaLabel: (item) => CATALOG[item.data.id]?.title,
};

const RecentBody = RecentWidget, WelcomeBody = WelcomeWidget, ResourcesBody = ResourcesWidget,
  ActivityBody = ActivityWidget, ConnectBody = ConnectWidget;

function Cost() {
  // Vyomi never bills, so the true figure is $0.00; projected AWS pricing is not simulated.
  return (
    <SpaceBetween size="s">
      <div><Box variant="awsui-key-label">Current month</Box><Box fontSize="heading-xl" color="text-status-info">$0.00</Box></div>
      <div><Box variant="awsui-key-label">Forecasted month end</Box><Box fontSize="heading-xl" color="text-status-info">$0.00</Box></div>
      <Box variant="small" color="text-body-secondary">Resources in Vyomi are free. Estimating what they would cost on AWS is not simulated.</Box>
    </SpaceBetween>
  );
}

function Explore() {
  return (
    <SpaceBetween size="s">
      <div><Link href="https://vyomi.cloud" external>Vyomi documentation</Link><Box variant="small" display="block" color="text-body-secondary">Guides for every simulated service.</Box></div>
      <div><Link href="#/services" onFollow={follow}>All services</Link><Box variant="small" display="block" color="text-body-secondary">What this console can open.</Box></div>
      <div><Link href={classicHref("")}>Classic Vyomi console</Link><Box variant="small" display="block" color="text-body-secondary">Services without a v4 page yet.</Box></div>
    </SpaceBetween>
  );
}

function Security() {
  return (
    <Box textAlign="center" color="text-body-secondary" padding={{ top: "l" }}>
      <Box variant="strong" color="inherit">No security data</Box>
      <Box variant="p" color="inherit">Security Hub findings are not simulated in Vyomi.</Box>
    </Box>
  );
}

function HealthBody({ probes }) {
  const rows = probes.data || [];
  const down = rows.filter((r) => !r.ok);
  if (probes.loading) return <StatusIndicator type="loading">Checking services</StatusIndicator>;
  return (
    <SpaceBetween size="m">
      <div style={{ display: "flex", justifyContent: "space-between" }}><div><Box variant="awsui-key-label">Open issues</Box><Box fontSize="heading-xl">{down.length}</Box></div><Box variant="small" color="text-body-secondary">Now</Box></div>
      <div style={{ display: "flex", justifyContent: "space-between" }}><div><Box variant="awsui-key-label">Services responding</Box><Box fontSize="heading-xl">{rows.length - down.length}/{rows.length}</Box></div><Box variant="small" color="text-body-secondary">Live check</Box></div>
      {down.map((r) => <StatusIndicator key={r.id} type="error">{byId[r.id]?.title || r.id}: {r.error}</StatusIndicator>)}
    </SpaceBetween>
  );
}

export default function Home() {
  const [items, setItems] = useState(() => (store.get("home.boardVersion", 0) === LAYOUT_VERSION ? store.get("home.board", DEFAULT_ITEMS) : DEFAULT_ITEMS));
  const [palette, setPalette] = useState(false);
  const [banner, setBanner] = useState(() => !store.get("home.bannerDismissed", false));
  const probes = useProbes();
  const save = (xs) => { setItems(xs); store.set("home.board", xs); store.set("home.boardVersion", LAYOUT_VERSION); };
  const content = {
    recent: <RecentBody />, welcome: <WelcomeBody />, health: <HealthBody probes={probes} />, cost: <Cost />,
    resources: <ResourcesBody probes={probes} />, activity: <ActivityBody />, explore: <Explore />, security: <Security />, connect: <ConnectBody />,
  };
  const footers = {
    recent: null,
    health: <Box textAlign="center"><Link href="#/" onFollow={(e) => { e.preventDefault(); probes.reload(); }}>Refresh health</Link></Box>,
    cost: <Box textAlign="center" color="text-body-secondary" variant="small">Billing and Cost Management is not simulated</Box>,
  };
  const actions = { recent: <Button href="#/services" onFollow={follow}>All services</Button> };
  const renderItem = (item, a) => {
    const id = item.data.id;
    return (
      <BoardItem
        i18nStrings={itemI18n}
        header={<Header variant="h2" actions={actions[id]}>{CATALOG[id].title}</Header>}
        settings={a && <ButtonDropdown variant="icon" ariaLabel={`${CATALOG[id].title} settings`} items={[{ id: "remove", text: "Remove" }]} onItemClick={() => a.removeItem()} />}
        footer={footers[id]}
      >
        {content[id]}
      </BoardItem>
    );
  };
  const hidden = Object.keys(CATALOG).filter((id) => !items.some((i) => i.id === id))
    .map((id) => ({ id, columnSpan: CATALOG[id].columnSpan, rowSpan: CATALOG[id].rowSpan, data: { id } }));

  return (
    <ContentLayout header={
      <SpaceBetween size="m">
        {banner && (
          <Alert type="info" dismissible onDismiss={() => { setBanner(false); store.set("home.bannerDismissed", true); }} header={vy("Welcome to the Vyomi AWS console")}>
            Everything here runs against your local Vyomi simulator, using the same native APIs your SDKs and CLI call. Features Vyomi doesn't simulate are marked.
          </Alert>
        )}
        <Header variant="h1" actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => save(DEFAULT_ITEMS)}>Reset to default layout</Button>
            <Button variant="primary" iconName="add-plus" onClick={() => setPalette((v) => !v)}>Add widgets</Button>
          </SpaceBetween>
        }>Console Home</Header>
      </SpaceBetween>
    }>
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Board items={items} renderItem={renderItem} onItemsChange={({ detail }) => save(detail.items)} i18nStrings={boardI18n}
            empty={<Box textAlign="center" padding="xxl" color="text-body-secondary"><b>No widgets</b><Box variant="p" color="inherit">Add widgets to your Console Home.</Box><Button onClick={() => save(DEFAULT_ITEMS)}>Reset to default layout</Button></Box>} />
          <Box textAlign="right" margin={{ top: "l" }}><Button iconName="add-plus" onClick={() => setPalette(true)}>Add widgets</Button></Box>
        </div>
        {palette && (
          <div style={{ width: 320, position: "sticky", top: 56 }}>
            <Container header={<Header variant="h2" actions={<Button variant="icon" iconName="close" ariaLabel="Close" onClick={() => setPalette(false)} />} description="Drag a widget onto the board.">Add widgets</Header>}>
              {hidden.length ? (
                <ItemsPalette items={hidden} i18nStrings={paletteI18n}
                  renderItem={(item) => <BoardItem i18nStrings={itemI18n} header={<Header variant="h3">{CATALOG[item.data.id].title}</Header>}><Box variant="small" color="text-body-secondary">Drag onto the board</Box></BoardItem>} />
              ) : <Box color="text-body-secondary">All widgets are on the board.</Box>}
            </Container>
          </div>
        )}
      </div>
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
                  <SvcLink s={s} size={32} fontSize="heading-s" />
                  <Box variant="small" display="block" color="text-body-secondary" margin={{ top: "xxxs", left: "xxxl" }}>{s.description}{!s.load ? " · classic console" : ""}</Box>
                </div>
              ))}
            </ColumnLayout>
          </Container>
        ))}
      </SpaceBetween>
    </ContentLayout>
  );
}
