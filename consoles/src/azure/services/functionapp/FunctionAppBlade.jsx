/* Function App resource blade: left resource menu + panels. Overview, Tags, App keys,
 * Environment variables, Scale and concurrency, Locks, Export template and Access control
 * (role assignments/roles) are backed by native ARM calls; everything else in the menu is an
 * honest NotSimulated panel (Vyomi has no diagnostics/telemetry/identity backend for them). */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import {
  ArrowClockwise20Regular, ArrowUpload20Regular, Delete20Regular, Dismiss20Regular, DocumentArrowDown20Regular, Pause20Regular,
  PlayCircle20Regular, Save20Regular,
} from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { armType, locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Essentials, fmtDate, Glyph, InfoBar, KV, Loading, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { ResourceRecommendations } from "../defender/Pages.jsx";

const ROLE_ASSIGNMENTS = armType("Microsoft.Authorization", "roleAssignments", "2022-04-01");
const ROLE_DEFINITIONS = armType("Microsoft.Authorization", "roleDefinitions", "2022-04-01");

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activity-log", label: "Activity log" },
  { id: "access-control-iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose-and-solve-problems", label: "Diagnose and solve problems" },
  { id: "microsoft-defender-for-cloud", label: "Microsoft Defender for Cloud" },
  { id: "events-preview", label: "Events (preview)" },
  { id: "log-stream", label: "Log stream" },
  { id: "resource-visualizer", label: "Resource visualizer" },
  { group: "Functions", items: [{ id: "app-keys", label: "App keys" }, { id: "app-files", label: "App files" }] },
  { group: "Deployment", items: [{ id: "deployment-center", label: "Deployment Center" }] },
  { group: "Settings", items: [
    { id: "environment-variables", label: "Environment variables" }, { id: "configuration", label: "Configuration" },
    { id: "authentication", label: "Authentication" }, { id: "application-insights", label: "Application Insights" },
    { id: "identity", label: "Identity" }, { id: "custom-domains", label: "Custom domains" }, { id: "certificates", label: "Certificates" },
    { id: "networking", label: "Networking" }, { id: "scale-and-concurrency", label: "Scale and concurrency" },
    { id: "service-connector", label: "Service Connector" }, { id: "locks", label: "Locks" },
  ] },
  { group: "Development Tools", items: [{ id: "advanced-tools", label: "Advanced Tools" }, { id: "extensions", label: "Extensions" }] },
  { group: "API", items: [{ id: "api-management", label: "API Management" }, { id: "cors", label: "CORS" }] },
  { group: "Monitoring", items: [
    { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "logs", label: "Logs" },
    { id: "advisor-recommendations", label: "Advisor recommendations" }, { id: "health-check", label: "Health check" },
    { id: "diagnostic-settings", label: "Diagnostic settings" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "export-template", label: "Export template" }] },
  { group: "Support + troubleshooting", items: [{ id: "resource-health", label: "Resource health" }, { id: "new-support-request", label: "New support request" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
// Panels backed by a real native call, grouped into one capability id each (see
// core/capabilities/azure/functionapp.json). The 7 left below in GAPS genuinely need something
// physically beyond a local simulator (a real external provider, real dedicated infrastructure,
// real human staff) — CapabilityContainer renders their honest Not-simulated panel itself from
// the registry's limitations text.
const GAPS = {
  "deployment-center": "azure.functionapp.deploymentcenter",
  "service-connector": "azure.functionapp.serviceconnector",
  "advanced-tools": "azure.functionapp.advancedtools",
  "extensions": "azure.functionapp.extensions",
  "api-management": "azure.functionapp.apimanagement",
  "tasks": "azure.functionapp.tasks",
  "new-support-request": "azure.functionapp.newsupportrequest",
};

export default function FunctionAppBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const site = useAsync(() => api.getFunctionApp(rg, name), [rg, name]);
  const self = `#/functionapp/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (site.data) remember({ name, type: "Function App", href: self }); }, [!!site.data, self]);

  let body;
  if (site.loading && !site.data) body = <Loading />;
  else if (site.error) body = <><ErrorBar error={site.error} title="Failed to load the function app" /><Link href="#/functionapp">Back to Function App</Link></>;
  else {
    const a = site.data, reload = site.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      "microsoft-defender-for-cloud": () => <ResourceRecommendations resourceId={a.id} />,
      tags: () => <Tags a={a} reload={reload} />,
      "app-keys": () => <AppKeys a={a} />,
      "environment-variables": () => <EnvironmentVariables a={a} />,
      "scale-and-concurrency": () => <ScaleAndConcurrency a={a} reload={reload} />,
      "locks": () => <Locks a={a} />,
      "access-control-iam": () => <AccessControl a={a} />,
      "export-template": () => <ExportTemplate a={a} />,
      "activity-log": () => <ActivityLog a={a} />,
      "configuration": () => <Placeholder name={a.name} id="configuration" extra={<p style={{ fontSize: 13 }}>App settings and connection strings moved to <Link href={`${self}/environment-variables`}>Environment variables</Link>.</p>} />,
      "identity": () => <Identity a={a} reload={reload} />,
      "custom-domains": () => <CustomDomains a={a} />,
      "certificates": () => <Certificates a={a} />,
      "cors": () => <Cors a={a} reload={reload} />,
      "networking": () => <Networking a={a} reload={reload} />,
      "authentication": () => <Authentication a={a} />,
      "diagnostic-settings": () => <DiagnosticSettings a={a} />,
      "metrics": () => <Metrics a={a} />,
      "logs": () => <LogsPanel a={a} />,
      "log-stream": () => <LogStream a={a} />,
      "events-preview": () => <EventsPreview a={a} />,
      "alerts": () => <Alerts a={a} />,
      "health-check": () => <HealthCheckPanel a={a} reload={reload} />,
      "advisor-recommendations": () => <Advisor a={a} />,
      "diagnose-and-solve-problems": () => <DiagnoseAndSolve a={a} />,
      "resource-health": () => <ResourceHealthPanel a={a} />,
      "resource-visualizer": () => <ResourceVisualizer a={a} />,
      "app-files": () => <AppFiles a={a} />,
      "application-insights": () => <ApplicationInsights a={a} />,
    }[panel];
    body = P ? P() : (GAPS[panel] ? <GapPanel name={a.name} id={panel} capId={GAPS[panel]} /> : <Placeholder name={a.name} id={panel} />);
  }

  return (
    <ResourceBlade title={name} subtitle="Function App" glyph={<Glyph id="functionapp" />} closeHref="#/functionapp"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}>
      {body}
    </ResourceBlade>
  );
}

function Placeholder({ name, id, extra }) {
  return (
    <>
      <div className="vy-panel-title">{name} | {LABEL[id] || id}</div>
      {extra}
      <NotSimulated feature={`The ${LABEL[id] || id} panel`} />
    </>
  );
}

// A gap genuinely beyond a local simulator (real external provider, dedicated infrastructure or
// real human staff — see core/capabilities/azure/functionapp.json). CapabilityContainer renders
// the honest Not-simulated note itself, straight from the registry, since the id's level is
// "not_simulated" — never a hand-written disclaimer.
function GapPanel({ name, id, capId }) {
  return (
    <>
      <div className="vy-panel-title">{name} | {LABEL[id] || id}</div>
      <CapabilityContainer id={capId} title={LABEL[id] || id} />
    </>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [tab, setTab] = useState("functions");
  const [del, setDel] = useState(false);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  const rt = (p.functionAppConfig?.runtime?.name || p.siteConfig?.linuxFxVersion || "python").split("|");

  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<ArrowUpload20Regular />} as="a" href={`${self}/app-files`}>Browse</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton icon={p.state === "Stopped" ? <PlayCircle20Regular /> : <Pause20Regular />} onClick={async () => {
          try { p.state === "Stopped" ? await api.startFunctionApp(a.resourceGroup, a.name) : await api.stopFunctionApp(a.resourceGroup, a.name); reload(); }
          catch (e) { notify.error(e, "Failed"); }
        }}>{p.state === "Stopped" ? "Start" : "Stop"}</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={async () => { try { await api.restartFunctionApp(a.resourceGroup, a.name); reload(); } catch (e) { notify.error(e, "Failed"); } }}>Restart</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<DocumentArrowDown20Regular />} onClick={async () => {
          try { const xml = await api.publishProfile(a.resourceGroup, a.name, false); const b = new Blob([xml], { type: "text/xml" }); const u = URL.createObjectURL(b); const el = document.createElement("a"); el.href = u; el.download = `${a.name}.PublishSettings`; document.body.appendChild(el); el.click(); el.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000); }
          catch (e) { notify.error(e, "Download failed"); }
        }}>Download publish profile</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={async () => { try { await api.publishProfile(a.resourceGroup, a.name, true); notify.success("Publish profile was reset.", "Reset succeeded"); } catch (e) { notify.error(e, "Reset failed"); } }}>Reset publish profile</ToolbarButton>
        <ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => notify.info("Downloading the deployed app content zip isn't simulated in Vyomi.")}>Download app content</ToolbarButton>
        <ToolbarButton onClick={() => notify.info("Thanks for the feedback!")}>Send us your feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Status", p.state],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Default domain", <a href={`https://${p.defaultHostName}`} target="_blank" rel="noreferrer">{p.defaultHostName}</a>],
          ["Operating System", p.reserved ? "Linux" : "Windows"],
          ["App Service Plan", p.serverFarmId?.split("/").pop()],
          ["Runtime version", rt[1] || "3.12"],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="functions">Functions</Tab>
        <Tab value="properties">Properties</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="logs">Logs</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="notifications">Notifications</Tab>
        <Tab value="recommendations">Recommendations</Tab>
      </TabList>
      {tab === "functions" && <Functions a={a} self={self} />}
      {tab === "properties" && <Properties a={a} rt={rt} />}
      {tab === "monitoring" && <NotSimulatedContainer feature="Function app monitoring (execution count, errors, duration charts)" />}
      {tab === "logs" && <NotSimulatedContainer feature="The Logs tab" />}
      {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
      {tab === "notifications" && <NotSimulatedContainer feature="Notifications" />}
      {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="function app" names={[a.name]}
        onConfirm={async () => { await api.deleteFunctionApp(a.resourceGroup, a.name); forget(self); notify.success(`Function app '${a.name}' was deleted.`, "Delete succeeded"); navigate("functionapp"); }} />
    </>
  );
}

function Functions({ a, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listFunctions(a.resourceGroup, a.name), [a.id]);
  return (
    <div style={{ marginTop: 8 }}>
      <BrowseGrid
        resourceName="function" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => navigate("functionapp", a.resourceGroup, a.name, "functions", "create")}
        onDelete={async (rows) => { for (const r of rows) await api.deleteFunction(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${rows.length} function${rows.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        extraCommands={<>
          <ToolbarButton icon={<PlayCircle20Regular />} disabled={!data?.length} onClick={async () => { for (const r of data || []) await api.createFunction(a.resourceGroup, a.name, r.name, { properties: { ...r.properties, isDisabled: false } }); reload(); }}>Enable</ToolbarButton>
          <ToolbarButton icon={<Pause20Regular />} disabled={!data?.length} onClick={async () => { for (const r of data || []) await api.createFunction(a.resourceGroup, a.name, r.name, { properties: { ...r.properties, isDisabled: true } }); reload(); }}>Disable</ToolbarButton>
        </>}
        columns={[
          { key: "name", label: "Name", render: (r) => <Link href={`${self}/functions/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
          { key: "trigger", label: "Trigger", value: (r) => r.properties?.trigger },
          { key: "status", label: "Status", value: (r) => (r.properties?.isDisabled ? "Disabled" : "Enabled") },
        ]}
        emptyAction={<Link as="button" onClick={() => navigate("functionapp", a.resourceGroup, a.name, "functions", "create")}>Create function</Link>}
      />
    </div>
  );
}

function Properties({ a, rt }) {
  const p = a.properties || {};
  return (
    <div className="vy-props" style={{ marginTop: 12 }}>
      <section className="vy-section"><h3>Function App</h3>
        <KV label="Name" value={a.name} />
        <KV label="Runtime version" value={rt[1] || "3.12"} />
        <KV label="Runtime Stack" value={rt[0]} />
      </section>
      <section className="vy-section"><h3>Hosting</h3>
        <KV label="Plan type" value={p.sku} />
        <KV label="Instance memory" value={`${p.functionAppConfig?.scaleAndConcurrency?.instanceMemoryMB ?? 2048} MB`} />
      </section>
      <section className="vy-section"><h3>Domains</h3>
        <KV label="Default domain" value={p.defaultHostName} />
      </section>
    </div>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const apply = async () => {
    setBusy(true);
    try {
      await api.updateFunctionApp(a.resourceGroup, a.name, { tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <table className="vy-grid" style={{ maxWidth: 760 }}>
        <thead><tr><th>Name</th><th>Value</th><th /></tr></thead>
        <tbody>
          {rows.map((t, i) => (
            <tr key={i}>
              <td><Input size="small" value={t.name} onChange={(_, d) => setRows(rows.map((x, j) => (j === i ? { ...x, name: d.value } : x)))} aria-label={`Tag name ${i + 1}`} /></td>
              <td><Input size="small" value={t.value} onChange={(_, d) => setRows(rows.map((x, j) => (j === i ? { ...x, value: d.value } : x)))} aria-label={`Tag value ${i + 1}`} /></td>
              <td>{i < rows.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => setRows(rows.filter((_, j) => j !== i))} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button onClick={() => setRows([{ name: "", value: "" }])}>Delete all</Button>
      </div>
    </>
  );
}

// ── App keys ─────────────────────────────────────────────────────────────────────────────
function AppKeys({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listHostKeys(a.resourceGroup, a.name), [a.id]);
  const [newKey, setNewKey] = useState(null); // "functionkeys" | "systemkeys" | null
  return (
    <>
      <div className="vy-panel-title">{a.name} | App keys</div>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <>
          <KeyTable title="Host keys (all functions)" bucket="functionkeys" rows={{ ...(data?.functionKeys || {}) }} onAdd={() => setNewKey("functionkeys")} onDeleted={reload} rg={a.resourceGroup} name={a.name} addLabel="New host key" />
          <KeyTable title="System keys" bucket="systemkeys" rows={{ ...(data?.systemKeys || {}) }} onAdd={() => setNewKey("systemkeys")} onDeleted={reload} rg={a.resourceGroup} name={a.name} addLabel="New system key" />
        </>
      )}
      <NewHostKey open={!!newKey} bucket={newKey} onClose={() => setNewKey(null)} rg={a.resourceGroup} name={a.name} onDone={reload} />
    </>
  );
}

function KeyTable({ title, bucket, rows, onAdd, onDeleted, rg, name, addLabel }) {
  const notify = useNotify();
  const [show, setShow] = useState({});
  const entries = Object.entries(rows);
  return (
    <section className="vy-section" style={{ maxWidth: 760 }}>
      <div className="vy-cmdbar" role="toolbar" aria-label={`${title} commands`}>
        <ToolbarButton icon={<ArrowUpload20Regular />} onClick={onAdd}>{addLabel}</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={onDeleted}>Refresh</ToolbarButton>
      </div>
      <h3>{title}</h3>
      <table className="vy-grid"><thead><tr><th>Name</th><th>Value</th><th /></tr></thead>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td>
                <Input readOnly size="small" type={show[k] ? "text" : "password"} value={v} style={{ width: 280 }} aria-label={`${k} value`} />
                <Button size="small" onClick={() => setShow((s) => ({ ...s, [k]: !s[k] }))}>{show[k] ? "Hide" : "Show"}</Button>
              </td>
              <td>{k !== "default" && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete ${k}`} onClick={async () => { await api.deleteHostKey(rg, name, bucket, k); notify.success(`Key '${k}' deleted.`, "Delete succeeded"); onDeleted(); }} />}</td>
            </tr>
          ))}
          {!entries.length && <tr><td colSpan={3} className="vy-muted">No keys.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

function NewHostKey({ open, bucket, onClose, rg, name, onDone }) {
  const notify = useNotify();
  const [kname, setKname] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await api.putHostKey(rg, name, bucket, kname); notify.success(`Key '${kname}' created.`, "Key created"); setKname(""); onClose(); onDone(); }
    catch (e) { notify.error(e, "Create key failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="New key"><DialogBody><DialogTitle>{bucket === "systemkeys" ? "New system key" : "New host key"}</DialogTitle>
        <DialogContent><Field label="Key name" required><Input value={kname} onChange={(_, d) => setKname(d.value)} aria-label="Key name" /></Field></DialogContent>
        <DialogActions><Button appearance="primary" disabled={!kname || busy} onClick={go}>Create</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}

// ── Environment variables ────────────────────────────────────────────────────────────────
function EnvironmentVariables({ a }) {
  const notify = useNotify();
  const [tab, setTab] = useState("appsettings");
  const settings = useAsync(() => api.listAppSettings(a.resourceGroup, a.name), [a.id]);
  const conns = useAsync(() => api.listConnectionStrings(a.resourceGroup, a.name), [a.id]);
  const [reveal, setReveal] = useState(false);
  const [editRows, setEditRows] = useState(null);
  const [addOpen, setAddOpen] = useState(false);

  const rows = Object.entries(settings.data || {});
  const dirty = editRows !== null;
  const save = async () => {
    try { await api.setAppSettings(a.resourceGroup, a.name, Object.fromEntries(editRows)); notify.success("App settings were saved.", "Saved"); setEditRows(null); settings.reload(); }
    catch (e) { notify.error(e, "Save failed"); }
  };

  return (
    <>
      <div className="vy-panel-title">{a.name} | Environment variables</div>
      <p style={{ fontSize: 13 }}>Use <b>Add</b> to open the <b>Add/Edit application setting</b> dialog, or <b>Advanced edit</b> to edit all settings as a table.</p>
      <div className="vy-cmdbar" role="toolbar" aria-label="Environment variables commands">
        <ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => setAddOpen(true)}>Add</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { settings.reload(); conns.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setReveal((v) => !v)}>{reveal ? "Hide values" : "Show values"}</ToolbarButton>
        <ToolbarButton onClick={() => setEditRows((editRows ?? rows).concat())}>Advanced edit</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Environment variables tabs">
        <Tab value="appsettings">App settings</Tab>
        <Tab value="connectionstrings">Connection strings</Tab>
      </TabList>
      {tab === "appsettings" && (
        <>
          <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Filter app settings" aria-label="Filter app settings" />
          <table className="vy-grid"><thead><tr><th>Name</th><th>Value</th><th>Deployment slot setting</th><th>Source</th></tr></thead>
            <tbody>
              {(editRows ?? rows).map(([k, v], i) => (
                <tr key={k + i}>
                  <td>{dirty ? <Input size="small" value={k} onChange={(_, d) => setEditRows(editRows.map((r, j) => (j === i ? [d.value, r[1]] : r)))} aria-label="Name" /> : k}</td>
                  <td>{dirty ? <Input size="small" value={v} onChange={(_, d) => setEditRows(editRows.map((r, j) => (j === i ? [r[0], d.value] : r)))} aria-label="Value" /> : (reveal ? v : "••••••••")}</td>
                  <td><Checkbox disabled aria-label="Deployment slot setting" /></td>
                  <td>App service</td>
                </tr>
              ))}
            </tbody>
          </table>
          {dirty && <Link as="button" style={{ marginTop: 6, display: "block" }} onClick={() => setEditRows([...editRows, ["", ""]])}>+ New application setting</Link>}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Button appearance="primary" disabled={!dirty} onClick={save}>Apply</Button>
            <Button disabled={!dirty} onClick={() => setEditRows(null)}>Discard</Button>
          </div>
        </>
      )}
      {tab === "connectionstrings" && (
        <>
          <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Filter connection strings" aria-label="Filter connection strings" />
          <table className="vy-grid"><thead><tr><th>Name</th><th>Value</th><th>Type</th><th>Deployment slot setting</th></tr></thead>
            <tbody>
              {Object.entries(conns.data || {}).map(([k, v]) => (
                <tr key={k}><td>{k}</td><td>{reveal ? v.value : "••••••••"}</td><td>{v.type}</td><td><Checkbox disabled aria-label="Deployment slot setting" /></td></tr>
              ))}
              {!Object.keys(conns.data || {}).length && <tr><td colSpan={4} className="vy-muted">No connection strings.</td></tr>}
            </tbody>
          </table>
        </>
      )}
      <AddSetting open={addOpen} onClose={() => setAddOpen(false)} rg={a.resourceGroup} name={a.name} onDone={() => { settings.reload(); setAddOpen(false); }} />
    </>
  );
}

function AddSetting({ open, onClose, rg, name, onDone }) {
  const notify = useNotify();
  const [n, setN] = useState(""); const [v, setV] = useState(""); const [slot, setSlot] = useState(false);
  const go = async () => {
    try { const cur = await api.listAppSettings(rg, name); await api.setAppSettings(rg, name, { ...cur, [n]: v }); notify.success(`Application setting '${n}' added.`, "Added"); setN(""); setV(""); onDone(); }
    catch (e) { notify.error(e, "Add failed"); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add/Edit application setting"><DialogBody><DialogTitle>Add/Edit application setting</DialogTitle>
        <DialogContent>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Field label="Name" required><Input value={n} onChange={(_, d) => setN(d.value)} aria-label="Name" /></Field>
            <Field label="Value"><Textarea value={v} onChange={(_, d) => setV(d.value)} aria-label="Value" /></Field>
            <Checkbox checked={slot} onChange={(_, d) => setSlot(!!d.checked)} label="Deployment slot setting" />
          </div>
        </DialogContent>
        <DialogActions><Button appearance="primary" disabled={!n} onClick={go}>OK</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}

// ── Scale and concurrency ────────────────────────────────────────────────────────────────
function ScaleAndConcurrency({ a, reload }) {
  const notify = useNotify();
  const sc = a.properties?.functionAppConfig?.scaleAndConcurrency || {};
  const init = () => ({ instanceMemoryMB: sc.instanceMemoryMB ?? 2048, maximumInstanceCount: sc.maximumInstanceCount ?? 100, perInstanceConcurrency: sc.triggers?.http?.perInstanceConcurrency ?? 16 });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [a]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const save = async () => {
    setBusy(true);
    try {
      await api.updateFunctionApp(a.resourceGroup, a.name, { properties: { functionAppConfig: { scaleAndConcurrency: { instanceMemoryMB: f.instanceMemoryMB, maximumInstanceCount: f.maximumInstanceCount, triggers: { http: { perInstanceConcurrency: f.perInstanceConcurrency } } } } } });
      notify.success("Scale and concurrency settings were saved.",
        f.maximumInstanceCount === 0 || f.perInstanceConcurrency === 0
          ? "Saved — capacity is 0, so every invoke will now be throttled (429), same as a real scaled-to-zero app."
          : "Saved — Vyomi stores this setting but runs every invoke synchronously, so a positive capacity is never enforced against concurrent callers.");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Scale and concurrency</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Scale and concurrency commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton icon={<Dismiss20Regular />} disabled={!dirty} onClick={() => setF(init())}>Discard</ToolbarButton>
      </div>
      <InfoBar>Stored on the Function App and returned from the API exactly as configured. A capacity of 0 (maximum instance count x per-instance concurrency) is enforced — every invoke is throttled, as on a real scaled-to-zero app; any positive capacity is not enforced, since Vyomi runs a single instance and every invoke is synchronous.</InfoBar>
      <div className="vy-form-row"><span className="vy-label">Instance memory</span>
        <Select value={String(f.instanceMemoryMB)} onChange={(_, d) => setF((x) => ({ ...x, instanceMemoryMB: Number(d.value) }))} aria-label="Instance memory">
          <option value="512">512 MB</option><option value="2048">2048 MB</option><option value="4096">4096 MB</option>
        </Select>
      </div>
      <Field label="Maximum instance count" style={{ maxWidth: 300 }}>
        <Input type="number" value={String(f.maximumInstanceCount)} onChange={(_, d) => setF((x) => ({ ...x, maximumInstanceCount: Number(d.value) || 0 }))} aria-label="Maximum instance count" />
      </Field>
      <Field label="HTTP concurrency per instance" style={{ maxWidth: 300, marginTop: 10 }}>
        <Input type="number" value={String(f.perInstanceConcurrency)} onChange={(_, d) => setF((x) => ({ ...x, perInstanceConcurrency: Number(d.value) || 0 }))} aria-label="HTTP concurrency per instance" />
      </Field>
    </>
  );
}

// ── Locks ────────────────────────────────────────────────────────────────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [q, setQ] = useState("");
  const rows = (data || []).filter((r) => r.name.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <>
      <div className="vy-panel-title">{a.name} | Locks</div>
      <p style={{ fontSize: 13 }}>Locking prevents other users in your organization from accidentally deleting or modifying critical resources. Use <b>Add lock</b> to lock this function app.</p>
      <div className="vy-cmdbar" role="toolbar" aria-label="Locks commands">
        <ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
        <ToolbarButton onClick={() => notify.info("Subscription-scoped locks aren't modelled in Vyomi; locks are scoped to this function app only.")}>Subscription</ToolbarButton>
        <ToolbarButton onClick={() => notify.info("Resource-group-scoped locks aren't modelled in Vyomi; locks are scoped to this function app only.")}>Resource group</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => notify.info("Thanks for the feedback!")}>Feedback</ToolbarButton>
      </div>
      <Input size="small" style={{ width: 260, margin: "8px 0" }} placeholder="Search to filter items..." value={q} onChange={(_, d) => setQ(d.value)} aria-label="Search to filter items..." />
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name}
        items={rows} loading={loading} error={error} onRefresh={reload}
        onDelete={async (rs) => { for (const r of rs) await api.deleteLock(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${rs.length} lock${rs.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Lock name" },
          { key: "type", label: "Lock type", value: (r) => r.properties?.level },
          { key: "scope", label: "Scope", value: () => a.name },
          { key: "notes", label: "Notes", value: (r) => r.properties?.notes },
        ]}
        emptyAction={<Link as="button" onClick={() => setAdd(true)}>Add lock</Link>}
      />
      <AddLock open={add} onClose={() => setAdd(false)} rg={a.resourceGroup} name={a.name} onDone={reload} />
    </>
  );
}

function AddLock({ open, onClose, rg, name, onDone }) {
  const notify = useNotify();
  const [n, setN] = useState(""); const [type, setType] = useState("Read-only"); const [notes, setNotes] = useState("");
  const go = async () => {
    try { await api.putLock(rg, name, n, type === "Read-only" ? "ReadOnly" : "CanNotDelete", notes); notify.success(`Lock '${n}' added.`, "Lock added"); setN(""); setNotes(""); onClose(); onDone(); }
    catch (e) { notify.error(e, "Add lock failed"); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add lock"><DialogBody><DialogTitle>Add lock</DialogTitle>
        <DialogContent>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Field label="Lock name" required><Input value={n} onChange={(_, d) => setN(d.value)} aria-label="Lock name" /></Field>
            <Field label="Lock type" required><Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type"><option>Read-only</option><option>Delete</option></Select></Field>
            <Field label="Notes"><Textarea value={notes} onChange={(_, d) => setNotes(d.value)} aria-label="Notes" /></Field>
          </div>
        </DialogContent>
        <DialogActions><Button appearance="primary" disabled={!n} onClick={go}>OK</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}

// ── Access control (IAM) ────────────────────────────────────────────────────────────────
function AccessControl({ a }) {
  const [tab, setTab] = useState("checkaccess");
  const assignments = useAsync(() => ROLE_ASSIGNMENTS.list(), [a.id]);
  const definitions = useAsync(() => ROLE_DEFINITIONS.list(), [a.id]);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Access control (IAM)</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Access control commands">
        <ToolbarButton icon={<ArrowUpload20Regular />} as="a" href="#/functionapp">Add</ToolbarButton>
        <ToolbarButton onClick={() => {}}>Download role assignments</ToolbarButton>
        <ToolbarButton onClick={() => {}}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { assignments.reload(); definitions.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton disabled>Remove</ToolbarButton>
        <ToolbarButton onClick={() => {}}>Feedback</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control tabs">
        <Tab value="checkaccess">Check access</Tab>
        <Tab value="roleassignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="denyassignments">Deny assignments</Tab>
        <Tab value="classicadministrators">Classic administrators</Tab>
      </TabList>
      {tab === "checkaccess" && (
        <div style={{ marginTop: 12 }}>
          <section className="vy-section"><h3>My access</h3><Button onClick={() => {}}>View my access</Button></section>
          <section className="vy-section"><h3>Check access</h3><Button onClick={() => {}}>Check access</Button></section>
        </div>
      )}
      {tab === "roleassignments" && (
        <section className="vy-section">
          <h3>Role assignments</h3>
          <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Search by name or email" aria-label="Search by name or email" />
          <table className="vy-grid"><thead><tr><th>Name</th><th>Type</th><th>Role</th><th>Scope</th><th>Condition</th></tr></thead>
            <tbody>
              {assignments.loading ? <tr><td colSpan={5}><Spinner size="tiny" /></td></tr> : (assignments.data || []).map((r) => (
                <tr key={r.name}><td>{r.properties?.principalId}</td><td>{r.properties?.principalType}</td><td>{r.properties?.roleDefinitionId?.split("/").pop()}</td><td>{r.properties?.scope}</td><td>None</td></tr>
              ))}
              {!assignments.loading && !(assignments.data || []).length && <tr><td colSpan={5} className="vy-muted">No role assignments found for this scope.</td></tr>}
            </tbody>
          </table>
        </section>
      )}
      {tab === "roles" && (
        <section className="vy-section">
          <h3>Roles</h3>
          <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Search by role name, description, permission, or ID" aria-label="Search by role name, description, permission, or ID" />
          <table className="vy-grid"><thead><tr><th>Name</th><th>Description</th><th>Type</th><th>Category</th><th>Details</th></tr></thead>
            <tbody>
              {definitions.loading ? <tr><td colSpan={5}><Spinner size="tiny" /></td></tr> : (definitions.data || []).map((r) => (
                <tr key={r.name}><td>{r.name}</td><td /><td>{r.properties?.type}</td><td>General</td><td /></tr>
              ))}
              {!definitions.loading && !(definitions.data || []).length && <tr><td colSpan={5} className="vy-muted">No custom roles defined.</td></tr>}
            </tbody>
          </table>
        </section>
      )}
      {tab === "denyassignments" && (
        <section className="vy-section"><h3>Deny assignments</h3>
          <table className="vy-grid"><thead><tr><th>Name</th><th>Description</th><th>Principal</th><th>Scope</th></tr></thead>
            <tbody><tr><td colSpan={4} className="vy-muted">No deny assignments found.</td></tr></tbody>
          </table>
        </section>
      )}
      {tab === "classicadministrators" && <InfoBar>No classic administrators are configured for this subscription.</InfoBar>}
    </>
  );
}

// ── Activity log ─────────────────────────────────────────────────────────────────────────
function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Activity log</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr><th>Operation name</th><th>Status</th><th>Time</th><th>Time stamp</th><th>Subscription</th><th>Event initiated by</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={6}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.id}>
              <td>{r.operationName?.value}</td>
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

// ── Export template ──────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [includeParams, setIncludeParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", contentVersion: "1.0.0.0",
    parameters: includeParams ? { name: { type: "string", defaultValue: a.name } } : {},
    resources: [{ type: "Microsoft.Web/sites", apiVersion: "2023-12-01", name: includeParams ? "[parameters('name')]" : a.name, location: a.location, kind: a.kind, properties: a.properties }],
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Export template</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<DocumentArrowDown20Regular />} onClick={() => {
          const blob = new Blob([JSON.stringify(template, null, 2)], { type: "application/json" });
          const u = URL.createObjectURL(blob); const el = document.createElement("a"); el.href = u; el.download = `${a.name}.json`; document.body.appendChild(el); el.click(); el.remove();
          setTimeout(() => URL.revokeObjectURL(u), 1000);
        }}>Download</ToolbarButton>
        <ToolbarButton disabled>Add to library (preview)</ToolbarButton>
        <ToolbarButton disabled>Deploy</ToolbarButton>
        <ToolbarButton disabled>Visualize template</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab><Tab value="bicep">Bicep</Tab><Tab value="terraform">Terraform</Tab>
      </TabList>
      {tab === "arm" && (
        <>
          <Checkbox style={{ marginTop: 8 }} checked={includeParams} onChange={(_, d) => setIncludeParams(!!d.checked)} label="Include parameters" />
          <section className="vy-section"><h3>Template</h3>
            <pre className="vy-mono" style={{ maxHeight: 360, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 10, borderRadius: 4, fontSize: 12 }}>{JSON.stringify(template, null, 2)}</pre>
          </section>
        </>
      )}
      {tab === "bicep" && <NotSimulatedContainer feature="ARM-to-Bicep decompilation" />}
      {tab === "terraform" && <NotSimulatedContainer feature="ARM-to-Terraform export" />}
    </>
  );
}

// ── Identity ─────────────────────────────────────────────────────────────────────────────
// `identity` is a top-level sibling of `properties` on the site (core/azure_webapp_core.py's
// _apply_identity): enabling System assigned mints a stable principalId/tenantId, usable as
// the subject of a role assignment on Access control (IAM).
function Identity({ a, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("systemassigned");
  const ident = a.identity || { type: "None" };
  const on = /systemassigned/i.test(ident.type || "");
  const [busy, setBusy] = useState(false);
  const toggle = async (enable) => {
    setBusy(true);
    try {
      await api.updateIdentity(a.resourceGroup, a.name, { type: enable ? "SystemAssigned" : "None" });
      notify.success(`System assigned managed identity was turned ${enable ? "on" : "off"} for '${a.name}'.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Identity</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Identity tabs">
        <Tab value="systemassigned">System assigned</Tab>
        <Tab value="userassigned">User assigned</Tab>
      </TabList>
      {tab === "systemassigned" && (
        <CapabilityContainer id="azure.functionapp.identity" title="System assigned managed identity">
          <p style={{ fontSize: 13, maxWidth: 640 }}>A system assigned managed identity is restricted to one per app and is shared by the whole app. It is deleted when the app itself is deleted.</p>
          <Field label="Status"><RadioGroup value={on ? "On" : "Off"} onChange={(_, d) => toggle(d.value === "On")} aria-label="Status">
            <Radio value="On" label="On" disabled={busy} /><Radio value="Off" label="Off" disabled={busy} />
          </RadioGroup></Field>
          {on && (
            <div className="vy-props" style={{ marginTop: 8 }}>
              <KV label="Object (principal) ID" value={ident.principalId} />
              <KV label="Tenant ID" value={ident.tenantId} />
            </div>
          )}
        </CapabilityContainer>
      )}
      {tab === "userassigned" && (
        <NotSimulatedContainer feature="User assigned managed identities" note="Vyomi has no User Assigned Identity resource of its own to attach here." />
      )}
    </>
  );
}

// ── Custom domains (hostNameBindings — real ARM shared with web apps) ────────────────────
function CustomDomains({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listCustomDomains(a.resourceGroup, a.name), [a.id]);
  const [adding, setAdding] = useState(false);
  const [host, setHost] = useState("");
  const [ssl, setSsl] = useState(false);
  const [busy, setBusy] = useState(false);
  const add = async () => {
    setBusy(true);
    try { await api.addCustomDomain(a.resourceGroup, a.name, host, ssl ? "SniEnabled" : "Disabled"); notify.success(`Custom domain '${host}' was added.`, "Add succeeded"); setAdding(false); setHost(""); setSsl(false); reload(); }
    catch (e) { notify.error(e, "Add custom domain failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Custom domains</div>
      <CapabilityContainer id="azure.functionapp.customdomains" title="Custom domains"
        actions={<ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => setAdding(true)}>Add custom domain</ToolbarButton>}>
        <BrowseGrid
          resourceName="custom domain" rowKey={(r) => r.name}
          items={(data || []).map((d) => ({ ...d, binding: d.properties?.sslState === "SniEnabled" ? "SNI SSL" : "Not configured" }))}
          loading={loading} error={error} onRefresh={reload}
          onDelete={async (rows) => { for (const r of rows) await api.removeCustomDomain(a.resourceGroup, a.name, r.name); notify.success("Custom domain(s) removed.", "Delete succeeded"); reload(); }}
          columns={[{ key: "name", label: "Custom domain" }, { key: "binding", label: "Binding type", value: (r) => r.binding }, { key: "cert", label: "Certificate", value: (r) => r.properties?.thumbprint || "--" }]}
          emptyAction={<Link as="button" onClick={() => setAdding(true)}>Add custom domain</Link>}
        />
      </CapabilityContainer>
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add custom domain"><DialogBody><DialogTitle>Add custom domain</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Field label="Custom domain" required><Input value={host} onChange={(_, d) => setHost(d.value)} placeholder="www.example.com" aria-label="Custom domain" /></Field>
              <Checkbox checked={ssl} onChange={(_, d) => setSsl(!!d.checked)} label="Add a TLS/SSL binding (SNI SSL)" />
            </div>
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={!host || busy} onClick={add}>{busy ? "Adding..." : "Add"}</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </>
  );
}

// ── Certificates (derived from any custom domain with an SSL binding) ────────────────────
function Certificates({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listCustomDomains(a.resourceGroup, a.name), [a.id]);
  const certs = (data || []).filter((d) => d.properties?.thumbprint);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Certificates</div>
      <CapabilityContainer id="azure.functionapp.certificates" title="Bindings">
        <BrowseGrid
          resourceName="certificate" rowKey={(r) => r.name}
          items={certs} loading={loading} error={error} onRefresh={reload}
          columns={[
            { key: "domain", label: "Custom domain", value: (r) => r.name },
            { key: "thumbprint", label: "Thumbprint", value: (r) => r.properties?.thumbprint },
            { key: "binding", label: "Binding type", value: () => "SNI SSL" },
          ]}
          emptyAction={<Link href={`#/functionapp/${encodeURIComponent(a.resourceGroup)}/${encodeURIComponent(a.name)}/custom-domains`}>Add a custom domain with a TLS/SSL binding</Link>}
        />
      </CapabilityContainer>
    </>
  );
}

// ── CORS ─────────────────────────────────────────────────────────────────────────────────
// Stored on siteConfig.cors (config/web) and ENFORCED on invoke (core/azure_webapp_core.py's
// _invoke_function checks the request's Origin header against allowedOrigins).
function Cors({ a, reload }) {
  const notify = useNotify();
  const cors = a.properties?.siteConfig?.cors || {};
  const [origins, setOrigins] = useState([...(cors.allowedOrigins || []), ""]);
  const [creds, setCreds] = useState(!!cors.supportCredentials);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setOrigins([...(cors.allowedOrigins || []), ""]); setCreds(!!cors.supportCredentials); }, [a]);
  const upd = (i, v) => {
    const xs = origins.map((o, j) => (j === i ? v : o));
    if (xs[xs.length - 1]) xs.push("");
    setOrigins(xs);
  };
  const save = async () => {
    setBusy(true);
    try {
      await api.updateSiteConfig(a.resourceGroup, a.name, { cors: { allowedOrigins: origins.filter(Boolean), supportCredentials: creds } });
      notify.success(`CORS settings for '${a.name}' were saved.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | CORS</div>
      <CapabilityContainer id="azure.functionapp.cors" title="Allowed Origins">
        <p style={{ fontSize: 13 }}>Allowed origins let browser pages hosted elsewhere call this function app's HTTP triggers. An empty list allows every origin — set one to test blocking from the function's Test/Run tab (add an "Origin" header).</p>
        {origins.map((o, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
            <Input size="small" style={{ width: 360 }} value={o} placeholder="https://example.com" onChange={(_, d) => upd(i, d.value)} aria-label={`Allowed origin ${i + 1}`} />
            {i < origins.length - 1 && <Button icon={<Delete20Regular />} onClick={() => setOrigins(origins.filter((_, j) => j !== i))} aria-label="Remove origin" />}
          </div>
        ))}
        <Checkbox checked={creds} onChange={(_, d) => setCreds(!!d.checked)} label="Enable Access-Control-Allow-Credentials" />
      </CapabilityContainer>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
        <Button onClick={reload}>Discard</Button>
      </div>
    </>
  );
}

// ── Networking ───────────────────────────────────────────────────────────────────────────
// Disabling public network access is ENFORCED on invoke; VNet integration is stored/returned
// but not enforced (Vyomi has no virtual network data plane) — see the capability's limitations.
function Networking({ a, reload }) {
  const notify = useNotify();
  const [pub, setPub] = useState(a.properties?.publicNetworkAccess !== "Disabled");
  const [vnet, setVnet] = useState(!!a.properties?.vnetRouteAllEnabled);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setPub(a.properties?.publicNetworkAccess !== "Disabled"); setVnet(!!a.properties?.vnetRouteAllEnabled); }, [a]);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateFunctionApp(a.resourceGroup, a.name, { properties: { publicNetworkAccess: pub ? "Enabled" : "Disabled", vnetRouteAllEnabled: vnet } });
      notify.success(`Networking settings for '${a.name}' were saved.`, pub ? "Save succeeded" : "Save succeeded — public network access is now disabled; every invoke will be rejected (403).");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Networking</div>
      <CapabilityContainer id="azure.functionapp.networking" title="Public network access">
        <Field label="Public network access"><RadioGroup value={pub ? "on" : "off"} onChange={(_, d) => setPub(d.value === "on")} aria-label="Public network access">
          <Radio value="on" label="Enabled from all networks" />
          <Radio value="off" label="Disabled" />
        </RadioGroup></Field>
        <Checkbox style={{ marginTop: 10 }} checked={vnet} onChange={(_, d) => setVnet(!!d.checked)} label="Enable virtual network integration (routes all outbound traffic — stored, not enforced)" />
      </CapabilityContainer>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
        <Button onClick={reload}>Discard</Button>
      </div>
    </>
  );
}

// ── Authentication (Easy Auth) ────────────────────────────────────────────────────────────
// A require-authentication toggle ENFORCED on invoke with a simulator-minted bearer token —
// Vyomi is not a real OAuth/OIDC identity provider, so no real provider login is modelled.
function Authentication({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getAuthSettings(a.resourceGroup, a.name), [a.id]);
  const [busy, setBusy] = useState(false);
  const enabled = !!data?.platform?.enabled;
  const toggle = async (next) => {
    setBusy(true);
    try { await api.updateAuthSettings(a.resourceGroup, a.name, next); notify.success(`Authentication was turned ${next ? "on" : "off"} for '${a.name}'.`, "Save succeeded"); reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Authentication</div>
      <CapabilityContainer id="azure.functionapp.authentication" title="App Service Authentication">
        <ErrorBar error={error} />
        {loading ? <Loading /> : (
          <>
            <Field label="App Service Authentication"><RadioGroup value={enabled ? "on" : "off"} onChange={(_, d) => toggle(d.value === "on")} aria-label="App Service Authentication">
              <Radio value="off" label="Disabled" disabled={busy} />
              <Radio value="on" label="Enabled (requires authentication)" disabled={busy} />
            </RadioGroup></Field>
            {enabled && data?.token && (
              <div style={{ marginTop: 10 }}>
                <p style={{ fontSize: 13 }}>Vyomi has no real identity provider, so turning this on mints its own bearer token instead. Add it as an "Authorization" header on the function's Test/Run tab to call an HTTP trigger while authentication is required:</p>
                <KV label="Authorization header" value={`Bearer ${data.token}`} />
              </div>
            )}
          </>
        )}
      </CapabilityContainer>
    </>
  );
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings — a real ARM extension
// resource scoped to this site's own id; core/azure_monitor_core.py, the same engine every
// Azure resource's "Diagnostic settings" page uses) ──────────────────────────────────────
function DiagnosticSettings({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDiagnosticSettings(a.resourceGroup, a.name), [a.id]);
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [adding, setAdding] = useState(false);
  const [dsName, setDsName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await api.putDiagnosticSetting(a.resourceGroup, a.name, dsName, {
        properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] },
      });
      notify.success(`Diagnostic setting '${dsName}' was created.`, "Save succeeded");
      setAdding(false); setDsName(""); reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Diagnostic settings</div>
      <CapabilityContainer id="azure.functionapp.diagnosticsettings" title="Diagnostic settings"
        actions={<ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => setAdding(true)}>Add diagnostic setting</ToolbarButton>}>
        <p style={{ fontSize: 13 }}>Diagnostic settings specify a destination for platform logs and metrics from this function app.</p>
        <ErrorBar error={error} />
        <BrowseGrid
          resourceName="diagnostic setting" rowKey={(r) => r.name}
          items={data || []} loading={loading} error={error} onRefresh={reload}
          onDelete={async (rows) => { for (const r of rows) await api.deleteDiagnosticSetting(a.resourceGroup, a.name, r.name); notify.success("Diagnostic setting(s) deleted.", "Delete succeeded"); reload(); }}
          columns={[
            { key: "name", label: "Name" },
            { key: "dest", label: "Destination details", value: (s) => (s.properties?.workspaceId ? "Log Analytics workspace" : "--") },
            { key: "logs", label: "Log categories", value: (s) => (s.properties?.logs || []).filter((l) => l.enabled).length },
            { key: "metrics", label: "Metric categories", value: (s) => (s.properties?.metrics || []).filter((m) => m.enabled).length },
          ]}
        />
      </CapabilityContainer>
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add diagnostic setting"><DialogBody><DialogTitle>Add diagnostic setting</DialogTitle>
          <DialogContent>
            <Field label="Diagnostic setting name" required><Input value={dsName} onChange={(_, d) => setDsName(d.value)} aria-label="Diagnostic setting name" /></Field>
            <Field label="Log Analytics workspace" required>
              {(workspaces.data || []).length ? (
                <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
                  <option value="">Select a workspace...</option>
                  {workspaces.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </Select>
              ) : <p style={{ fontSize: 13 }}>No Log Analytics workspace yet. Create one from the Log Analytics workspaces console.</p>}
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!dsName || !workspace || busy} onClick={create}>{busy ? "Saving..." : "Save"}</Button>
            <Button onClick={() => setAdding(false)}>Cancel</Button>
          </DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </>
  );
}

// ── Invocation telemetry (Metrics, Logs, Log stream, Events preview, Alerts, Application
// Insights all read the SAME real ring buffer core/azure_webapp_core.py's invoke sandbox
// appends to — never synthetic/random data) ──────────────────────────────────────────────
const useInvocationLogs = (a) => useAsync(() => api.listInvocationLogs(a.resourceGroup, a.name), [a.id]);

function Metrics({ a }) {
  const { data, loading, error, reload } = useInvocationLogs(a);
  const rows = data || [];
  const total = rows.length;
  const errors = rows.filter((r) => !r.ok).length;
  const avgDuration = total ? (rows.reduce((s, r) => s + (r.durationMs || 0), 0) / total).toFixed(2) : "0";
  return (
    <>
      <div className="vy-panel-title">{a.name} | Metrics</div>
      <CapabilityContainer id="azure.functionapp.telemetry" title="Function app metrics"
        actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
        <ErrorBar error={error} />
        {loading ? <Loading /> : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, margin: "8px 0" }}>
            <div className="vy-section"><h3>Function Execution Count</h3><div style={{ fontSize: 28, fontWeight: 600 }}>{total}</div><p style={{ fontSize: 12 }}>Recorded invocations (last {total})</p></div>
            <div className="vy-section"><h3>Rejected / failed</h3><div style={{ fontSize: 28, fontWeight: 600 }}>{errors}</div></div>
            <div className="vy-section"><h3>Avg. duration</h3><div style={{ fontSize: 28, fontWeight: 600 }}>{avgDuration} ms</div></div>
          </div>
        )}
      </CapabilityContainer>
    </>
  );
}

function LogsPanel({ a }) {
  const { data, loading, error, reload } = useInvocationLogs(a);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Logs</div>
      <CapabilityContainer id="azure.functionapp.telemetry" title="Recent invocations"
        actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
        <ErrorBar error={error} />
        <table className="vy-grid">
          <thead><tr><th>Timestamp</th><th>Function</th><th>Status</th><th>Duration (ms)</th><th>Detail</th></tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={5}><Spinner size="tiny" /></td></tr> : (data || []).length ? data.map((r, i) => (
              <tr key={i}><td>{fmtDate(r.timestamp)}</td><td>{r.function}</td><td>{r.status}</td><td>{r.durationMs}</td><td>{r.error || ""}</td></tr>
            )) : <tr><td colSpan={5} className="vy-muted">No invocations recorded yet.</td></tr>}
          </tbody>
        </table>
      </CapabilityContainer>
    </>
  );
}

function LogStream({ a }) {
  const { data, loading, error, reload } = useInvocationLogs(a);
  const [live, setLive] = useState(true);
  useEffect(() => {
    if (!live) return undefined;
    const id = setInterval(reload, 4000);
    return () => clearInterval(id);
  }, [live, reload]);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Log stream</div>
      <CapabilityContainer id="azure.functionapp.telemetry" title="Log stream"
        actions={<div className="vy-cmdbar" role="toolbar" aria-label="Log stream commands">
          <ToolbarButton icon={live ? <Pause20Regular /> : <PlayCircle20Regular />} onClick={() => setLive((v) => !v)}>{live ? "Pause" : "Resume"}</ToolbarButton>
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        </div>}>
        <ErrorBar error={error} />
        <pre className="vy-mono" style={{ maxHeight: 360, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 10, borderRadius: 4, fontSize: 12 }}>
          {loading ? "Connecting..." : (data || []).length ? data.map((r) => `${r.timestamp}  ${r.function}  ${r.status}${r.error ? "  " + r.error : ""}`).join("\n") : "No invocations recorded yet."}
        </pre>
      </CapabilityContainer>
    </>
  );
}

function EventsPreview({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Events (preview)</div>
      <CapabilityContainer id="azure.functionapp.telemetry" title="Events"
        actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
        <p style={{ fontSize: 13 }}>The real resource lifecycle events recorded for this app (the same feed behind Activity log), shown as events.</p>
        <ErrorBar error={error} />
        <table className="vy-grid">
          <thead><tr><th>Event</th><th>Status</th><th>Time</th></tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={3}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
              <tr key={r.id}><td>{r.operationName?.value}</td><td>{r.status?.localizedValue || r.status?.value}</td><td>{fmtDate(r.eventTimestamp)}</td></tr>
            )) : <tr><td colSpan={3} className="vy-muted">No events recorded yet.</td></tr>}
          </tbody>
        </table>
      </CapabilityContainer>
    </>
  );
}

// ── Alerts (Microsoft.Insights/metricAlerts — subscription-wide generic CRUD scoped to this
// app via `properties.scopes`; "current value" is computed on demand from the real recorded
// invocation log, not a continuous evaluation loop — see the capability's limitations) ─────
function Alerts({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listMetricAlertsFor(a.resourceGroup, a.name), [a.id]);
  const logs = useInvocationLogs(a);
  const [adding, setAdding] = useState(false);
  const [alertName, setAlertName] = useState("");
  const [metric, setMetric] = useState("Http5xxCount");
  const [threshold, setThreshold] = useState(5);
  const [busy, setBusy] = useState(false);

  const currentValue = (metricName) => {
    const rows = logs.data || [];
    if (metricName === "Http5xxCount") return rows.filter((r) => r.status >= 500).length;
    if (metricName === "RejectedCount") return rows.filter((r) => !r.ok && r.status < 500).length;
    return rows.length; // FunctionExecutionCount
  };

  const create = async () => {
    setBusy(true);
    try {
      await api.putMetricAlert(a.resourceGroup, alertName, {
        location: "global",
        properties: {
          severity: 3, enabled: true, scopes: [a.id], evaluationFrequency: "PT5M", windowSize: "PT15M",
          criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
            allOf: [{ name: "c1", metricName: metric, timeAggregation: "Total", operator: "GreaterThan", threshold: Number(threshold) || 0 }] },
        },
      });
      notify.success(`Alert rule '${alertName}' was created.`, "Save succeeded");
      setAdding(false); setAlertName(""); reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Alerts</div>
      <CapabilityContainer id="azure.functionapp.alerts" title="Alert rules"
        actions={<ToolbarButton icon={<ArrowUpload20Regular />} onClick={() => setAdding(true)}>Create alert rule</ToolbarButton>}>
        <BrowseGrid
          resourceName="alert rule" rowKey={(r) => r.name}
          items={data || []} loading={loading} error={error} onRefresh={reload}
          onDelete={async (rows) => { for (const r of rows) await api.deleteMetricAlert(a.resourceGroup, r.name); notify.success("Alert rule(s) deleted.", "Delete succeeded"); reload(); }}
          columns={[
            { key: "name", label: "Name" },
            { key: "condition", label: "Condition", value: (r) => { const c = r.properties?.criteria?.allOf?.[0]; return c ? `${c.metricName} ${c.operator} ${c.threshold}` : "--"; } },
            { key: "current", label: "Current value (computed now)", value: (r) => { const c = r.properties?.criteria?.allOf?.[0]; return c ? currentValue(c.metricName) : "--"; } },
            { key: "status", label: "Status", value: (r) => { const c = r.properties?.criteria?.allOf?.[0]; if (!c) return "--"; return currentValue(c.metricName) > c.threshold ? "Fired" : "OK"; } },
          ]}
          emptyAction={<Link as="button" onClick={() => setAdding(true)}>Create alert rule</Link>}
        />
      </CapabilityContainer>
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Create alert rule"><DialogBody><DialogTitle>Create alert rule</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Field label="Alert rule name" required><Input value={alertName} onChange={(_, d) => setAlertName(d.value)} aria-label="Alert rule name" /></Field>
              <Field label="Metric"><Select value={metric} onChange={(_, d) => setMetric(d.value)} aria-label="Metric">
                <option value="Http5xxCount">Http Server Errors</option>
                <option value="FunctionExecutionCount">Function Execution Count</option>
                <option value="RejectedCount">Rejected invocations (throttled/blocked)</option>
              </Select></Field>
              <Field label="Threshold (greater than)"><Input type="number" value={String(threshold)} onChange={(_, d) => setThreshold(d.value)} aria-label="Threshold" /></Field>
            </div>
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={!alertName || busy} onClick={create}>{busy ? "Saving..." : "Save"}</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </>
  );
}

// ── Health check ─────────────────────────────────────────────────────────────────────────
// "Run health check now" resolves the configured path to a function by name and runs it
// through the REAL invoke sandbox (core/azure_webapp_core.py's _run_health_check).
function HealthCheckPanel({ a, reload }) {
  const notify = useNotify();
  const [path, setPath] = useState(a.properties?.siteConfig?.healthCheckPath || "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  useEffect(() => setPath(a.properties?.siteConfig?.healthCheckPath || ""), [a]);
  const save = async () => {
    setBusy(true);
    try { await api.updateSiteConfig(a.resourceGroup, a.name, { healthCheckPath: path }); notify.success("Health check path was saved.", "Save succeeded"); reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  const run = async () => {
    try { setResult(await api.runHealthCheck(a.resourceGroup, a.name)); }
    catch (e) { notify.error(e, "Health check failed"); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Health check</div>
      <CapabilityContainer id="azure.functionapp.healthcheck" title="Health check"
        actions={<ToolbarButton icon={<PlayCircle20Regular />} onClick={run}>Run health check now</ToolbarButton>}>
        <Field label="Health check path" style={{ maxWidth: 360 }}>
          <Input value={path} onChange={(_, d) => setPath(d.value)} placeholder="/api/httptrigger" aria-label="Health check path" />
        </Field>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <Button appearance="primary" disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
        </div>
        {result && (
          <InfoBar intent={result.healthy ? "success" : "warning"}>
            {result.configured ? result.detail : "No health check path is configured."}
          </InfoBar>
        )}
      </CapabilityContainer>
    </>
  );
}

// ── Advisor recommendations / Diagnose and solve problems — real rule-based signals derived
// from this app's actual configuration and its real recent invocation outcomes (never
// random/synthetic data); core/azure_webapp_core.py's _advisor_recommendations/_diagnose_detectors.
function Advisor({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listAdvisorRecommendations(a.resourceGroup, a.name), [a.id]);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Advisor recommendations</div>
      <CapabilityContainer id="azure.functionapp.advisor" title="Recommendations"
        actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
        <ErrorBar error={error} />
        <table className="vy-grid">
          <thead><tr><th>Category</th><th>Impact</th><th>Recommendation</th></tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={3}><Spinner size="tiny" /></td></tr> : (data || []).length ? data.map((r, i) => (
              <tr key={i}><td>{r.category}</td><td>{r.impact}</td><td><div>{r.title}</div><div style={{ fontSize: 12, opacity: 0.8 }}>{r.detail}</div></td></tr>
            )) : <tr><td colSpan={3} className="vy-muted">No recommendations — this app looks healthy.</td></tr>}
          </tbody>
        </table>
      </CapabilityContainer>
    </>
  );
}

function DiagnoseAndSolve({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listDiagnoseDetectors(a.resourceGroup, a.name), [a.id]);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Diagnose and solve problems</div>
      <CapabilityContainer id="azure.functionapp.diagnosedetectors" title="Detectors"
        actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
        <ErrorBar error={error} />
        <table className="vy-grid">
          <thead><tr><th>Detector</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={3}><Spinner size="tiny" /></td></tr> : (data || []).map((d, i) => (
              <tr key={i}><td>{d.name}</td><td>{d.status}</td><td>{d.detail}</td></tr>
            ))}
          </tbody>
        </table>
      </CapabilityContainer>
    </>
  );
}

// ── Resource health — derived from the app's real `state` ────────────────────────────────
function ResourceHealthPanel({ a }) {
  const p = a.properties || {};
  const available = p.state === "Running";
  return (
    <>
      <div className="vy-panel-title">{a.name} | Resource health</div>
      <CapabilityContainer id="azure.functionapp.resourcehealth" title="Current health">
        <div className="vy-props">
          <KV label="Status" value={available ? "Available" : "Unavailable"} />
          <KV label="Reason" value={available ? "The app is Running." : `The app is ${p.state}.`} />
        </div>
      </CapabilityContainer>
    </>
  );
}

// ── Resource visualizer — this app's real linked resource references, as a list ──────────
function ResourceVisualizer({ a }) {
  const { data } = useAsync(() => api.listAppSettings(a.resourceGroup, a.name), [a.id]);
  const p = a.properties || {};
  const plan = p.serverFarmId?.split("/").pop();
  const storageSetting = (data || {}).AzureWebJobsStorage || "";
  const storageAccount = (storageSetting.match(/AccountName=([^;]+)/) || [])[1];
  const aiKey = (data || {}).APPINSIGHTS_INSTRUMENTATIONKEY;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Resource visualizer</div>
      <CapabilityContainer id="azure.functionapp.resourcevisualizer" title="Linked resources">
        <table className="vy-grid">
          <thead><tr><th>Resource</th><th>Type</th><th>Relationship</th></tr></thead>
          <tbody>
            <tr><td>{a.name}</td><td>Function App</td><td>This app</td></tr>
            {plan && <tr><td>{plan}</td><td>App Service plan</td><td>Hosts this app</td></tr>}
            {storageAccount && <tr><td>{storageAccount}</td><td>Storage account</td><td>AzureWebJobsStorage (runtime state)</td></tr>}
            {aiKey && <tr><td>{aiKey.slice(0, 12)}...</td><td>Application Insights</td><td>Instrumentation key — see Application Insights</td></tr>}
          </tbody>
        </table>
      </CapabilityContainer>
    </>
  );
}

// ── App files — read-only view of this app's real stored function code/bindings ──────────
function AppFiles({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listFunctions(a.resourceGroup, a.name), [a.id]);
  const [open, setOpen] = useState("host.json");
  const hostJson = JSON.stringify({ version: "2.0", extensionBundle: { id: "Microsoft.Azure.Functions.ExtensionBundle", version: "[4.*, 5.0.0)" } }, null, 2);
  const activeFn = (data || []).find((f) => open.startsWith(`${f.name}/`));
  const content = open === "host.json" ? hostJson
    : open.endsWith("/function.json") ? JSON.stringify(activeFn?.properties?.config || {}, null, 2)
    : activeFn?.properties?.files?.["__init__.py"] || "";
  return (
    <>
      <div className="vy-panel-title">{a.name} | App files</div>
      <CapabilityContainer id="azure.functionapp.appfiles" title="Files"
        actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
        <ErrorBar error={error} />
        <div style={{ display: "flex", gap: 24 }}>
          <div style={{ minWidth: 220 }}>
            <div style={{ fontWeight: 600, cursor: "pointer" }} role="button" tabIndex={0} onClick={() => setOpen("host.json")}>host.json</div>
            {loading ? <Spinner size="tiny" /> : (data || []).map((fn) => (
              <div key={fn.name}>
                <div style={{ fontWeight: 600, marginTop: 8 }}>{fn.name}/</div>
                <div style={{ paddingLeft: 12, cursor: "pointer" }} role="button" tabIndex={0} onClick={() => setOpen(`${fn.name}/function.json`)}>function.json</div>
                <div style={{ paddingLeft: 12, cursor: "pointer" }} role="button" tabIndex={0} onClick={() => setOpen(`${fn.name}/__init__.py`)}>__init__.py</div>
              </div>
            ))}
          </div>
          <pre className="vy-mono" style={{ flex: 1, maxHeight: 400, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 10, borderRadius: 4, fontSize: 12 }}>
            {content}
          </pre>
        </div>
      </CapabilityContainer>
    </>
  );
}

// ── Application Insights — this app's real instrumentation key + request stats derived from
// the real recorded invocation log (no real App Insights resource or Kusto query engine) ───
function ApplicationInsights({ a }) {
  const settings = useAsync(() => api.listAppSettings(a.resourceGroup, a.name), [a.id]);
  const logs = useInvocationLogs(a);
  const key = (settings.data || {}).APPINSIGHTS_INSTRUMENTATIONKEY;
  const rows = logs.data || [];
  const failed = rows.filter((r) => !r.ok).length;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Application Insights</div>
      <CapabilityContainer id="azure.functionapp.applicationinsights" title="Application Insights">
        {key ? (
          <>
            <KV label="Instrumentation key" value={key} />
            <div className="vy-props" style={{ marginTop: 10 }}>
              <KV label="Requests (recorded)" value={rows.length} />
              <KV label="Failed requests" value={failed} />
              <KV label="Failure rate" value={rows.length ? `${Math.round((failed / rows.length) * 100)}%` : "0%"} />
            </div>
          </>
        ) : <p style={{ fontSize: 13 }}>No Application Insights instrumentation key found on this app.</p>}
      </CapabilityContainer>
    </>
  );
}
