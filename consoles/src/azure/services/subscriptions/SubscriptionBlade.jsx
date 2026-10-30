/* Subscription blade: left resource menu + panels. Overview, Activity log, Access control
 * (IAM), Tags, Cost Management (Cost analysis/Cost alerts/Budgets), Resource groups,
 * Resources, Resource providers, Deployments and Resource locks are backed by real native
 * ARM calls; everything else in the menu is an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
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
// Every other menu item with no dedicated panel below: one of two registry-driven gaps.
const GAP_CAP = { usagequotas: "azure.subscriptions.usage_quotas" };

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
          ["Offer", "--"],
        ]}
        right={[
          ["Offer ID", "--"],
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

// ── Access control (IAM) — generic Microsoft.Authorization catalog, subscription scope ──
function AccessControlIam({ id }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  const assignments = useAsync(() => api.listRoleAssignments(id), [id]);
  const definitions = useAsync(() => api.listRoleDefinitions(id), [id]);
  return (
    <>
      <div className="vy-panel-title">Access control (IAM)</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Access control commands">
        <ToolbarButton onClick={() => setDlg("add")}>Add</ToolbarButton>
        <ToolbarButton onClick={() => setDlg("download")}>Download role assignments</ToolbarButton>
        <ToolbarButton onClick={() => setDlg("columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { assignments.reload(); definitions.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton disabled>Remove</ToolbarButton>
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
          <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Role assignments">
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
          <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Roles">
            <Input size="small" style={{ margin: "8px 0", width: 260 }} placeholder="Search by role name, description, permission, or ID" aria-label="Search by role name, description, permission, or ID" />
            <table className="vy-grid"><thead><tr><th>Name</th><th>Description</th><th>Type</th><th>Category</th><th>Details</th></tr></thead>
              <tbody>
                {definitions.loading ? <tr><td colSpan={5}><Spinner size="tiny" /></td></tr> : (definitions.data || []).map((r) => (
                  <tr key={r.name}><td>{r.name}</td><td /><td>{r.properties?.type}</td><td>General</td><td /></tr>
                ))}
                {!definitions.loading && !(definitions.data || []).length && <tr><td colSpan={5} className="vy-muted">No custom roles defined.</td></tr>}
              </tbody>
            </table>
          </CapabilityContainer>
        </div>
      )}
      {tab === "deny" && (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Deny assignments">
            <table className="vy-grid"><thead><tr><th>Name</th><th>Description</th><th>Principal</th><th>Scope</th></tr></thead>
              <tbody><tr><td colSpan={4} className="vy-muted">No deny assignments found.</td></tr></tbody>
            </table>
          </CapabilityContainer>
        </div>
      )}
      {tab === "classic" && (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id="azure.subscriptions.access_control_iam" title="Classic administrators">
            <InfoBar>No classic administrators are configured for this subscription.</InfoBar>
          </CapabilityContainer>
        </div>
      )}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access control dialog">
          <DialogBody>
            <DialogTitle>{{ mine: "My access", check: "Check access", add: "Add role assignment", download: "Download role assignments", columns: "Edit columns", feedback: "Feedback" }[dlg]}</DialogTitle>
            <DialogContent>
              <NotSimulated feature={{
                mine: "Per-identity role-assignment resolution for this subscription",
                check: "Per-identity role-assignment resolution for this subscription",
                add: "Creating a new role assignment",
                download: "Downloading role assignments as CSV",
                columns: "Customizing the role-assignments grid's columns",
                feedback: "Sending product feedback",
              }[dlg]} />
            </DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
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
