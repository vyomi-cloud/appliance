/* API Management service resource blade: left resource menu + panels. Overview, Activity
 * log, Access control (IAM) (subscription-wide, see capabilities.json), Tags, APIs, Products,
 * Subscriptions, Named values, Backends, API Tags, Policy fragments, Diagnostic settings,
 * Scale out and up, Pricing tier, Properties, Locks and Export template (ARM Template tab)
 * are backed by native ARM calls; everything else in the menu — Diagnose and solve problems,
 * Events, Developer portal, the rest of Monitoring, the rest of Deployment + infrastructure,
 * Security, Automation tasks, Help — is an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Select, Spinner, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import Apis from "./Apis.jsx";
import Products from "./Products.jsx";
import Subscriptions from "./Subscriptions.jsx";
import NamedValues from "./NamedValues.jsx";
import Backends from "./Backends.jsx";
import ApiTags from "./ApiTags.jsx";
import PolicyFragments from "./PolicyFragments.jsx";
import DiagnosticSettings from "./DiagnosticSettings.jsx";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "events", label: "Events" },
  { group: "APIs", items: [
    { id: "apis", label: "APIs" }, { id: "mcpservers", label: "MCP Servers" }, { id: "products", label: "Products" },
    { id: "subscriptions", label: "Subscriptions" }, { id: "namedvalues", label: "Named values" }, { id: "backends", label: "Backends" },
    { id: "apitags", label: "API Tags" }, { id: "policyfragments", label: "Policy fragments" }, { id: "workspaces", label: "Workspaces" },
    { id: "credentialmanager", label: "Credential manager" },
  ] },
  { group: "Developer portal", items: [
    { id: "portaloverview", label: "Portal overview" }, { id: "portalsettings", label: "Portal settings" }, { id: "users", label: "Users" },
    { id: "groups", label: "Groups" }, { id: "identities", label: "Identities" }, { id: "delegation", label: "Delegation" },
  ] },
  { group: "Monitoring", items: [
    { id: "appinsights", label: "Application Insights" }, { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }, { id: "analytics", label: "Analytics" },
  ] },
  { group: "Deployment + infrastructure", items: [
    { id: "network", label: "Network" }, { id: "customdomains", label: "Custom domains" }, { id: "locations", label: "Locations" },
    { id: "scaleoutandup", label: "Scale out and up" }, { id: "pricingtier", label: "Pricing tier" }, { id: "managedidentities", label: "Managed identities" },
    { id: "certificates", label: "Certificates" }, { id: "gateways", label: "Gateways" }, { id: "selfhostedgateways", label: "Self-hosted gateways" },
  ] },
  { group: "Security", items: [{ id: "defenderforcloud", label: "Defender for Cloud" }, { id: "protocolsciphers", label: "Protocols + ciphers" }] },
  { group: "Settings", items: [{ id: "properties", label: "Properties" }, { id: "locks", label: "Locks" }] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "support", label: "Support + Troubleshooting" }] },
];
export const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

// Every blade item with no real backing maps to a capability id (core/capabilities/azure/
// apim.json) — CapabilityContainer renders the honest NotSimulated panel from there, never
// a hand-written disclaimer.
const CAP_FOR = {
  diagnose: "azure.apim.tools", events: "azure.apim.tools", tasks: "azure.apim.tools", support: "azure.apim.tools",
  mcpservers: "azure.apim.tools", workspaces: "azure.apim.tools", credentialmanager: "azure.apim.tools",
  portaloverview: "azure.apim.developerportal", portalsettings: "azure.apim.developerportal", users: "azure.apim.developerportal",
  groups: "azure.apim.developerportal", identities: "azure.apim.developerportal", delegation: "azure.apim.developerportal",
  appinsights: "azure.apim.monitoring", alerts: "azure.apim.monitoring", metrics: "azure.apim.monitoring",
  logs: "azure.apim.monitoring", analytics: "azure.apim.monitoring",
  network: "azure.apim.deployment", customdomains: "azure.apim.deployment", locations: "azure.apim.deployment",
  managedidentities: "azure.apim.deployment",
  certificates: "azure.apim.deployment", gateways: "azure.apim.deployment", selfhostedgateways: "azure.apim.deployment",
  defenderforcloud: "azure.apim.deployment",
};

export default function ApimBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const svc = useAsync(() => api.getService(rg, name), [rg, name]);
  const self = `#/apim/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (svc.data) remember({ name, type: "API Management service", href: self }); }, [!!svc.data, self]);

  let body;
  if (svc.loading && !svc.data) body = <Loading />;
  else if (svc.error) body = <><ErrorBar error={svc.error} title="Failed to load the API Management service" /><Link href="#/apim">Back to API Management services</Link></>;
  else {
    const a = svc.data, reload = svc.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog a={a} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      apis: () => <Apis rg={rg} svc={name} self={self} />,
      products: () => <Products rg={rg} svc={name} />,
      subscriptions: () => <Subscriptions rg={rg} svc={name} />,
      namedvalues: () => <NamedValues rg={rg} svc={name} />,
      backends: () => <Backends rg={rg} svc={name} />,
      apitags: () => <ApiTags rg={rg} svc={name} />,
      policyfragments: () => <PolicyFragments rg={rg} svc={name} />,
      diagnosticsettings: () => <DiagnosticSettings rg={rg} svc={name} />,
      scaleoutandup: () => <ScaleOutAndUp a={a} reload={reload} />,
      pricingtier: () => <PricingTier a={a} reload={reload} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      protocolsciphers: () => <ProtocolsCiphers a={a} reload={reload} />,
    }[panel];
    body = P ? P() : (
      <CapabilityContainer id={CAP_FOR[panel] || "azure.apim.tools"} title={`${name} | ${LABEL[panel] || panel}`} />
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="API Management service" glyph={<Glyph id="apim" />} closeHref="#/apim"
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
  const [json, setJson] = useState(false);
  const [gap, setGap] = useState(null);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Restore")}>Restore</ToolbarButton>
        <ToolbarButton onClick={() => notify.info("Move isn't simulated — resources stay in their original resource group.")}>Move</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
      </div>
      <Essentials
        actions={<Link as="button" onClick={() => setJson(true)}>JSON View</Link>}
        left={[
          ["Resource group", <Link href="#/apim">{a.resourceGroup}</Link>],
          ["Status", p.provisioningState || "Online"],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Tier", a.sku?.name || "--"],
          ["Gateway URL", p.gatewayUrl || api.gatewayUrl(a.name)],
          ["Developer portal URL", p.portalUrl || api.portalUrl(a.name)],
          ["Platform version", "stv2"],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="getstarted">Get started</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="capacity">Capacity</Tab>
        <Tab value="properties">Properties</Tab>
      </TabList>
      {tab === "getstarted" && (
        <div style={{ marginTop: 12 }}>
          <p style={{ fontSize: 13 }}>Manage your APIs, products and subscriptions, or explore the developer portal.</p>
          <Link href={`${self}/apis`}>APIs</Link>{" · "}<Link href={`${self}/products`}>Products</Link>{" · "}<Link href={`${self}/subscriptions`}>Subscriptions</Link>
        </div>
      )}
      {tab === "monitoring" && <NotSimulatedContainer feature="API Management monitoring (capacity, requests, latency charts)" />}
      {tab === "capacity" && <NotSimulatedContainer feature="The capacity gauge" />}
      {tab === "properties" && <PropertyList a={a} />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="API Management service" names={[a.name]}
        onConfirm={async () => {
          await api.deleteService(a.resourceGroup, a.name);
          forget(self);
          notify.success(`API Management service '${a.name}' was deleted.`, "Delete succeeded");
          navigate("apim");
        }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : "Restoring a soft-deleted API Management service"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog open={json} onOpenChange={(_, d) => setJson(d.open)}>
        <DialogSurface style={{ maxWidth: 820 }} aria-label="Resource JSON">
          <DialogBody>
            <DialogTitle>Resource JSON</DialogTitle>
            <DialogContent>
              <Field label="Resource ID"><Input readOnly value={a.id} /></Field>
              <pre className="vy-mono" style={{ maxHeight: 420, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 12, borderRadius: 4 }}>{JSON.stringify(Object.fromEntries(Object.entries(a).filter(([k]) => k !== "resourceGroup")), null, 2)}</pre>
            </DialogContent>
            <DialogActions><Button onClick={() => setJson(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function PropertyList({ a }) {
  const p = a.properties || {};
  return (
    <div className="vy-props" style={{ marginTop: 12 }}>
      <KV label="Resource name" value={a.name} />
      <KV label="Resource ID" value={a.id} />
      <KV label="Tier" value={a.sku?.name} />
      <KV label="Publisher email" value={p.publisherEmail} />
      <KV label="Publisher name" value={p.publisherName} />
      <KV label="Gateway URL" value={p.gatewayUrl || api.gatewayUrl(a.name)} />
    </div>
  );
}

// Read-only "Properties" blade item (same data as the Overview Properties tab, under its
// own menu entry — the real portal repeats several panels this way).
function Properties({ a }) {
  return <><div className="vy-panel-title">{a.name} | Properties</div><PropertyList a={a} /></>;
}

// ── Access control (IAM): Role assignments / Roles are real ARM resources
// (Microsoft.Authorization/roleAssignments, roleDefinitions), subscription-wide rather than
// scoped to this one service — see capabilities.json azure.apim.iam. ──────────────────────
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("checkaccess");
  const [gap, setGap] = useState(null);
  const roleAssignments = useAsync(() => api.listRoleAssignments(), []);
  const roleDefinitions = useAsync(() => api.listRoleDefinitions(), []);
  return (
    <CapabilityContainer id="azure.apim.iam" title={`${a.name} | Access control (IAM)`}>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="checkaccess">Check access</Tab>
        <Tab value="roleassignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "checkaccess" && (
        <div style={{ display: "flex", gap: 24, marginTop: 12 }}>
          <section className="vy-section"><h3>My access</h3><Button onClick={() => setGap("View my access")}>View my access</Button></section>
          <section className="vy-section"><h3>Check access</h3><Button onClick={() => setGap("Check access")}>Check access</Button></section>
        </div>
      )}
      {tab === "roleassignments" && (
        <section className="vy-section" style={{ marginTop: 12 }}>
          <BrowseGrid resourceName="role assignment" rowKey={(r) => r.id} filterPlaceholder="Search by name or email"
            items={roleAssignments.data || []} loading={roleAssignments.loading} error={roleAssignments.error} onRefresh={roleAssignments.reload}
            csvName="role-assignments.csv"
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
        <section className="vy-section" style={{ marginTop: 12 }}>
          <BrowseGrid resourceName="role" rowKey={(r) => r.id} filterPlaceholder="Search by role name, description, permission, or ID"
            items={roleDefinitions.data || []} loading={roleDefinitions.loading} error={roleDefinitions.error} onRefresh={roleDefinitions.reload}
            csvName="roles.csv"
            columns={[
              { key: "name", label: "Name", value: (r) => r.properties?.roleName || r.name },
              { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
              { key: "type", label: "Type", value: (r) => r.properties?.type || "BuiltInRole" },
              { key: "category", label: "Category", value: () => "General" },
            ]}
          />
        </section>
      )}
      {tab === "deny" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Deny assignments" feature="Deny assignments" /></div>}
      {tab === "classic" && <div style={{ marginTop: 12 }} />}
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody><DialogTitle>{gap}</DialogTitle><DialogContent><NotSimulated feature={`${gap} evaluation`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions></DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
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
    <table className="vy-grid" style={{ maxWidth: 760 }}>
      <thead><tr><th>Name</th><th>Value</th><th>Resource</th><th /></tr></thead>
      <tbody>
        {tags.map((t, i) => (
          <tr key={i}>
            <td><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></td>
            <td><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></td>
            <td>{resource}</td>
            <td>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete tag ${i + 1}`} onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const save = async (next) => {
    setBusy(true);
    try {
      await api.updateService(a.resourceGroup, a.name, { tags: next, properties: {} });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  const tagsOf = (xs) => Object.fromEntries(xs.filter((r) => r.name).map((r) => [r.name, r.value]));
  return (
    <>
      <div className="vy-panel-title">Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs; the same tag can apply to multiple resources.</p>
      <TagRows tags={rows} onChange={setRows} resource={a.name} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={() => save(tagsOf(rows))}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button disabled={busy} onClick={() => { setRows([{ name: "", value: "" }]); save({}); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this service) ─────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton onClick={() => setAdd(true)}>Add</ToolbarButton>
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
          <DialogTitle>Add lock</DialogTitle>
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

// Pads JS's millisecond ISO string to the backend's 6-digit microsecond `%f` format
// (zero-padding the remainder keeps the bound inclusive — see core/azure_arm_core._filter_by_timespan).
const isoMicro = (d) => d.toISOString().replace(/(\.\d{3})Z$/, "$1000Z");
const TIMESPANS = [["6h", "Last 6 hours", 6], ["24h", "Last 24 hours", 24], ["7d", "Last 7 days", 24 * 7], ["30d", "Last 30 days", 24 * 30], ["all", "All time", null]];

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this service) ──
function ActivityLog({ a }) {
  const [timespan, setTimespan] = useState("24h");
  const hours = TIMESPANS.find(([k]) => k === timespan)?.[2];
  const ge = hours ? isoMicro(new Date(Date.now() - hours * 3600e3)) : null;
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name, ge ? { ge } : undefined), [a.id, timespan]);
  const rows = data || [];
  const [gap, setGap] = useState(null);
  return (
    <CapabilityContainer id="azure.apim.activity_log" title={`${a.name} | Activity log`}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton onClick={() => setGap("Activity")}>Activity</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Edit columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Download as CSV")}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Insights")}>Insights</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Pin current filters")}>Pin current filters</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Reset filters")}>Reset filters</ToolbarButton>
      </div>
      <Field label="Timespan" style={{ maxWidth: 200, marginBottom: 8 }}>
        <Select value={timespan} onChange={(_, d) => setTimespan(d.value)} aria-label="Timespan">
          {TIMESPANS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </Select>
      </Field>
      <ErrorBar error={error} />
      <table className="vy-grid" style={{ width: "100%" }}>
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
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || ""}>
          <DialogBody><DialogTitle>{gap}</DialogTitle><DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `The ${gap} action`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions></DialogBody>
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
    ...(params ? { parameters: { serviceName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.ApiManagement/service", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('serviceName')]" : a.name, location: a.location, sku: a.sku, properties: a.properties }],
  };
  const text = JSON.stringify(template, null, 2);
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    el.download = `${a.name}.json`;
    document.body.appendChild(el); el.click(); el.remove();
  };
  return (
    <CapabilityContainer id="azure.apim.exporttemplate" title={`${a.name} | Export template`}>
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
    </CapabilityContainer>
  );
}

// ── Scale out and up / Pricing tier (post-creation sku.capacity / sku.name over ARM — the
// SAME generic sku merge the create wizard's Pricing tier step writes) ────────────────────
const TIER_NAMES = ["Developer", "Basic", "Standard", "Premium", "BasicV2", "StandardV2", "PremiumV2", "Consumption"];

function ScaleOutAndUp({ a, reload }) {
  const notify = useNotify();
  const [units, setUnits] = useState(a.sku?.capacity ?? 1);
  const [busy, setBusy] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.scaletier" title={`${a.name} | Scale out and up`}>
      <p style={{ fontSize: 13 }}>Current tier: <b>{a.sku?.name || "--"}</b>. Units: <b>{a.sku?.capacity ?? 0}</b>.</p>
      <Field label="Units" style={{ maxWidth: 240 }}>
        <Input type="number" min={0} max={12} value={String(units)} onChange={(_, d) => setUnits(Number(d.value) || 0)} aria-label="Units" />
      </Field>
      <div style={{ marginTop: 12 }}>
        <Button appearance="primary" disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            await api.updateService(a.resourceGroup, a.name, { sku: { capacity: units } });
            notify.success(`Scaled '${a.name}' to ${units} unit${units === 1 ? "" : "s"}.`, "Scale succeeded");
            reload();
          } catch (e) { notify.error(e, "Scaling failed"); }
          finally { setBusy(false); }
        }}>Save</Button>
      </div>
    </CapabilityContainer>
  );
}

function PricingTier({ a, reload }) {
  const notify = useNotify();
  const [tier, setTier] = useState(a.sku?.name || "Developer");
  const [busy, setBusy] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.scaletier" title={`${a.name} | Pricing tier`}>
      <Field label="Pricing tier" style={{ maxWidth: 280 }}>
        <Select value={tier} onChange={(_, d) => setTier(d.value)} aria-label="Pricing tier">
          {TIER_NAMES.map((t) => <option key={t}>{t}</option>)}
        </Select>
      </Field>
      <div style={{ marginTop: 12 }}>
        <Button appearance="primary" disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            await api.updateService(a.resourceGroup, a.name, { sku: { name: tier } });
            notify.success(`'${a.name}' tier changed to ${tier}.`, "Pricing tier updated");
            reload();
          } catch (e) { notify.error(e, "Changing tier failed"); }
          finally { setBusy(false); }
        }}>Save</Button>
      </div>
    </CapabilityContainer>
  );
}

// ── Protocols + ciphers (Settings > Protocols + ciphers blade item — re-edits the SAME
// properties.customProperties flags the create wizard's "Protocol settings" step writes) ──
function ProtocolsCiphers({ a, reload }) {
  const notify = useNotify();
  const p = a.properties?.customProperties || {};
  const [busy, setBusy] = useState(false);
  const toggle = async (key, value) => {
    setBusy(true);
    try {
      await api.updateService(a.resourceGroup, a.name, { properties: { customProperties: { [key]: value } } });
      notify.success("Protocol settings saved.", "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving protocol settings failed"); }
    finally { setBusy(false); }
  };
  const side = (s) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: 360 }}>
      {api.PROTOCOL_KEYS.filter(([, , side2]) => side2 === s).map(([key, label]) => (
        <div key={key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{label}</span>
          <Checkbox disabled={busy} checked={p[key] === "True"} onChange={(_, d) => toggle(key, d.checked ? "True" : "False")} aria-label={`${label} (${s} side)`} />
        </div>
      ))}
    </div>
  );
  return (
    <CapabilityContainer id="azure.apim.service.protocols" title={`${a.name} | Protocols + ciphers`}>
      <section className="vy-section"><h3>Client side</h3>{side("client")}</section>
      <section className="vy-section"><h3>Backend side</h3>{side("backend")}</section>
    </CapabilityContainer>
  );
}
