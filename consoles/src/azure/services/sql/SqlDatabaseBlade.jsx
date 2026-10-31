/* SQL database resource blade: left resource menu + panels. Overview, Tags, Activity log,
 * Query editor, Compute + storage, Connection strings, Properties, Locks, Transparent data
 * encryption, Identity, Automatic tuning, Performance recommendations and Export template
 * are backed by native ARM / the azure-sql data-plane wire; everything else in the menu is
 * an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Play20Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtBytes, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import ComputeStorageFields from "./ComputeStorageFields.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "gettingstarted", label: "Getting started" },
  { id: "queryeditor", label: "Query editor (preview)" },
  { id: "mirrorfabric", label: "Mirror database in Fabric" },
  { group: "Settings", items: [{ id: "computestorage", label: "Compute + storage" }, { id: "connectionstrings", label: "Connection strings" }, { id: "maintenance", label: "Maintenance" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" }] },
  { group: "Data management", items: [{ id: "replicas", label: "Replicas" }, { id: "syncdatabases", label: "Sync to other databases" }] },
  { group: "Integrations", items: [{ id: "streamanalytics", label: "Stream analytics (preview)" }, { id: "addazuresearch", label: "Add Azure Search" }] },
  { group: "Power Platform", items: [{ id: "powerbi", label: "Power BI" }, { id: "powerapps", label: "Power Apps" }, { id: "powerautomate", label: "Power Automate" }] },
  { group: "Security", items: [{ id: "auditing", label: "Auditing" }, { id: "datadiscovery", label: "Data Discovery & Classification" }, { id: "datamasking", label: "Dynamic Data Masking" }, { id: "defender", label: "Microsoft Defender for Cloud" }, { id: "tde", label: "Transparent data encryption" }, { id: "ledger", label: "Ledger" }, { id: "identity", label: "Identity" }] },
  { group: "Intelligent Performance", items: [{ id: "perfoverview", label: "Performance overview" }, { id: "perfrecommendations", label: "Performance recommendations" }, { id: "queryperfinsight", label: "Query Performance Insight" }, { id: "autotuning", label: "Automatic tuning" }] },
  { group: "Monitoring", items: [{ id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }, { id: "databasewatcher", label: "Database watcher" }] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "resourcehealth", label: "Resource health" }, { id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  diagnose: "Diagnose and solve problems",
  mirrorfabric: "Mirroring this database into Microsoft Fabric",
  maintenance: "Maintenance event history",
  replicas: "Geo-replication / active geo-replicas",
  syncdatabases: "Data Sync between databases",
  streamanalytics: "Azure Stream Analytics integration",
  addazuresearch: "Azure AI Search integration",
  powerbi: "Power BI integration",
  powerapps: "Power Apps integration",
  powerautomate: "Power Automate integration",
  auditing: "SQL auditing to a storage account / Log Analytics / Event Hub",
  datadiscovery: "Data Discovery & Classification",
  datamasking: "Dynamic Data Masking rules",
  defender: "Microsoft Defender for Cloud",
  ledger: "Database ledger",
  perfoverview: "Performance overview dashboards",
  queryperfinsight: "Query Performance Insight",
  alerts: "Alert rules",
  metrics: "Database metrics charts",
  diagnosticsettings: "Diagnostic settings",
  logs: "Log Analytics queries",
  databasewatcher: "Database watcher",
  tasks: "Tasks",
  resourcehealth: "Resource health",
  support: "Support + Troubleshooting",
};

export default function SqlDatabaseBlade({ params }) {
  const { rg, server, db } = params;
  const panel = params.panel || "overview";
  const dbData = useAsync(() => api.getDatabase(rg, server, db), [rg, server, db]);
  const self = `#/sql/${encodeURIComponent(rg)}/${encodeURIComponent(server)}/${encodeURIComponent(db)}`;
  useEffect(() => { if (dbData.data) remember({ name: db, type: "SQL database", href: self }); }, [!!dbData.data, self]);

  let body;
  if (dbData.loading && !dbData.data) body = <Loading />;
  else if (dbData.error) body = <><ErrorBar error={dbData.error} title="Failed to load the database" /><Link href="#/sql">Back to SQL databases</Link></>;
  else {
    const a = dbData.data, reload = dbData.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      tags: () => <Tags a={a} reload={reload} />,
      gettingstarted: () => <GettingStarted self={self} />,
      queryeditor: () => <QueryEditor a={a} />,
      computestorage: () => <ComputeStorage a={a} reload={reload} />,
      connectionstrings: () => <ConnectionStrings a={a} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      tde: () => <Tde a={a} reload={reload} />,
      identity: () => <IdentityPanel a={a} reload={reload} />,
      autotuning: () => <AutomaticTuning a={a} reload={reload} />,
      perfrecommendations: () => <PerformanceRecommendations a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{LABEL[panel] || panel}</div>
        <NotSimulated feature={NS_NOTES[panel] || `The ${LABEL[panel] || panel} panel`} />
      </>
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? db : `${db} | ${LABEL[panel] || panel}`} subtitle="SQL database" glyph={<Glyph id="sql" />} closeHref="#/sql"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [tab, setTab] = useState("getstarted");
  const [del, setDel] = useState(false);
  const [gap, setGap] = useState(null); // "Copy" | "Restore" | "Export" | "Connect with..." | "Feedback"
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton onClick={() => setGap("Copy")}>Copy</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Restore")}>Restore</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export")}>Export</ToolbarButton>
        <ToolbarButton onClick={() => navigate("sql", "servers", a.resourceGroup, a.server, "networking")}>Set server firewall</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Connect with...")}>Connect with...</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Status", a.properties?.status || "Online"],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Server name", <Link href={`#/sql/servers/${encodeURIComponent(a.resourceGroup)}/${encodeURIComponent(a.server)}`}>{api.serverFqdn(a.server)}</Link>],
        ]}
        right={[
          ["Elastic pool", "None"],
          ["Connection strings", <Link href={`${self}/connectionstrings`}>Show database connection strings</Link>],
          ["Pricing tier", a.sku ? `${a.sku.tier}${a.sku.capacity ? ` (${a.sku.capacity} ${a.sku.name?.includes("_S_") || a.sku.name?.includes("_S") ? "vCores, Serverless" : "vCores"})` : ""}` : "--"],
          ["Earliest restore point", "Not available"],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="getstarted">Getting started</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="properties">Properties</Tab>
        <Tab value="features">Features</Tab>
        <Tab value="notifications">Notifications</Tab>
        <Tab value="integrations">Integrations</Tab>
        <Tab value="tutorials">Tutorials</Tab>
      </TabList>
      {tab === "getstarted" && <div style={{ marginTop: 12 }}><GettingStarted self={self} /></div>}
      {tab === "monitoring" && <NotSimulatedContainer feature="Database monitoring (DTU/vCore, storage and connection charts)" />}
      {tab === "properties" && <Properties a={a} />}
      {tab === "features" && <NotSimulatedContainer feature="The features overview" />}
      {tab === "notifications" && <NotSimulatedContainer feature="Notifications" />}
      {tab === "integrations" && <NotSimulatedContainer feature="Integrations" />}
      {tab === "tutorials" && <NotSimulatedContainer feature="Tutorials" />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="SQL database" names={[a.name]}
        onConfirm={async () => {
          await api.deleteDatabase(a.resourceGroup, a.server, a.name);
          await api.dropDataPlane(a.server, a.name);
          forget(self);
          notify.success(`Database '${a.name}' was deleted.`, "Delete succeeded");
          navigate("sql");
        }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : gap === "Connect with..." ? "Launching an external SQL client" : `${gap} a database`} />
            </DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function GettingStarted({ self }) {
  return (
    <>
      <p style={{ fontSize: 13 }}>Use the Query editor to run T-SQL against this database, or copy a connection string to connect from your application.</p>
      <Link href={`${self}/queryeditor`}>Query editor (preview)</Link>{" · "}<Link href={`${self}/connectionstrings`}>Connection strings</Link>
    </>
  );
}

function Properties({ a }) {
  const p = a.properties || {};
  return (
    <div className="vy-props" style={{ marginTop: 12 }}>
      <KV label="Status" value={p.status || "Online"} />
      <KV label="Server name" value={api.serverFqdn(a.server)} />
      <KV label="Collation" value={p.collation} />
      <KV label="Creation date" value={p.creationDate ? fmtDate(p.creationDate) : "--"} />
      <KV label="Max size" value={p.maxSizeBytes ? fmtBytes(p.maxSizeBytes) : "--"} />
      <KV label="Pricing tier" value={a.sku?.tier} />
      <KV label="Location" value={locationLabel(a.location)} />
      <KV label="Resource ID" value={a.id} />
    </div>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
function TagRows({ tags, onChange }) {
  const upd = (i, k, v) => {
    const xs = tags.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "" });
    onChange(xs);
  };
  return (
    <Table size="small" aria-label="Tags" style={{ maxWidth: 760 }}>
      <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
      <TableBody>
        {tags.map((t, i) => (
          <TableRow key={i}>
            <TableCell><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></TableCell>
            <TableCell><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></TableCell>
            <TableCell>SQL database</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const apply = async () => {
    setBusy(true);
    try {
      const { id, name, type, resourceGroup, server, ...rest } = a;
      await api.createDatabase(a.resourceGroup, a.server, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={rows} onChange={setRows} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={async () => { setRows([{ name: "", value: "" }]); await apply(); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Compute + storage ────────────────────────────────────────────────────────────────────
function ComputeStorage({ a, reload }) {
  const notify = useNotify();
  const init = () => {
    const sku = a.sku || {}, p = a.properties || {};
    const tier = sku.tier || "GeneralPurpose";
    const serverless = (sku.name || "").includes("_S_") || (sku.name || "").includes("_S");
    return {
      tier, serverless, maxVCores: sku.capacity || 2, minVCores: p.minCapacity || 0.5,
      autoPause: (p.autoPauseDelay ?? -1) >= 0,
      days: p.autoPauseDelay > 0 ? Math.floor(p.autoPauseDelay / 1440) : 0,
      hours: p.autoPauseDelay > 0 ? Math.floor((p.autoPauseDelay % 1440) / 60) : 1,
      minutes: p.autoPauseDelay > 0 ? p.autoPauseDelay % 60 : 0,
      dataMaxSizeGb: p.maxSizeBytes ? Math.round(p.maxSizeBytes / (1024 * 1024 * 1024)) : 32,
      zoneRedundant: !!p.zoneRedundant,
    };
  };
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [a]);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const save = async () => {
    setBusy(true);
    try {
      await api.updateDatabase(a.resourceGroup, a.server, a.name, api.computeStorageBody(f));
      notify.success(`Compute + storage for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving compute + storage failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Compute + storage</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Compute + storage commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Apply</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.sql.compute_storage" title="Compute + storage">
        <div style={{ marginTop: 12 }}><ComputeStorageFields f={f} set={set} /></div>
      </CapabilityContainer>
    </>
  );
}

// ── Connection strings ────────────────────────────────────────────────────────────────────
function ConnectionStrings({ a }) {
  const [tab, setTab] = useState("ADO.NET");
  const cs = api.connectionStrings(a.server, a.name);
  const current = cs[tab];
  return (
    <>
      <div className="vy-panel-title">Connection strings</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Connection strings tabs">
        {Object.keys(cs).map((t) => <Tab key={t} value={t}>{t}</Tab>)}
      </TabList>
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
        <section className="vy-section"><h3>{tab} (SQL authentication)</h3>
          <Textarea readOnly value={current.sql} style={{ width: "100%", minHeight: 80, fontFamily: "monospace" }} aria-label="Connection string" /></section>
        <section className="vy-section"><h3>{tab} (Microsoft Entra passwordless authentication)</h3>
          <Textarea readOnly value={current.entra} style={{ width: "100%", minHeight: 80, fontFamily: "monospace" }} aria-label="Connection string" /></section>
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this database) ────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const resPath = api.databasePath(a.resourceGroup, a.server, a.name);
  const { data, loading, error, reload } = useAsync(() => api.listLocks(resPath), [resPath]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows.map((r) => ({ ...r, name: r.id.split("/").pop() }))} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Subscription")}>Subscription</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Resource group")}>Resource group</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteLock(resPath, r.name);
          notify.success(`Deleted ${sel.length} lock${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="locks.csv"
        columns={[
          { key: "name", label: "Lock name" },
          { key: "type", label: "Lock type", value: (r) => (r.properties?.level === "ReadOnly" ? "Read-only" : "Delete") },
          { key: "scope", label: "Scope", value: () => a.name },
          { key: "notes", label: "Notes", value: (r) => r.properties?.notes || "--" },
        ]}
      />
      <AddLockDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, level, notes) => { await api.putLock(resPath, name, { properties: { level, notes } }); reload(); }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `Locks scoped to the ${(gap || "").toLowerCase()}`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function AddLockDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [type, setType] = useState("Delete");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-zA-Z0-9._-]{1,90}$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name, type === "Read-only" ? "ReadOnly" : "CanNotDelete", notes);
      notify.success(`Lock '${name}' was added.`, "Lock added");
      setName(""); setNotes(""); setType("Delete"); onClose();
    } catch (e) { notify.error(e, "Failed to add lock"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add lock">
        <DialogBody>
          <DialogTitle>Add lock</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Lock name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Lock name" /></Field>
              <Field label="Lock type" required><Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type"><option>Read-only</option><option>Delete</option></Select></Field>
              <Field label="Notes"><Textarea value={notes} onChange={(_, d) => setNotes(d.value)} aria-label="Notes" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>OK</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Activity log ──────────────────────────────────────────────────────────────────────
function ActivityLog({ a }) {
  const resPath = api.databasePath(a.resourceGroup, a.server, a.name);
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(resPath), [resPath]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  const GAPS = ["Edit columns", "Export Activity Logs", "Download as CSV", "Insights", "Feedback", "Pin current filters", "Reset filters"];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Activity log</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton onClick={reload}>Activity</ToolbarButton>
        {GAPS.map((g) => <ToolbarButton key={g} onClick={() => setGap(g)}>{g}</ToolbarButton>)}
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <ErrorBar error={error} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `${gap} on the activity log`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <table className="vy-grid">
        <thead><tr><th>Operation name</th><th>Status</th><th>Time</th><th>Time stamp</th><th>Subscription</th><th>Event initiated by</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={6}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.id}>
              <td>{r.operationName?.localizedValue || r.operationName?.value}</td>
              <td>{r.status?.localizedValue || r.status?.value}</td>
              <td>{fmtDate(r.eventTimestamp)}</td>
              <td>{r.eventTimestamp}</td>
              <td>{r.subscriptionId}</td>
              <td>{r.caller}</td>
            </tr>
          )) : <tr><td colSpan={6} className="vy-muted">No events to display</td></tr>}
        </tbody>
      </table>
    </>
  );
}

// ── Transparent data encryption ──────────────────────────────────────────────────────
function Tde({ a, reload }) {
  const notify = useNotify();
  const tde = a.properties?.transparentDataEncryption || {};
  const enabled = tde.state !== "Disabled";
  const hasIdentity = a.identity?.type === "SystemAssigned" && !!a.identity?.principalId;
  const init = () => ({ value: enabled ? "ON" : "OFF", keyType: tde.keyVaultKeyUri ? "cmk" : "smk", keyName: tde.keyVaultKeyUri ? tde.keyVaultKeyUri.split("/keys/")[1]?.split("/")[0] || "" : "" });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [a]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const invalid = f.keyType === "cmk" && (!hasIdentity || !f.keyName);
  const save = async () => {
    setBusy(true);
    try {
      const transparentDataEncryption = { state: f.value === "ON" ? "Enabled" : "Disabled" };
      if (f.keyType === "cmk" && f.keyName) transparentDataEncryption.keyVaultKeyUri = `https://vault.vault.azure.net/keys/${f.keyName}`;
      await api.updateDatabase(a.resourceGroup, a.server, a.name, { properties: { transparentDataEncryption } });
      notify.success(`Transparent data encryption for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Transparent data encryption</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Transparent data encryption commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy || invalid} onClick={save}>Save</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.sql.transparent_data_encryption" title="Data encryption">
        <RadioGroup layout="horizontal" value={f.value} onChange={(_, d) => setF((x) => ({ ...x, value: d.value }))} aria-label="Data encryption">
          <Radio value="ON" label="ON" /><Radio value="OFF" label="OFF" />
        </RadioGroup>
        <div style={{ marginTop: 16 }}>
          <div className="vy-muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Key management</div>
          <RadioGroup layout="horizontal" value={f.keyType} onChange={(_, d) => setF((x) => ({ ...x, keyType: d.value }))} aria-label="Key management">
            <Radio value="smk" label="Service-managed key" />
            <Radio value="cmk" label="Customer-managed key" />
          </RadioGroup>
          {f.keyType === "cmk" && (
            <>
              <Field label="Key Vault key name" required style={{ maxWidth: 360, marginTop: 8 }}>
                <Input value={f.keyName} onChange={(_, d) => setF((x) => ({ ...x, keyName: d.value }))} aria-label="Key Vault key name" />
              </Field>
              {!hasIdentity && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>Requires a system-assigned managed identity — turn it on under Identity first.</div>}
            </>
          )}
        </div>
      </CapabilityContainer>
    </>
  );
}

// ── Identity ──────────────────────────────────────────────────────────────────────────
function IdentityPanel({ a, reload }) {
  const notify = useNotify();
  const type = a.identity?.type || "None";
  const [value, setValue] = useState(type);
  const [busy, setBusy] = useState(false);
  useEffect(() => setValue(type), [type]);
  const dirty = value !== type;
  const save = async () => {
    setBusy(true);
    try {
      const identity = value === "None" ? { type: "None" } : { type: value, principalId: a.identity?.principalId || crypto.randomUUID(), tenantId: "00000000-0000-0000-0000-000000000000" };
      await api.updateDatabase(a.resourceGroup, a.server, a.name, { identity });
      notify.success(`Identity for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving identity failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Identity</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Identity commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setValue(type)}>Discard</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.sql.identity" title="System assigned managed identity">
        <RadioGroup layout="horizontal" value={value === "SystemAssigned" ? "On" : "Off"} onChange={(_, d) => setValue(d.value === "On" ? "SystemAssigned" : "None")} aria-label="Status">
          <Radio value="On" label="On" /><Radio value="Off" label="Off" />
        </RadioGroup>
        {value === "SystemAssigned" && <div className="vy-props" style={{ marginTop: 8 }}><KV label="Object (principal) ID" value={a.identity?.principalId || "(assigned on save)"} /></div>}
      </CapabilityContainer>
      <NotSimulatedContainer title="User assigned managed identity" feature="Attaching a user-assigned managed identity" />
    </>
  );
}

// ── Automatic tuning ──────────────────────────────────────────────────────────────────
function AutomaticTuning({ a, reload }) {
  const notify = useNotify();
  const opts = a.properties?.automaticTuning?.options || {};
  const init = () => ({ forceLastGoodPlan: opts.forceLastGoodPlan?.desiredState !== "Off", createIndex: opts.createIndex?.desiredState !== "Off", dropIndex: opts.dropIndex?.desiredState !== "Off" });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [a]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const save = async () => {
    setBusy(true);
    try {
      const options = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, { desiredState: v ? "On" : "Off" }]));
      await api.updateDatabase(a.resourceGroup, a.server, a.name, { properties: { automaticTuning: { desiredState: "Custom", options } } });
      notify.success(`Automatic tuning for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving automatic tuning failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Automatic tuning</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Automatic tuning commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Apply</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.sql.automatic_tuning" title="Automatic tuning options">
        <Checkbox label="FORCE LAST GOOD PLAN" checked={f.forceLastGoodPlan} onChange={(_, d) => setF((x) => ({ ...x, forceLastGoodPlan: !!d.checked }))} />
        <Checkbox label="CREATE INDEX" checked={f.createIndex} onChange={(_, d) => setF((x) => ({ ...x, createIndex: !!d.checked }))} />
        <Checkbox label="DROP INDEX" checked={f.dropIndex} onChange={(_, d) => setF((x) => ({ ...x, dropIndex: !!d.checked }))} />
      </CapabilityContainer>
    </>
  );
}

// ── Performance recommendations (real CREATE_INDEX suggestions from the query log) ─────
function PerformanceRecommendations({ a }) {
  const notify = useNotify();
  const recs = useAsync(() => api.listRecommendations(a.server, a.name), [a.server, a.name]);
  const [applying, setApplying] = useState(null);
  const apply = async (rec) => {
    setApplying(rec.id);
    try {
      await api.applyRecommendation(a.server, a.name, rec.id);
      notify.success(`Created an index on ${rec.table}(${rec.column}).`, "Recommendation applied");
      recs.reload();
    } catch (e) { notify.error(e, "Applying the recommendation failed"); }
    finally { setApplying(null); }
  };
  return (
    <>
      <div className="vy-panel-title">Performance recommendations</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Performance recommendations commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={recs.reload}>Refresh</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.sql.automatic_tuning" title="Recommendations">
        <ErrorBar error={recs.error} title="Failed to load recommendations" />
        {recs.loading && !recs.data ? <Loading /> : !recs.data?.length ? (
          <div className="vy-muted">No recommendations right now. Vyomi looks for WHERE-equality lookups in the Query editor's recent activity that need a table scan — run some queries first.</div>
        ) : (
          <Table aria-label="Performance recommendations">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Recommendation</TableHeaderCell>
                <TableHeaderCell>Type</TableHeaderCell>
                <TableHeaderCell>Impacted queries</TableHeaderCell>
                <TableHeaderCell></TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recs.data.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>Create index on {r.table}({r.column})</TableCell>
                  <TableCell>Create index</TableCell>
                  <TableCell>{r.impactedQueries}</TableCell>
                  <TableCell>
                    <Button size="small" disabled={applying === r.id} onClick={() => apply(r)}>Apply</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CapabilityContainer>
    </>
  );
}

// ── Query editor (preview) ────────────────────────────────────────────────────────────
function QueryEditor({ a }) {
  const notify = useNotify();
  const server = useAsync(() => api.getServer(a.resourceGroup, a.server), [a.resourceGroup, a.server]);
  const [connected, setConnected] = useState(false);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const [sql, setSql] = useState("SELECT 1 AS hello;");
  const [result, setResult] = useState(null);
  const [queryError, setQueryError] = useState(null);
  const [running, setRunning] = useState(false);
  const tables = useAsync(() => (connected ? api.listTables(a.server, a.name).then((r) => r.rows.map((x) => x[0])) : Promise.resolve([])), [connected]);
  const views = useAsync(() => (connected ? api.listViews(a.server, a.name).then((r) => r.rows.map((x) => x[0])) : Promise.resolve([])), [connected]);

  const connectSql = async () => {
    const admin = server.data?.properties?.administratorLogin;
    if (admin && (login !== admin || password !== server.data?.properties?.administratorLoginPassword)) {
      setAuthError("Login failed for user " + login); return;
    }
    setConnecting(true);
    try { await api.ensureDataPlane(a.server, a.name); setConnected(true); setAuthError(null); }
    catch (e) { setAuthError(e.message); }
    finally { setConnecting(false); }
  };
  const connectEntra = async () => {
    setConnecting(true);
    try { await api.ensureDataPlane(a.server, a.name); setConnected(true); }
    finally { setConnecting(false); }
  };
  const run = async () => {
    setRunning(true); setQueryError(null);
    try { setResult(await api.runQuery(a.server, a.name, sql)); }
    catch (e) { setQueryError(e); setResult(null); }
    finally { setRunning(false); }
  };

  if (!connected) {
    return (
      <>
        <div className="vy-panel-title">Query editor (preview)</div>
        <div style={{ display: "flex", gap: 24, marginTop: 12 }}>
          <section className="vy-section" style={{ maxWidth: 360 }}>
            <h3>SQL server authentication</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Field label="Login"><Input value={login} onChange={(_, d) => setLogin(d.value)} aria-label="Login" /></Field>
              <Field label="Password"><Input type="password" value={password} onChange={(_, d) => setPassword(d.value)} aria-label="Password" /></Field>
              {authError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12 }}>{authError}</div>}
              <Button appearance="primary" disabled={connecting} onClick={connectSql}>OK</Button>
            </div>
          </section>
          <section className="vy-section">
            <h3>Microsoft Entra authentication</h3>
            <Button disabled={connecting} onClick={connectEntra}>Continue as uic@vyomi.local</Button>
          </section>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="vy-panel-title">Query editor (preview)</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Query editor commands">
        <ToolbarButton icon={<Play20Regular />} disabled={running} onClick={run}>Run</ToolbarButton>
        <ToolbarButton disabled>Cancel</ToolbarButton>
        <ToolbarButton icon={<Save20Regular />} disabled>Save query</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled>Export data as</ToolbarButton>
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
        <nav style={{ width: 200, flex: "none" }}>
          <div className="vy-muted" style={{ fontSize: 12, fontWeight: 600 }}>Tables</div>
          <ul style={{ margin: "4px 0 12px", paddingLeft: 16, fontSize: 13 }}>
            {(tables.data || []).map((t) => <li key={t}><Link as="button" onClick={() => setSql(`SELECT * FROM ${t};`)}>{t}</Link></li>)}
            {!tables.data?.length && <li className="vy-muted">No tables</li>}
          </ul>
          <div className="vy-muted" style={{ fontSize: 12, fontWeight: 600 }}>Views</div>
          <ul style={{ margin: "4px 0 12px", paddingLeft: 16, fontSize: 13 }}>
            {(views.data || []).map((v) => <li key={v}><Link as="button" onClick={() => setSql(`SELECT * FROM ${v};`)}>{v}</Link></li>)}
            {!views.data?.length && <li className="vy-muted">No views</li>}
          </ul>
          <div className="vy-muted" style={{ fontSize: 12, fontWeight: 600 }}>Stored Procedures</div>
          <NotSimulated feature="Stored procedures (T-SQL procedural objects)" />
        </nav>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
          <Textarea value={sql} onChange={(_, d) => setSql(d.value)} aria-label="SQL query" style={{ width: "100%", minHeight: 120, fontFamily: "monospace" }} />
          <ErrorBar error={queryError} title="Query failed" />
          {result && (
            <Table size="small" aria-label="Query results">
              <TableHeader><TableRow>{result.columns.map((c) => <TableHeaderCell key={c}>{c}</TableHeaderCell>)}</TableRow></TableHeader>
              <TableBody>
                {result.rows.map((row, i) => <TableRow key={i}>{row.map((v, j) => <TableCell key={j}>{String(v)}</TableCell>)}</TableRow>)}
              </TableBody>
            </Table>
          )}
          {result && !result.rows.length && <p className="vy-muted" style={{ fontSize: 13 }}>{result.rowCount} row(s) affected.</p>}
        </div>
      </div>
    </>
  );
}

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { databaseName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.Sql/servers/databases", apiVersion: api.API_VERSION, name: params ? `[concat('${a.server}/', parameters('databaseName'))]` : `${a.server}/${a.name}`, location: a.location, sku: a.sku, properties: a.properties }],
  };
  const text = JSON.stringify(template, null, 2);
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    el.download = `${a.name}.json`;
    document.body.appendChild(el); el.click(); el.remove();
  };
  return (
    <>
      <div className="vy-panel-title">Export template</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={download}>Download</ToolbarButton>
        <ToolbarButton disabled>Add to library (preview)</ToolbarButton>
        <ToolbarButton disabled>Deploy</ToolbarButton>
        <ToolbarButton disabled>Visualize template</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab><Tab value="bicep">Bicep</Tab><Tab value="terraform">Terraform</Tab>
      </TabList>
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Template</h3>
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        {tab === "arm" && <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
        {tab !== "arm" && <NotSimulatedContainer feature={`${tab === "bicep" ? "Bicep" : "Terraform"} template export`} />}
      </section>
    </>
  );
}
