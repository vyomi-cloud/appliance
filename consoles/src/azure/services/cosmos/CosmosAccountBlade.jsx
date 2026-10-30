/* Azure Cosmos DB account resource blade: left resource menu + panels. Overview, Activity log,
 * Tags, Data Explorer, Replicate data globally, Default consistency, Backup & Restore, Keys,
 * Locks, Access control (IAM) and Export template are backed by native ARM / the native Cosmos
 * DB REST (SQL/Core API) data plane; everything else in the menu is an honest NotSimulated panel
 * (the spec captures them as blade menu items with no further content — "title only"). */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import DataExplorer from "./DataExplorer.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "costmgmt", label: "Cost Management" },
  { id: "quickstart", label: "Quick start" },
  { id: "notifications", label: "Notifications" },
  { id: "dataexplorer", label: "Data Explorer" },
  { group: "Settings", items: [
    { id: "features", label: "Features" },
    { id: "replicate", label: "Replicate data globally" },
    { id: "consistency", label: "Default consistency" },
    { id: "backup", label: "Backup & Restore" },
    { id: "networking", label: "Networking" },
    { id: "keys", label: "Keys" },
    { id: "datamigration", label: "Data Migration" },
    { id: "cors", label: "CORS" },
    { id: "dedicatedgateway", label: "Dedicated Gateway" },
    { id: "defender", label: "Microsoft Defender for Cloud" },
    { id: "identity", label: "Identity" },
    { id: "dataencryption", label: "Data Encryption" },
    { id: "locks", label: "Locks" },
  ] },
  { group: "Containers", items: [{ id: "browse", label: "Browse" }, { id: "scale", label: "Scale" }] },
  { group: "Integrations", items: [
    { id: "powerbi", label: "Power BI" },
    { id: "addsearch", label: "Add Azure Cognitive Search" },
    { id: "addfunction", label: "Add Azure Function" },
  ] },
  { group: "Monitoring", items: [
    { id: "insights", label: "Insights" }, { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" },
    { id: "logs", label: "Logs" }, { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "workbooks", label: "Workbooks" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "resourcehealth", label: "Resource health" }, { id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  diagnose: "Diagnose and solve problems",
  costmgmt: "Cost Management for this account",
  quickstart: "The Quick start code samples blade",
  notifications: "Notifications",
  features: "The Features overview",
  networking: "Private endpoint / VNet networking configuration (see the create wizard's Connectivity method, and Access control for IP-based restrictions)",
  datamigration: "The Data Migration tool integration",
  cors: "CORS rules",
  dedicatedgateway: "Dedicated Gateway (integrated cache) provisioning",
  defender: "Microsoft Defender for Cloud",
  identity: "Managed identity assignment",
  dataencryption: "Customer-managed key rotation (Data Encryption blade)",
  browse: "The Browse blade (select a container from Data Explorer instead)",
  scale: "The Scale blade (select a container from Data Explorer instead)",
  powerbi: "Power BI integration",
  addsearch: "Azure Cognitive Search integration",
  addfunction: "Azure Function integration",
  insights: "Insights dashboards",
  alerts: "Alert rules",
  metrics: "Metrics charts",
  logs: "Log Analytics queries",
  diagnosticsettings: "Diagnostic settings",
  workbooks: "Workbooks",
  tasks: "Tasks",
  resourcehealth: "Resource health",
  support: "Support + Troubleshooting",
};

export default function CosmosAccountBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const data = useAsync(() => api.getAccount(rg, name), [rg, name]);
  const self = `#/cosmos/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (data.data) remember({ name, type: "Azure Cosmos DB account", href: self }); }, [!!data.data, self]);

  let body;
  if (data.loading && !data.data) body = <Loading />;
  else if (data.error) body = <><ErrorBar error={data.error} title="Failed to load the account" /><Link href="#/cosmos">Back to Azure Cosmos DB</Link></>;
  else {
    const a = data.data, reload = data.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog a={a} />,
      iam: () => <Iam />,
      tags: () => <Tags a={a} reload={reload} />,
      dataexplorer: () => <DataExplorer />,
      replicate: () => <Replicate a={a} reload={reload} />,
      consistency: () => <Consistency a={a} reload={reload} />,
      backup: () => <Backup a={a} />,
      keys: () => <Keys a={a} />,
      locks: () => <Locks a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{LABEL[panel] || panel}</div>
        <NotSimulated feature={NS_NOTES[panel] || `The ${LABEL[panel] || panel} panel`} />
      </>
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Azure Cosmos DB account" glyph={<Glyph id="cosmos" />} closeHref="#/cosmos"
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
  const [tab, setTab] = useState("getstarted");
  const [del, setDel] = useState(false);
  const [gap, setGap] = useState(null);
  const containers = useAsync(() => api.listAllContainers(), []);
  const rows = containers.data || [];
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => navigate("cosmos", a.resourceGroup, a.name, "dataexplorer")}>Add container</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); containers.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Move")}>Move</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete account</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Status", a.properties?.provisioningState || "Succeeded"],
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["URI", api.accountEndpoint(a.name)],
        ]}
        right={[
          ["Read Locations", locationLabel(a.location)],
          ["Write Locations", locationLabel(a.location)],
          ["Capacity mode", a.properties?.capabilities?.some((c) => c.name === "EnableServerless") ? "Serverless" : "Provisioned throughput"],
          ["Backup policy", a.properties?.backupPolicy?.type || "Periodic"],
          ["Tags", Object.entries(a.tags || {}).map(([k, v]) => `${k} : ${v}`).join(", ") || "--"],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="getstarted">Get started</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="properties">Properties</Tab>
        <Tab value="tutorials">Tutorials</Tab>
      </TabList>
      {tab === "getstarted" && (
        <div style={{ marginTop: 12, fontSize: 13 }}>
          Use <Link href={`${self}/dataexplorer`}>Data Explorer</Link> to create databases and containers and browse items, or copy a key from <Link href={`${self}/keys`}>Keys</Link> to connect from your application.
        </div>
      )}
      {tab === "monitoring" && <NotSimulatedContainer feature="Account monitoring (request units, storage and latency charts)" />}
      {tab === "properties" && (
        <div className="vy-props" style={{ marginTop: 12 }}>
          <KV label="Resource ID" value={a.id} />
          <KV label="Kind" value={a.kind} />
          <KV label="Document endpoint" value={api.accountEndpoint(a.name)} />
        </div>
      )}
      {tab === "tutorials" && <NotSimulatedContainer feature="Tutorials" />}

      <section className="vy-section" style={{ marginTop: 16 }}>
        <h3>Containers</h3>
        <Table size="small" aria-label="Containers">
          <TableHeader><TableRow><TableHeaderCell>Database</TableHeaderCell><TableHeaderCell>Container</TableHeaderCell><TableHeaderCell>Partition key</TableHeaderCell><TableHeaderCell>Throughput</TableHeaderCell></TableRow></TableHeader>
          <TableBody>
            {containers.loading ? <TableRow><TableCell colSpan={4}><Spinner size="tiny" /></TableCell></TableRow> : rows.length ? rows.map((c) => (
              <TableRow key={`${c.database}/${c.id}`}>
                <TableCell>{c.database}</TableCell>
                <TableCell><Link href={`${self}/dataexplorer`}>{c.id}</Link></TableCell>
                <TableCell>{(c.partitionKey?.paths || []).join(", ")}</TableCell>
                <TableCell>--</TableCell>
              </TableRow>
            )) : <TableRow><TableCell colSpan={4} className="vy-muted">No containers to display</TableCell></TableRow>}
          </TableBody>
        </Table>
      </section>

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="Azure Cosmos DB account" names={[a.name]}
        onConfirm={async () => {
          await api.deleteAccount(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Account '${a.name}' was deleted.`, "Delete succeeded");
          navigate("cosmos");
        }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : "Moving a resource to a different resource group/subscription"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Activity log ──────────────────────────────────────────────────────────────────────
function ActivityLog({ a }) {
  const sub = useSubscription();
  const resPath = api.resourcePath(a.resourceGroup, a.name);
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(resPath, sub.id), [resPath, sub.id]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  const GAPS = ["Edit columns", "Export Activity Logs", "Download as CSV", "Insights", "Feedback", "Pin current filters", "Reset filters"];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Activity log</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton onClick={reload}>Activity</ToolbarButton>
        {GAPS.map((g) => <ToolbarButton key={g} onClick={() => setGap(g)}>{g}</ToolbarButton>)}
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <ErrorBar error={error} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `${gap} on the activity log`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
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
    </>
  );
}

// ── Access control (IAM) ─────────────────────────────────────────────────────────────────
function Iam() {
  const sub = useSubscription();
  const [tab, setTab] = useState("checkaccess");
  const [gap, setGap] = useState(null);
  const roleAssignments = useAsync(() => api.listRoleAssignments(sub.id), [sub.id]);
  const roleDefinitions = useAsync(() => api.listRoleDefinitions(sub.id), [sub.id]);
  return (
    <>
      <div className="vy-panel-title">Access control (IAM)</div>
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

function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const apply = async () => {
    setBusy(true);
    try {
      await api.updateAccount(a.resourceGroup, a.name, { tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
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
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={async () => { setRows([{ name: "", value: "" }]); await apply(); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Replicate data globally ────────────────────────────────────────────────────────────
function Replicate({ a, reload }) {
  const notify = useNotify();
  const [gap, setGap] = useState(null);
  const [addRegion, setAddRegion] = useState(false);
  const locations = a.properties?.locations || [{ locationName: a.location, failoverPriority: 0 }];
  return (
    <>
      <div className="vy-panel-title">Replicate data globally</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Replicate data globally commands">
        <ToolbarButton onClick={() => setGap("Manual Failover")}>Manual Failover</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Service-Managed Failover")}>Service-Managed Failover</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.cosmos.replicate_data_globally" title="Regions" actions={<Button size="small" icon={<Add20Regular />} onClick={() => setAddRegion(true)}>Add region</Button>}>
        <Table size="small" aria-label="Regions" style={{ marginTop: 8 }}>
          <TableHeader><TableRow><TableHeaderCell>Region</TableHeaderCell><TableHeaderCell>Read</TableHeaderCell><TableHeaderCell>Write</TableHeaderCell></TableRow></TableHeader>
          <TableBody>
            {locations.map((l) => (
              <TableRow key={l.locationName}>
                <TableCell>{locationLabel(l.locationName)}</TableCell>
                <TableCell>Enabled</TableCell>
                <TableCell>{l.failoverPriority === 0 ? "Enabled" : "--"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CapabilityContainer>
      <Dialog open={addRegion} onOpenChange={(_, d) => !d.open && setAddRegion(false)}>
        <DialogSurface aria-label="Add region">
          <DialogBody>
            <DialogTitle>Add region</DialogTitle>
            <DialogContent><NotSimulated feature="Provisioning a second replica region" note="Vyomi has one logical region; a region you add is recorded on the account but no second replica is actually provisioned." /></DialogContent>
            <DialogActions><Button onClick={() => setAddRegion(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={`${gap} between regions`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Default consistency ────────────────────────────────────────────────────────────────
function Consistency({ a, reload }) {
  const notify = useNotify();
  const current = a.properties?.consistencyPolicy?.defaultConsistencyLevel || "Session";
  const [value, setValue] = useState(current);
  const [busy, setBusy] = useState(false);
  useEffect(() => setValue(current), [current]);
  const dirty = value !== current;
  const save = async () => {
    setBusy(true);
    try {
      await api.updateAccount(a.resourceGroup, a.name, { properties: { consistencyPolicy: { defaultConsistencyLevel: value } } });
      notify.success(`Default consistency for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving default consistency failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Default consistency</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Default consistency commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setValue(current)}>Discard</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.cosmos.default_consistency" title="Default consistency">
        <RadioGroup value={value} onChange={(_, d) => setValue(d.value)} aria-label="Default consistency">
          <Radio value="Strong" label="Strong" />
          <Radio value="BoundedStaleness" label="Bounded Staleness" />
          <Radio value="Session" label="Session" />
          <Radio value="ConsistentPrefix" label="Consistent Prefix" />
          <Radio value="Eventual" label="Eventual" />
        </RadioGroup>
      </CapabilityContainer>
    </>
  );
}

// ── Backup & Restore ────────────────────────────────────────────────────────────────────
function Backup({ a }) {
  const p = a.properties?.backupPolicy || { type: "Periodic", periodicModeProperties: { backupIntervalInMinutes: 240, backupRetentionIntervalInHours: 8, backupStorageRedundancy: "Geo" } };
  const redundancy = { Geo: "Geo-redundant backup storage", Zone: "Zone-redundant backup storage", Local: "Locally-redundant backup storage" };
  return (
    <>
      <div className="vy-panel-title">Backup & Restore</div>
      <CapabilityContainer id="azure.cosmos.backup_restore" title="Backup Policy">
        <div className="vy-props" style={{ marginTop: 8 }}>
          <KV label="Backup policy" value={p.type} />
          {p.type === "Periodic" && <>
            <KV label="Backup Interval" value={`${p.periodicModeProperties?.backupIntervalInMinutes ?? 240} minutes`} />
            <KV label="Backup Retention" value={`${p.periodicModeProperties?.backupRetentionIntervalInHours ?? 8} hours`} />
            <KV label="Backup storage redundancy" value={redundancy[p.periodicModeProperties?.backupStorageRedundancy] || "Geo-redundant backup storage"} />
          </>}
        </div>
      </CapabilityContainer>
    </>
  );
}

// ── Keys ──────────────────────────────────────────────────────────────────────────────
function Keys({ a }) {
  const notify = useNotify();
  const [tab, setTab] = useState("rw");
  const [show, setShow] = useState(false);
  const rw = useAsync(() => api.listKeys(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const ro = useAsync(() => api.listReadOnlyKeys(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const cs = useAsync(() => api.listConnectionStrings(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const mask = (v) => (show ? v : (v || "").replace(/./g, "•").slice(0, 32));
  const regen = async (keyKind) => {
    try {
      await api.regenerateKey(a.resourceGroup, a.name, keyKind);
      notify.success(`Key '${keyKind}' was regenerated.`, "Key regenerated");
      rw.reload(); ro.reload(); cs.reload();
    } catch (e) { notify.error(e, "Regenerating key failed"); }
  };
  const uri = api.accountEndpoint(a.name);
  const csFor = (desc) => (cs.data?.connectionStrings || []).find((c) => c.description === desc)?.connectionString || "";
  return (
    <>
      <div className="vy-panel-title">Keys</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Keys commands">
        <ToolbarButton onClick={() => regen("primary")}>Regenerate Primary Key</ToolbarButton>
        <ToolbarButton onClick={() => regen("secondary")}>Regenerate Secondary Key</ToolbarButton>
        <ToolbarButton onClick={() => setShow((s) => !s)}>{show ? "Hide keys" : "Show keys"}</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.cosmos.keys" title="">
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Keys tabs">
          <Tab value="rw">Read-write Keys</Tab>
          <Tab value="ro">Read-only Keys</Tab>
        </TabList>
        {tab === "rw" && (
          <div className="vy-props" style={{ marginTop: 12 }}>
            <KV label="URI" value={uri} />
            <KV label="PRIMARY KEY" value={mask(rw.data?.primaryMasterKey)} />
            <KV label="SECONDARY KEY" value={mask(rw.data?.secondaryMasterKey)} />
            <KV label="PRIMARY CONNECTION STRING" value={mask(csFor("Primary SQL Connection String"))} />
            <KV label="SECONDARY CONNECTION STRING" value={mask(csFor("Secondary SQL Connection String"))} />
          </div>
        )}
        {tab === "ro" && (
          <div className="vy-props" style={{ marginTop: 12 }}>
            <KV label="URI" value={uri} />
            <KV label="PRIMARY KEY" value={mask(ro.data?.primaryReadonlyMasterKey)} />
            <KV label="SECONDARY KEY" value={mask(ro.data?.secondaryReadonlyMasterKey)} />
            <KV label="PRIMARY CONNECTION STRING" value={mask(csFor("Primary Read-Only SQL Connection String"))} />
            <KV label="SECONDARY CONNECTION STRING" value={mask(csFor("Secondary Read-Only SQL Connection String"))} />
          </div>
        )}
      </CapabilityContainer>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this account) ────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const resPath = api.resourcePath(a.resourceGroup, a.name);
  const { data, loading, error, reload } = useAsync(() => api.listLocks(resPath), [resPath]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows.map((r) => ({ ...r, name: r.id.split("/").pop() }))} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Subscription")}>Subscription</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Resource group")}>Resource group</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteLock(resPath, r.name);
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
        onCreate={async (name, level, notes) => { await api.putLock(resPath, name, { properties: { level, notes } }); reload(); }} />
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
          <DialogTitle>Add lock</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Lock name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Lock name" /></Field>
              <Field label="Lock type" required><Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type"><option>Read-only</option><option>Delete</option></Select></Field>
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
    ...(params ? { parameters: { accountName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.DocumentDB/databaseAccounts", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('accountName')]" : a.name, location: a.location, kind: a.kind, properties: a.properties }],
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
