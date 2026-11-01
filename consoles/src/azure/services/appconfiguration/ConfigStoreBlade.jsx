/* Configuration store resource blade: left resource menu + panels. Overview, Tags, Activity
 * log, Access control (IAM), Configuration explorer, Feature manager, Access settings
 * (access keys), Geo-replication, Networking, Properties, Locks and Export template are
 * backed by native ARM / App Configuration data-plane calls; everything else in the menu is
 * an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Switch, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
  Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import {
  Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular,
  Eye16Regular, EyeOff16Regular, LockClosed16Regular, LockOpen16Regular, Save20Regular,
} from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, downloadCsv, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Operations", items: [
    { id: "explorer", label: "Configuration explorer" }, { id: "features", label: "Feature manager" },
    { id: "importexport", label: "Import/export" }, { id: "events", label: "Events" },
  ] },
  { group: "Settings", items: [
    { id: "access", label: "Access settings" }, { id: "replicas", label: "Geo-replication" },
    { id: "networking", label: "Networking" }, { id: "encryption", label: "Encryption" },
    { id: "identity", label: "Identity" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" },
  ] },
  { group: "Monitoring", items: [
    { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "resourcehealth", label: "Resource health" }, { id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  diagnose: "Diagnose and solve problems",
  importexport: "Bulk import/export of key-values (file, App Service, another configuration store)",
  events: "Event Grid subscriptions on configuration store events",
  encryption: "Customer-managed key encryption",
  identity: "Managed identity",
  alerts: "Alert rules",
  metrics: "Configuration store metrics",
  diagnosticsettings: "Diagnostic settings",
  logs: "Log Analytics queries",
  tasks: "Tasks",
  resourcehealth: "Resource health",
  support: "Support + Troubleshooting",
};

export default function ConfigStoreBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const store = useAsync(() => api.getStore(rg, name), [rg, name]);
  const self = `#/appconfiguration/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (store.data) remember({ name, type: "Configuration store", href: self }); }, [!!store.data, self]);
  // Configuration explorer / Feature manager calls carry this store's name on the wire (see
  // api.js setActiveStore) so the single shared data-plane relay knows which store's
  // key-values to read/write (same seam as the Key Vault lens's x-vyomi-vault).
  useEffect(() => { api.setActiveStore(name); return () => api.setActiveStore(""); }, [name]);

  let body;
  if (store.loading && !store.data) body = <Loading />;
  else if (store.error) body = <><ErrorBar error={store.error} title="Failed to load the configuration store" /><Link href="#/appconfiguration">Back to Configuration stores</Link></>;
  else {
    const a = store.data, reload = store.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog a={a} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      explorer: () => <ConfigExplorer self={self} query={query} />,
      features: () => <FeatureManager />,
      access: () => <AccessSettings a={a} reload={reload} />,
      replicas: () => <Replicas a={a} />,
      networking: () => <Networking a={a} reload={reload} />,
      properties: () => <PropertiesPanel a={a} />,
      locks: () => <Locks a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{name} | {LABEL[panel] || panel}</div>
        <NotSimulated feature={NS_NOTES[panel] || `The ${LABEL[panel] || panel} panel`} />
      </>
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Configuration store" glyph={<Glyph id="appconfiguration" />} closeHref="#/appconfiguration"
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
  const [del, setDel] = useState(false);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Endpoint", p.endpoint],
          ["Pricing tier", api.skuLabel(a.sku)],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="configuration store" names={[a.name]}
        onConfirm={async () => {
          await api.deleteStore(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Configuration store '${a.name}' was deleted.`, "Delete succeeded");
          navigate("appconfiguration");
        }} />
    </>
  );
}

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this store) ──
const ACTIVITY_LOG_COLUMNS = [
  { key: "op", label: "Operation name", csv: (r) => r.operationName?.localizedValue || r.operationName?.value },
  { key: "status", label: "Status", csv: (r) => r.status?.localizedValue || r.status?.value },
  { key: "time", label: "Time", csv: (r) => fmtDate(r.eventTimestamp) },
  { key: "stamp", label: "Time stamp", csv: (r) => r.eventTimestamp },
  { key: "sub", label: "Subscription", csv: (r) => r.subscriptionId },
  { key: "by", label: "Event initiated by", csv: (r) => r.caller },
];
const TIMESPANS = [["1h", "Last hour"], ["24h", "Last 24 hours"], ["7d", "Last 7 days"], ["30d", "Last 30 days"], ["90d", "Last 90 days"]];
const timespanSinceIso = (code) => {
  const ms = { "1h": 36e5, "24h": 24 * 36e5, "7d": 7 * 24 * 36e5, "30d": 30 * 24 * 36e5, "90d": 90 * 24 * 36e5 }[code] || 90 * 24 * 36e5;
  return new Date(Date.now() - ms).toISOString();
};

function ActivityLog({ a }) {
  const [timespan, setTimespan] = useState("90d");
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name, timespanSinceIso(timespan)), [a.id, timespan]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.appconfiguration.activity_log" title={`${a.name} | Activity log`}
      actions={<>
        <ToolbarButton onClick={() => setGap("Edit columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!rows.length}
          onClick={() => downloadCsv("activity-log.csv", ACTIVITY_LOG_COLUMNS, rows)}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Pin current filters")}>Pin current filters</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Reset filters")}>Reset filters</ToolbarButton>
      </>}>
      <ErrorBar error={error} />
      <Field label="Timespan" style={{ maxWidth: 220, marginBottom: 8 }}>
        <Select value={timespan} onChange={(_, d) => setTimespan(d.value)} aria-label="Timespan">
          {TIMESPANS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </Select>
      </Field>
      <table className="vy-grid">
        <thead><tr>{ACTIVITY_LOG_COLUMNS.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
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
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : gap} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Access control (IAM) ──────────────────────────────────────────────────────────────
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  return (
    <>
      <div className="vy-panel-title">Access control (IAM)</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="check">Check access</Tab>
        <Tab value="assignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "check" && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="vy-section"><h3>My access</h3>
            <Button onClick={() => setDlg("mine")}>View my access</Button>
          </section>
          <section className="vy-section"><h3>Check access</h3>
            <Button onClick={() => setDlg("check")}>Check access</Button>
          </section>
        </div>
      )}
      {tab === "assignments" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Role assignments</div>
          <NotSimulatedContainer feature="Role assignments scoped to this configuration store (Microsoft.Authorization/roleAssignments is simulated at subscription scope only)" />
        </div>
      )}
      {tab === "roles" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Roles</div>
          <NotSimulatedContainer feature="The built-in and custom role catalog" />
        </div>
      )}
      {tab === "deny" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Deny assignments</div>
          <NotSimulatedContainer feature="Deny assignments" />
        </div>
      )}
      {tab === "classic" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Classic administrators" feature="Classic administrators (co-administrators)" /></div>}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access check">
          <DialogBody>
            <DialogTitle>{dlg === "mine" ? "My access" : "Check access"}</DialogTitle>
            <DialogContent><NotSimulated feature="Per-identity role-assignment resolution for this resource" note={`The store's resource id is ${a.id}.`} /></DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
export function TagRows({ tags, onChange, resource }) {
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
            <TableCell>{resource}</TableCell>
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
  // App Configuration's PATCH replaces the tag set wholesale (core/azure_appconfiguration_core.py
  // _apply_props), unlike a generic merge-PATCH, so a direct PATCH is enough (no PUT workaround).
  const apply = async () => {
    setBusy(true);
    try {
      await api.updateStore(a.resourceGroup, a.name, { tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={rows} onChange={setRows} resource={a.name} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={async () => { setRows([{ name: "", value: "" }]); await apply(); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Configuration explorer (data plane: /kv) ────────────────────────────────────────────
function ConfigExplorer({ self, query }) {
  if (query.key) return <KeyValueDetail self={self} keyName={query.key} label={query.label || ""} />;
  return <ConfigExplorerList self={self} />;
}

function ConfigExplorerList({ self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listKv(), []);
  const [create, setCreate] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Configuration explorer</div>
      <BrowseGrid
        resourceName="key-value" rowKey={(r) => `${r.key}$${r.label || ""}`} filterPlaceholder="Search by key or value"
        items={rows} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setCreate(true)}
        pills={[{ key: "label", label: "Label", value: (r) => r.label || "(no label)" }]}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteKv(r.key, r.label || undefined);
          notify.success(`Deleted ${sel.length} key-value${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="configuration-explorer.csv"
        columns={[
          { key: "key", label: "Key", render: (r) => <Link href={`${self}/explorer?key=${encodeURIComponent(r.key)}&label=${encodeURIComponent(r.label || "")}`}>{r.key}</Link> },
          { key: "value", label: "Value" },
          { key: "label", label: "Label", value: (r) => r.label || "" },
          { key: "content_type", label: "Content type", value: (r) => r.content_type || "" },
        ]}
        emptyAction={<Link as="button" onClick={() => setCreate(true)}>Create key-value</Link>}
      />
      <NotSimulatedContainer feature="Export and Import of key-values (file, App Service, another configuration store)" />
      <CreateKeyValueDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
    </>
  );
}

function CreateKeyValueDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [contentType, setContentType] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await api.putKv(key, label || undefined, { value, content_type: contentType || undefined });
      notify.success(`Key-value '${key}' was created.`, "Key-value created");
      setKey(""); setValue(""); setContentType(""); setLabel(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create the key-value"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create key-value">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create key-value</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Key" required><Input value={key} onChange={(_, d) => setKey(d.value)} aria-label="Key" /></Field>
              <Field label="Value"><Textarea value={value} onChange={(_, d) => setValue(d.value)} aria-label="Value" /></Field>
              <Field label="Content type"><Input value={contentType} onChange={(_, d) => setContentType(d.value)} aria-label="Content type" /></Field>
              <Field label="Label"><Input value={label} onChange={(_, d) => setLabel(d.value)} aria-label="Label" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!key || busy} onClick={go}>Apply</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function KeyValueDetail({ self, keyName, label }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getKv(keyName, label || undefined), [keyName, label]);
  const [value, setValue] = useState("");
  const [contentType, setContentType] = useState("");
  const [del, setDel] = useState(false);
  useEffect(() => { if (data) { setValue(data.value || ""); setContentType(data.content_type || ""); } }, [data]);
  const backToList = () => navigate("appconfiguration", self.split("/")[2], self.split("/")[3], "explorer");
  if (loading && !data) return <Loading />;
  if (error) return <><ErrorBar error={error} title="Failed to load the key-value" /><Link href={`${self}/explorer`}>Back to Configuration explorer</Link></>;
  const locked = !!data.locked;
  const save = async () => {
    try {
      await api.putKv(keyName, label || undefined, { value, content_type: contentType || undefined });
      notify.success(`Key-value '${keyName}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving the key-value failed"); }
  };
  const toggleLock = async () => {
    try {
      locked ? await api.unlockKv(keyName, label || undefined) : await api.lockKv(keyName, label || undefined);
      notify.success(`Key-value '${keyName}' was ${locked ? "unlocked" : "locked"}.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Failed to change the lock state"); }
  };
  return (
    <>
      <div style={{ fontSize: 13, marginTop: 12 }}><Link href={`${self}/explorer`}>Configuration explorer</Link> <span className="vy-muted">&gt;</span> {keyName}</div>
      <div className="vy-panel-title">{keyName}</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Key-value commands">
        <ToolbarButton icon={<Save20Regular />} disabled={locked} onClick={save}>Save</ToolbarButton>
        <ToolbarButton onClick={reload}>Discard changes</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} disabled={locked} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={locked ? <LockOpen16Regular /> : <LockClosed16Regular />} onClick={toggleLock}>{locked ? "Unlock" : "Lock"}</ToolbarButton>
      </div>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 12 }}>
        <h3>Edit key-value</h3>
        <Field label="Key"><Input readOnly value={keyName} aria-label="Key" /></Field>
        <Field label="Label"><Input readOnly value={label || "(none)"} aria-label="Label" /></Field>
        <Field label="Content type"><Input disabled={locked} value={contentType} onChange={(_, d) => setContentType(d.value)} aria-label="Content type" /></Field>
        <Field label="Value"><Textarea disabled={locked} value={value} onChange={(_, d) => setValue(d.value)} aria-label="Value" /></Field>
        {locked && <NotSimulated feature="Editing a locked key-value" note="Unlock it first — real App Configuration refuses writes to a locked key the same way." />}
      </section>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="key-value" names={[keyName]}
        onConfirm={async () => { await api.deleteKv(keyName, label || undefined); notify.success(`Key-value '${keyName}' was deleted.`, "Delete succeeded"); backToList(); }} />
    </>
  );
}

// ── Feature manager (data plane: /kv filtered to .appconfig.featureflag/*) ─────────────
function FeatureManager() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listKv(), []);
  const [create, setCreate] = useState(false);
  const rows = (data || []).filter(api.isFeatureFlag).map((kv) => ({ kv, ...api.parseFeatureFlag(kv) }));
  const toggle = async (row) => {
    try {
      await api.putKv(row.kv.key, row.kv.label || undefined, { value: api.featureFlagBody(row.id, { enabled: !row.enabled, description: row.description }), content_type: api.FF_CONTENT_TYPE });
      reload();
    } catch (e) { notify.error(e, "Failed to update the feature flag"); }
  };
  return (
    <>
      <div className="vy-panel-title">Feature manager</div>
      <BrowseGrid
        resourceName="feature flag" rowKey={(r) => `${r.kv.key}$${r.kv.label || ""}`} filterPlaceholder="Search by name"
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={(sel) => <>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setCreate(true)}>Add</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={() => sel[0] && toggle(sel[0])}>Enable</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={() => sel[0] && toggle(sel[0])}>Disable</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteKv(r.kv.key, r.kv.label || undefined);
          notify.success(`Deleted ${sel.length} feature flag${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="feature-manager.csv"
        columns={[
          { key: "id", label: "Name" },
          { key: "enabled", label: "Enabled", value: (r) => (r.enabled ? "Enabled" : "Disabled"), render: (r) => <Switch checked={!!r.enabled} onChange={() => toggle(r)} label={r.enabled ? "Enabled" : "Disabled"} /> },
          { key: "label", label: "Label", value: (r) => r.kv.label || "" },
          { key: "description", label: "Description", value: (r) => r.description || "" },
        ]}
        emptyAction={<Link as="button" onClick={() => setCreate(true)}>Add feature flag</Link>}
      />
      <CreateFeatureFlagDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
    </>
  );
}

function CreateFeatureFlagDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const valid = /^[^\s]+$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await api.putKv(api.FF_PREFIX + name, label || undefined, { value: api.featureFlagBody(name, { enabled, description }), content_type: api.FF_CONTENT_TYPE });
      notify.success(`Feature flag '${name}' was created.`, "Feature flag created");
      setName(""); setLabel(""); setDescription(""); setEnabled(false); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to add the feature flag"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add feature flag">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add feature flag</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Checkbox label="Enable feature flag" checked={enabled} onChange={(_, d) => setEnabled(!!d.checked)} />
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
              <Field label="Label"><Input value={label} onChange={(_, d) => setLabel(d.value)} aria-label="Label" /></Field>
              <Field label="Description"><Textarea value={description} onChange={(_, d) => setDescription(d.value)} aria-label="Description" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Apply</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Access settings (listKeys / regenerateKey ARM actions) ─────────────────────────────
function AccessSettings({ a, reload }) {
  const notify = useNotify();
  const { data, loading, error, reload: reloadKeys } = useAsync(() => api.listKeys(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [show, setShow] = useState({});
  const [tab, setTab] = useState("rw");
  const [busy, setBusy] = useState(false);
  const keys = data || [];
  const byName = (n) => keys.find((k) => k.name === n);
  const regen = async (k) => {
    setBusy(true);
    try { await api.regenerateKey(a.resourceGroup, a.name, k.id); notify.success(`${k.name} key was regenerated.`, "Key regenerated"); reloadKeys(); }
    catch (e) { notify.error(e, "Failed to regenerate the key"); }
    finally { setBusy(false); }
  };
  const toggleLocalAuth = async () => {
    setBusy(true);
    try { await api.updateStore(a.resourceGroup, a.name, { properties: { disableLocalAuth: !a.properties?.disableLocalAuth } }); notify.success("Access settings were saved.", "Saved"); reload(); }
    catch (e) { notify.error(e, "Saving access settings failed"); }
    finally { setBusy(false); }
  };
  const KeyCard = ({ title, keyName, verb }) => {
    const k = byName(keyName);
    const visible = !!show[keyName];
    return (
      <section className="vy-section" style={{ maxWidth: 760 }}>
        <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>{title}</span>
          <ToolbarButton size="small" disabled={!k || busy} onClick={() => k && regen(k)}>{verb}</ToolbarButton>
        </h3>
        {!k ? <ErrorBar error={error} /> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Field label="Connection string"><Input readOnly type={visible ? "text" : "password"} value={k.connectionString} /></Field>
            <Field label="Key ID"><Input readOnly value={k.id} /></Field>
            <Field label="Secret Value">
              <div style={{ display: "flex", gap: 4 }}>
                <Input readOnly type={visible ? "text" : "password"} value={k.value} style={{ flex: 1 }} aria-label="Secret Value" />
                <Button icon={visible ? <EyeOff16Regular /> : <Eye16Regular />} onClick={() => setShow((s) => ({ ...s, [keyName]: !s[keyName] }))}>{visible ? "Hide" : "Show"}</Button>
              </div>
            </Field>
          </div>
        )}
      </section>
    );
  };
  return (
    <>
      <div className="vy-panel-title">Access settings</div>
      <section className="vy-section"><h3>Authentication mode</h3>
        <Checkbox label="Enable access key authentication" checked={!a.properties?.disableLocalAuth} disabled={busy} onChange={toggleLocalAuth} />
      </section>
      {loading && <Loading />}
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access settings tabs">
        <Tab value="rw">Read-write keys</Tab>
        <Tab value="ro">Read-only keys</Tab>
      </TabList>
      {tab === "rw" && <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
        <KeyCard title="Primary key" keyName="Primary" verb="Regenerate Primary Key" />
        <KeyCard title="Secondary key" keyName="Secondary" verb="Regenerate Secondary Key" />
      </div>}
      {tab === "ro" && <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
        <KeyCard title="Primary read-only key" keyName="Primary Read Only" verb="Regenerate Primary Key" />
        <KeyCard title="Secondary read-only key" keyName="Secondary Read Only" verb="Regenerate Secondary Key" />
      </div>}
    </>
  );
}

// ── Geo-replication (ARM child resource: configurationStores/{name}/replicas) ──────────
function Replicas({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listReplicas(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [create, setCreate] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Geo-replication</div>
      <BrowseGrid
        resourceName="replica" rowKey={(r) => r.name} filterPlaceholder="Filter by name..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setCreate(true)}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteReplica(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} replica${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="replicas.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
          { key: "endpoint", label: "Endpoint", value: (r) => r.properties?.endpoint },
          { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState },
        ]}
        emptyAction={<Link as="button" onClick={() => setCreate(true)}>Add a replica</Link>}
      />
      <CreateReplicaDialog open={create} onClose={() => setCreate(false)} onCreated={reload} rg={a.resourceGroup} name={a.name} />
    </>
  );
}

function CreateReplicaDialog({ open, onClose, onCreated, rg, name }) {
  const notify = useNotify();
  const [replicaName, setReplicaName] = useState("");
  const [location, setLocation] = useState("westus");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await api.createReplica(rg, name, replicaName, { location });
      notify.success(`Replica '${replicaName}' was added.`, "Replica added");
      setReplicaName(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to add the replica"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add replica">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add replica</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={replicaName} onChange={(_, d) => setReplicaName(d.value)} aria-label="Name" /></Field>
              <Field label="Location" required>
                <Select value={location} onChange={(_, d) => setLocation(d.value)} aria-label="Location">
                  <option value="westus">(US) West US</option><option value="westeurope">(Europe) West Europe</option>
                  <option value="southeastasia">(Asia Pacific) Southeast Asia</option>
                </Select>
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!replicaName || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Networking (public network access) ──────────────────────────────────────────────────
function Networking({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const net = p.publicNetworkAccess === "Disabled" ? "disabled" : "all";
  const [value, setValue] = useState(net);
  const [busy, setBusy] = useState(false);
  useEffect(() => setValue(net), [net]);
  const save = async (v) => {
    setValue(v);
    setBusy(true);
    try {
      await api.updateStore(a.resourceGroup, a.name, { properties: { publicNetworkAccess: v === "disabled" ? "Disabled" : "Enabled" } });
      notify.success(`Networking for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving networking failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.appconfiguration.networking" title="Firewalls and virtual networks">
      <RadioGroup disabled={busy} value={value} onChange={(_, d) => save(d.value)} aria-label="Allow access from">
        <Radio value="all" label="Allow public access from all networks" />
        <Radio value="disabled" label="Disable public access" />
      </RadioGroup>
    </CapabilityContainer>
  );
}

// ── Properties ─────────────────────────────────────────────────────────────────────────
function PropertiesPanel({ a }) {
  const p = a.properties || {};
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <div className="vy-props">
        <KV label="Name" value={a.name} />
        <KV label="Resource ID" value={a.id} />
        <KV label="Pricing tier" value={api.skuLabel(a.sku)} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="Endpoint" value={p.endpoint} />
        <KV label="Subscription ID" value={a._sub} />
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this store) ───────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteLock(a.resourceGroup, a.name, r.name);
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
        onCreate={async (name, level, notes) => { await api.putLock(a.resourceGroup, a.name, name, { properties: { level, notes } }); reload(); }} />
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
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add lock</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Lock name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Lock name" /></Field>
              <Field label="Lock type" required>
                <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type">
                  <option>Read-only</option><option>Delete</option>
                </Select>
              </Field>
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

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { storeName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.AppConfiguration/configurationStores", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('storeName')]" : a.name, location: a.location, sku: a.sku, properties: a.properties }],
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
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab>
        <Tab value="bicep">Bicep</Tab>
        <Tab value="terraform">Terraform</Tab>
      </TabList>
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Template</h3>
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        {tab === "arm" && <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
        {tab !== "arm" && <NotSimulatedContainer feature={`${tab === "bicep" ? "Bicep" : "Terraform"} template export`} />}
      </section>
    </>
  );
}
