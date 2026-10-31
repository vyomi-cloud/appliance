/* Resource group blade: left resource menu + panels. Overview, Tags, Access control (IAM),
 * Locks, Deployments, Export template, Properties, Activity log and the resource-group-scoped
 * Cost Management pages are backed by real native ARM calls; everything else in the menu is
 * an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { downloadCsv, Essentials, ErrorBar, Glyph, InfoBar, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "resourcevisualizer", label: "Resource visualizer" },
  { id: "events", label: "Events" },
  { group: "Settings", items: [
    { id: "deployments", label: "Deployments" },
    { id: "security", label: "Security" },
    { id: "deploymentstacks", label: "Deployment stacks" },
    { id: "policies", label: "Policies" },
    { id: "properties", label: "Properties" },
    { id: "locks", label: "Locks" },
  ] },
  { group: "Cost Management", items: [
    { id: "costanalysis", label: "Cost analysis" },
    { id: "costalertspreview", label: "Cost alerts (preview)" },
    { id: "budgets", label: "Budgets" },
    { id: "advisorrecommendations", label: "Advisor recommendations" },
  ] },
  { group: "Monitoring", items: [
    { id: "insightspreview", label: "Insights (preview)" },
    { id: "alerts", label: "Alerts" },
    { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" },
    { id: "logs", label: "Logs" },
    { id: "workbooks", label: "Workbooks" },
  ] },
  { group: "Automation", items: [
    { id: "tasks", label: "Tasks" },
    { id: "exporttemplate", label: "Export template" },
  ] },
  { group: "Help", items: [
    { id: "resourcehealth", label: "Resource health" },
    { id: "support", label: "Support + Troubleshooting" },
  ] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  resourcevisualizer: "The Resource visualizer graph",
  events: "Event Grid subscriptions on resource group events",
  security: "Microsoft Defender for Cloud",
  deploymentstacks: "Deployment stacks",
  policies: "Azure Policy compliance",
  advisorrecommendations: "Advisor recommendations",
  insightspreview: "Resource group insights",
  alerts: "Alert rules",
  metrics: "Resource group metrics",
  diagnosticsettings: "Diagnostic settings",
  logs: "Log Analytics queries",
  workbooks: "Workbooks",
  tasks: "Tasks",
  resourcehealth: "Resource health",
  support: "Support + Troubleshooting",
};

export default function ResourceGroupBlade({ params }) {
  const { name } = params;
  const panel = params.panel || "overview";
  const group = useAsync(() => api.getGroup(name), [name]);
  const self = `#/resourcegroups/${encodeURIComponent(name)}`;
  useEffect(() => { if (group.data) remember({ name, type: "Resource group", href: self }); }, [!!group.data, self]);

  let body;
  if (group.loading && !group.data) body = <Loading />;
  else if (group.error) body = <><ErrorBar error={group.error} title="Failed to load the resource group" /><Link href="#/resourcegroups">Back to Resource groups</Link></>;
  else {
    const a = group.data, reload = group.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} name={name} />,
      activitylog: () => <ActivityLog name={name} />,
      iam: () => <AccessControlIam name={name} />,
      tags: () => <Tags a={a} reload={reload} />,
      deployments: () => <Deployments name={name} />,
      locks: () => <Locks name={name} />,
      exporttemplate: () => <ExportTemplate a={a} name={name} />,
      properties: () => <Properties a={a} />,
      costanalysis: () => <CostAnalysis name={name} />,
      costalertspreview: () => <CostAlerts name={name} />,
      budgets: () => <Budgets name={name} />,
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
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Resource group" glyph={<Glyph id="resourcegroups" />} closeHref="#/resourcegroups"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self, name }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [tab, setTab] = useState("resources");
  const [gap, setGap] = useState(null); // "Create" | "Manage view" | "Open query" | "Move" | "Open in mobile"
  const [assign, setAssign] = useState(false);
  const resources = useAsync(() => api.listResources(name), [name]);
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Resource group commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setGap("Create")}>Create</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Manage view")}>Manage view</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} as="a" href={`${self}/delete`}>Delete resource group</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Open query")}>Open query</ToolbarButton>
        <ToolbarButton onClick={() => setAssign(true)}>Assign tags</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Move")}>Move</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} as="a" href={`${self}/exporttemplate`}>Export template</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Open in mobile")}>Open in mobile</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
        right={[
          ["Deployments", <Link href={`${self}/deployments`}>Deployments</Link>],
          ["Location", locationLabel(a.location)],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Resource group tabs">
        <Tab value="resources">Resources</Tab>
        <Tab value="recommendations">Recommendations</Tab>
      </TabList>
      {tab === "resources" && (
        <div style={{ marginTop: 12 }}>
          <BrowseGrid
            resourceName="resource" rowKey={(r) => r.id} filterPlaceholder="Filter for any field..."
            items={resources.data || []} loading={resources.loading} error={resources.error} onRefresh={resources.reload}
            onDelete={async (rows) => {
              for (const r of rows) await api.deleteResourceById(r.id);
              notify.success(`Deleted ${rows.length} resource${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
              resources.reload();
            }}
            csvName={`${name}-resources.csv`}
            emptyAction={<Link href="#/">Create a resource</Link>}
            columns={[
              { key: "name", label: "Name" },
              { key: "type", label: "Type" },
              { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            ]}
          />
        </div>
      )}
      {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}

      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={{
                Create: "Creating a new resource from the Marketplace",
                "Manage view": "Saving a custom blade layout",
                "Open query": "Azure Resource Graph Explorer",
                Move: "Moving resources to another resource group or subscription",
                "Open in mobile": "Opening this resource group in the Azure mobile app",
              }[gap] || gap} />
            </DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <AssignTagsDialog open={assign} onClose={() => setAssign(false)} tags={a.tags || {}}
        onAssign={async (name2, value) => {
          await api.createGroup(a.name, { location: a.location, tags: { ...a.tags, [name2]: value } });
          notify.success(`Tag '${name2}' was assigned to '${a.name}'.`, "Tags saved");
          reload();
        }} />
    </>
  );
}

function AssignTagsDialog({ open, tags, onClose, onAssign }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onAssign(name, value); setName(""); setValue(""); onClose(); }
    catch (e) { notify.error(e, "Assigning tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Assign tags">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Assign tags</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <p style={{ fontSize: 13 }}>{Object.keys(tags).length} existing tag{Object.keys(tags).length === 1 ? "" : "s"}.</p>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Tag name" /></Field>
              <Field label="Value"><Input value={value} onChange={(_, d) => setValue(d.value)} aria-label="Tag value" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!name || busy} onClick={go}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
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
  const apply = async (desired) => {
    setBusy(true);
    try {
      // PUT replaces the resource group's tag set exactly (a PATCH would merge and keep removed keys).
      await api.createGroup(a.name, { location: a.location, tags: Object.fromEntries((desired ?? rows).filter((t) => t.name).map((t) => [t.name, t.value])) });
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
        <Button appearance="primary" disabled={busy} onClick={() => apply()}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={() => { const empty = [{ name: "", value: "" }]; setRows(empty); apply(empty); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Access control (IAM) — role assignments are real ARM resources scoped to this resource
// group (core/azure_arm_core.py stamps properties.scope from the containing resourceGroups
// id); Check access / My access run the real checkAccess decision algorithm. ──
const CURRENT_USER = "admin@vyomi.local";    // the one simulated signed-in identity (see web_engine._record_event)

function AccessControlIam({ name }) {
  const notify = useNotify();
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  const [add, setAdd] = useState(false);
  const [sel, setSel] = useState(new Set());
  const assignments = useAsync(() => api.listRoleAssignments(name), [name]);
  const definitions = useAsync(() => api.listRoleDefinitions(name), [name]);
  const rows = assignments.data || [];
  const roleNameOf = (r) => r.properties?.roleName || r.properties?.roleDefinitionId?.split("/").pop();
  const toggle = (n) => setSel((s) => { const k = new Set(s); k.has(n) ? k.delete(n) : k.add(n); return k; });
  const removeSelected = async () => {
    for (const n of sel) await api.deleteRoleAssignment(name, n);
    notify.success(`Removed ${sel.size} role assignment${sel.size === 1 ? "" : "s"}.`, "Remove succeeded");
    setSel(new Set());
    assignments.reload();
  };
  return (
    <>
      <div className="vy-panel-title">Access control (IAM)</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Access control commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
        <ToolbarButton onClick={() => downloadCsv("role-assignments.csv",
          [{ key: "principal", label: "Name" }, { key: "role", label: "Role" }, { key: "scope", label: "Scope" }],
          rows.map((r) => ({ principal: r.properties?.principalId, role: roleNameOf(r), scope: r.properties?.scope })))}>
          Download role assignments
        </ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { assignments.reload(); definitions.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} disabled={!sel.size} onClick={removeSelected}>Remove</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="check">Check access</Tab>
        <Tab value="assignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "check" && (
        <CapabilityContainer id="azure.resourcegroups.access_control_iam" title="Check access">
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <section className="vy-section"><h3>My access</h3>
              <p style={{ fontSize: 13 }}>The roles {CURRENT_USER} has on this resource group.</p>
              <Button onClick={() => setDlg("mine")}>View my access</Button>
            </section>
            <section className="vy-section"><h3>Check access</h3>
              <p style={{ fontSize: 13 }}>Check whether a specific user can perform a specific action on this resource group.</p>
              <Button onClick={() => setDlg("check")}>Check access</Button>
            </section>
          </div>
        </CapabilityContainer>
      )}
      {tab === "assignments" && (
        <CapabilityContainer id="azure.resourcegroups.access_control_iam" title="Role assignments">
          <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Search by name or email" aria-label="Search by name or email" />
          <table className="vy-grid"><thead><tr><th /><th>Name</th><th>Type</th><th>Role</th><th>Scope</th><th>Condition</th></tr></thead>
            <tbody>
              {assignments.loading ? <tr><td colSpan={6}><Spinner size="tiny" /></td></tr> : rows.map((r) => (
                <tr key={r.name}>
                  <td><Checkbox checked={sel.has(r.name)} onChange={() => toggle(r.name)} aria-label={`Select ${r.properties?.principalId}`} /></td>
                  <td>{r.properties?.principalId}</td><td>{r.properties?.principalType}</td>
                  <td>{roleNameOf(r)}</td><td>{r.properties?.scope}</td><td>None</td>
                </tr>
              ))}
              {!assignments.loading && !rows.length && <tr><td colSpan={6} className="vy-muted">No role assignments found for this scope.</td></tr>}
            </tbody>
          </table>
        </CapabilityContainer>
      )}
      {tab === "roles" && (
        <CapabilityContainer id="azure.resourcegroups.access_control_iam" title="Roles">
          <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Search by role name, description, permission, or ID" aria-label="Search by role name, description, permission, or ID" />
          <table className="vy-grid"><thead><tr><th>Name</th><th>Description</th><th>Type</th><th>Category</th><th>Details</th></tr></thead>
            <tbody>
              {definitions.loading ? <tr><td colSpan={5}><Spinner size="tiny" /></td></tr> : (definitions.data || []).map((r) => (
                <tr key={r.name}><td>{r.name}</td><td>{r.properties?.description || "--"}</td><td>{r.properties?.type}</td><td>General</td><td>{r.assignmentCount} assignment{r.assignmentCount === 1 ? "" : "s"}</td></tr>
              ))}
              {!definitions.loading && !(definitions.data || []).length && <tr><td colSpan={5} className="vy-muted">No roles found.</td></tr>}
            </tbody>
          </table>
        </CapabilityContainer>
      )}
      {tab === "deny" && (
        <CapabilityContainer id="azure.resourcegroups.access_control_iam" title="Deny assignments">
          <table className="vy-grid"><thead><tr><th>Name</th><th>Description</th><th>Principal</th><th>Scope</th></tr></thead>
            <tbody><tr><td colSpan={4} className="vy-muted">No deny assignments found.</td></tr></tbody>
          </table>
        </CapabilityContainer>
      )}
      {tab === "classic" && (
        <CapabilityContainer id="azure.resourcegroups.access_control_iam" title="Classic administrators">
          <InfoBar>No classic administrators are configured for this subscription.</InfoBar>
        </CapabilityContainer>
      )}
      <AddRoleAssignmentDialog open={add} onClose={() => setAdd(false)} roles={definitions.data || []}
        onCreate={async (roleName, principalId) => {
          await api.putRoleAssignment(name, api.uid(), { properties: { roleName, principalId, principalType: "User" } });
          assignments.reload();
        }} />
      <CheckAccessDialog open={!!dlg} mine={dlg === "mine"} onClose={() => setDlg(null)}
        onCheck={(principalId, action) => api.checkAccess(name, principalId, action)} />
    </>
  );
}

function AddRoleAssignmentDialog({ open, onClose, onCreate, roles }) {
  const notify = useNotify();
  const [roleName, setRoleName] = useState("");
  const [principalId, setPrincipalId] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setRoleName(roles[0]?.name || ""); setPrincipalId(""); } }, [open, roles]);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(roleName, principalId);
      notify.success(`'${roleName}' was assigned to '${principalId}'.`, "Add role assignment");
      onClose();
    } catch (e) { notify.error(e, "Failed to add role assignment"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add role assignment">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add role assignment</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Role" required>
                <Select value={roleName} onChange={(_, d) => setRoleName(d.value)} aria-label="Role">
                  {roles.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
                </Select>
              </Field>
              <Field label="Member" required hint="A user, group or service principal name — Vyomi has no directory to search, so type the exact principal ID.">
                <Input value={principalId} onChange={(_, d) => setPrincipalId(d.value)} aria-label="Member" placeholder="e.g. alice@contoso.com" />
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !roleName || !principalId} onClick={go}>Review + assign</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function CheckAccessDialog({ open, mine, onClose, onCheck }) {
  const [principalId, setPrincipalId] = useState("");
  const [action, setAction] = useState("Microsoft.Resources/subscriptions/resourceGroups/read");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) { setResult(null); return; }
    if (mine) { setPrincipalId(CURRENT_USER); run(CURRENT_USER, action); } else { setPrincipalId(""); setResult(null); }
  }, [open, mine]);
  const run = async (pid, act) => {
    setBusy(true);
    try { setResult((await onCheck(pid, act))[0] || null); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={mine ? "My access" : "Check access"}>
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>{mine ? "My access" : "Check access"}</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {!mine && <Field label="Find a user, group or service principal" required>
                <Input value={principalId} onChange={(_, d) => setPrincipalId(d.value)} aria-label="Find a user, group or service principal" placeholder="e.g. bob@contoso.com" />
              </Field>}
              <Field label="Action to check" required hint="An ARM operation ID, e.g. Microsoft.Storage/storageAccounts/write">
                <Input value={action} onChange={(_, d) => setAction(d.value)} aria-label="Action to check" />
              </Field>
              <Button appearance="primary" disabled={busy || !principalId || !action} onClick={() => run(principalId, action)}>Check access</Button>
              {busy && <Spinner size="tiny" />}
              {result && (
                <InfoBar intent={result.accessDecision === "Allowed" ? "success" : "warning"}>
                  <b>{principalId}</b> is <b>{result.accessDecision}</b> to perform <code>{action}</code> on this resource group
                  {result.roles?.length ? ` via: ${result.roles.join(", ")}` : ""}.
                </InfoBar>
              )}
            </div>
          </DialogContent>
          <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to the resource group itself) ─────────
function Locks({ name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(name), [name]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null); // "Subscription" | "Resource group" | "Feedback"
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Subscription")}>Subscription</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteLock(name, r.name);
          notify.success(`Deleted ${sel.length} lock${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="locks.csv"
        columns={[
          { key: "name", label: "Lock name" },
          { key: "type", label: "Lock type", value: (r) => (r.properties?.level === "ReadOnly" ? "Read-only" : "Delete") },
          { key: "scope", label: "Scope", value: () => name },
          { key: "notes", label: "Notes", value: (r) => r.properties?.notes || "--" },
        ]}
        emptyAction={<span className="vy-muted">This resource has no locks.</span>}
      />
      <AddLockDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (lockName, level, notes) => { await api.putLock(name, lockName, { properties: { level, notes } }); reload(); }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap === "Subscription" ? "Resource group" : gap}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : "Locks scoped to the subscription (viewing another scope's lock list)"} />
            </DialogContent>
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

// ── Deployments (Microsoft.Resources/deployments) ──────────────────────────────────────
function Deployments({ name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDeployments(name), [name]);
  const [tpl, setTpl] = useState(null);
  const [busy, setBusy] = useState(false);
  const rows = data || [];
  const act = async (verb, fn, depName) => {
    setBusy(true);
    try {
      await fn(name, depName);
      notify.success(`${verb === "cancel" ? "Cancel" : "Redeploy"} of '${depName}' ${verb === "cancel" ? "requested" : "succeeded"}.`, verb === "cancel" ? "Cancel" : "Redeploy");
    } catch (e) { notify.error(e, verb === "cancel" ? "Cancel failed" : "Redeploy failed"); }
    finally { setBusy(false); reload(); }
  };
  return (
    <>
      <CapabilityContainer id="azure.resourcegroups.deployments" title="Deployments">
      <BrowseGrid
        resourceName="deployment" rowKey={(r) => r.name} filterPlaceholder="Filter by deployment name"
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={(selected) => <>
          <ToolbarButton disabled={busy || selected.length !== 1} onClick={() => act("cancel", api.cancelDeployment, selected[0]?.name)}>Cancel</ToolbarButton>
          <ToolbarButton disabled={busy || selected.length !== 1} onClick={() => act("redeploy", api.redeployDeployment, selected[0]?.name)}>Redeploy</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteDeployment(name, r.name);
          notify.success(`Deleted ${sel.length} deployment${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="deployments.csv"
        emptyAction={<span className="vy-muted">No deployments found.</span>}
        columns={[
          { key: "name", label: "Deployment name" },
          { key: "status", label: "Status", value: (r) => r.properties?.provisioningState || "--" },
          { key: "modified", label: "Last modified", value: (r) => (r.properties?.timestamp ? fmtDate(r.properties.timestamp) : "--") },
          { key: "duration", label: "Duration", value: (r) => (r.properties?.provisioningState === "Succeeded" ? "Less than a minute" : "--") },
          { key: "events", label: "Related events", value: () => "--" },
          { key: "template", label: "", render: (r) => <Link as="button" onClick={() => setTpl(r)}>View template</Link> },
        ]}
      />
      </CapabilityContainer>
      <Dialog open={!!tpl} onOpenChange={(_, d) => !d.open && setTpl(null)}>
        <DialogSurface aria-label="Template">
          <DialogBody>
            <DialogTitle>{tpl?.name}</DialogTitle>
            <DialogContent>
              <Textarea readOnly value={JSON.stringify(tpl?.properties?.template || {}, null, 2)} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />
              {tpl?.properties?.outputResources?.length > 0 && <>
                <p style={{ marginTop: 12, fontWeight: 600 }}>Resources provisioned by this deployment</p>
                <ul>{tpl.properties.outputResources.map((r) => <li key={r.id}>{r.resourceType}/{r.resourceName}</li>)}</ul>
              </>}
            </DialogContent>
            <DialogActions><Button onClick={() => setTpl(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Activity log ─────────────────────────────────────────────────────────────────────────
function ActivityLog({ name }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(name), [name]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">{name} | Activity log</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv("activity-log.csv",
          [{ key: "op", label: "Operation name" }, { key: "status", label: "Status" }, { key: "ts", label: "Time stamp" }],
          rows.map((r) => ({ op: r.operationName?.localizedValue || r.operationName?.value, status: r.status?.localizedValue || r.status?.value, ts: r.eventTimestamp })))}>
          Download as CSV
        </ToolbarButton>
      </div>
      <ErrorBar error={error} />
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
      <NotSimulatedContainer feature="Activity, Edit columns, Export Activity Logs, Insights, Feedback, Pin current filters and Reset filters from the command bar" />
    </>
  );
}

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a, name }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const resources = useAsync(() => api.listResources(name), [name]);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { resourceGroupTags: { type: "object", defaultValue: a.tags || {} } } } : {}),
    resources: (resources.data || []).map((r) => ({ type: r.type, apiVersion: "2023-01-01", name: r.name, location: r.location, properties: r.properties })),
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

// ── Properties ─────────────────────────────────────────────────────────────────────────
function Properties({ a }) {
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <div className="vy-props">
        <KV label="Resource group" value={a.name} />
        <KV label="Resource ID" value={a.id} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="Provisioning state" value={a.properties?.provisioningState} />
        <KV label="Tags" value={Object.entries(a.tags || {}).map(([k, v]) => `${k}=${v}`).join(", ") || undefined} />
      </div>
    </>
  );
}

// ── Cost Management, scoped to this resource group ─────────────────────────────────────
const DOLLAR = (n) => `$${Number(n || 0).toFixed(2)}`;

function CostAnalysis({ name }) {
  const [total, setTotal] = useState(null);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api.costQuery(name, { type: "ActualCost", timeframe: "MonthToDate", dataset: { aggregation: { totalCost: { name: "Cost", function: "Sum" } } } })
      .then((r) => setTotal(r.properties.rows[0]?.[0] || 0)).catch(setError);
    api.costQuery(name, { type: "ActualCost", timeframe: "MonthToDate", dataset: { grouping: [{ type: "Dimension", name: "ServiceName" }] } })
      .then((r) => setRows(r.properties.rows)).catch(() => setRows([]));
  }, [name]);
  return (
    <>
      <div className="vy-panel-title">Cost analysis</div>
      <ErrorBar error={error} title="Cost query failed" />
      <div className="vy-kv"><span>Actual cost (USD), this resource group</span><span>{total == null ? "Loading..." : DOLLAR(total)}</span></div>
      <section className="vy-form-section"><h3>Cost by service name</h3>
        {rows === null ? <Loading /> : rows.length === 0 ? <p>No cost yet.</p> : (
          <Table size="small" aria-label="Cost by service name">
            <TableHeader><TableRow><TableHeaderCell>Service name</TableHeaderCell><TableHeaderCell>Cost</TableHeaderCell></TableRow></TableHeader>
            <TableBody>{rows.map(([cost, key]) => <TableRow key={key}><TableCell>{key}</TableCell><TableCell>{DOLLAR(cost)}</TableCell></TableRow>)}</TableBody>
          </Table>
        )}
      </section>
    </>
  );
}

function Budgets({ name }) {
  const { data, loading, error, reload } = useAsync(() => api.listBudgets(name), [name]);
  return (
    <>
      <div className="vy-panel-title">Budgets</div>
      <BrowseGrid
        resourceName="budget" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        csvName="budgets.csv"
        emptyAction={<span className="vy-muted">No budgets for this resource group.</span>}
        columns={[
          { key: "name", label: "Name" },
          { key: "amount", label: "Amount", value: (b) => DOLLAR(b.properties?.amount) },
          { key: "spend", label: "Evaluated spend", value: (b) => DOLLAR(b.properties?.currentSpend?.amount) },
        ]}
      />
    </>
  );
}

function CostAlerts({ name }) {
  const { data, loading, error, reload } = useAsync(() => api.listCostAlerts(name), [name]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Cost alerts (preview)</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Cost alerts commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <ErrorBar error={error} title="Failed to load alerts" />
      {loading ? <Loading /> : !rows.length ? <p>No cost alerts to display. Alerts appear automatically once a budget crosses its threshold.</p> : (
        <Table size="small" aria-label="Cost alerts">
          <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Created on</TableHeaderCell></TableRow></TableHeader>
          <TableBody>{rows.map((a) => <TableRow key={a.name}><TableCell>{a.properties?.description}</TableCell><TableCell>{a.properties?.status}</TableCell><TableCell>{fmtDate(a.properties?.creationTime)}</TableCell></TableRow>)}</TableBody>
        </Table>
      )}
    </>
  );
}
