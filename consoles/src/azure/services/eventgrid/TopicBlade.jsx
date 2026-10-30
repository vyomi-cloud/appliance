/* Event Grid topic resource blade: left resource menu + panels. Overview, Tags, Access keys,
 * Event Subscriptions, Networking, Identity, Configuration and Properties are backed by native
 * ARM calls; Activity log, Access control (IAM), Locks and the monitoring/automation/support
 * menu items are honest NotSimulated panels (core/capabilities/azure/eventgrid.json). */
import { useEffect, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, Copy16Regular, Delete20Regular, Eye16Regular, EyeOff16Regular, ArrowRight20Regular, Save20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, fmtDate, Glyph, InfoBar, KV, Loading, ErrorBar } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./TagRows.jsx";
import * as api from "./api.js";
import { VyomiMark } from "../../../common/VyomiMark.jsx";

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
      activitylog: () => <CapabilityContainer id="azure.eventgrid.topic.activitylog" title={`${name} | Activity log`}
        note="Columns shown in the real portal: Operation name, Status, Time, Time stamp, Subscription, Event initiated by. Actions: Activity, Edit columns, Export Activity Logs, Download as CSV, Insights, Feedback, Pin current filters, Reset filters." />,
      accesscontrol: () => <CapabilityContainer id="azure.eventgrid.topic.iam" title={`${name} | Access control (IAM)`}
        note="Tabs: Check access, Role assignments, Roles, Deny assignments, Classic administrators. My access and Check access actions (View my access) live on the Check access tab." />,
      locks: () => <CapabilityContainer id="azure.eventgrid.topic.locks" title={`${name} | Locks`}
        note="Columns: Lock name, Lock type, Scope, Notes. Actions: Add, Subscription, Resource group, Feedback. Filter: Search to filter items... Add lock fields: Lock name, Lock type, Notes." />,
      diagnose: () => <CapabilityContainer id="azure.eventgrid.topic.tools" title={`${name} | Diagnose and solve problems`} />,
      tasks: () => <CapabilityContainer id="azure.eventgrid.topic.tools" title={`${name} | Tasks`} />,
      support: () => <CapabilityContainer id="azure.eventgrid.topic.tools" title={`${name} | Support + Troubleshooting`} />,
      alerts: () => <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${name} | Alerts`} />,
      metrics: () => <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${name} | Metrics`} />,
      diagnosticsettings: () => <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${name} | Diagnostic settings`} />,
      logs: () => <CapabilityContainer id="azure.eventgrid.topic.monitoring" title={`${name} | Logs`} />,
      exporttemplate: () => <CapabilityContainer id="azure.eventgrid.topic.exporttemplate" title={`${name} | Export template`}
        note="Tabs: ARM Template, Bicep, Terraform. Template section field: Include parameters." />,
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
      <InfoBar>Keys come from the native <span className="vy-mono">listKeys</span> ARM action. <VyomiMark /> issues fixed simulator keys and does not verify SAS signatures.</InfoBar>
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
