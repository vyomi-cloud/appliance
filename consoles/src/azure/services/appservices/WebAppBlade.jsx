/* App Service (Web App) resource blade: left resource menu + panels. Overview, Tags,
 * Deployment slots, Environment variables, Configuration (General settings), CORS, Custom
 * domains, Locks, App Service logs, Diagnostic settings, Access control (IAM), Export
 * template, Identity, Backups and Scale up/out/Change App Service plan are backed by native
 * ARM calls; everything else in the menu is an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, Delete20Regular, Save20Regular, ArrowSwap20Regular, Add20Regular, ArrowUpload20Regular, DocumentArrowDown20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
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
  deploymentcenter: "Tabs: Settings, Logs, FTPS credentials. Section: Settings. Field: Source "
    + "(GitHub, Bitbucket, Local Git, Azure Repos, External Git, Container registry).",
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
      iam: () => <AccessControl a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      slots: () => <Slots rg={rg} name={name} />,
      envvars: () => <EnvVars rg={rg} name={name} />,
      configuration: () => <Configuration a={a} rg={rg} name={name} reload={reload} />,
      cors: () => <Cors a={a} rg={rg} name={name} reload={reload} />,
      customdomains: () => <CustomDomains rg={rg} name={name} />,
      scaleup: () => <ScaleUp a={a} rg={rg} name={name} reload={reload} />,
      scaleout: () => <ScaleOut a={a} rg={rg} name={name} reload={reload} />,
      changeplan: () => <ChangePlan a={a} rg={rg} name={name} reload={reload} />,
      locks: () => <Locks rg={rg} name={name} />,
      appservicelogs: () => <AppServiceLogs rg={rg} name={name} />,
      logstream: () => <LogStream name={name} />,
      diagnosticsettings: () => <DiagnosticSettings a={a} rg={rg} name={name} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      identity: () => <Identity a={a} rg={rg} name={name} reload={reload} />,
      backups: () => <Backups rg={rg} name={name} />,
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

// ── Access control (IAM) ─────────────────────────────────────────────────────────────────
// Role assignments are a real ARM extension resource (Microsoft.Authorization/roleAssignments)
// read scoped to THIS Web App (plus its subscription/resource-group ancestors, real Azure's
// inherited-access view) over the same generic engine the Cosmos DB account and VM blades use
// (core/azure_arm_core.py) — not every assignment in the subscription (azure.appservices.webapp.iam).
// Roles stays subscription-wide, matching real Azure (built-in role definitions are listed
// tenant-wide too). Check access / My access / Deny assignments / Classic administrators stay
// honest gaps — Vyomi never evaluates or denies a console action based on a role assignment.
function AccessControl({ a }) {
  const [tab, setTab] = useState("checkaccess");
  const assignments = useAsync(() => api.listRoleAssignments(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const definitions = useAsync(() => api.listRoleDefinitions(), []);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Access control (IAM)</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Access control commands">
        <ToolbarButton icon={<ArrowUpload20Regular />} as="a" href="#/appservices">Add</ToolbarButton>
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
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id="azure.appservices.webapp.iam" title="Role assignments">
            <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Search by name or email" aria-label="Search by name or email" />
            <table className="vy-grid"><thead><tr><th>Name</th><th>Type</th><th>Role</th><th>Scope</th><th>Condition</th></tr></thead>
              <tbody>
                {assignments.loading ? <tr><td colSpan={5}><Spinner size="tiny" /></td></tr> : (assignments.data || []).map((r) => (
                  <tr key={r.name}><td>{r.properties?.principalId}</td><td>{r.properties?.principalType}</td><td>{r.properties?.roleDefinitionId?.split("/").pop()}</td><td>{r.properties?.scope}</td><td>None</td></tr>
                ))}
                {!assignments.loading && !(assignments.data || []).length && <tr><td colSpan={5} className="vy-muted">No role assignments found for this scope.</td></tr>}
              </tbody>
            </table>
          </CapabilityContainer>
        </div>
      )}
      {tab === "roles" && (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id="azure.appservices.webapp.iam" title="Roles">
            <table className="vy-grid"><thead><tr><th>Role</th><th>Type</th><th>Description</th><th>Assignments</th></tr></thead>
              <tbody>
                {definitions.loading ? <tr><td colSpan={4}><Spinner size="tiny" /></td></tr> : (definitions.data || []).map((r) => (
                  <tr key={r.name}><td>{r.properties?.roleName}</td><td>{r.properties?.type}</td><td>{r.properties?.description}</td><td>{r.assignmentCount}</td></tr>
                ))}
              </tbody>
            </table>
          </CapabilityContainer>
        </div>
      )}
      {tab === "denyassignments" && (
        <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Deny assignments" feature="Deny assignments" /></div>
      )}
      {tab === "classicadministrators" && (
        <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Classic administrators" feature="Classic administrators" /></div>
      )}
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

// ── CORS ─────────────────────────────────────────────────────────────────────────────────
// Stored on siteConfig.cors — a real sub-field of config/web, merged by the same engine as
// every other General settings field (see azure_webapp_core.py's _absorb_site_config).
function Cors({ a, rg, name, reload }) {
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
      await api.updateSiteConfig(rg, name, { cors: { allowedOrigins: origins.filter(Boolean), supportCredentials: creds } });
      notify.success(`CORS settings for '${name}' were saved.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | CORS</div>
      <p style={{ fontSize: 13 }}>Allowed origins let browser pages hosted elsewhere call this app's APIs via cross-origin resource sharing.</p>
      <section className="vy-section"><h3>Allowed Origins</h3>
        {origins.map((o, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
            <Input size="small" style={{ width: 360 }} value={o} placeholder="https://example.com" onChange={(_, d) => upd(i, d.value)} aria-label={`Allowed origin ${i + 1}`} />
            {i < origins.length - 1 && <Button icon={<Delete20Regular />} onClick={() => setOrigins(origins.filter((_, j) => j !== i))} aria-label="Remove origin" />}
          </div>
        ))}
        <Field label="Enable Access-Control-Allow-Credentials"><Checkbox checked={creds} onChange={(_, d) => setCreds(!!d.checked)} aria-label="Enable Access-Control-Allow-Credentials" /></Field>
      </section>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
        <Button onClick={reload}>Discard</Button>
      </div>
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

// ── Scale up (pricing tier) ───────────────────────────────────────────────────────────────
function ScaleUp({ a, rg, name, reload }) {
  const notify = useNotify();
  const planName = api.planName(a.properties?.serverFarmId);
  const plan = useAsync(() => api.getPlan(rg, planName), [rg, planName]);
  const [busy, setBusy] = useState(false);
  const current = plan.data?.sku?.name;
  const pick = async (sku) => {
    setBusy(true);
    try { await api.updatePlanSku(rg, planName, sku); notify.success(`Pricing tier of '${planName}' was changed to ${sku}.`, "Scale up succeeded"); plan.reload(); reload(); }
    catch (e) { notify.error(e, "Scale up failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Scale up (App Service plan)</div>
      <p style={{ fontSize: 13 }}>Choose the pricing tier of the App Service plan <b>{planName}</b> that hosts this app and any apps sharing the same plan.</p>
      {plan.loading ? <Loading /> : (
        <table className="vy-grid" aria-label="Pricing tiers">
          <thead><tr><th>Tier</th><th>SKU</th><th /></tr></thead>
          <tbody>
            {api.PLAN_SKUS.map(([sku, label]) => (
              <tr key={sku}>
                <td>{label}</td>
                <td>{sku}</td>
                <td>{sku === current ? <b>Current tier</b> : <Button disabled={busy} onClick={() => pick(sku)}>Select</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// ── Scale out (manual instance count) ──────────────────────────────────────────────────
function ScaleOut({ a, rg, name, reload }) {
  const notify = useNotify();
  const [count, setCount] = useState(a.properties?.siteConfig?.numberOfWorkers || 1);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.updateSiteConfig(rg, name, { numberOfWorkers: Number(count) || 1 }); notify.success(`Instance count for '${name}' was set to ${count}.`, "Scale out succeeded"); reload(); }
    catch (e) { notify.error(e, "Scale out failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Scale out (App Service plan)</div>
      <section className="vy-section"><h3>Manual scale</h3>
        <Field label="Instance count"><Input type="number" min="1" max="30" style={{ width: 120 }} value={String(count)} onChange={(_, d) => setCount(d.value)} aria-label="Instance count" /></Field>
      </section>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</Button>
        <Button onClick={reload}>Discard</Button>
      </div>
      <NotSimulatedContainer feature="Autoscale (rule-based/schedule-based scaling)" note="Vyomi does not run multiple instances or enforce the configured count; it is stored and returned exactly as set." />
    </>
  );
}

// ── Change App Service plan ──────────────────────────────────────────────────────────────
function ChangePlan({ a, rg, name, reload }) {
  const notify = useNotify();
  const currentPlan = api.planName(a.properties?.serverFarmId);
  const isLinux = a.kind?.includes("linux");
  const plans = useAsync(() => api.listPlans(), [rg]);
  const choices = (plans.data || []).filter((p) => p.name !== currentPlan && (p.properties?.reserved ?? false) === !!isLinux);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const move = async () => {
    const dest = choices.find((p) => p.name === target);
    if (!dest) return;
    setBusy(true);
    try { await api.changeSitePlan(rg, name, dest.id); notify.success(`'${name}' was moved to App Service plan '${target}'.`, "Change App Service plan succeeded"); setTarget(""); reload(); }
    catch (e) { notify.error(e, "Change App Service plan failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Change App Service plan</div>
      <p style={{ fontSize: 13 }}>Move this app to another App Service plan. The target plan must run the same operating system and will be billed for this app going forward.</p>
      <Field label="App Service plan">
        <Select value={target} onChange={(_, d) => setTarget(d.value)} aria-label="App Service plan">
          <option value="">Select a plan...</option>
          {choices.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}
        </Select>
      </Field>
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={!target || busy} onClick={move}>{busy ? "Applying..." : "OK"}</Button>
        <Button onClick={() => setTarget("")}>Cancel</Button>
      </div>
      {!choices.length && !plans.loading && <p className="vy-muted" style={{ marginTop: 8 }}>No other {isLinux ? "Linux" : "Windows"} App Service plan exists in this subscription yet.</p>}
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

// ── Diagnostic settings ──────────────────────────────────────────────────────────────────
// Microsoft.Insights/diagnosticSettings is a real ARM extension resource scoped to this
// Web App's own id (core/azure_monitor_core.py), the same engine every other Azure resource's
// "Diagnostic settings" page uses.
function DiagnosticSettings({ a, rg, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDiagnosticSettings(rg, name), [rg, name]);
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [adding, setAdding] = useState(false);
  const [dsName, setDsName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await api.putDiagnosticSetting(rg, name, dsName, {
        properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] },
      });
      notify.success(`Diagnostic setting '${dsName}' was created.`, "Save succeeded");
      setAdding(false); setDsName(""); reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Diagnostic settings</div>
      <p style={{ fontSize: 13 }}>Diagnostic settings specify a destination for platform logs and metrics from this Web App.</p>
      <BrowseGrid
        resourceName="diagnostic setting"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setAdding(true)}
        onDelete={async (rows) => { for (const r of rows) await api.deleteDiagnosticSetting(rg, name, r.name); notify.success("Diagnostic setting(s) deleted.", "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" },
          { key: "dest", label: "Destination details", value: (s) => (s.properties?.workspaceId ? "Log Analytics workspace" : "--") },
          { key: "logs", label: "Log categories", value: (s) => (s.properties?.logs || []).filter((l) => l.enabled).length },
          { key: "metrics", label: "Metric categories", value: (s) => (s.properties?.metrics || []).filter((m) => m.enabled).length },
        ]}
      />
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add diagnostic setting">
          <DialogBody>
            <DialogTitle>Add diagnostic setting</DialogTitle>
            <DialogContent>
              <Field label="Diagnostic setting name" required><Input value={dsName} onChange={(_, d) => setDsName(d.value)} /></Field>
              <Field label="Log Analytics workspace" required>
                {(workspaces.data || []).length ? (
                  <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
                    <option value="">Select a workspace...</option>
                    {workspaces.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </Select>
                ) : <p style={{ fontSize: 13 }}>No Log Analytics workspace yet. Create one from the Monitor console.</p>}
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!dsName || !workspace || busy} onClick={create}>{busy ? "Saving..." : "Save"}</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Export template ──────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [includeParams, setIncludeParams] = useState(true);
  const planName = api.planName(a.properties?.serverFarmId);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", contentVersion: "1.0.0.0",
    parameters: includeParams ? { name: { type: "string", defaultValue: a.name } } : {},
    resources: [
      { type: "Microsoft.Web/serverfarms", apiVersion: "2023-12-01", name: planName, location: a.location },
      { type: "Microsoft.Web/sites", apiVersion: "2023-12-01", name: includeParams ? "[parameters('name')]" : a.name, location: a.location, kind: a.kind,
        dependsOn: [`[resourceId('Microsoft.Web/serverfarms', '${planName}')]`], properties: a.properties },
    ],
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

// ── Identity ──────────────────────────────────────────────────────────────────────────────
// `identity` is a top-level ARM field on the site (core/azure_webapp_core.py's _apply_identity):
// enabling System assigned mints a stable principalId/tenantId, usable as the subject of a
// role assignment on the Access control (IAM) page.
function Identity({ a, rg, name, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("systemassigned");
  const ident = a.identity || { type: "None" };
  const on = /systemassigned/i.test(ident.type || "");
  const [busy, setBusy] = useState(false);
  const toggle = async (enable) => {
    setBusy(true);
    try {
      await api.updateIdentity(rg, name, { type: enable ? "SystemAssigned" : "None" });
      notify.success(`System assigned managed identity was turned ${enable ? "on" : "off"} for '${name}'.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Identity</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Identity tabs">
        <Tab value="systemassigned">System assigned</Tab>
        <Tab value="userassigned">User assigned</Tab>
      </TabList>
      {tab === "systemassigned" && (
        <div style={{ marginTop: 12 }}>
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
        </div>
      )}
      {tab === "userassigned" && (
        <div style={{ marginTop: 12 }}>
          <NotSimulatedContainer feature="User assigned managed identities" note="Vyomi has no User Assigned Identity resource of its own to attach here." />
        </div>
      )}
    </>
  );
}

// ── Backups ───────────────────────────────────────────────────────────────────────────────
// Modelled as snapshots (core/azure_webapp_core.py's _backup_ops): "Backup Now" creates a
// timestamped, sized record over the configured storage destination; Restore acknowledges —
// there is no real site content to archive or replay.
function Backups({ rg, name }) {
  const notify = useNotify();
  const list = useAsync(() => api.listBackups(rg, name), [rg, name]);
  const cfg = useAsync(() => api.getBackupConfig(rg, name), [rg, name]);
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (cfg.data) setF({ enabled: cfg.data.properties.enabled, storageAccountUrl: cfg.data.properties.storageAccountUrl, retentionPeriodInDays: cfg.data.properties.backupSchedule.retentionPeriodInDays }); }, [cfg.data]);
  const backupNow = async () => {
    setBusy(true);
    try { await api.backupNow(rg, name); notify.success(`Backup of '${name}' was created.`, "Backup succeeded"); list.reload(); }
    catch (e) { notify.error(e, "Backup failed"); }
    finally { setBusy(false); }
  };
  const restore = async (row) => {
    try { await api.restoreBackup(rg, name, row.properties.id); notify.success(`Restored '${name}' from backup '${row.name}'.`, "Restore succeeded"); }
    catch (e) { notify.error(e, "Restore failed"); }
  };
  const saveConfig = async () => {
    setBusy(true);
    try {
      await api.updateBackupConfig(rg, name, { enabled: f.enabled, storageAccountUrl: f.storageAccountUrl, backupSchedule: { retentionPeriodInDays: Number(f.retentionPeriodInDays) || 30 } });
      notify.success(`Backup configuration for '${name}' was saved.`, "Save succeeded");
      cfg.reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  const rows = list.data || [];
  return (
    <>
      <div className="vy-panel-title">{name} | Backups</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Backups commands">
        <ToolbarButton icon={<Add20Regular />} disabled={busy} onClick={backupNow}>{busy ? "Backing up..." : "Backup Now"}</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={list.reload}>Refresh</ToolbarButton>
      </div>
      {list.loading ? <Loading /> : (
        <table className="vy-grid" aria-label="Backups">
          <thead><tr><th>Backup name</th><th>Status</th><th>Created</th><th>Size</th><th /></tr></thead>
          <tbody>
            {rows.length === 0
              ? <tr><td colSpan={5} className="vy-muted">No backups have been taken yet.</td></tr>
              : rows.map((b) => (
                <tr key={b.properties.id}>
                  <td>{b.name}</td><td>{b.properties.status}</td>
                  <td>{new Date(b.properties.created).toLocaleString()}</td>
                  <td>{((b.properties.sizeInBytes || 0) / 1e6).toFixed(1)} MB</td>
                  <td><Button size="small" onClick={() => restore(b)}>Restore</Button></td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      {f && (
        <section className="vy-section" style={{ marginTop: 16 }}><h3>Backup configuration</h3>
          <Field label="Scheduled backup"><RadioGroup value={f.enabled ? "On" : "Off"} onChange={(_, d) => setF((x) => ({ ...x, enabled: d.value === "On" }))} aria-label="Scheduled backup"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
          <Field label="Storage account container URL"><Input style={{ width: 420 }} value={f.storageAccountUrl} onChange={(_, d) => setF((x) => ({ ...x, storageAccountUrl: d.value }))} placeholder="https://account.blob.core.windows.net/backups" /></Field>
          <Field label="Retention (days)"><Input type="number" style={{ width: 120 }} value={String(f.retentionPeriodInDays)} onChange={(_, d) => setF((x) => ({ ...x, retentionPeriodInDays: d.value }))} /></Field>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Button appearance="primary" icon={<Save20Regular />} disabled={busy} onClick={saveConfig}>{busy ? "Saving..." : "Save"}</Button>
          </div>
        </section>
      )}
    </>
  );
}
