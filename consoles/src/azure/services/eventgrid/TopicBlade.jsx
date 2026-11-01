/* Event Grid topic resource blade: left resource menu + panels. Overview, Tags, Access keys,
 * Event Subscriptions, Networking, Identity, Configuration, Properties, Activity log, Locks,
 * Access control (IAM) and the ARM Template tab of Export template are backed by native ARM
 * calls (the Access control/Export template pattern mirrors the Cosmos DB account blade); the
 * remaining monitoring/automation/support menu items are honest NotSimulated panels
 * (core/capabilities/azure/eventgrid.json). */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowDownload20Regular, Copy16Regular, Delete20Regular, Eye16Regular, EyeOff16Regular, ArrowRight20Regular, Save20Regular, Dismiss20Regular, Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { downloadCsv, Essentials, fmtDate, Glyph, InfoBar, KV, Loading, ErrorBar, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./TagRows.jsx";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "accesscontrol", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Events", items: [{ id: "eventsubscriptions", label: "Event Subscriptions" }] },
  { group: "Settings", items: [{ id: "networking", label: "Networking" }, { id: "identity", label: "Identity" }, { id: "configuration", label: "Configuration" }, { id: "accesskeys", label: "Access keys" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" }] },
  { group: "Monitoring", items: [{ id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { id: "support", label: "Support + Troubleshooting" },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

export default function TopicBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const topic = useAsync(() => api.getTopic(rg, name), [rg, name]);
  const self = `#/eventgrid/topics/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (topic.data) remember({ name, type: "Event Grid Topic", href: self }); }, [!!topic.data, self]);

  let body;
  if (topic.loading && !topic.data) body = <Loading />;
  else if (topic.error) body = <><ErrorBar error={topic.error} title="Failed to load the topic" /><Link href="#/eventgrid/topics">Back to Event Grid Topics</Link></>;
  else {
    const t = topic.data, reload = topic.reload;
    const P = {
      overview: () => <Overview t={t} reload={reload} self={self} />,
      tags: () => <Tags t={t} reload={reload} />,
      eventsubscriptions: () => <EventSubscriptions rg={rg} topic={name} self={self} />,
      networking: () => <Networking t={t} reload={reload} />,
      identity: () => <Identity t={t} reload={reload} />,
      configuration: () => <Configuration t={t} reload={reload} />,
      accesskeys: () => <AccessKeys t={t} />,
      properties: () => <Properties t={t} />,
      activitylog: () => <ActivityLog t={t} name={name} />,
      accesscontrol: () => <Iam name={name} />,
      locks: () => <Locks rg={rg} topic={name} />,
      diagnose: () => <Diagnose t={t} rg={rg} name={name} />,
      tasks: () => <CapabilityContainer id="azure.eventgrid.topic.tools" title={`${name} | Tasks`} />,
      support: () => <CapabilityContainer id="azure.eventgrid.topic.tools" title={`${name} | Support + Troubleshooting`} />,
      alerts: () => <Alerts t={t} />,
      metrics: () => <Metrics t={t} />,
      diagnosticsettings: () => <DiagnosticSettings t={t} />,
      logs: () => <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${name} | Logs`} />,
      exporttemplate: () => <ExportTemplate t={t} />,
    }[panel];
    body = P ? P() : <><div className="vy-panel-title">{LABEL[panel] || panel}</div><CapabilityContainer id="azure.eventgrid.topic.tools" title={LABEL[panel] || panel} /></>;
  }

  return (
    <ResourceBlade
      title={name} subtitle="Event Grid Topic" glyph={<Glyph id="eventgrid" />} closeHref="#/eventgrid/topics"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

/** A small filterable table for event subscriptions — the real portal's sub-resource grid
 *  uses "Filter by name..." rather than the browse blade's "Filter for any field...". */
function SubscriptionsTable({ rows, scope, onDeleted }) {
  const notify = useNotify();
  const [filter, setFilter] = useState("");
  const f = filter.trim().toLowerCase();
  const shown = rows.filter((r) => !f || r.name.toLowerCase().includes(f));
  return (
    <>
      <Input size="small" style={{ width: 260, margin: "8px 0" }} placeholder="Filter by name..." value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter by name" />
      <table className="vy-grid" style={{ width: "100%" }}>
        <thead><tr><th>Name</th><th>Endpoint</th><th>Provisioning state</th><th>Event Schema</th><th /></tr></thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td>{r.properties?.destination?.endpointType}{r.properties?.destination?.properties?.endpointUrl ? ` — ${r.properties.destination.properties.endpointUrl}` : ""}</td>
              <td>{r.properties?.provisioningState}</td>
              <td>{r.properties?.eventDeliverySchema}</td>
              <td><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete ${r.name}`} onClick={async () => {
                await api.deleteEventSubscription(scope.rg, scope.topic, r.name);
                notify.success(`Event subscription '${r.name}' was deleted.`, "Delete succeeded");
                onDeleted();
              }} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {!shown.length && <div className="vy-empty"><h3>No event subscriptions to display</h3></div>}
    </>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ t, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [del, setDel] = useState(false);
  const [json, setJson] = useState(false);
  const p = t.properties || {};
  const tags = Object.entries(t.tags || {});
  const es = useAsync(() => api.listEventSubscriptions(t.resourceGroup, t.name), [t.id]);
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<ArrowRight20Regular />} as="a" href={`${self}/subscriptions/create`}>Event Subscription</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton icon={<ArrowRight20Regular />} onClick={() => notify.info("Move isn't simulated — resources stay in their original resource group.")}>Move</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
      </div>
      <Essentials
        actions={<Link as="button" onClick={() => setJson(true)}>JSON View</Link>}
        left={[
          ["Resource group", <Link href="#/eventgrid/topics">{t.resourceGroup}</Link>],
          ["Location", locationLabel(t.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Topic Endpoint", p.endpoint],
          ["Status", p.provisioningState],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <div className="vy-panel-title" style={{ marginTop: 8 }}>Event Subscriptions</div>
      <ErrorBar error={es.error} />
      {es.loading ? <Loading /> : <SubscriptionsTable rows={es.data || []} scope={{ rg: t.resourceGroup, topic: t.name }} onDeleted={es.reload} />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="topic" names={[t.name]}
        onConfirm={async () => {
          await api.deleteTopic(t.resourceGroup, t.name);
          forget(self);
          notify.success(`Topic '${t.name}' was deleted.`, "Delete succeeded");
          navigate("eventgrid", "topics");
        }} />
      <Dialog open={json} onOpenChange={(_, d) => setJson(d.open)}>
        <DialogSurface style={{ maxWidth: 820 }} aria-label="Resource JSON">
          <DialogBody>
            <DialogTitle>Resource JSON</DialogTitle>
            <DialogContent>
              <Field label="Resource ID"><Input readOnly value={t.id} /></Field>
              <pre className="vy-mono" style={{ maxHeight: 420, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 12, borderRadius: 4 }}>{JSON.stringify(Object.fromEntries(Object.entries(t).filter(([k]) => k !== "resourceGroup")), null, 2)}</pre>
            </DialogContent>
            <DialogActions><Button onClick={() => setJson(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Event Subscriptions (standalone panel) ───────────────────────────────────────────────
function EventSubscriptions({ rg, topic, self }) {
  const es = useAsync(() => api.listEventSubscriptions(rg, topic), [rg, topic]);
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Event Subscriptions commands">
        <ToolbarButton icon={<ArrowRight20Regular />} as="a" href={`${self}/subscriptions/create`}>Event Subscription</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={es.reload}>Refresh</ToolbarButton>
      </div>
      <div className="vy-panel-title">{topic} | Event Subscriptions</div>
      <ErrorBar error={es.error} />
      {es.loading ? <Loading /> : <SubscriptionsTable rows={es.data || []} scope={{ rg, topic }} onDeleted={es.reload} />}
    </>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
function Tags({ t, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(t.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [t]);
  const apply = async () => {
    setBusy(true);
    try {
      const { id, name, type, resourceGroup, ...rest } = t;
      await api.createTopic(t.resourceGroup, t.name, { ...rest, tags: Object.fromEntries(rows.filter((r) => r.name).map((r) => [r.name, r.value])) });
      notify.success(`Tags on '${t.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{t.name} | Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={rows} onChange={setRows} resource={t.name} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
      </div>
    </>
  );
}

// ── Access keys ──────────────────────────────────────────────────────────────────────────
function Secret({ label, value }) {
  const [show, setShow] = useState(false);
  const notify = useNotify();
  return (
    <Field label={label}>
      <div style={{ display: "flex", gap: 4 }}>
        <Input readOnly type={show ? "text" : "password"} value={value} style={{ flex: 1 }} aria-label={label} />
        <Button icon={show ? <EyeOff16Regular /> : <Eye16Regular />} onClick={() => setShow((v) => !v)}>{show ? "Hide" : "Show"}</Button>
        <Button icon={<Copy16Regular />} aria-label={`Copy ${label}`} onClick={() => navigator.clipboard?.writeText(value).then(() => notify.info(`${label} copied to clipboard.`))} />
      </div>
    </Field>
  );
}

function AccessKeys({ t }) {
  const notify = useNotify();
  const keys = useAsync(() => api.listKeys(t.resourceGroup, t.name), [t.id]);
  const regen = async (keyName) => {
    await api.regenerateKey(t.resourceGroup, t.name, keyName);
    notify.success(`${keyName} was regenerated.`, "Key regenerated");
    keys.reload();
  };
  return (
    <>
      <div className="vy-panel-title">{t.name} | Access keys</div>
      <InfoBar>Keys come from the native <span className="vy-mono">listKeys</span> ARM action. Vyomi issues fixed simulator keys and does not verify SAS signatures.</InfoBar>
      <ErrorBar error={keys.error} />
      {keys.loading ? <Loading /> : (
        <section className="vy-section">
          {(keys.data || []).map((k) => (
            <div key={k.keyName} style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
              <h3>{k.keyName}</h3>
              <Secret label="Key" value={k.value} />
              <Button onClick={() => regen(k.keyName)}>Regenerate</Button>
            </div>
          ))}
        </section>
      )}
    </>
  );
}

// ── Networking ───────────────────────────────────────────────────────────────────────────
function Networking({ t, reload }) {
  const notify = useNotify();
  const p = t.properties || {};
  const [busy, setBusy] = useState(false);
  const save = async (publicNetworkAccess) => {
    setBusy(true);
    try {
      await api.updateTopic(t.resourceGroup, t.name, { properties: { publicNetworkAccess } });
      notify.success("Networking settings saved.", "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving networking settings failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{t.name} | Networking</div>
      <div className="vy-form-row"><span className="vy-label">Public network access</span>
        <RadioGroup disabled={busy} layout="horizontal" value={p.publicNetworkAccess === "Disabled" ? "Disabled" : "Enabled"} onChange={(_, d) => save(d.value)} aria-label="Public network access">
          <Radio value="Enabled" label="All networks" /><Radio value="Disabled" label="Disabled" />
        </RadioGroup>
      </div>
      <CapabilityContainer id="azure.eventgrid.eventsubscriptions.delivery" title="Private endpoint connections" note="Private endpoints for topics are not modeled." />
    </>
  );
}

// ── Identity ─────────────────────────────────────────────────────────────────────────────
function Identity({ t, reload }) {
  const notify = useNotify();
  const type = t.identity?.type || "None";
  const [busy, setBusy] = useState(false);
  const save = async (next) => {
    setBusy(true);
    try {
      await api.updateTopic(t.resourceGroup, t.name, { identity: { type: next } });
      notify.success("Identity settings saved.", "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving identity failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{t.name} | Identity</div>
      <div className="vy-form-row"><label htmlFor="eg-id-type">Managed identity type</label>
        <Select id="eg-id-type" disabled={busy} value={type === "None" ? "None" : type} onChange={(_, d) => save(d.value)} aria-label="Managed identity type">
          <option value="None">None</option><option value="SystemAssigned">System assigned</option><option value="UserAssigned">User assigned</option>
        </Select>
      </div>
      {type !== "None" && <KV label="Principal ID" value={t.identity?.principalId || "(assigned on next refresh)"} />}
    </>
  );
}

// ── Configuration ────────────────────────────────────────────────────────────────────────
function Configuration({ t, reload }) {
  const notify = useNotify();
  const p = t.properties || {};
  const [f, setF] = useState({ inputSchema: p.inputSchema || "EventGridSchema", minimumTlsVersionAllowed: p.minimumTlsVersionAllowed || "1.2", disableLocalAuth: !!p.disableLocalAuth });
  const [busy, setBusy] = useState(false);
  useEffect(() => setF({ inputSchema: p.inputSchema || "EventGridSchema", minimumTlsVersionAllowed: p.minimumTlsVersionAllowed || "1.2", disableLocalAuth: !!p.disableLocalAuth }), [t]);
  const dirty = JSON.stringify(f) !== JSON.stringify({ inputSchema: p.inputSchema || "EventGridSchema", minimumTlsVersionAllowed: p.minimumTlsVersionAllowed || "1.2", disableLocalAuth: !!p.disableLocalAuth });
  const save = async () => {
    setBusy(true);
    try {
      await api.updateTopic(t.resourceGroup, t.name, { properties: f });
      notify.success(`Configuration of '${t.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving configuration failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{t.name} | Configuration</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Configuration commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton icon={<Dismiss20Regular />} disabled={!dirty} onClick={() => setF({ inputSchema: p.inputSchema || "EventGridSchema", minimumTlsVersionAllowed: p.minimumTlsVersionAllowed || "1.2", disableLocalAuth: !!p.disableLocalAuth })}>Discard</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <div className="vy-form-row"><label htmlFor="eg-cfg-schema">Event Schema</label>
        <Select id="eg-cfg-schema" value={f.inputSchema} onChange={(_, d) => setF((x) => ({ ...x, inputSchema: d.value }))} aria-label="Event Schema">
          <option value="EventGridSchema">Event Grid Schema</option><option value="CloudEventSchemaV1_0">Cloud Event Schema v1.0</option><option value="CustomEventSchema">Custom Input Schema</option>
        </Select></div>
      <div className="vy-form-row"><label htmlFor="eg-cfg-tls">Minimum TLS version</label>
        <Select id="eg-cfg-tls" value={f.minimumTlsVersionAllowed} onChange={(_, d) => setF((x) => ({ ...x, minimumTlsVersionAllowed: d.value }))} aria-label="Minimum TLS version">
          <option value="1.0">1.0</option><option value="1.1">1.1</option><option value="1.2">1.2</option>
        </Select></div>
      <div className="vy-form-row"><span className="vy-label">Enable access keys and Shared Access Signatures (SAS)</span>
        <RadioGroup layout="horizontal" value={f.disableLocalAuth ? "off" : "on"} onChange={(_, d) => setF((x) => ({ ...x, disableLocalAuth: d.value === "off" }))} aria-label="Enable access keys and Shared Access Signatures (SAS)">
          <Radio value="off" label="Disabled" /><Radio value="on" label="Enabled" />
        </RadioGroup></div>
    </>
  );
}

// ── Properties ───────────────────────────────────────────────────────────────────────────
function Properties({ t }) {
  return (
    <>
      <div className="vy-panel-title">{t.name} | Properties</div>
      <KV label="Resource ID" value={t.id} />
      <KV label="Resource type" value={t.type} />
      <KV label="Resource group" value={t.resourceGroup} />
      <KV label="Location" value={locationLabel(t.location)} />
      <KV label="Provisioning state" value={t.properties?.provisioningState} />
      <KV label="Topic endpoint" value={t.properties?.endpoint} />
      <KV label="Created" value={t._created ? fmtDate(t._created) : undefined} />
    </>
  );
}

// ── Activity log (CapabilityContainer wraps it so the "generic feed, not the real Insights
// audit trail" limitation still surfaces as a badge). Download as CSV and Reset filters are
// REAL (client-side over the real rows, same mechanism as BrowseGrid's Export to CSV);
// Export Activity Logs (continuous export to a workspace/storage/event hub), Insights and
// Feedback stay an honest gap (azure.eventgrid.topic.listactions). ─────────────────────────
const ACTIVITY_LOG_COLUMNS = [
  { key: "operation", label: "Operation name", value: (e) => e.operationName?.localizedValue || e.operationName?.value },
  { key: "status", label: "Status", value: (e) => e.status?.value },
  { key: "time", label: "Time", value: (e) => (e.eventTimestamp ? fmtDate(e.eventTimestamp) : ""), csv: (e) => e.eventTimestamp },
  { key: "timestamp", label: "Time stamp", value: (e) => e.eventTimestamp },
  { key: "subscription", label: "Subscription", value: (e) => e.subscriptionId },
  { key: "caller", label: "Event initiated by", value: (e) => e.caller },
];

function ActivityLog({ t, name }) {
  const log = useAsync(() => api.listActivityLog(t.id), [t.id]);
  const [filter, setFilter] = useState("");
  const [gap, setGap] = useState(null);
  const f = filter.trim().toLowerCase();
  const rows = (log.data || []).filter((e) => !f || (ACTIVITY_LOG_COLUMNS.some((c) => String(c.value(e) ?? "").toLowerCase().includes(f))));
  return (
    <CapabilityContainer id="azure.eventgrid.topic.activitylog" title={`${name} | Activity log`}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton onClick={() => setGap("Activity")}>Activity</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Edit columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={log.reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!rows.length} onClick={() => downloadCsv("activity-log.csv", ACTIVITY_LOG_COLUMNS, rows)}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Insights")}>Insights</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Pin current filters")}>Pin current filters</ToolbarButton>
        <ToolbarButton onClick={() => setFilter("")}>Reset filters</ToolbarButton>
      </div>
      <Input size="small" style={{ width: 260, margin: "8px 0" }} placeholder="Filter by operation..." value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter by operation" />
      <ErrorBar error={log.error} />
      {log.loading ? <Loading /> : (
        <table className="vy-grid" style={{ width: "100%" }}>
          <thead><tr>{ACTIVITY_LOG_COLUMNS.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>{ACTIVITY_LOG_COLUMNS.map((c) => <td key={c.key}>{c.value(e)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      )}
      {!log.loading && !rows.length && <div className="vy-empty"><h3>No events to display</h3></div>}
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || ""}>
          <DialogBody><CapabilityContainer id="azure.eventgrid.topic.listactions" title={gap || ""} /></DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Access control (IAM): real ARM resources (Microsoft.Authorization/roleAssignments,
// roleDefinitions), subscription-wide rather than scoped to this one topic — same honest
// shape as the Cosmos DB account blade (core/capabilities/azure/eventgrid.json) ───────────
function Iam({ name }) {
  const sub = useSubscription();
  const [tab, setTab] = useState("checkaccess");
  const [gap, setGap] = useState(null);
  const roleAssignments = useAsync(() => api.listRoleAssignments(sub.id), [sub.id]);
  const roleDefinitions = useAsync(() => api.listRoleDefinitions(sub.id), [sub.id]);
  return (
    <>
      <div className="vy-panel-title">{name} | Access control (IAM)</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control tabs">
        <Tab value="checkaccess">Check access</Tab>
        <Tab value="roleassignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="denyassignments">Deny assignments</Tab>
        <Tab value="classicadmins">Classic administrators</Tab>
      </TabList>
      {tab === "checkaccess" && (
        <div style={{ display: "flex", gap: 24, marginTop: 12 }}>
          <section className="vy-section"><h3>My access</h3><Button onClick={() => setGap("View my access")}>View my access</Button></section>
          <section className="vy-section"><h3>Check access</h3><Button onClick={() => setGap("Check access")}>Check access</Button></section>
        </div>
      )}
      {tab === "roleassignments" && (
        <section className="vy-section" style={{ marginTop: 12 }}><h3>Role assignments</h3>
          <BrowseGrid resourceName="role assignment" rowKey={(r) => r.id} filterPlaceholder="Search by name or email"
            items={roleAssignments.data || []} loading={roleAssignments.loading} error={roleAssignments.error} onRefresh={roleAssignments.reload}
            columns={[
              { key: "name", label: "Name", value: (r) => r.properties?.principalId },
              { key: "type", label: "Type", value: (r) => r.properties?.principalType || "--" },
              { key: "role", label: "Role", value: (r) => r.properties?.roleDefinitionId?.split("/").pop() },
              { key: "scope", label: "Scope", value: (r) => r.properties?.scope || "/" },
              { key: "condition", label: "Condition", value: () => "None" },
            ]}
          />
        </section>
      )}
      {tab === "roles" && (
        <section className="vy-section" style={{ marginTop: 12 }}><h3>Roles</h3>
          <BrowseGrid resourceName="role" rowKey={(r) => r.id} filterPlaceholder="Search by role name, description, permission, or ID"
            items={roleDefinitions.data || []} loading={roleDefinitions.loading} error={roleDefinitions.error} onRefresh={roleDefinitions.reload}
            columns={[
              { key: "name", label: "Name", value: (r) => r.properties?.roleName || r.name },
              { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
              { key: "type", label: "Type", value: (r) => r.properties?.type || "BuiltInRole" },
              { key: "category", label: "Category", value: () => "General" },
              { key: "details", label: "Details", value: () => "View" },
            ]}
          />
        </section>
      )}
      {tab === "denyassignments" && <NotSimulatedContainer title="Deny assignments" feature="Deny assignments" />}
      {tab === "classicadmins" && <div style={{ marginTop: 12 }} />}
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={`${gap} evaluation`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Export template (ARM Template tab reflects this topic's own live resource JSON; Bicep
// and Terraform output are an honest gap, same as the Cosmos DB account blade) ────────────
function ExportTemplate({ t }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { topicName: { type: "string", defaultValue: t.name } } } : {}),
    resources: [{ type: "Microsoft.EventGrid/topics", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('topicName')]" : t.name, location: t.location, properties: t.properties }],
  };
  const text = JSON.stringify(template, null, 2);
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    el.download = `${t.name}.json`;
    document.body.appendChild(el); el.click(); el.remove();
  };
  return (
    <>
      <div className="vy-panel-title">{t.name} | Export template</div>
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

// ── Locks (resource-scoped Microsoft.Authorization/locks) ─────────────────────────────────
const LOCK_TYPE_LABEL = { CanNotDelete: "Delete", ReadOnly: "Read-only" };

function Locks({ rg, topic }) {
  const notify = useNotify();
  const locks = useAsync(() => api.listLocks(rg, topic), [rg, topic]);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", type: "Delete", notes: "" });
  const [busy, setBusy] = useState(false);
  const [gap, setGap] = useState(null);

  const add = async () => {
    setBusy(true);
    try {
      const level = f.type === "Read-only" ? "ReadOnly" : "CanNotDelete";
      await api.createLock(rg, topic, f.name, { properties: { level, notes: f.notes } });
      notify.success(`Lock '${f.name}' was created.`, "Add lock succeeded");
      setAdding(false); setF({ name: "", type: "Delete", notes: "" });
      locks.reload();
    } catch (e) { notify.error(e, "Add lock failed"); }
    finally { setBusy(false); }
  };

  return (
    <>
      <CapabilityContainer id="azure.eventgrid.topic.locks" title={`${topic} | Locks`}>
        <BrowseGrid
          resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
          items={locks.data || []} loading={locks.loading} error={locks.error} onRefresh={locks.reload}
          extraCommands={<>
            <ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Add</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Subscription")}>Subscription</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Resource group")}>Resource group</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
          </>}
          onDelete={async (sel) => {
            for (const l of sel) await api.deleteLock(rg, topic, l.name);
            notify.success(`Deleted ${sel.length} lock${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
            locks.reload();
          }}
          csvName="locks.csv"
          columns={[
            { key: "name", label: "Lock name" },
            { key: "type", label: "Lock type", value: (l) => LOCK_TYPE_LABEL[l.properties?.level] || l.properties?.level },
            { key: "scope", label: "Scope", value: () => topic },
            { key: "notes", label: "Notes", value: (l) => l.properties?.notes || "--" },
          ]}
        />
      </CapabilityContainer>

      <Dialog open={adding} onOpenChange={(_, d) => setAdding(d.open)}>
        <DialogSurface aria-label="Add lock">
          <DialogBody>
            <DialogTitle>Add lock</DialogTitle>
            <DialogContent style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Lock name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Lock name" autoFocus /></Field>
              <Field label="Lock type" required>
                <Select value={f.type} onChange={(_, d) => setF((x) => ({ ...x, type: d.value }))} aria-label="Lock type">
                  <option value="Read-only">Read-only</option><option value="Delete">Delete</option>
                </Select>
              </Field>
              <Field label="Notes"><Input value={f.notes} onChange={(_, d) => setF((x) => ({ ...x, notes: d.value }))} aria-label="Notes" /></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!f.name.trim() || busy} onClick={add}>OK</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || ""}>
          <DialogBody><CapabilityContainer id="azure.eventgrid.topic.listactions" title={gap || ""} /></DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Metrics: the topic's REAL, activity-derived counters (core/azure_eventgrid_core.py
// publish/deliver) — not the generic Microsoft.Insights/metrics time-series engine (no
// time-grain charting or aggregation types), see azure.eventgrid.topic.monitoring. ────────
const METRIC_LABEL = {
  PublishSuccessCount: "Published Events", PublishFailCount: "Publish Failures",
  MatchedEventCount: "Matched Events", DeliverySuccessCount: "Delivered Events",
  DeliveryAttemptFailCount: "Delivery Attempt Failures", DeadLetteredCount: "Dead-Lettered Events",
  DroppedEventCount: "Dropped Events",
};

function Metrics({ t }) {
  const metrics = useAsync(() => api.listTopicMetrics(t.resourceGroup, t.name), [t.id]);
  return (
    <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${t.name} | Metrics`}>
      <ErrorBar error={metrics.error} />
      {metrics.loading ? <Loading /> : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
          {Object.entries(metrics.data || {}).map(([k, v]) => (
            <div key={k} className="vy-section" style={{ minWidth: 180 }}>
              <div style={{ fontSize: 28, fontWeight: 600 }}>{v}</div>
              <div>{METRIC_LABEL[k] || k}</div>
            </div>
          ))}
        </div>
      )}
    </CapabilityContainer>
  );
}

// ── Alerts (Microsoft.Insights/metricAlerts, real ARM resources scoped to this topic via
// `properties.scopes` — same generic engine the Monitor service's own Alerts pages use).
// Threshold evaluation against the metrics above is not modelled: creating/listing/deleting
// the rule is real, it firing is not (azure.eventgrid.topic.monitoring). ───────────────────
const ALERT_METRICS = Object.keys(METRIC_LABEL);
const ALERT_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

function Alerts({ t }) {
  const notify = useNotify();
  const alerts = useAsync(() => api.listMetricAlerts(t.id), [t.id]);
  const [add, setAdd] = useState(false);
  const [f, setF] = useState({ name: "", metric: ALERT_METRICS[0], threshold: 0, severity: "3" });
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await api.putMetricAlert(f.name, {
        location: "global",
        properties: {
          severity: Number(f.severity), enabled: true, scopes: [t.id],
          evaluationFrequency: "PT1M", windowSize: "PT5M",
          criteria: {
            "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
            allOf: [{ name: "c1", metricName: f.metric, operator: "GreaterThan", threshold: Number(f.threshold), timeAggregation: "Total" }],
          },
        },
      });
      notify.success(`Alert rule '${f.name}' was created.`, "Create succeeded");
      setAdd(false); setF({ name: "", metric: ALERT_METRICS[0], threshold: 0, severity: "3" });
      alerts.reload();
    } catch (e) { notify.error(e, "Creating the alert rule failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${t.name} | Alerts`}>
      <BrowseGrid
        resourceName="alert rule" rowKey={(r) => r.name} filterPlaceholder="Search alert rules"
        items={alerts.data || []} loading={alerts.loading} error={alerts.error} onRefresh={alerts.reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>New alert rule</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteMetricAlert(r.name);
          notify.success(`Deleted ${sel.length} alert rule${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          alerts.reload();
        }}
        csvName="alert-rules.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "condition", label: "Condition", value: (r) => r.properties?.criteria?.allOf?.[0]?.metricName },
          { key: "threshold", label: "Threshold", value: (r) => r.properties?.criteria?.allOf?.[0]?.threshold },
          { key: "severity", label: "Severity", value: (r) => `Sev${r.properties?.severity}` },
          { key: "enabled", label: "Enabled", value: (r) => (r.properties?.enabled ? "Yes" : "No") },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => setAdd(d.open)}>
        <DialogSurface aria-label="New alert rule">
          <DialogBody>
            <DialogTitle>New alert rule</DialogTitle>
            <DialogContent style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Rule name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Rule name" autoFocus /></Field>
              <Field label="Signal (metric)">
                <Select value={f.metric} onChange={(_, d) => setF((x) => ({ ...x, metric: d.value }))} aria-label="Signal">
                  {ALERT_METRICS.map((m) => <option key={m} value={m}>{METRIC_LABEL[m]}</option>)}
                </Select>
              </Field>
              <Field label="Threshold value (greater than)"><Input type="number" value={String(f.threshold)} onChange={(_, d) => setF((x) => ({ ...x, threshold: d.value }))} aria-label="Threshold value" /></Field>
              <Field label="Severity">
                <Select value={f.severity} onChange={(_, d) => setF((x) => ({ ...x, severity: d.value }))} aria-label="Severity">
                  <option value="0">0 - Critical</option><option value="1">1 - Error</option><option value="2">2 - Warning</option><option value="3">3 - Informational</option><option value="4">4 - Verbose</option>
                </Select>
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!ALERT_ID_RE.test(f.name) || busy} onClick={create}>Create</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this topic — same generic mechanism every other lens resource's
// Diagnostic settings page uses). Logs/metrics are stored and validated exactly as the real
// resource requires, but never delivered anywhere (azure.eventgrid.topic.monitoring). ─────
const DIAG_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

function DiagnosticSettings({ t }) {
  const notify = useNotify();
  const diag = useAsync(() => api.listDiagnosticSettings(t.id), [t.id]);
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const ws = workspaces.data || [];
  return (
    <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${t.name} | Diagnostic settings`}>
      <BrowseGrid
        resourceName="diagnostic setting" rowKey={(r) => r.name} filterPlaceholder="Search diagnostic settings"
        items={diag.data || []} loading={diag.loading} error={diag.error} onRefresh={diag.reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => { setAdd(true); setWorkspace(ws[0]?.id || ""); }}>Add diagnostic setting</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteDiagnosticSetting(t.id, r.name);
          notify.success(`Deleted ${sel.length} diagnostic setting${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          diag.reload();
        }}
        csvName="diagnostic-settings.csv"
        columns={[
          { key: "name", label: "Diagnostic setting name" },
          { key: "dest", label: "Destination details", value: (r) => (r.properties?.workspaceId ? "Log Analytics workspace" : "--") },
          { key: "logs", label: "Log categories", value: (r) => (r.properties?.logs || []).filter((l) => l.enabled).length },
          { key: "metrics", label: "Metric categories", value: (r) => (r.properties?.metrics || []).filter((m) => m.enabled).length },
        ]}
      />
      {add && (
        <section className="vy-section" style={{ marginTop: 16 }}>
          <h3>Add diagnostic setting</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 480 }}>
            <Field label="Diagnostic setting name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Diagnostic setting name" /></Field>
            <Field label="Log Analytics workspace">
              {ws.length ? (
                <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
                  {ws.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </Select>
              ) : <p style={{ margin: 0 }}>No Log Analytics workspace yet. Create one in the Monitor service first.</p>}
            </Field>
          </div>
          <div className="vy-cmdbar" style={{ marginTop: 12 }}>
            <Button appearance="primary" disabled={!DIAG_ID_RE.test(name) || !workspace} onClick={async () => {
              await api.putDiagnosticSetting(t.id, name, {
                properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] },
              });
              notify.success(`Diagnostic setting '${name}' was created.`, "Create succeeded");
              setAdd(false); setName(""); diag.reload();
            }}>Save</Button>
            <Button onClick={() => setAdd(false)}>Cancel</Button>
          </div>
        </section>
      )}
    </CapabilityContainer>
  );
}

// ── Diagnose and solve problems: a fixed set of REAL checks against this topic's actual
// configuration and delivery counters — not Microsoft's diagnostics knowledge base or
// automated remediation flows (azure.eventgrid.topic.tools). ──────────────────────────────
function Diagnose({ t, rg, name }) {
  const data = useAsync(async () => {
    const [subs, locksList] = await Promise.all([api.listEventSubscriptions(rg, name), api.listLocks(rg, name)]);
    const delivery = await Promise.all(subs.map((s) => api.getDeliveryStatus(rg, name, s.name)));
    return { subs: subs.map((s, i) => ({ ...s, _delivery: delivery[i] })), locks: locksList };
  }, [rg, name]);
  const loading = data.loading;
  const checks = [];
  if (!loading && data.data) {
    const subs = data.data.subs;
    checks.push(subs.length
      ? { level: "success", text: `${subs.length} event subscription${subs.length === 1 ? "" : "s"} configured on this topic.` }
      : { level: "warning", text: "No event subscriptions are configured on this topic — published events have nowhere to go." });
    const failing = subs.filter((s) => (s._delivery?.failed || 0) > 0 && !s.properties?.deadLetterDestination);
    if (failing.length) {
      checks.push({ level: "warning", text: `${failing.length} event subscription${failing.length === 1 ? "" : "s"} (${failing.map((s) => s.name).join(", ")}) ` +
        "had delivery failures with no dead-letter destination configured — those events were dropped." });
    }
    const roLock = (data.data.locks || []).find((l) => l.properties?.level === "ReadOnly");
    checks.push(roLock
      ? { level: "warning", text: `A ReadOnly lock ('${roLock.name}') blocks any change to this topic until it's removed.` }
      : { level: "success", text: "No ReadOnly lock is blocking changes to this topic." });
    const p = t.properties || {};
    checks.push({ level: p.publicNetworkAccess === "Disabled" ? "warning" : "success",
      text: `Public network access is ${p.publicNetworkAccess || "Enabled"}.` });
  }
  return (
    <CapabilityContainer id="azure.eventgrid.topic.diagnose" title={`${name} | Diagnose and solve problems`}>
      <ErrorBar error={data.error} />
      {loading ? <Loading /> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {checks.map((c, i) => (
            <div key={i} className="vy-section" style={{ borderLeft: `4px solid ${c.level === "warning" ? "var(--colorPaletteYellowBorder2)" : "var(--colorPaletteGreenBorder2)"}` }}>
              {c.level === "warning" ? "⚠ " : "✓ "}{c.text}
            </div>
          ))}
        </div>
      )}
    </CapabilityContainer>
  );
}
