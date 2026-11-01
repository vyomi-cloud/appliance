/* Log Analytics workspace resource blade: left resource menu + panels. Overview, Activity log,
 * Tags, Agents management, Locks, Properties, Usage and estimated costs, Logs, Saved searches,
 * Tables, Data sources, Legacy solutions and Export template are backed by native ARM calls
 * (core/azure_operationalinsights_core.py); everything else in the menu renders its honest
 * capability level via CapabilityContainer (core/capabilities/azure/loganalytics.json — never a
 * hand-written disclaimer). */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular, Play20Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, downloadCsv, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Settings", items: [
    { id: "agents", label: "Agents management" },
    { id: "computergroups", label: "Computer groups (classic)" },
    { id: "dataexport", label: "Data export" },
    { id: "linkedstorage", label: "Linked storage accounts" },
    { id: "locks", label: "Locks" },
    { id: "properties", label: "Properties" },
    { id: "usage", label: "Usage and estimated costs" },
  ] },
  { group: "General", items: [
    { id: "logs", label: "Logs" },
    { id: "savedsearches", label: "Saved searches" },
    { id: "tables", label: "Tables" },
    { id: "datasources", label: "Data sources" },
  ] },
  { group: "Classic solutions", items: [
    { id: "legacysolutions", label: "Legacy solutions" },
  ] },
  { group: "Monitoring", items: [
    { id: "alerts", label: "Alerts" },
    { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" },
    { id: "workbooks", label: "Workbooks" },
  ] },
  { group: "Automation", items: [
    { id: "exporttemplate", label: "Export template" },
  ] },
  { group: "Help", items: [
    { id: "resourcehealth", label: "Resource health" },
    { id: "support", label: "Support + Troubleshooting" },
  ] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
// Panels with no built handler below render their honest capability level
// (core/capabilities/azure/loganalytics.json).
const CAP_FOR_PANEL = {
  diagnose: "azure.loganalytics.workspace.tools", computergroups: "azure.loganalytics.workspace.tools",
  dataexport: "azure.loganalytics.workspace.tools", linkedstorage: "azure.loganalytics.workspace.tools",
  resourcehealth: "azure.loganalytics.workspace.tools", support: "azure.loganalytics.workspace.tools",
  alerts: "azure.loganalytics.workspace.monitoring", metrics: "azure.loganalytics.workspace.monitoring",
  diagnosticsettings: "azure.loganalytics.workspace.monitoring", workbooks: "azure.loganalytics.workspace.monitoring",
};

export default function WorkspaceBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const ws = useAsync(() => api.getWorkspace(rg, name), [rg, name]);
  const self = `#/loganalytics/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (ws.data) remember({ name, type: "Log Analytics workspace", href: self }); }, [!!ws.data, self]);

  let body;
  if (ws.loading && !ws.data) body = <Loading />;
  else if (ws.error) body = <><ErrorBar error={ws.error} title="Failed to load the workspace" /><Link href="#/loganalytics">Back to Log Analytics workspaces</Link></>;
  else {
    const a = ws.data, reload = ws.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog a={a} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      agents: () => <Agents a={a} />,
      locks: () => <Locks a={a} />,
      properties: () => <Properties a={a} />,
      usage: () => <Usage a={a} reload={reload} />,
      logs: () => <Logs a={a} />,
      savedsearches: () => <SavedSearches a={a} />,
      tables: () => <Tables a={a} />,
      datasources: () => <DataSources a={a} />,
      legacysolutions: () => <LegacySolutions a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
    }[panel];
    body = P ? P() : <CapabilityContainer id={CAP_FOR_PANEL[panel] || "azure.loganalytics.workspace.tools"} title={`${a.name} | ${LABEL[panel] || panel}`} />;
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Log Analytics Workspace" glyph={<Glyph id="loganalytics" />} closeHref="#/loganalytics"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

function MiniTable({ columns, rows, empty }) {
  return (
    <table className="vy-grid" style={{ marginTop: 8 }}>
      <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{rows.length ? rows : <tr><td colSpan={columns.length} className="vy-muted">{empty}</td></tr>}</tbody>
    </table>
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
        <ToolbarButton as="a" href={`${self}/logs`}>Logs</ToolbarButton>
        <ToolbarButton>Feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Status", p.provisioningState || "Succeeded"],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Workspace ID", p.customerId],
          ["Pricing tier", api.skuLabel(p.sku)],
          ["Retention (days)", p.retentionInDays],
          ["Daily cap", p.workspaceCapping?.dailyQuotaGb === -1 ? "Off" : `${p.workspaceCapping?.dailyQuotaGb} GB`],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <section className="vy-section" style={{ marginTop: 12 }}>
        <h3>Get started</h3>
        <p>Run Kusto queries over this workspace's tables from the <Link href={`${self}/logs`}>Logs</Link> blade, manage its <Link href={`${self}/tables`}>Tables</Link>, and connect agents from <Link href={`${self}/agents`}>Agents management</Link>.</p>
      </section>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="workspace" names={[a.name]}
        onConfirm={async () => {
          await api.deleteWorkspace(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Workspace '${a.name}' was deleted.`, "Delete succeeded");
          navigate("loganalytics");
        }} />
    </>
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
          <section className="vy-section"><h3>My access</h3><Button onClick={() => setDlg("mine")}>View my access</Button></section>
          <section className="vy-section"><h3>Check access</h3><Button onClick={() => setDlg("check")}>Check access</Button></section>
        </div>
      )}
      {tab === "assignments" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.loganalytics.workspace.iam" title="Role assignments" /></div>}
      {tab === "roles" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.loganalytics.workspace.iam" title="Roles" /></div>}
      {tab === "deny" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.loganalytics.workspace.iam" title="Deny assignments" /></div>}
      {tab === "classic" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.loganalytics.workspace.iam" title="Classic administrators" /></div>}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access check">
          <DialogBody>
            <DialogTitle>{dlg === "mine" ? "My access" : "Check access"}</DialogTitle>
            <DialogContent><NotSimulated feature="Per-identity role-assignment resolution for this resource" note={`The workspace's resource id is ${a.id}.`} /></DialogContent>
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
  const apply = async () => {
    setBusy(true);
    try {
      // ARM PUT replaces the resource's tag set exactly (a PATCH would merge and keep removed keys).
      const { id, name, type, resourceGroup, systemData, ...rest } = a;
      await api.createWorkspace(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
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

// ── Agents management (sharedKeys / regenerateSharedKey) ───────────────────────────────
function Agents({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getSharedKeys(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const regen = async (which) => {
    try {
      await api.regenerateSharedKey(a.resourceGroup, a.name, which);
      notify.success(`The ${which} key was regenerated.`, "Key regenerated");
      reload();
    } catch (e) { notify.error(e, "Regenerate failed"); }
  };
  return (
    <CapabilityContainer id="azure.loganalytics.workspace.agents" title="Log Analytics agent instructions">
      {loading ? <Loading /> : (
        <>
          <ErrorBar error={error} />
          <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 760 }}>
            <Field label="Workspace ID"><Input readOnly value={a.properties?.customerId || ""} aria-label="Workspace ID" /></Field>
            <Field label="Primary key">
              <div style={{ display: "flex", gap: 8 }}>
                <Input readOnly value={data?.primarySharedKey || ""} aria-label="Primary key" style={{ flex: 1 }} />
                <Button onClick={() => regen("primary")}>Regenerate</Button>
              </div>
            </Field>
            <Field label="Secondary key">
              <div style={{ display: "flex", gap: 8 }}>
                <Input readOnly value={data?.secondarySharedKey || ""} aria-label="Secondary key" style={{ flex: 1 }} />
                <Button onClick={() => regen("secondary")}>Regenerate</Button>
              </div>
            </Field>
          </div>
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this workspace) ───────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <CapabilityContainer id="azure.loganalytics.workspace.locks" title="Locks">
        <BrowseGrid
          resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
          items={rows} loading={loading} error={error} onRefresh={reload}
          extraCommands={<>
            <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Subscription")}>Subscription</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Resource group")}>Resource group</ToolbarButton>
            <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
          </>}
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
      </CapabilityContainer>
      <AddLockDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, level, notes) => { await api.putLock(a.resourceGroup, a.name, name, { properties: { level, notes } }); reload(); }} />
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
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add lock</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Lock name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Lock name" /></Field>
              <Field label="Lock type" required>
                <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type"><option>Read-only</option><option>Delete</option></Select>
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

// ── Properties ─────────────────────────────────────────────────────────────────────────
function Properties({ a }) {
  const p = a.properties || {};
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <CapabilityContainer id="azure.loganalytics.workspace.properties" title="Properties">
        <div className="vy-props">
          <KV label="Resource ID" value={a.id} />
          <KV label="Workspace ID" value={p.customerId} />
          <KV label="Pricing tier" value={api.skuLabel(p.sku)} />
          <KV label="Location" value={locationLabel(a.location)} />
          <KV label="Created" value={fmtDate(p.createdDate)} />
          <KV label="Updated" value={fmtDate(p.modifiedDate)} />
        </div>
      </CapabilityContainer>
    </>
  );
}

// ── Usage and estimated costs ───────────────────────────────────────────────────────────
function Usage({ a, reload }) {
  const notify = useNotify();
  const { data, loading, error, reload: reloadUsage } = useAsync(() => api.getUsages(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const p = a.properties || {};
  const [cap, setCap] = useState(String(p.workspaceCapping?.dailyQuotaGb ?? -1));
  const [busy, setBusy] = useState(false);
  useEffect(() => setCap(String(p.workspaceCapping?.dailyQuotaGb ?? -1)), [a]);
  const dirty = cap !== String(p.workspaceCapping?.dailyQuotaGb ?? -1);
  const metric = (name) => (data || []).find((m) => m.name?.value === name);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateWorkspace(a.resourceGroup, a.name, { properties: { workspaceCapping: { dailyQuotaGb: Number(cap) } } });
      notify.success(`The daily cap for '${a.name}' was saved.`, "Saved");
      reload(); reloadUsage();
    } catch (e) { notify.error(e, "Saving daily cap failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.loganalytics.workspace.usage" title="Usage and estimated costs"
      actions={<Button appearance="primary" size="small" icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</Button>}>
      {loading ? <Loading /> : (
        <>
          <ErrorBar error={error} />
          <div className="vy-props">
            <KV label="Data analyzed" value="0 B" />
            <KV label="Tables" value={metric("TableCount")?.currentValue} />
            <KV label="Saved searches" value={metric("SavedSearchCount")?.currentValue} />
            <KV label="Pricing tier" value={api.skuLabel(p.sku)} />
          </div>
          <Field label="Daily cap (GB)" hint="-1 = no limit" style={{ maxWidth: 240, marginTop: 12 }}>
            <Input type="number" value={cap} onChange={(_, d) => setCap(d.value)} aria-label="Daily cap (GB)" />
          </Field>
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Logs (KQL query editor over POST .../api/query) ─────────────────────────────────────
const STARTER_QUERIES = ["AzureActivity | take 50", "Heartbeat | take 10", "AzureActivity | where Level == 'Informational' | count"];

function Logs({ a }) {
  const [query, setQuery] = useState(STARTER_QUERIES[0]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setError(null);
    try { setResult(await api.runQuery(a.resourceGroup, a.name, query)); }
    catch (e) { setError(e); setResult(null); }
    finally { setBusy(false); }
  };
  const table = result?.tables?.[0];
  return (
    <CapabilityContainer id="azure.loganalytics.workspace.logs" title="Logs">
      <div className="vy-cmdbar" role="toolbar" aria-label="Logs commands">
        <ToolbarButton icon={<Play20Regular />} disabled={busy || !query.trim()} onClick={run}>Run</ToolbarButton>
        <ToolbarButton icon={<Save20Regular />} as="a" href="#/loganalytics">Save</ToolbarButton>
      </div>
      <h3>Query editor</h3>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        {STARTER_QUERIES.map((q) => <Button key={q} size="small" appearance="subtle" onClick={() => setQuery(q)}>{q.split("|")[0].trim()}</Button>)}
      </div>
      <Textarea value={query} onChange={(_, d) => setQuery(d.value)} aria-label="Query" style={{ width: "100%", minHeight: 100, fontFamily: "monospace" }} />
      <ErrorBar error={error} title="Query failed" />
      {busy && <Loading label="Running query..." />}
      {table && (
        <>
          <div className="vy-count">{table.rows.length} record{table.rows.length === 1 ? "" : "s"}</div>
          <table className="vy-grid">
            <thead><tr>{table.columns.map((c) => <th key={c.name}>{c.name}</th>)}</tr></thead>
            <tbody>
              {table.rows.length ? table.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v ?? "--"}</td>)}</tr>)
                : <tr><td colSpan={table.columns.length} className="vy-muted">No results</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Saved searches ───────────────────────────────────────────────────────────────────────
function SavedSearches({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listSavedSearches(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Saved searches</div>
      <BrowseGrid
        resourceName="saved search" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add saved search</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteSavedSearch(a.resourceGroup, a.name, r.name); reload(); }}
        csvName="saved-searches.csv"
        columns={[
          { key: "name", label: "Display name", value: (r) => r.properties?.displayName || r.name },
          { key: "category", label: "Category", value: (r) => r.properties?.category },
          { key: "query", label: "Query", value: (r) => r.properties?.query },
        ]}
      />
      <AddSavedSearchDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (id, category, displayName, query) => { await api.putSavedSearch(a.resourceGroup, a.name, id, { properties: { category, displayName, query } }); reload(); }} />
    </>
  );
}

function AddSavedSearchDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [id, setId] = useState("");
  const [category, setCategory] = useState("General");
  const [displayName, setDisplayName] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[^<>*%&:\\?+/#]{1,260}$/.test(id) && displayName.trim() && query.trim();
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(id, category, displayName || id, query);
      notify.success(`Saved search '${displayName || id}' was created.`, "Create succeeded");
      setId(""); setDisplayName(""); setQuery(""); onClose();
    } catch (e) { notify.error(e, "Failed to create saved search"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add saved search">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add saved search</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="ID" required><Input value={id} onChange={(_, d) => setId(d.value)} aria-label="ID" /></Field>
              <Field label="Display name" required><Input value={displayName} onChange={(_, d) => setDisplayName(d.value)} aria-label="Display name" /></Field>
              <Field label="Category" required><Input value={category} onChange={(_, d) => setCategory(d.value)} aria-label="Category" /></Field>
              <Field label="Query" required><Textarea value={query} onChange={(_, d) => setQuery(d.value)} aria-label="Query" /></Field>
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

// ── Tables (built-in + custom _CL/_RST) ──────────────────────────────────────────────────
function Tables({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listTables(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Tables</div>
      <BrowseGrid
        resourceName="table" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add table</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteTable(a.resourceGroup, a.name, r.name); reload(); }}
        csvName="tables.csv"
        columns={[
          { key: "name", label: "Table name" },
          { key: "plan", label: "Plan", value: (r) => r.properties?.plan },
          { key: "retention", label: "Retention (days)", value: (r) => r.properties?.retentionInDays },
          { key: "total", label: "Total retention (days)", value: (r) => r.properties?.totalRetentionInDays },
          { key: "source", label: "Source", value: (r) => r.properties?.schema?.source },
        ]}
      />
      <AddTableDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name) => {
          await api.putTable(a.resourceGroup, a.name, name, { properties: { schema: { columns: [{ name: "TimeGenerated", type: "dateTime" }, { name: "Message", type: "string" }] } } });
          reload();
        }} />
    </>
  );
}

function AddTableDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[A-Za-z][A-Za-z0-9_]{0,60}_(CL|RST)$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name);
      notify.success(`Table '${name}' was created.`, "Create succeeded");
      setName(""); onClose();
    } catch (e) { notify.error(e, "Failed to create table"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add table">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add table</DialogTitle>
          <DialogContent>
            <Field label="Table name" required hint="Must end in _CL (custom log) or _RST (restored logs); starts with a letter.">
              <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Table name" />
            </Field>
            <p style={{ fontSize: 12, marginTop: 8 }}>The table is created with a default schema: TimeGenerated (datetime), Message (string).</p>
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

// ── Data sources ──────────────────────────────────────────────────────────────────────────
function DataSources({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listAllDataSources(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Data sources</div>
      <CapabilityContainer id="azure.loganalytics.workspace.datasources" title="Data sources"
        actions={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add data source</ToolbarButton>}>
        <BrowseGrid
          resourceName="data source" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
          items={rows} loading={loading} error={error} onRefresh={reload}
          onDelete={async (sel) => { for (const r of sel) await api.deleteDataSource(a.resourceGroup, a.name, r.name); reload(); }}
          csvName="data-sources.csv"
          columns={[{ key: "name", label: "Name" }, { key: "kind", label: "Kind" }]}
        />
      </CapabilityContainer>
      <AddDataSourceDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, kind) => { await api.putDataSource(a.resourceGroup, a.name, name, { kind, properties: { eventLogName: "System" } }); reload(); }} />
    </>
  );
}

function AddDataSourceDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [kind, setKind] = useState(api.DS_KINDS[0]);
  const [busy, setBusy] = useState(false);
  const valid = /^[^<>*%&:\\?+/#]{1,260}$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name, kind);
      notify.success(`Data source '${name}' was created.`, "Create succeeded");
      setName(""); onClose();
    } catch (e) { notify.error(e, "Failed to create data source"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add data source">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add data source</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
              <Field label="Kind" required>
                <Select value={kind} onChange={(_, d) => setKind(d.value)} aria-label="Kind">
                  {api.DS_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                </Select>
              </Field>
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

// ── Legacy solutions (intelligencePacks) ─────────────────────────────────────────────────
function LegacySolutions({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listPacks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const rows = data || [];
  const toggle = async (pack, enabled) => {
    try { await api.setPack(a.resourceGroup, a.name, pack, enabled); reload(); }
    catch (e) { notify.error(e, "Failed to update solution"); }
  };
  return (
    <CapabilityContainer id="azure.loganalytics.workspace.legacysolutions" title="Legacy solutions">
      {loading ? <Loading /> : (
        <>
          <ErrorBar error={error} />
          <MiniTable columns={["Solution", "Enabled", ""]} empty="No solutions"
            rows={rows.map((p) => (
              <tr key={p.name}>
                <td>{p.name}</td>
                <td>{p.enabled ? "Yes" : "No"}</td>
                <td>{p.enabled ? <Button size="small" onClick={() => toggle(p.name, false)}>Disable</Button> : <Button size="small" onClick={() => toggle(p.name, true)}>Enable</Button>}</td>
              </tr>
            ))} />
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this workspace) ──
const ACTIVITY_LOG_COLUMNS = [
  { key: "operationName", label: "Operation name", value: (r) => r.operationName?.localizedValue || r.operationName?.value, csv: (r) => r.operationName?.value },
  { key: "status", label: "Status", value: (r) => r.status?.localizedValue || r.status?.value, csv: (r) => r.status?.value },
  { key: "time", label: "Time", value: (r) => fmtDate(r.eventTimestamp) },
  { key: "subscription", label: "Subscription", value: (r) => r.subscriptionId },
  { key: "caller", label: "Event initiated by", value: (r) => r.caller },
];

function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const [gap, setGap] = useState(null);
  const [filter, setFilter] = useState("");
  const rows = data || [];
  const filtered = filter.trim() ? rows.filter((r) => ACTIVITY_LOG_COLUMNS.some((c) => String(c.value(r) ?? "").toLowerCase().includes(filter.trim().toLowerCase()))) : rows;
  return (
    <CapabilityContainer id="azure.loganalytics.workspace.activitylog" title={`${a.name} | Activity log`}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!filtered.length} onClick={() => downloadCsv("activity-log.csv", ACTIVITY_LOG_COLUMNS, filtered)}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setFilter("")}>Reset filters</ToolbarButton>
      </div>
      <div className="vy-filters">
        <Input size="small" style={{ width: 280 }} placeholder="Filter by operation, status or caller..."
          value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter by operation, status or caller..." />
      </div>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr>{ACTIVITY_LOG_COLUMNS.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={ACTIVITY_LOG_COLUMNS.length}><Spinner size="tiny" /></td></tr> : filtered.length
            ? filtered.map((r) => <tr key={r.id}>{ACTIVITY_LOG_COLUMNS.map((c) => <td key={c.key}>{c.value(r)}</td>)}</tr>)
            : <tr><td colSpan={ACTIVITY_LOG_COLUMNS.length} className="vy-muted">No events to display</td></tr>}
        </tbody>
      </table>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody><CapabilityContainer id="azure.loganalytics.workspace.listactions" title={gap || ""} /></DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { workspaceName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.OperationalInsights/workspaces", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('workspaceName')]" : a.name, location: a.location, properties: a.properties }],
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
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab>
        <Tab value="bicep">Bicep</Tab>
        <Tab value="terraform">Terraform</Tab>
      </TabList>
      <CapabilityContainer id="azure.loganalytics.workspace.exporttemplate" title="Template">
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        {tab === "arm" && <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
        {tab !== "arm" && <NotSimulatedContainer feature={`${tab === "bicep" ? "Bicep" : "Terraform"} template export`} />}
      </CapabilityContainer>
    </>
  );
}
