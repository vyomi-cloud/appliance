/* App Service (Web App) resource blade: left resource menu + panels. Overview, Tags,
 * Deployment slots, Environment variables, Configuration (General settings), Custom
 * domains, Locks and App Service logs are backed by native ARM calls; everything else in
 * the menu is an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, Delete20Regular, Save20Regular, ArrowSwap20Regular, Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Essentials, Glyph, KV, Loading, NotSimulatedContainer } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

/** Resource menu: [id, label] | {group, items}. Matches the real Web App blade's nav exactly
 * (labels double as the "{name} | Label" page titles the captured spec records). */
export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "defender", label: "Microsoft Defender for Cloud" },
  { id: "events", label: "Events (preview)" },
  { id: "visualizer", label: "Resource visualizer" },
  { group: "Deployment", items: [{ id: "slots", label: "Deployment slots" }, { id: "deploymentcenter", label: "Deployment Center" }] },
  { group: "Settings", items: [
    { id: "envvars", label: "Environment variables" }, { id: "configuration", label: "Configuration" },
    { id: "authentication", label: "Authentication" }, { id: "appinsights", label: "Application Insights" },
    { id: "identity", label: "Identity" }, { id: "backups", label: "Backups" },
    { id: "customdomains", label: "Custom domains" }, { id: "certificates", label: "Certificates" },
    { id: "networking", label: "Networking" }, { id: "scaleup", label: "Scale up (App Service plan)" },
    { id: "scaleout", label: "Scale out (App Service plan)" }, { id: "webjobs", label: "WebJobs" },
    { id: "serviceconnector", label: "Service Connector" }, { id: "locks", label: "Locks" },
  ] },
  { group: "App Service plan", items: [
    { id: "appserviceplan", label: "App Service plan" }, { id: "quotas", label: "Quotas" }, { id: "changeplan", label: "Change App Service plan" },
  ] },
  { group: "Development Tools", items: [
    { id: "cloneapp", label: "Clone App" }, { id: "console", label: "Console" }, { id: "advancedtools", label: "Advanced Tools" },
    { id: "appeditor", label: "App Service Editor (Preview)" }, { id: "extensions", label: "Extensions" },
  ] },
  { group: "API", items: [
    { id: "apimanagement", label: "API Management" }, { id: "apidefinition", label: "API definition" }, { id: "cors", label: "CORS" },
  ] },
  { group: "Monitoring", items: [
    { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "logs", label: "Logs" },
    { id: "advisor", label: "Advisor recommendations" }, { id: "healthcheck", label: "Health check" },
    { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "appservicelogs", label: "App Service logs" },
    { id: "logstream", label: "Log stream" }, { id: "processexplorer", label: "Process explorer" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Support + troubleshooting", items: [{ id: "resourcehealth", label: "Resource health" }, { id: "supportrequest", label: "New support request" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

// Extra honest text for panels whose real-portal page carries more than a bare title, so
// every spec tab/section/field is at least declared a gap (never silently missing).
const RICH_NOTES = {
  iam: "Tabs: Check access, Role assignments, Roles, Deny assignments, Classic administrators. "
    + "Sections: My access, Check access, Role assignments, Roles, Deny assignments. Fields: View my access, Check access.",
  deploymentcenter: "Tabs: Settings, Logs, FTPS credentials. Section: Settings. Field: Source "
    + "(GitHub, Bitbucket, Local Git, Azure Repos, External Git, Container registry).",
  exporttemplate: "Tabs: ARM Template, Bicep, Terraform. Section: Template. Field: Include parameters.",
};

export default function WebAppBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const site = useAsync(() => api.getSite(rg, name), [rg, name]);
  const self = `#/appservices/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (site.data) remember({ name, type: "App Service", href: self }); }, [!!site.data, self]);

  let body;
  if (site.loading && !site.data) body = <Loading />;
  else if (site.error) body = <><ErrorBar error={site.error} title="Failed to load the app service" /><Link href="#/appservices">Back to App Services</Link></>;
  else {
    const a = site.data, reload = site.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog rg={rg} name={name} />,
      tags: () => <Tags a={a} reload={reload} />,
      slots: () => <Slots rg={rg} name={name} />,
      envvars: () => <EnvVars rg={rg} name={name} />,
      configuration: () => <Configuration a={a} rg={rg} name={name} reload={reload} />,
      customdomains: () => <CustomDomains rg={rg} name={name} />,
      locks: () => <Locks rg={rg} name={name} />,
      appservicelogs: () => <AppServiceLogs rg={rg} name={name} />,
      logstream: () => <LogStream name={name} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{name} | {LABEL[panel] || panel}</div>
        <NotSimulatedContainer feature={LABEL[panel] || panel} note={RICH_NOTES[panel]} />
      </>
    );
  }

  return (
    <ResourceBlade
      title={name} subtitle="App Service" glyph={<Glyph id="appservices" />} closeHref="#/appservices"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ─────────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [tab, setTab] = useState("properties");
  const [del, setDel] = useState(false);
  const [swap, setSwap] = useState(false);
  const p = a.properties || {};

  const act = async (fn, label) => {
    try { await fn(); notify.success(`'${a.name}' ${label}.`, `${label[0].toUpperCase()}${label.slice(1)}`); reload(); }
    catch (e) { notify.error(e, `${label} failed`); }
  };

  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton as="a" href={`https://${p.defaultHostName}`} target="_blank" rel="noreferrer">Browse</ToolbarButton>
        {p.state === "Running"
          ? <ToolbarButton onClick={() => act(() => api.stopSite(a.resourceGroup, a.name), "stopped")}>Stop</ToolbarButton>
          : <ToolbarButton onClick={() => act(() => api.startSite(a.resourceGroup, a.name), "started")}>Start</ToolbarButton>}
        <ToolbarButton icon={<ArrowSwap20Regular />} onClick={() => setSwap(true)}>Swap</ToolbarButton>
        <ToolbarButton onClick={() => act(() => api.restartSite(a.resourceGroup, a.name), "restarted")}>Restart</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
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
          ["Default domain", <Link href={`https://${p.defaultHostName}`} target="_blank" rel="noreferrer">{p.defaultHostName}</Link>],
          ["App Service Plan", <Link href={`${self}/appserviceplan`}>{api.planName(p.serverFarmId)}</Link>],
          ["Operating System", a.kind?.includes("linux") ? "Linux" : "Windows"],
          ["Health Check", p.siteConfig?.healthCheckPath || "--"],
          ["Tags", Object.entries(a.tags || {}).length ? Object.entries(a.tags).map(([k, v]) => `${k}:${v}`).join(", ") : <Link href={`${self}/tags`}>Add tags</Link>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="properties">Properties</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="logs">Logs</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="notifications">Notifications</Tab>
        <Tab value="recommendations">Recommendations</Tab>
      </TabList>
      {tab === "properties" && (
        <div className="vy-props" style={{ marginTop: 12 }}>
          <section className="vy-section"><h3>Web app</h3>
            <KV label="Name" value={a.name} /><KV label="Publishing model" value="Web Deploy, GIT, GitHub" /><KV label="Runtime Stack" value={p.runtime || p.siteConfig?.linuxFxVersion || p.siteConfig?.netFrameworkVersion} />
          </section>
          <section className="vy-section"><h3>Deployment Center</h3>
            <KV label="Deployment logs" value="--" /><KV label="Last deployment" value="--" /><KV label="Deployment provider" value={p.siteConfig?.scmType === "None" ? "None" : p.siteConfig?.scmType} />
          </section>
          <section className="vy-section"><h3>Application Insights</h3><KV label="Name" value="--" /></section>
          <section className="vy-section"><h3>Hosting</h3>
            <KV label="Plan Type" value={api.appType(a.kind)} /><KV label="Name" value={api.planName(p.serverFarmId)} />
            <KV label="Operating System" value={a.kind?.includes("linux") ? "Linux" : "Windows"} /><KV label="Instance Count" value={p.siteConfig?.numberOfWorkers} />
            <KV label="SKU and size" value="--" />
          </section>
          <section className="vy-section"><h3>Domains</h3><KV label="Default domain" value={p.defaultHostName} /><KV label="Custom domain" value={(p.hostNames || []).find((h) => h !== p.defaultHostName) || "0 custom domains"} /></section>
          <section className="vy-section"><h3>Networking</h3><KV label="Virtual IP address" value={p.outboundIpAddresses?.split(",")[0]} /><KV label="Outbound IP addresses" value={p.outboundIpAddresses} /><KV label="Additional Outbound IP addresses" value={p.possibleOutboundIpAddresses} /></section>
        </div>
      )}
      {tab === "monitoring" && <NotSimulatedContainer feature="App Service monitoring (requests, response time, errors)" />}
      {tab === "logs" && <NotSimulatedContainer feature="The resource's Logs (Log Analytics queries)" />}
      {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
      {tab === "notifications" && <NotSimulatedContainer feature="Notifications" />}
      {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="app service" names={[a.name]}
        onConfirm={async () => { await api.deleteSite(a.resourceGroup, a.name); forget(self); notify.success(`App service '${a.name}' was deleted.`, "Delete succeeded"); navigate("appservices"); }} />
      <SwapDialog open={swap} onClose={() => setSwap(false)} rg={a.resourceGroup} name={a.name} onDone={reload} />
    </>
  );
}

function SwapDialog({ open, onClose, rg, name, onDone }) {
  const notify = useNotify();
  const slots = useAsync(() => (open ? api.listSlots(rg, name) : Promise.resolve([])), [open]);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await api.swapSlot(rg, name, target); notify.success(`Swapped production with '${target}'.`, "Swap succeeded"); onDone(); onClose(); }
    catch (e) { notify.error(e, "Swap failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Swap deployment slots">
        <DialogBody>
          <DialogTitle>Swap</DialogTitle>
          <DialogContent>
            <Field label="Source" required><Input readOnly value="production" /></Field>
            <Field label="Target" required>
              <Select value={target} onChange={(_, d) => setTarget(d.value)} aria-label="Target slot">
                <option value="">Select a slot...</option>
                {(slots.data || []).map((s) => <option key={s.name} value={s.name.split("/").pop()}>{s.name.split("/").pop()}</option>)}
              </Select>
            </Field>
          </DialogContent>
          <DialogActions><Button appearance="primary" icon={<ArrowSwap20Regular />} disabled={!target || busy} onClick={go}>{busy ? "Swapping..." : "Swap"}</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Activity log ─────────────────────────────────────────────────────────────────────────
function ActivityLog({ rg, name }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(rg, name), [rg, name]);
  const rows = (data || []).map((e) => ({
    key: `${e.id}`,
    op: e.operationName?.localizedValue || e.operationName?.value || "--",
    status: e.status?.localizedValue || e.status?.value || "--",
    time: e.eventTimestamp ? new Date(e.eventTimestamp).toLocaleString() : "--",
    ts: e.eventTimestamp || "--",
    sub: e.subscriptionId || "--",
    caller: e.caller || "--",
  }));
  return (
    <>
      <div className="vy-panel-title">{name} | Activity log</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      {loading ? <Loading /> : error ? <ErrorBar error={error} title="Failed to load the activity log" /> : (
        <table className="vy-grid" aria-label="Activity log">
          <thead><tr><th>Operation name</th><th>Status</th><th>Time</th><th>Time stamp</th><th>Subscription</th><th>Event initiated by</th></tr></thead>
          <tbody>
            {rows.length === 0
              ? <tr><td colSpan={6}>No events to display</td></tr>
              : rows.map((r) => <tr key={r.key}><td>{r.op}</td><td>{r.status}</td><td>{r.time}</td><td>{r.ts}</td><td>{r.sub}</td><td>{r.caller}</td></tr>)}
          </tbody>
        </table>
      )}
      <NotSimulatedContainer feature="Activity log filters and export"
        note={("Filters (Management Group, Subscription, Event severity, Timespan, Resource group, Resource, Add Filter) and the "
          + "Edit columns / Export Activity Logs / Download as CSV / Insights / Feedback / Pin current filters / Reset filters actions are "
          + "not simulated; Vyomi lists the real create/update/delete/action operations performed on this Web App.")} />
    </>
  );
}

// ── Tags ─────────────────────────────────────────────────────────────────────────────────
function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const upd = (i, k, v) => {
    const xs = rows.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "" });
    setRows(xs);
  };
  const apply = async () => {
    setBusy(true);
    try {
      await api.updateSiteTags(a.resourceGroup, a.name, Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])), a);
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Tags</div>
      <div className="vy-panel-title">Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <table className="vy-grid" aria-label="Tags" style={{ maxWidth: 700 }}>
        <thead><tr><th>Name</th><th>Value</th></tr></thead>
        <tbody>
          {rows.map((t, i) => (
            <tr key={i}>
              <td><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></td>
              <td><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
      </div>
    </>
  );
}

// ── Deployment slots ─────────────────────────────────────────────────────────────────────
function Slots({ rg, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listSlots(rg, name), [rg, name]);
  const [adding, setAdding] = useState(false);
  const [swap, setSwap] = useState(false);
  const [slotName, setSlotName] = useState("");
  const [busy, setBusy] = useState(false);
  const rows = [{ name: "production", status: "Running", traffic: "100%" }, ...(data || []).map((s) => ({ name: s.name.split("/").pop(), status: s.properties?.state, traffic: "0%" }))];
  const create = async () => {
    setBusy(true);
    try { await api.createSlot(rg, name, slotName); notify.success(`Deployment slot '${slotName}' was created.`, "Add slot succeeded"); setAdding(false); setSlotName(""); reload(); }
    catch (e) { notify.error(e, "Add slot failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Deployment slots</div>
      <BrowseGrid
        resourceName="deployment slot"
        items={rows}
        loading={loading} error={error} onRefresh={reload}
        onCreate={() => setAdding(true)}
        onDelete={async (xs) => { for (const r of xs.filter((x) => x.name !== "production")) await api.deleteSlot(rg, name, r.name); notify.success("Deployment slot(s) deleted.", "Delete succeeded"); reload(); }}
        extraCommands={<ToolbarButton icon={<ArrowSwap20Regular />} disabled={!data?.length} onClick={() => setSwap(true)}>Swap</ToolbarButton>}
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status" },
          { key: "plan", label: "App service plan", value: () => api.planName(name) + "-plan" },
          { key: "traffic", label: "Traffic %" },
        ]}
      />
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add slot">
          <DialogBody>
            <DialogTitle>Add Slot</DialogTitle>
            <DialogContent><Field label="Slot name" required><Input value={slotName} onChange={(_, d) => setSlotName(d.value)} /></Field></DialogContent>
            <DialogActions><Button appearance="primary" icon={<Add20Regular />} disabled={!slotName || busy} onClick={create}>{busy ? "Adding..." : "Add"}</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <SwapDialog open={swap} onClose={() => setSwap(false)} rg={rg} name={name} onDone={reload} />
    </>
  );
}

// ── Environment variables (App settings / Connection strings) ──────────────────────────
function EnvVars({ rg, name }) {
  const [tab, setTab] = useState("appsettings");
  return (
    <>
      <div className="vy-panel-title">{name} | Environment variables</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Environment variables tabs">
        <Tab value="appsettings">App settings</Tab>
        <Tab value="connectionstrings">Connection strings</Tab>
      </TabList>
      {tab === "appsettings"
        ? <KvEditor rg={rg} name={name} title="App settings" get={api.getAppSettings} update={api.updateAppSettings} extraCol="Deployment slot setting" />
        : <KvEditor rg={rg} name={name} title="Connection strings" get={api.getConnectionStrings} update={api.updateConnectionStrings} extraCol="Type" connStrings />}
    </>
  );
}

function KvEditor({ rg, name, title, get, update, extraCol, connStrings }) {
  const notify = useNotify();
  const { data, loading, reload } = useAsync(() => get(rg, name), [rg, name, title]);
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const entries = Object.entries(data || {});
    setRows([...entries.map(([k, v]) => ({ name: k, value: connStrings ? (v.value ?? v) : v, slot: false })), { name: "", value: "", slot: false }]);
  }, [data]);
  const upd = (i, k, v) => {
    const xs = rows.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "", slot: false });
    setRows(xs);
  };
  const apply = async () => {
    setBusy(true);
    try {
      const body = Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, connStrings ? { value: t.value, type: "Custom" } : t.value]));
      await update(rg, name, body);
      notify.success(`${title} were updated.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  if (loading) return <Loading />;
  return (
    <div style={{ marginTop: 12 }}>
      <div className="vy-panel-title">{title}</div>
      <div className="vy-cmdbar" role="toolbar" aria-label={`${title} commands`}>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setRows((r) => [{ name: "", value: "", slot: false }, ...r])}>Add</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <table className="vy-grid" aria-label={title}>
        <thead><tr><th>Name</th><th>Value</th><th>{extraCol}</th></tr></thead>
        <tbody>
          {rows.map((t, i) => (
            <tr key={i}>
              <td><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label="Name" /></td>
              <td><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label="Value" /></td>
              <td>{connStrings ? "Custom" : <Checkbox checked={t.slot} onChange={(_, d) => upd(i, "slot", !!d.checked)} aria-label="Deployment slot setting" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="vy-panel-title" style={{ fontSize: 13, fontWeight: 400, marginTop: 10 }}>Add/Edit application setting</div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={reload}>Discard</Button>
      </div>
    </div>
  );
}

// ── Configuration (General settings) ────────────────────────────────────────────────────
const STACKS = { "PYTHON": "Python", "NODE": "Node", "JAVA": "Java", "PHP": "PHP", "DOTNETCORE": "" };

function Configuration({ a, rg, name, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("general");
  const fx = a.properties?.siteConfig?.linuxFxVersion || "";
  const [stack, major] = fx.split("|");
  const [f, setF] = useState(() => ({ ...a.properties.siteConfig, httpsOnly: a.properties.httpsOnly, clientAffinityEnabled: a.properties.clientAffinityEnabled }));
  const [busy, setBusy] = useState(false);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const onoff = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value === "On" }));
  const save = async () => {
    setBusy(true);
    try {
      const { httpsOnly, clientAffinityEnabled, ...siteConfig } = f;
      await api.updateSiteConfig(rg, name, siteConfig);
      await api.createSite(rg, name, { ...a, properties: { ...a.properties, httpsOnly, clientAffinityEnabled } });
      notify.success(`Configuration for '${name}' was saved.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Configuration</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Configuration tabs">
        <Tab value="general">General settings</Tab>
        <Tab value="defaultdocs">Default documents</Tab>
        <Tab value="pathmappings">Path mappings</Tab>
        <Tab value="errorpages">Error pages (preview)</Tab>
      </TabList>
      {tab === "general" && (
        <div className="vy-props" style={{ marginTop: 12 }}>
          <section className="vy-section"><h3>Stack settings</h3>
            <Field label="Stack"><Select value={STACKS[stack] ?? ""} onChange={(_, d) => setF((x) => ({ ...x, linuxFxVersion: d.value ? `${Object.entries(STACKS).find(([, v]) => v === d.value)[0]}|${major || "latest"}` : "" }))} aria-label="Stack">
              <option value="">.NET</option><option value="Python">Python</option><option value="Node">Node</option><option value="PHP">PHP</option><option value="Java">Java</option>
            </Select></Field>
            <Field label="Major version"><Input value={major || ""} onChange={(_, d) => setF((x) => ({ ...x, linuxFxVersion: stack ? `${stack}|${d.value}` : x.linuxFxVersion }))} aria-label="Major version" /></Field>
            <Field label="Minor version"><Input value="" aria-label="Minor version" /></Field>
            <Field label="Startup Command"><Input value={f.appCommandLine || ""} onChange={set("appCommandLine")} aria-label="Startup Command" /></Field>
          </section>
          <section className="vy-section"><h3>Platform settings</h3>
            <Field label="Platform"><RadioGroup value={f.use32BitWorkerProcess ? "32 Bit" : "64 Bit"} onChange={(_, d) => setF((x) => ({ ...x, use32BitWorkerProcess: d.value === "32 Bit" }))} aria-label="Platform"><Radio value="32 Bit" label="32 Bit" /><Radio value="64 Bit" label="64 Bit" /></RadioGroup></Field>
            <Field label="SCM Basic Auth Publishing Credentials"><RadioGroup value={f.scmBasicAuthEnabled ? "On" : "Off"} onChange={onoff("scmBasicAuthEnabled")} aria-label="SCM Basic Auth Publishing Credentials"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
            <Field label="FTP Basic Auth Publishing Credentials"><RadioGroup value={f.ftpBasicAuthEnabled ? "On" : "Off"} onChange={onoff("ftpBasicAuthEnabled")} aria-label="FTP Basic Auth Publishing Credentials"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
            <Field label="FTP state"><Select value={f.ftpsState} onChange={set("ftpsState")} aria-label="FTP state"><option value="AllAllowed">All allowed</option><option value="FtpsOnly">FTPS only</option><option value="Disabled">Disabled</option></Select></Field>
            <Field label="HTTP version"><Select value={f.http20Enabled ? "2.0" : "1.1"} onChange={(_, d) => setF((x) => ({ ...x, http20Enabled: d.value === "2.0" }))} aria-label="HTTP version"><option value="1.1">1.1</option><option value="2.0">2.0</option></Select></Field>
            <Field label="Web sockets"><RadioGroup value={f.webSocketsEnabled ? "On" : "Off"} onChange={onoff("webSocketsEnabled")} aria-label="Web sockets"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
            <Field label="Always on"><RadioGroup value={f.alwaysOn ? "On" : "Off"} onChange={onoff("alwaysOn")} aria-label="Always on"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
            <Field label="Session affinity"><RadioGroup value={f.sessionAffinityEnabled ? "On" : "Off"} onChange={onoff("sessionAffinityEnabled")} aria-label="Session affinity"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
            <Field label="HTTPS Only"><RadioGroup value={f.httpsOnly ? "On" : "Off"} onChange={onoff("httpsOnly")} aria-label="HTTPS Only"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
            <Field label="Minimum Inbound TLS Version"><Select value={f.minTlsVersion} onChange={set("minTlsVersion")} aria-label="Minimum Inbound TLS Version"><option value="1.0">1.0</option><option value="1.1">1.1</option><option value="1.2">1.2</option><option value="1.3">1.3</option></Select></Field>
          </section>
          <section className="vy-section"><h3>Debugging</h3>
            <Field label="Remote debugging"><RadioGroup value={f.remoteDebuggingEnabled ? "On" : "Off"} onChange={onoff("remoteDebuggingEnabled")} aria-label="Remote debugging"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
          </section>
          <section className="vy-section"><h3>Incoming client certificates</h3>
            <Field label="Client certificate mode"><RadioGroup value={f.clientCertMode} onChange={set("clientCertMode")} aria-label="Client certificate mode">
              <Radio value="Required" label="Required" /><Radio value="Optional" label="Optional" /><Radio value="OptionalInteractiveUser" label="Optional Interactive User" /><Radio value="Ignore" label="Ignore" />
            </RadioGroup></Field>
          </section>
          <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
            <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
            <Button onClick={reload}>Discard</Button>
          </div>
        </div>
      )}
      {tab === "defaultdocs" && <NotSimulatedContainer feature="Default documents" />}
      {tab === "pathmappings" && <NotSimulatedContainer feature="Path mappings" />}
      {tab === "errorpages" && <NotSimulatedContainer feature="Error pages (preview)" />}
    </>
  );
}

// ── Custom domains ───────────────────────────────────────────────────────────────────────
function CustomDomains({ rg, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listCustomDomains(rg, name), [rg, name]);
  const [adding, setAdding] = useState(false);
  const [host, setHost] = useState("");
  const [busy, setBusy] = useState(false);
  const add = async () => {
    setBusy(true);
    try { await api.addCustomDomain(rg, name, host); notify.success(`Custom domain '${host}' was added.`, "Add custom domain succeeded"); setAdding(false); setHost(""); reload(); }
    catch (e) { notify.error(e, "Add custom domain failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Custom domains</div>
      <BrowseGrid
        resourceName="custom domain"
        items={(data || []).map((d) => ({ ...d, status: "Secure", binding: d.properties?.sslState === "SniEnabled" ? "SNI SSL" : "Not configured", cert: "--" }))}
        loading={loading} error={error} onRefresh={reload}
        onCreate={() => setAdding(true)}
        onDelete={async (xs) => { for (const r of xs) await api.removeCustomDomain(rg, name, r.name); notify.success("Custom domain(s) removed.", "Delete succeeded"); reload(); }}
        columns={[{ key: "name", label: "Custom domain" }, { key: "status", label: "Status" }, { key: "binding", label: "Binding type" }, { key: "cert", label: "Certificate" }]}
      />
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add custom domain">
          <DialogBody>
            <DialogTitle>Add custom domain</DialogTitle>
            <DialogContent><Field label="Custom domain" required><Input value={host} onChange={(_, d) => setHost(d.value)} placeholder="www.example.com" /></Field></DialogContent>
            <DialogActions><Button appearance="primary" icon={<Add20Regular />} disabled={!host || busy} onClick={add}>{busy ? "Adding..." : "Add"}</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Locks ────────────────────────────────────────────────────────────────────────────────
function Locks({ rg, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(rg, name), [rg, name]);
  const [f, setF] = useState({ name: "", level: "CanNotDelete", notes: "" });
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(false);
  const add = async () => {
    setBusy(true);
    try { await api.addLock(rg, name, f.name, f.level, f.notes); notify.success(`Lock '${f.name}' was added.`, "Add succeeded"); setF({ name: "", level: "CanNotDelete", notes: "" }); reload(); }
    catch (e) { notify.error(e, "Add lock failed"); }
    finally { setBusy(false); }
  };
  const rows = (data || []).map((l) => ({ ...l, scope: name, level: l.properties?.level === "ReadOnly" ? "Read-only" : "Delete" }))
    .filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase()));
  return (
    <>
      <div className="vy-panel-title">{name} | Locks</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Locks commands">
        <ToolbarButton icon={<Add20Regular />} disabled={!f.name || busy} onClick={add}>{busy ? "Adding..." : "Add"}</ToolbarButton>
        <ToolbarButton disabled>Subscription</ToolbarButton>
        <ToolbarButton disabled>Resource group</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setFeedback(true)}>Feedback</ToolbarButton>
      </div>
      <Input size="small" style={{ width: 260, margin: "8px 0" }} placeholder="Search to filter items..." aria-label="Search to filter items..." value={search} onChange={(_, d) => setSearch(d.value)} />
      <div className="vy-panel-title" style={{ fontSize: 13, fontWeight: 400 }}>Add lock</div>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
        <Field label="Lock name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} /></Field>
        <Field label="Lock type" required><Select value={f.level} onChange={(_, d) => setF((x) => ({ ...x, level: d.value }))} aria-label="Lock type"><option value="ReadOnly">Read-only</option><option value="CanNotDelete">Delete</option></Select></Field>
        <Field label="Notes"><Textarea value={f.notes} onChange={(_, d) => setF((x) => ({ ...x, notes: d.value }))} /></Field>
      </div>
      <BrowseGrid
        resourceName="lock"
        items={rows}
        loading={loading} error={error} onRefresh={reload}
        onDelete={async (xs) => { for (const r of xs) await api.removeLock(rg, name, r.name); notify.success("Lock(s) removed.", "Delete succeeded"); reload(); }}
        columns={[{ key: "name", label: "Lock name" }, { key: "level", label: "Lock type" }, { key: "scope", label: "Scope" }, { key: "notes", label: "Notes", value: (r) => r.properties?.notes }]}
        emptyAction={null}
      />
      <Dialog open={feedback} onOpenChange={(_, d) => !d.open && setFeedback(false)}>
        <DialogSurface aria-label="Feedback">
          <DialogBody>
            <DialogTitle>Feedback</DialogTitle>
            <DialogContent><Textarea placeholder="Tell us about your experience..." style={{ width: "100%" }} /></DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={() => { notify.success("Thanks for your feedback.", "Feedback sent"); setFeedback(false); }}>Submit</Button>
              <Button onClick={() => setFeedback(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── App Service logs ─────────────────────────────────────────────────────────────────────
function AppServiceLogs({ rg, name }) {
  const notify = useNotify();
  const { data, loading, reload } = useAsync(() => api.getAppServiceLogs(rg, name), [rg, name]);
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setF({ level: data.properties.applicationLogs.fileSystem.level, quota: data.properties.httpLogs.fileSystem.retentionInMb, retention: data.properties.httpLogs.fileSystem.retentionInDays }); }, [data]);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateAppServiceLogs(rg, name, { applicationLogs: { fileSystem: { level: f.level } }, httpLogs: { fileSystem: { retentionInMb: Number(f.quota) || 35, retentionInDays: Number(f.retention) || 0, enabled: true } } });
      notify.success(`App Service logs for '${name}' were saved.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  if (loading || !f) return <Loading />;
  return (
    <>
      <div className="vy-panel-title">{name} | App Service logs</div>
      <section className="vy-section"><h3>App Service logs</h3>
        <Field label="Application logging"><RadioGroup value={f.level === "Off" ? "Off" : "File System"} onChange={(_, d) => setF((x) => ({ ...x, level: d.value === "Off" ? "Off" : "Verbose" }))} aria-label="Application logging">
          <Radio value="Off" label="Off" /><Radio value="File System" label="File System" />
        </RadioGroup></Field>
        <Field label="Quota (MB)"><Input type="number" value={String(f.quota)} onChange={(_, d) => setF((x) => ({ ...x, quota: d.value }))} aria-label="Quota (MB)" /></Field>
        <Field label="Retention Period (Days)"><Input type="number" value={String(f.retention)} onChange={(_, d) => setF((x) => ({ ...x, retention: d.value }))} aria-label="Retention Period (Days)" /></Field>
      </section>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
        <Button onClick={reload}>Discard</Button>
      </div>
    </>
  );
}

// ── Log stream ───────────────────────────────────────────────────────────────────────────
function LogStream({ name }) {
  const [type, setType] = useState("App Service logs");
  return (
    <>
      <div className="vy-panel-title">{name} | Log stream</div>
      <section className="vy-section"><h3>Log stream</h3>
        <Field label="Log type"><Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Log type"><option>App Service logs</option><option>Platform logs</option></Select></Field>
      </section>
      <NotSimulatedContainer feature="Live log streaming" note={"Vyomi stores App Service log settings; there is no running workload to tail a live stream from."} />
    </>
  );
}
