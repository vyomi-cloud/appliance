/* Subscription blade: left resource menu + panels. Overview, Activity log, Access control
 * (IAM), Tags, Cost Management (Cost analysis/Cost alerts/Budgets), Resource groups,
 * Resources, Resource providers, Deployments and Resource locks are backed by real native
 * ARM calls; everything else in the menu is an honest NotSimulated panel. */
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
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { downloadCsv, Essentials, ErrorBar, Glyph, InfoBar, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember } from "../../kit/recent.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "security", label: "Security" },
  { id: "events", label: "Events" },
  { group: "Cost Management", items: [
    { id: "costanalysis", label: "Cost analysis" },
    { id: "costalerts", label: "Cost alerts" },
    { id: "budgets", label: "Budgets" },
    { id: "advisorrecommendations", label: "Advisor recommendations" },
  ] },
  { group: "Billing", items: [
    { id: "invoices", label: "Invoices" },
    { id: "partnerinformation", label: "Partner information" },
  ] },
  { group: "Settings", items: [
    { id: "programmaticdeployment", label: "Programmatic deployment" },
    { id: "billingproperties", label: "Billing properties" },
    { id: "resourcegroups", label: "Resource groups" },
    { id: "resources", label: "Resources" },
    { id: "previewfeatures", label: "Preview features" },
    { id: "usagequotas", label: "Usage + quotas" },
    { id: "policies", label: "Policies" },
    { id: "managementcertificates", label: "Management certificates" },
    { id: "mypermissions", label: "My permissions" },
    { id: "resourceproviders", label: "Resource providers" },
    { id: "deployments", label: "Deployments" },
    { id: "deploymentstacks", label: "Deployment stacks" },
    { id: "resourcelocks", label: "Resource locks" },
  ] },
  { group: "Help", items: [
    { id: "support", label: "Support + Troubleshooting" },
  ] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
// The portal's Essentials "Offer"/"Offer ID" are looked up from subscriptionPolicies.quotaId
// through this same static catalog in real Azure — not a separate field on the subscription.
const OFFERS = { "PayAsYouGo_2014-09-01": { offer: "Pay-As-You-Go", offerId: "MS-AZR-0003P" } };
// Every other menu item with no dedicated panel below: the remaining honest not_simulated gaps.
const GAP_CAP = {
  managementcertificates: "azure.subscriptions.management_certificates",
  partnerinformation: "azure.subscriptions.partner_information",
  support: "azure.subscriptions.support_troubleshooting",
};

export default function SubscriptionBlade({ params }) {
  const { id } = params;
  const panel = params.panel || "overview";
  const sub = useAsync(() => api.getSubscriptionInfo(id), [id]);
  const self = `#/subscriptions/${encodeURIComponent(id)}`;
  const name = sub.data?.displayName || id;
  useEffect(() => { if (sub.data) remember({ name, type: "Subscription", href: self }); }, [!!sub.data, name, self]);

  let body;
  if (sub.loading && !sub.data) body = <Loading />;
  else if (sub.error) body = <><ErrorBar error={sub.error} title="Failed to load the subscription" /><Link href="#/subscriptions">Back to Subscriptions</Link></>;
  else {
    const a = sub.data, reload = sub.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} id={id} name={name} self={self} />,
      activitylog: () => <ActivityLog id={id} name={name} />,
      iam: () => <AccessControlIam id={id} />,
      tags: () => <Tags a={a} id={id} reload={reload} />,
      costanalysis: () => <CostAnalysis id={id} />,
      costalerts: () => <CostAlerts id={id} />,
      budgets: () => <Budgets id={id} />,
      resourcegroups: () => <ResourceGroupsPanel id={id} />,
      resources: () => <ResourcesPanel id={id} />,
      resourceproviders: () => <ResourceProviders id={id} />,
      deployments: () => <Deployments id={id} />,
      resourcelocks: () => <Locks id={id} />,
      security: () => <Security id={id} />,
      diagnose: () => <Diagnostics id={id} />,
      events: () => <Events id={id} />,
      advisorrecommendations: () => <Advisor id={id} />,
      invoices: () => <Invoices id={id} />,
      previewfeatures: () => <PreviewFeatures id={id} />,
      usagequotas: () => <UsageQuotas id={id} name={name} />,
      policies: () => <Policies id={id} />,
      mypermissions: () => <MyPermissions id={id} />,
      deploymentstacks: () => <DeploymentStacks id={id} />,
      programmaticdeployment: () => <ProgrammaticDeployment id={id} />,
      billingproperties: () => <BillingProperties id={id} />,
    }[panel];
    body = P ? P() : <CapabilityContainer id={GAP_CAP[panel] || "azure.subscriptions.menu_gaps"} title={`${name} | ${LABEL[panel] || panel}`} />;
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Subscription" glyph={<Glyph id="subscriptions" />} closeHref="#/subscriptions"
      menu={MENU} active={panel} hrefFor={(pid) => (pid === "overview" ? self : `${self}/${pid}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, id, name, self }) {
  const notify = useNotify();
  const [tab, setTab] = useState("start");
  const [gap, setGap] = useState(null); // "Cancel subscription" | "Change directory" | "Feedback"
  const [rename, setRename] = useState(false);
  const cost = useAsync(() => api.costQuery(id, { type: "ActualCost", timeframe: "MonthToDate", dataset: { aggregation: { totalCost: { name: "Cost", function: "Sum" } } } }), [id]);
  const byResource = useAsync(() => api.costQuery(id, { type: "ActualCost", timeframe: "MonthToDate", dataset: { grouping: [{ type: "Dimension", name: "ResourceId" }] } }), [id]);
  const DOLLAR = (n) => `$${Number(n || 0).toFixed(2)}`;
  const offer = OFFERS[a.subscriptionPolicies?.quotaId] || { offer: "--", offerId: "--" };
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Subscription commands">
        <ToolbarButton onClick={() => setGap("Cancel subscription")}>Cancel subscription</ToolbarButton>
        <ToolbarButton onClick={() => setRename(true)}>Rename</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Change directory")}>Change directory</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Subscription ID", id],
          ["Directory", "Vyomi simulator (default directory)"],
          ["My role", "Owner"],
          ["Offer", offer.offer],
        ]}
        right={[
          ["Offer ID", offer.offerId],
          ["Parent management group", "--"],
          ["Status", a.state || "Enabled"],
          ["Secure score", "--"],
        ]}
        actions={<CapabilityBadge id="azure.subscriptions.overview" />}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Subscription tabs">
        <Tab value="start">Get started</Tab>
        <Tab value="spending">Spending</Tab>
        <Tab value="byresource">Costs by resource</Tab>
        <Tab value="free">Top free services by usage</Tab>
      </TabList>
      {tab === "start" && (
        <div style={{ marginTop: 12, fontSize: 13, lineHeight: 1.6 }}>
          <p>Welcome to subscription <b>{name}</b>. Use the resource menu on the left to manage access, tags, cost and the resource groups and resources that live in this subscription.</p>
          <p>Create your first resource group from <Link href={`${self}/resourcegroups`}>Resource groups</Link>, or browse everything already in this subscription from <Link href={`${self}/resources`}>Resources</Link>.</p>
        </div>
      )}
      {tab === "spending" && (
        <div style={{ marginTop: 12 }}>
          <ErrorBar error={cost.error} title="Cost query failed" />
          <div className="vy-kv"><span>Actual cost (USD), month to date</span><span>{cost.loading ? "Loading..." : DOLLAR(cost.data?.properties?.rows?.[0]?.[0])}</span></div>
        </div>
      )}
      {tab === "byresource" && (
        <div style={{ marginTop: 12 }}>
          <ErrorBar error={byResource.error} title="Cost query failed" />
          {byResource.loading ? <Loading /> : !byResource.data?.properties?.rows?.length ? <p>No cost yet.</p> : (
            <Table size="small" aria-label="Costs by resource">
              <TableHeader><TableRow><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell>Cost</TableHeaderCell></TableRow></TableHeader>
              <TableBody>{byResource.data.properties.rows.map(([cost2, key]) => <TableRow key={key}><TableCell>{key}</TableCell><TableCell>{DOLLAR(cost2)}</TableCell></TableRow>)}</TableBody>
            </Table>
          )}
        </div>
      )}
      {tab === "free" && <div style={{ marginTop: 12 }}><NotSimulatedContainer feature="Top free services by usage" /></div>}

      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={{
                "Cancel subscription": "Cancelling the subscription — every other Vyomi Azure service's fixtures depend on this one simulated subscription existing",
                "Change directory": "Multi-tenant directories (Microsoft Entra ID)",
                Feedback: "Sending product feedback",
              }[gap] || gap} />
            </DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <RenameDialog open={rename} onClose={() => setRename(false)} current={name}
        onRename={async (newName) => { await api.renameSubscription(id, newName); notify.success(`Subscription renamed to '${newName}'.`, "Rename succeeded"); reload(); }} />
    </>
  );
}

function RenameDialog({ open, current, onClose, onRename }) {
  const notify = useNotify();
  const [name, setName] = useState(current);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onRename(name.trim()); onClose(); }
    catch (e) { notify.error(e, "Rename failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => { if (!d.open) { setName(current); onClose(); } }}>
      <DialogSurface aria-label="Rename subscription">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Rename subscription</DialogTitle>
          <DialogContent>
            <Field label="Subscription name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Subscription name" /></Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!name.trim() || busy} onClick={go}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
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
      <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
      <TableBody>
        {tags.map((t, i) => (
          <TableRow key={i}>
            <TableCell><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></TableCell>
            <TableCell><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Tags({ a, id, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  const apply = async (desired) => {
    setBusy(true);
    try {
      await api.putTags(id, Object.fromEntries((desired ?? rows).filter((t) => t.name).map((t) => [t.name, t.value])));
      notify.success("Tags were updated.", "Tags saved");
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
        <Button appearance="primary" disabled={busy} onClick={() => apply()}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={() => { const empty = [{ name: "", value: "" }]; setRows(empty); apply(empty); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Access control (IAM) — role assignments are real ARM resources scoped to this
// subscription (core/azure_arm_core.py stamps properties.scope from the subscription path);
// Check access / My access run the real checkAccess decision algorithm, same as resourcegroups. ──
const CURRENT_USER = "admin@vyomi.local";    // the one simulated signed-in identity

function AccessControlIam({ id }) {
  const notify = useNotify();
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  const [add, setAdd] = useState(false);
  const [sel, setSel] = useState(new Set());
  const assignments = useAsync(() => api.listRoleAssignments(id), [id]);
  const definitions = useAsync(() => api.listRoleDefinitions(id), [id]);
  const rows = assignments.data || [];
  const roleNameOf = (r) => r.properties?.roleName || r.properties?.roleDefinitionId?.split("/").pop();
  const toggle = (n) => setSel((s) => { const k = new Set(s); k.has(n) ? k.delete(n) : k.add(n); return k; });
  const removeSelected = async () => {
    for (const n of sel) await api.deleteRoleAssignment(id, n);
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
        <ToolbarButton onClick={() => setDlg("columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { assignments.reload(); definitions.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} disabled={!sel.size} onClick={removeSelected}>Remove</ToolbarButton>
        <ToolbarButton onClick={() => setDlg("feedback")}>Feedback</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="check">Check access</Tab>
        <Tab value="assignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "check" && (
        <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Check access">
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <section className="vy-section"><h3>My access</h3>
              <p style={{ fontSize: 13 }}>The roles {CURRENT_USER} has on this subscription.</p>
              <Button onClick={() => setDlg("mine")}>View my access</Button>
            </section>
            <section className="vy-section"><h3>Check access</h3>
              <p style={{ fontSize: 13 }}>Check whether a specific user can perform a specific action on this subscription.</p>
              <Button onClick={() => setDlg("check")}>Check access</Button>
            </section>
          </div>
        </CapabilityContainer>
      )}
      {tab === "assignments" && (
        <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Role assignments">
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
        <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Roles">
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
        <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Deny assignments">
          <table className="vy-grid"><thead><tr><th>Name</th><th>Description</th><th>Principal</th><th>Scope</th></tr></thead>
            <tbody><tr><td colSpan={4} className="vy-muted">No deny assignments found.</td></tr></tbody>
          </table>
        </CapabilityContainer>
      )}
      {tab === "classic" && (
        <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Classic administrators">
          <InfoBar>No classic administrators are configured for this subscription.</InfoBar>
        </CapabilityContainer>
      )}
      <AddRoleAssignmentDialog open={add} onClose={() => setAdd(false)} roles={definitions.data || []}
        onCreate={async (roleName, principalId) => {
          await api.putRoleAssignment(id, api.uid(), { properties: { roleName, principalId, principalType: "User" } });
          assignments.reload();
        }} />
      <CheckAccessDialog open={dlg === "mine" || dlg === "check"} mine={dlg === "mine"} onClose={() => setDlg(null)}
        onCheck={(principalId, action) => api.checkAccess(id, principalId, action)} />
      <Dialog open={dlg === "feedback" || dlg === "columns"} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label={dlg === "columns" ? "Edit columns" : "Feedback"}>
          <DialogBody>
            <DialogTitle>{dlg === "columns" ? "Edit columns" : "Feedback"}</DialogTitle>
            <DialogContent><NotSimulated feature={dlg === "columns" ? "Customizing the role-assignments grid's columns" : "Sending product feedback"} /></DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
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
                  <b>{principalId}</b> is <b>{result.accessDecision}</b> to perform <code>{action}</code> on this subscription
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

// ── Activity log (Microsoft.Insights/eventtypes/management/values, subscription-wide) ──
function ActivityLog({ id, name }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(id), [id]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.subscriptions.activity_log" title={`${name} | Activity log`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log tools">
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv("activity-log.csv",
          [{ key: "op", label: "Operation name" }, { key: "status", label: "Status" }, { key: "ts", label: "Time stamp" }],
          rows.map((r) => ({ op: r.operationName?.localizedValue || r.operationName?.value, status: r.status?.localizedValue || r.status?.value, ts: r.eventTimestamp })))}>
          Download as CSV
        </ToolbarButton>
        {["Activity", "Edit columns", "Export Activity Logs", "Insights", "Feedback", "Pin current filters", "Reset filters"].map((l) => (
          <ToolbarButton key={l} onClick={() => setGap(l)}>{l}</ToolbarButton>
        ))}
      </div>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody><DialogTitle>{gap}</DialogTitle><DialogContent><NotSimulated feature={gap || ""} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions></DialogBody>
        </DialogSurface>
      </Dialog>
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
    </CapabilityContainer>
  );
}

// ── Cost Management, subscription scope ─────────────────────────────────────────────────
const DOLLAR = (n) => `$${Number(n || 0).toFixed(2)}`;

function CostAnalysis({ id }) {
  const [total, setTotal] = useState(null);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api.costQuery(id, { type: "ActualCost", timeframe: "MonthToDate", dataset: { aggregation: { totalCost: { name: "Cost", function: "Sum" } } } })
      .then((r) => setTotal(r.properties.rows[0]?.[0] || 0)).catch(setError);
    api.costQuery(id, { type: "ActualCost", timeframe: "MonthToDate", dataset: { grouping: [{ type: "Dimension", name: "ServiceName" }] } })
      .then((r) => setRows(r.properties.rows)).catch(() => setRows([]));
  }, [id]);
  return (
    <>
      <div className="vy-panel-title">Cost analysis</div>
      <ErrorBar error={error} title="Cost query failed" />
      <div className="vy-kv"><span>Actual cost (USD), this subscription</span><span>{total == null ? "Loading..." : DOLLAR(total)}</span></div>
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

function Budgets({ id }) {
  const { data, loading, error, reload } = useAsync(() => api.listBudgets(id), [id]);
  return (
    <>
      <div className="vy-panel-title">Budgets</div>
      <BrowseGrid
        resourceName="budget" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        csvName="budgets.csv"
        emptyAction={<span className="vy-muted">No budgets for this subscription.</span>}
        columns={[
          { key: "name", label: "Name" },
          { key: "amount", label: "Amount", value: (b) => DOLLAR(b.properties?.amount) },
          { key: "spend", label: "Evaluated spend", value: (b) => DOLLAR(b.properties?.currentSpend?.amount) },
        ]}
      />
    </>
  );
}

function CostAlerts({ id }) {
  const { data, loading, error, reload } = useAsync(() => api.listCostAlerts(id), [id]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Cost alerts</div>
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

// ── Settings > Resource groups (subscription-scoped browse, links out to the RG service) ──
function ResourceGroupsPanel({ id }) {
  const { data, loading, error, reload } = useAsync(() => api.listResourceGroups(id), [id]);
  const [gap, setGap] = useState(null);
  return (
    <>
      <div className="vy-panel-title">Resource groups</div>
      <BrowseGrid
        resourceName="resource group" rowKey={(r) => r.id} filterPlaceholder="Filter for any field..."
        items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => navigate("resourcegroups", "create")}
        extraCommands={<>
          <ToolbarButton onClick={() => setGap("Open query")}>Open query</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Assign tags")}>Assign tags</ToolbarButton>
        </>}
        csvName="resource-groups.csv"
        emptyAction={<Link href="#/resourcegroups/create">Create resource group</Link>}
        columns={[
          { key: "name", label: "Name", render: (r) => <Link href={`#/resourcegroups/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
          { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
        ]}
      />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Open query" ? "Azure Resource Graph Explorer" : "Assigning tags across a multi-selection"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Settings > Resources (every resource across every resource group, at once) ─────────
function ResourcesPanel({ id }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listResources(id), [id]);
  const [gap, setGap] = useState(null);
  return (
    <>
      <div className="vy-panel-title">Resources</div>
      <BrowseGrid
        resourceName="resource" rowKey={(r) => r.id} filterPlaceholder="Filter for any field..."
        items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setGap("Create")}
        extraCommands={<>
          <ToolbarButton onClick={() => setGap("Manage view")}>Manage view</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Open query")}>Open query</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Assign tags")}>Assign tags</ToolbarButton>
        </>}
        onDelete={async (rows) => {
          for (const r of rows) await api.deleteResourceById(r.id);
          notify.success(`Deleted ${rows.length} resource${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="resources.csv"
        emptyAction={<Link href="#/">Create a resource</Link>}
        columns={[
          { key: "name", label: "Name" },
          { key: "type", label: "Type" },
          { key: "rg", label: "Resource group", value: (r) => r.id?.split("/")[4] || "--" },
          { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
        ]}
      />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={{
                Create: "Creating a new resource from the Marketplace",
                "Manage view": "Saving a custom browse-grid layout",
                "Open query": "Azure Resource Graph Explorer",
                "Assign tags": "Assigning tags across a multi-selection",
              }[gap] || gap} />
            </DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Settings > Resource providers ───────────────────────────────────────────────────────
function ResourceProviders({ id }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listProviders(id), [id]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Resource providers</div>
      <p style={{ fontSize: 13 }}>Register or unregister a provider from its row in the Status column — the portal's header Register/Unregister act on the grid selection, which Vyomi applies per-row instead.</p>
      <BrowseGrid
        resourceName="provider" rowKey={(r) => r.namespace} filterPlaceholder="Filter by name..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        csvName="resource-providers.csv"
        columns={[
          { key: "namespace", label: "Provider" },
          { key: "status", label: "Status", render: (r) => (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span>{r.registrationState}</span>
              {r.registrationState === "Registered" ? (
                <Button size="small" onClick={async () => { await api.unregisterProvider(id, r.namespace); notify.success(`'${r.namespace}' was unregistered.`, "Unregister succeeded"); reload(); }}>Unregister</Button>
              ) : (
                <Button size="small" onClick={async () => { await api.registerProvider(id, r.namespace); notify.success(`'${r.namespace}' was registered.`, "Register succeeded"); reload(); }}>Register</Button>
              )}
            </div>
          ), value: (r) => r.registrationState },
        ]}
      />
    </>
  );
}

// ── Settings > Deployments (Microsoft.Resources/deployments, subscription scope) ───────
function Deployments({ id }) {
  const { data, loading, error, reload } = useAsync(() => api.listDeployments(id), [id]);
  const [tpl, setTpl] = useState(null);
  const [gap, setGap] = useState(null); // "Cancel" | "Redeploy"
  const notify = useNotify();
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Deployments <CapabilityBadge id="azure.subscriptions.deployments" /></div>
      <BrowseGrid
        resourceName="deployment" rowKey={(r) => r.name} filterPlaceholder="Filter by deployment name"
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton onClick={() => setGap("Cancel")}>Cancel</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Redeploy")}>Redeploy</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteDeployment(id, r.name);
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
      <Dialog open={!!tpl} onOpenChange={(_, d) => !d.open && setTpl(null)}>
        <DialogSurface aria-label="Template">
          <DialogBody>
            <DialogTitle>{tpl?.name}</DialogTitle>
            <DialogContent>
              <Textarea readOnly value={JSON.stringify(tpl?.properties?.template || {}, null, 2)} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />
            </DialogContent>
            <DialogActions><Button onClick={() => setTpl(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Cancel" ? "Cancelling an in-progress deployment" : "Redeploying a past deployment"} note="Every simulated deployment completes synchronously, so there is nothing in-flight to cancel or re-run." /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Settings > Resource locks (Microsoft.Authorization/locks, scoped to the subscription itself) ──
function Locks({ id }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(id), [id]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null); // "Subscription" | "Resource group" | "Feedback"
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Resource locks</div>
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
          for (const r of sel) await api.deleteLock(id, r.name);
          notify.success(`Deleted ${sel.length} lock${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="locks.csv"
        columns={[
          { key: "name", label: "Lock name" },
          { key: "type", label: "Lock type", value: (r) => (r.properties?.level === "ReadOnly" ? "Read-only" : "Delete") },
          { key: "scope", label: "Scope", value: () => "This subscription" },
          { key: "notes", label: "Notes", value: (r) => r.properties?.notes || "--" },
        ]}
        emptyAction={<span className="vy-muted">This resource has no locks.</span>}
      />
      <AddLockDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (lockName, level, notes) => { await api.putLock(id, lockName, { properties: { level, notes } }); reload(); }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : "Locks scoped to a resource group (viewing another scope's lock list)"} />
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

// ── Security (Microsoft.Security — Defender for Cloud secure score + recommendations, the
// SAME real rule engine as the dedicated Defender console, reused at the subscription scope) ──
function Security({ id }) {
  const score = useAsync(() => api.getSecureScore(id), [id]);
  const assessments = useAsync(() => api.listAssessments(id), [id]);
  const rows = assessments.data || [];
  const pct = score.data?.properties?.score?.percentage;
  return (
    <CapabilityContainer id="azure.subscriptions.security" title="Security"
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { score.reload(); assessments.reload(); }}>Refresh</ToolbarButton>}>
      <ErrorBar error={score.error || assessments.error} />
      <div className="vy-kv"><span>Secure score</span><span>{score.loading ? "Loading..." : pct != null ? `${Math.round(pct * 100)}%` : "--"}</span></div>
      <section className="vy-form-section"><h3>Recommendations</h3>
        <table className="vy-grid">
          <thead><tr><th>Severity</th><th>Recommendation</th><th>Status</th><th>Resource</th></tr></thead>
          <tbody>
            {assessments.loading ? <tr><td colSpan={4}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((a) => (
              <tr key={a.id}>
                <td>{a.properties?.metadata?.severity || "--"}</td>
                <td>{a.properties?.displayName}</td>
                <td>{a.properties?.status?.code}</td>
                <td>{(a.properties?.resourceDetails?.Id || "").split("/").pop()}</td>
              </tr>
            )) : <tr><td colSpan={4} className="vy-muted">No recommendations — every evaluated resource is healthy.</td></tr>}
          </tbody>
        </table>
      </section>
    </CapabilityContainer>
  );
}

// ── Diagnose and solve problems: concrete, live checks over this subscription's own real
// state (Activity log failures, no resource lock, quota near its limit) — not a fabricated
// catalog of guides. ─────────────────────────────────────────────────────────────────────
function Diagnostics({ id }) {
  const self = `#/subscriptions/${encodeURIComponent(id)}`;
  const locks = useAsync(() => api.listLocks(id), [id]);
  const activity = useAsync(() => api.listActivityLog(id), [id]);
  const compute = useAsync(() => api.listComputeUsages(id), [id]);
  const network = useAsync(() => api.listNetworkUsages(id), [id]);
  const loading = locks.loading || activity.loading || compute.loading || network.loading;
  const problems = [];
  for (const r of activity.data || []) {
    const status = r.status?.value || r.status?.localizedValue;
    if (status === "Failed")
      problems.push({ title: `Operation failed: ${r.operationName?.localizedValue || r.operationName?.value}`, href: `${self}/activitylog`, label: "Open Activity log" });
  }
  for (const u of [...(compute.data || []), ...(network.data || [])]) {
    if (u.limit && u.currentValue / u.limit >= 0.8)
      problems.push({ title: `${u.name?.localizedValue} usage is at ${Math.round(100 * u.currentValue / u.limit)}% of its quota`, href: `${self}/usagequotas`, label: "Open Usage + quotas" });
  }
  if (!(locks.data || []).length)
    problems.push({ title: "This subscription has no resource lock — it can be deleted or modified without a confirmation step", href: `${self}/resourcelocks`, label: "Open Resource locks" });
  return (
    <CapabilityContainer id="azure.subscriptions.diagnostics" title="Diagnose and solve problems">
      <p style={{ fontSize: 13 }}>Vyomi checks this subscription's own real state for common problems and links to the page that explains and fixes each one.</p>
      {loading ? <Loading /> : problems.length ? (
        <ul>{problems.map((p, i) => <li key={i}>{p.title} — <Link href={p.href}>{p.label}</Link></li>)}</ul>
      ) : <InfoBar intent="success">No problems detected in this subscription.</InfoBar>}
    </CapabilityContainer>
  );
}

// ── Events: the same real, subscription-wide Activity log feed Activity log itself uses —
// Vyomi has no platform outages to show as separate Service Health events. ────────────────
function Events({ id }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(id), [id]);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.subscriptions.events" title="Events"
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr><th>Operation</th><th>Status</th><th>Time</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={3}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.id}>
              <td>{r.operationName?.localizedValue || r.operationName?.value}</td>
              <td>{r.status?.localizedValue || r.status?.value}</td>
              <td>{fmtDate(r.eventTimestamp)}</td>
            </tr>
          )) : <tr><td colSpan={3} className="vy-muted">No events to display</td></tr>}
        </tbody>
      </table>
    </CapabilityContainer>
  );
}

// ── Advisor recommendations: real findings over data Vyomi actually has — Security mirrors
// Defender's own Unhealthy assessments, Cost flags spend with no budget, Reliability flags a
// subscription with no resource lock. No Performance category (no utilization metrics exist). ──
function Advisor({ id }) {
  const assessments = useAsync(() => api.listAssessments(id), [id]);
  const budgets = useAsync(() => api.listBudgets(id), [id]);
  const cost = useAsync(() => api.costQuery(id, { type: "ActualCost", timeframe: "MonthToDate", dataset: { aggregation: { totalCost: { name: "Cost", function: "Sum" } } } }), [id]);
  const locks = useAsync(() => api.listLocks(id), [id]);
  const loading = assessments.loading || budgets.loading || cost.loading || locks.loading;
  const recs = [];
  for (const a of assessments.data || []) {
    if (a.properties?.status?.code === "Unhealthy")
      recs.push({ category: "Security", title: a.properties?.displayName, detail: a.properties?.status?.description || "" });
  }
  const spend = cost.data?.properties?.rows?.[0]?.[0] || 0;
  if (spend > 0 && !(budgets.data || []).length)
    recs.push({ category: "Cost", title: "Create a budget", detail: `This subscription has ${DOLLAR(spend)} of month-to-date spend and no budget configured.` });
  if (!(locks.data || []).length)
    recs.push({ category: "Reliability", title: "Add a resource lock", detail: "This subscription has no resource lock, so it can be accidentally deleted or modified." });
  return (
    <CapabilityContainer id="azure.subscriptions.advisor_recommendations" title="Advisor recommendations">
      {loading ? <Loading /> : recs.length ? (
        <table className="vy-grid">
          <thead><tr><th>Category</th><th>Recommendation</th><th>Description</th></tr></thead>
          <tbody>{recs.map((r, i) => <tr key={i}><td>{r.category}</td><td>{r.title}</td><td>{r.detail}</td></tr>)}</tbody>
        </table>
      ) : <InfoBar intent="success">No recommendations — this subscription follows Vyomi's modeled best practices.</InfoBar>}
    </CapabilityContainer>
  );
}

// ── Invoices (Microsoft.Billing/invoices) — derived from the real cost engine ──────────────
function Invoices({ id }) {
  const { data, loading, error, reload } = useAsync(() => api.listInvoices(id), [id]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Invoices <CapabilityBadge id="azure.subscriptions.invoices" /></div>
      <BrowseGrid
        resourceName="invoice" rowKey={(r) => r.name}
        items={rows} loading={loading} error={error} onRefresh={reload}
        csvName="invoices.csv"
        emptyAction={<span className="vy-muted">No invoices yet.</span>}
        columns={[
          { key: "period", label: "Billing period", value: (r) => r.properties?.invoicePeriodStartDate },
          { key: "status", label: "Status", value: (r) => r.properties?.status },
          { key: "amount", label: "Amount due", value: (r) => DOLLAR(r.properties?.amountDue?.value) },
        ]}
      />
    </>
  );
}

// ── Preview features (Microsoft.Features/providers/{ns}/features) — register/unregister
// persists exactly like real ARM. ───────────────────────────────────────────────────────
function PreviewFeatures({ id }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listPreviewFeatures(id), [id]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Preview features <CapabilityBadge id="azure.subscriptions.preview_features" /></div>
      <BrowseGrid
        resourceName="feature" rowKey={(r) => r.name} filterPlaceholder="Filter by name"
        items={rows} loading={loading} error={error} onRefresh={reload}
        csvName="preview-features.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "state", label: "State", render: (r) => (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span>{r.properties?.state}</span>
              {r.properties?.state === "Registered" ? (
                <Button size="small" onClick={async () => { await api.unregisterPreviewFeature(id, r.name); notify.success(`'${r.name}' was unregistered.`, "Unregister succeeded"); reload(); }}>Unregister</Button>
              ) : (
                <Button size="small" onClick={async () => { await api.registerPreviewFeature(id, r.name); notify.success(`'${r.name}' was registered.`, "Register succeeded"); reload(); }}>Register</Button>
              )}
            </div>
          ), value: (r) => r.properties?.state },
        ]}
      />
    </>
  );
}

// ── Usage + quotas (Microsoft.Compute|Network/locations/{location}/usages) — live counts,
// enforced at create time (core/azure_arm_core.py's AzureArm._quota_block). ────────────────
function UsageQuotas({ id, name }) {
  const [gap, setGap] = useState(false);
  const compute = useAsync(() => api.listComputeUsages(id), [id]);
  const network = useAsync(() => api.listNetworkUsages(id), [id]);
  const loading = compute.loading || network.loading;
  const rows = [...(compute.data || []), ...(network.data || [])];
  return (
    <>
      <div className="vy-panel-title">Usage + quotas <CapabilityBadge id="azure.subscriptions.usage_quotas" /></div>
      <BrowseGrid
        resourceName="quota" rowKey={(r) => r.name.value} filterPlaceholder="Search"
        items={rows} loading={loading} error={compute.error || network.error}
        onRefresh={() => { compute.reload(); network.reload(); }}
        extraCommands={<ToolbarButton onClick={() => setGap(true)}>Request increase</ToolbarButton>}
        csvName="usage-quotas.csv"
        columns={[
          { key: "name", label: "Quota name", value: (r) => r.name.localizedValue },
          { key: "region", label: "Region", value: () => locationLabel("eastus") },
          { key: "subscription", label: "Subscription", value: () => name },
          { key: "usage", label: "Current Usage", render: (r) => (
            <span>{r.currentValue} / {r.limit}{r.resources?.length ? ` (${r.resources.join(", ")})` : ""}</span>
          ), value: (r) => `${r.currentValue} / ${r.limit}` },
          { key: "adjustable", label: "Adjustable", value: () => "Yes" },
        ]}
      />
      <Dialog open={gap} onOpenChange={(_, d) => !d.open && setGap(false)}>
        <DialogSurface aria-label="Request increase">
          <DialogBody>
            <DialogTitle>Request increase</DialogTitle>
            <DialogContent>
              <NotSimulated feature="Requesting a quota increase" note="Raising a real Azure quota goes through Microsoft support approval outside Vyomi; Vyomi's modeled default limits are fixed." />
            </DialogContent>
            <DialogActions><Button onClick={() => setGap(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Policies (Microsoft.Authorization/policyDefinitions|policyAssignments) — assignments are
// real ARM resources; the one built-in Vyomi enforces (Allowed locations, real GUID) is
// genuinely evaluated, both at create time and on this page's Compliance tab. ─────────────
function Policies({ id }) {
  const notify = useNotify();
  const [tab, setTab] = useState("assignments");
  const [add, setAdd] = useState(false);
  const assignments = useAsync(() => api.listPolicyAssignments(id), [id]);
  const compliance = useAsync(() => api.policyComplianceStates(id), [id]);
  const rows = assignments.data || [];
  return (
    <>
      <div className="vy-panel-title">Policies <CapabilityBadge id="azure.subscriptions.policies" /></div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => { setTab(d.value); if (d.value === "compliance") compliance.reload(); }} aria-label="Policies tabs">
        <Tab value="assignments">Assignments</Tab>
        <Tab value="compliance">Compliance</Tab>
      </TabList>
      {tab === "assignments" && (
        <BrowseGrid
          resourceName="assignment" rowKey={(r) => r.name}
          items={rows} loading={assignments.loading} error={assignments.error} onRefresh={assignments.reload}
          onCreate={() => setAdd(true)}
          onDelete={async (sel) => {
            for (const r of sel) await api.deletePolicyAssignment(id, r.name);
            notify.success(`Deleted ${sel.length} assignment${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
            assignments.reload();
          }}
          csvName="policy-assignments.csv"
          emptyAction={<span className="vy-muted">No policy assignments.</span>}
          columns={[
            { key: "name", label: "Assignment name" },
            { key: "definition", label: "Policy", value: (r) => r.properties?.displayName || r.properties?.policyDefinitionId?.split("/").pop() },
            { key: "locations", label: "Allowed locations", value: (r) => (r.properties?.parameters?.listOfAllowedLocations?.value || []).join(", ") || "--" },
          ]}
        />
      )}
      {tab === "compliance" && (
        <>
          <ErrorBar error={compliance.error} />
          <table className="vy-grid">
            <thead><tr><th>Resource</th><th>Policy assignment</th><th>Compliance state</th></tr></thead>
            <tbody>
              {compliance.loading ? <tr><td colSpan={3}><Spinner size="tiny" /></td></tr> : (compliance.data || []).length ? (compliance.data || []).map((r, i) => (
                <tr key={i}><td>{r.resourceId?.split("/").pop()}</td><td>{r.policyAssignmentId?.split("/").pop()}</td><td>{r.complianceState}</td></tr>
              )) : <tr><td colSpan={3} className="vy-muted">No policy assignments to evaluate.</td></tr>}
            </tbody>
          </table>
        </>
      )}
      <AddPolicyAssignmentDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, locations) => {
          await api.putPolicyAssignment(id, name, {
            properties: { displayName: "Allowed locations", policyDefinitionId: api.ALLOWED_LOCATIONS_POLICY_ID,
                         parameters: { listOfAllowedLocations: { value: locations } } },
          });
          assignments.reload();
        }} />
    </>
  );
}

function AddPolicyAssignmentDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [locations, setLocations] = useState("eastus");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name, locations.split(",").map((s) => s.trim()).filter(Boolean));
      notify.success(`Policy '${name}' was assigned.`, "Assign policy");
      setName(""); setLocations("eastus"); onClose();
    } catch (e) { notify.error(e, "Failed to assign policy"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Assign policy">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Assign policy</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Policy definition" hint="Vyomi evaluates and enforces exactly one built-in policy: Allowed locations.">
                <Input value="Allowed locations" readOnly aria-label="Policy definition" />
              </Field>
              <Field label="Assignment name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Assignment name" /></Field>
              <Field label="Allowed locations" required hint="Comma-separated location names, e.g. eastus, westus">
                <Input value={locations} onChange={(_, d) => setLocations(d.value)} aria-label="Allowed locations" />
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!name.trim() || !locations.trim() || busy} onClick={go}>Assign</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── My permissions (Microsoft.Authorization/permissions) — derived live from the same role
// catalog/assignments checkAccess uses. ────────────────────────────────────────────────────
function MyPermissions({ id }) {
  const { data, loading, error } = useAsync(() => api.myPermissions(id), [id]);
  const perm = (data || [])[0];
  return (
    <CapabilityContainer id="azure.subscriptions.my_permissions" title="My permissions">
      <p style={{ fontSize: 13 }}>The actions {CURRENT_USER} can perform on this subscription.</p>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <>
          <section className="vy-form-section"><h3>Actions</h3>
            <ul>{(perm?.actions || []).map((a) => <li key={a}><code>{a}</code></li>)}</ul>
          </section>
          {perm?.notActions?.length > 0 && (
            <section className="vy-form-section"><h3>Not actions</h3>
              <ul>{perm.notActions.map((a) => <li key={a}><code>{a}</code></li>)}</ul>
            </section>
          )}
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Deployment stacks (Microsoft.Resources/deploymentStacks) — deleting a stack really
// cascade-deletes every resource it manages (unless actionOnUnmanage is "detach"). ────────
function DeploymentStacks({ id }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDeploymentStacks(id), [id]);
  const [view, setView] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Deployment stacks <CapabilityBadge id="azure.subscriptions.deployment_stacks" /></div>
      <BrowseGrid
        resourceName="deployment stack" rowKey={(r) => r.name}
        items={rows} loading={loading} error={error} onRefresh={reload}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteDeploymentStack(id, r.name);
          notify.success(`Deleted ${sel.length} stack${sel.length === 1 ? "" : "s"} and the resources it managed.`, "Delete succeeded");
          reload();
        }}
        csvName="deployment-stacks.csv"
        emptyAction={<span className="vy-muted">No deployment stacks found.</span>}
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status", value: (r) => r.properties?.provisioningState || "--" },
          { key: "resources", label: "Managed resources", value: (r) => (r.properties?.resources || []).length },
          { key: "action", label: "Action on unmanage", value: (r) => r.properties?.actionOnUnmanage?.resources || "delete" },
          { key: "view", label: "", render: (r) => <Link as="button" onClick={() => setView(r)}>View managed resources</Link> },
        ]}
      />
      <Dialog open={!!view} onOpenChange={(_, d) => !d.open && setView(null)}>
        <DialogSurface aria-label="Managed resources">
          <DialogBody>
            <DialogTitle>{view?.name}</DialogTitle>
            <DialogContent>
              <ul>{(view?.properties?.resources || []).map((r) => <li key={r.id}>{r.resourceType}/{r.resourceName}</li>)}</ul>
            </DialogContent>
            <DialogActions><Button onClick={() => setView(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Programmatic deployment: generates a real service principal with a real Contributor
// roleAssignment (observable in Access control (IAM), enforced by checkAccess). ───────────
function ProgrammaticDeployment({ id }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDeploymentCredentials(id), [id]);
  const [created, setCreated] = useState(null);
  const rows = data || [];
  const generate = async () => {
    const rec = await api.createDeploymentCredential(id);
    setCreated(rec);
    notify.success(`Deployment credential '${rec.name}' was created.`, "Credential created");
    reload();
  };
  return (
    <CapabilityContainer id="azure.subscriptions.programmatic_deployment" title="Programmatic deployment"
      actions={<ToolbarButton icon={<Add20Regular />} onClick={generate}>Generate deployment credential</ToolbarButton>}>
      <p style={{ fontSize: 13 }}>Generate a service principal with Contributor access to this subscription, for CI/CD or SDK/CLI automation.</p>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr><th>Name</th><th>App ID</th><th>Created</th><th /></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={4}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td><td>{r.appId}</td><td>{fmtDate(r.createdAt)}</td>
              <td>
                <Button size="small" icon={<Delete20Regular />} onClick={async () => {
                  await api.deleteDeploymentCredential(id, r.name);
                  notify.success(`Credential '${r.name}' was revoked.`, "Revoke succeeded");
                  reload();
                }}>Revoke</Button>
              </td>
            </tr>
          )) : <tr><td colSpan={4} className="vy-muted">No deployment credentials yet.</td></tr>}
        </tbody>
      </table>
      <Dialog open={!!created} onOpenChange={(_, d) => !d.open && setCreated(null)}>
        <DialogSurface aria-label="Deployment credential created">
          <DialogBody>
            <DialogTitle>Deployment credential created</DialogTitle>
            <DialogContent>
              <p style={{ fontSize: 13 }}>Copy the client secret now — Vyomi won't show it again.</p>
              <div className="vy-kv"><span>App ID</span><span>{created?.appId}</span></div>
              <div className="vy-kv"><span>Client secret</span><span style={{ fontFamily: "monospace" }}>{created?.secret}</span></div>
              <div className="vy-kv"><span>Tenant ID</span><span>{created?.tenantId}</span></div>
            </DialogContent>
            <DialogActions><Button onClick={() => setCreated(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Billing properties (Microsoft.Billing/billingProperties, subscription-scoped in Vyomi) ──
function BillingProperties({ id }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getBillingProperties(id), [id]);
  const [admin, setAdmin] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setAdmin(data.accountAdmin || ""); }, [data?.accountAdmin]);
  const save = async () => {
    setBusy(true);
    try { await api.patchBillingProperties(id, { accountAdmin: admin }); notify.success("Billing properties were updated.", "Save succeeded"); reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.subscriptions.billing_properties" title="Billing properties">
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 420 }}>
          <div className="vy-kv"><span>Currency</span><span>{data?.currency}</span></div>
          <div className="vy-kv"><span>Channel</span><span>{data?.channel}</span></div>
          <Field label="Account admin"><Input value={admin} onChange={(_, d) => setAdmin(d.value)} aria-label="Account admin" /></Field>
          <div><Button appearance="primary" disabled={busy || !admin.trim()} onClick={save}>Save</Button></div>
        </div>
      )}
    </CapabilityContainer>
  );
}
