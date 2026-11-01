/* Panels shared by the Environment / Container App / Job blades: Tags, Locks, Activity log,
 * Access control (IAM), Diagnostic settings and Export template are the same generic ARM
 * extension-resource engine (core/azure_arm_core.py) every other Azure blade in this lens
 * uses — genericised here over `resPath` (the resource's own ARM id) instead of being
 * duplicated three times. */
import { useEffect, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Spinner,
  Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowUpload20Regular, DocumentArrowDown20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { ErrorBar, Loading, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export function MiniTable({ columns, rows, empty }) {
  return (
    <table className="vy-grid" style={{ marginTop: 8 }}>
      <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{rows.length ? rows : <tr><td colSpan={columns.length} className="vy-muted">{empty}</td></tr>}</tbody>
    </table>
  );
}

export function ActivityLog({ resPath, name }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(resPath), [resPath]);
  const rows = (data || []).map((e) => ({
    key: e.id, op: e.operationName?.localizedValue || e.operationName?.value || "--",
    status: e.status?.localizedValue || e.status?.value || "--",
    time: e.eventTimestamp ? new Date(e.eventTimestamp).toLocaleString() : "--",
    ts: e.eventTimestamp || "--", sub: e.subscriptionId || "--", caller: e.caller || "--",
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
            {rows.length === 0 ? <tr><td colSpan={6}>No events to display</td></tr>
              : rows.map((r) => <tr key={r.key}><td>{r.op}</td><td>{r.status}</td><td>{r.time}</td><td>{r.ts}</td><td>{r.sub}</td><td>{r.caller}</td></tr>)}
          </tbody>
        </table>
      )}
      <NotSimulatedContainer feature="Activity log filters and export"
        note="Filters (Management Group, Subscription, Event severity, Timespan, Resource group, Resource, Add Filter) and the Edit columns / Export Activity Logs / Download as CSV / Insights / Feedback / Pin current filters / Reset filters actions are not simulated; Vyomi lists the real create/update/delete/action operations performed on this resource." />
    </>
  );
}

export function AccessControlIam({ resPath, name, capId }) {
  const [tab, setTab] = useState("checkaccess");
  const assignments = useAsync(() => api.listRoleAssignments(resPath), [resPath]);
  const definitions = useAsync(() => api.listRoleDefinitions(), []);
  return (
    <>
      <div className="vy-panel-title">{name} | Access control (IAM)</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Access control commands">
        <ToolbarButton icon={<ArrowUpload20Regular />}>Add</ToolbarButton>
        <ToolbarButton>Download role assignments</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { assignments.reload(); definitions.reload(); }}>Refresh</ToolbarButton>
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
          <section className="vy-section"><h3>My access</h3><Button>View my access</Button></section>
          <section className="vy-section"><h3>Check access</h3><Button>Check access</Button></section>
        </div>
      )}
      {tab === "roleassignments" && (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id={capId} title="Role assignments">
            <table className="vy-grid"><thead><tr><th>Name</th><th>Type</th><th>Role</th><th>Scope</th></tr></thead>
              <tbody>
                {assignments.loading ? <tr><td colSpan={4}><Spinner size="tiny" /></td></tr> : (assignments.data || []).map((r) => (
                  <tr key={r.name}><td>{r.properties?.principalId}</td><td>{r.properties?.principalType}</td><td>{r.properties?.roleDefinitionId?.split("/").pop() || r.properties?.roleName}</td><td>{r.properties?.scope}</td></tr>
                ))}
                {!assignments.loading && !(assignments.data || []).length && <tr><td colSpan={4} className="vy-muted">No role assignments found for this scope.</td></tr>}
              </tbody>
            </table>
          </CapabilityContainer>
        </div>
      )}
      {tab === "roles" && (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id={capId} title="Roles">
            <table className="vy-grid"><thead><tr><th>Role</th><th>Type</th><th>Description</th></tr></thead>
              <tbody>{(definitions.data || []).map((r) => <tr key={r.name}><td>{r.properties?.roleName}</td><td>{r.properties?.type}</td><td>{r.properties?.description}</td></tr>)}</tbody>
            </table>
          </CapabilityContainer>
        </div>
      )}
      {tab === "denyassignments" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Deny assignments" feature="Deny assignments" /></div>}
      {tab === "classicadministrators" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Classic administrators" feature="Classic administrators" /></div>}
    </>
  );
}

export function Tags({ a, name, reload, save }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([n, value]) => ({ name: n, value })), { name: "", value: "" }];
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
    try { await save(Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value]))); notify.success(`Tags on '${name}' were updated.`, "Tags saved"); reload(); }
    catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Tags</div>
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

export function Locks({ resPath, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(resPath), [resPath]);
  const [f, setF] = useState({ name: "", level: "CanNotDelete", notes: "" });
  const [busy, setBusy] = useState(false);
  const add = async () => {
    setBusy(true);
    try { await api.addLock(resPath, f.name, f.level, f.notes); notify.success(`Lock '${f.name}' was added.`, "Add succeeded"); setF({ name: "", level: "CanNotDelete", notes: "" }); reload(); }
    catch (e) { notify.error(e, "Add lock failed"); }
    finally { setBusy(false); }
  };
  const rows = (data || []).map((l) => ({ ...l, scope: name, level: l.properties?.level === "ReadOnly" ? "Read-only" : "Delete" }));
  return (
    <>
      <div className="vy-panel-title">{name} | Locks</div>
      <div className="vy-panel-title" style={{ fontSize: 13, fontWeight: 400 }}>Add lock</div>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
        <Field label="Lock name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} /></Field>
        <Field label="Lock type" required><Select value={f.level} onChange={(_, d) => setF((x) => ({ ...x, level: d.value }))} aria-label="Lock type"><option value="ReadOnly">Read-only</option><option value="CanNotDelete">Delete</option></Select></Field>
        <Field label="Notes"><Textarea value={f.notes} onChange={(_, d) => setF((x) => ({ ...x, notes: d.value }))} /></Field>
        <Button icon={<Add20Regular />} disabled={!f.name || busy} onClick={add}>{busy ? "Adding..." : "Add"}</Button>
      </div>
      <BrowseGrid
        resourceName="lock" items={rows} loading={loading} error={error} onRefresh={reload}
        onDelete={async (xs) => { for (const r of xs) await api.removeLock(resPath, r.name); notify.success("Lock(s) removed.", "Delete succeeded"); reload(); }}
        columns={[{ key: "name", label: "Lock name" }, { key: "level", label: "Lock type" }, { key: "scope", label: "Scope" }, { key: "notes", label: "Notes", value: (r) => r.properties?.notes }]}
        emptyAction={null}
      />
    </>
  );
}

export function DiagnosticSettings({ resPath, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDiagnosticSettings(resPath), [resPath]);
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [adding, setAdding] = useState(false);
  const [dsName, setDsName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await api.putDiagnosticSetting(resPath, dsName, { properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] } });
      notify.success(`Diagnostic setting '${dsName}' was created.`, "Save succeeded");
      setAdding(false); setDsName(""); reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Diagnostic settings</div>
      <p style={{ fontSize: 13 }}>Diagnostic settings specify a destination for platform logs and metrics from this resource.</p>
      <BrowseGrid
        resourceName="diagnostic setting" items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setAdding(true)}
        onDelete={async (rows) => { for (const r of rows) await api.deleteDiagnosticSetting(resPath, r.name); notify.success("Diagnostic setting(s) deleted.", "Delete succeeded"); reload(); }}
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

export function ExportTemplate({ a, name, type, extra }) {
  const [tab, setTab] = useState("arm");
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", contentVersion: "1.0.0.0",
    resources: [{ type, apiVersion: api.API_VERSION, name: a.name, location: a.location, properties: a.properties, ...extra }],
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Export template</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<DocumentArrowDown20Regular />} onClick={() => {
          const blob = new Blob([JSON.stringify(template, null, 2)], { type: "application/json" });
          const u = URL.createObjectURL(blob); const el = document.createElement("a"); el.href = u; el.download = `${a.name}.json`; document.body.appendChild(el); el.click(); el.remove();
          setTimeout(() => URL.revokeObjectURL(u), 1000);
        }}>Download</ToolbarButton>
        <ToolbarButton disabled>Deploy</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab><Tab value="bicep">Bicep</Tab><Tab value="terraform">Terraform</Tab>
      </TabList>
      {tab === "arm" && (
        <section className="vy-section"><h3>Template</h3>
          <pre className="vy-mono" style={{ maxHeight: 360, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 10, borderRadius: 4, fontSize: 12 }}>{JSON.stringify(template, null, 2)}</pre>
        </section>
      )}
      {tab === "bicep" && <NotSimulatedContainer feature="ARM-to-Bicep decompilation" />}
      {tab === "terraform" && <NotSimulatedContainer feature="ARM-to-Terraform export" />}
    </>
  );
}

export const activityLogFmt = fmtDate;
