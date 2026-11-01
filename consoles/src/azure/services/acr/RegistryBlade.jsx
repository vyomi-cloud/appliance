/* Container registry resource blade: left resource menu + panels. Overview, Tags, Access
 * keys, Repositories (+ repository detail), Webhooks, Locks, Properties, Access control (IAM)
 * (Role assignments/Roles real; Deny assignments/Classic administrators honest), Diagnostic
 * settings, Export template (ARM/Bicep/Terraform), Quick start, Events, Encryption, Identity,
 * Networking, Geo-replications, Tasks, Cache, Connected registries, Tokens, Scope maps and
 * Retention (Preview) are all backed by real native calls (ARM control plane + the registry's
 * own OCI/ACR REST data plane) — only Support + Troubleshooting (a real Microsoft support
 * ticket) stays an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular, Eye16Regular, EyeOff16Regular, Play16Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { LOCATIONS, locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "../keyvaults/KeyVaultBlade.jsx";
import * as kv from "../keyvaults/api.js";
import { ResourceRecommendations } from "../defender/Pages.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "quickstart", label: "Quick start" },
  { id: "events", label: "Events" },
  { group: "Settings", items: [{ id: "accesskeys", label: "Access keys" }, { id: "encryption", label: "Encryption" }, { id: "identity", label: "Identity" }, { id: "networking", label: "Networking" }, { id: "defender", label: "Microsoft Defender for Cloud" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" }] },
  { group: "Services", items: [{ id: "repositories", label: "Repositories" }, { id: "webhooks", label: "Webhooks" }, { id: "georeplications", label: "Geo-replications" }, { id: "tasks", label: "Tasks" }, { id: "cache", label: "Cache" }, { id: "connectedregistries", label: "Connected registries" }] },
  { group: "Repository permissions", items: [{ id: "tokens", label: "Tokens" }, { id: "scopemaps", label: "Scope maps" }] },
  { group: "Policies", items: [{ id: "retention", label: "Retention (Preview)" }] },
  { group: "Monitoring", items: [{ id: "insights", label: "Insights" }, { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }] },
  { group: "Automation", items: [{ id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
// Every blade menu item is wired to its own capability id in core/capabilities/azure/acr.json
// (azure.acr.<item>) and rendered by a real panel below. Support + Troubleshooting is the one
// item that falls through to the default NotSimulated branch — opening a support request
// routes to Microsoft's own ticketing system, a genuine third party Vyomi has no backing
// organization to open a ticket against. The Monitoring-group items besides Diagnostic settings
// (Insights, Alerts, Metrics, Logs) stay an explicit honest gap (azure.acr.monitoring).

export default function RegistryBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const reg = useAsync(() => api.getRegistry(rg, name), [rg, name]);
  const self = `#/acr/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (reg.data) remember({ name, type: "Container registry", href: self }); }, [!!reg.data, self]);
  useEffect(() => { api.setActiveRegistry(name); return () => api.setActiveRegistry(""); }, [name]);

  let body;
  if (reg.loading && !reg.data) body = <Loading />;
  else if (reg.error) body = <><ErrorBar error={reg.error} title="Failed to load the container registry" /><Link href="#/acr">Back to Container registries</Link></>;
  else {
    const a = reg.data, reload = reg.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      defender: () => <ResourceRecommendations resourceId={a.id} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      accesskeys: () => <AccessKeys a={a} reload={reload} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      repositories: () => <Repositories query={query} self={self} />,
      webhooks: () => <Webhooks a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      diagnosticsettings: () => <DiagnosticSettings a={a} />,
      insights: () => <NotSimulatedContainer title={`${name} | Insights`} feature="Insights" />,
      alerts: () => <NotSimulatedContainer title={`${name} | Alerts`} feature="Alerts" />,
      metrics: () => <NotSimulatedContainer title={`${name} | Metrics`} feature="Metrics" />,
      logs: () => <NotSimulatedContainer title={`${name} | Logs`} feature="Logs" />,
      quickstart: () => <QuickStart a={a} />,
      events: () => <EventsPanel a={a} rg={a.resourceGroup} />,
      encryption: () => <Encryption a={a} reload={reload} />,
      identity: () => <Identity a={a} rg={a.resourceGroup} name={a.name} reload={reload} />,
      networking: () => <Networking a={a} reload={reload} />,
      georeplications: () => <GeoReplications a={a} />,
      tasks: () => <Tasks a={a} />,
      cache: () => <CacheRules a={a} />,
      connectedregistries: () => <ConnectedRegistries a={a} />,
      tokens: () => <Tokens a={a} />,
      scopemaps: () => <ScopeMaps a={a} />,
      retention: () => <Retention a={a} reload={reload} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{LABEL[panel] || panel}</div>
        <CapabilityContainer id="azure.acr.support_troubleshooting" title={LABEL[panel] || panel} />
      </>
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Container registry" glyph={<Glyph id="acr" />} closeHref="#/acr"
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
  const [gap, setGap] = useState(null); // "Import image" | "Move" | "Feedback"
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton onClick={() => setGap("Import image")}>Import image</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Move")}>Move</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Login server", api.loginServer(a.name)],
        ]}
        right={[
          ["Creation date", fmtDate(p.creationDate)],
          ["Provisioning state", p.provisioningState],
          ["Pricing plan", api.skuLabel(a.sku)],
          ["Soft delete", "Disabled"],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="getstarted">Get started</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="properties">Properties</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="recommendations">Recommendations</Tab>
      </TabList>
      {tab === "getstarted" && (
        <div style={{ marginTop: 12 }}>
          <p style={{ fontSize: 13 }}>Push and pull container images, or browse what's already in this registry.</p>
          <Link href={`${self}/repositories`}>Repositories</Link>{" · "}<Link href={`${self}/webhooks`}>Webhooks</Link>
        </div>
      )}
      {tab === "monitoring" && <MonitoringTab a={a} />}
      {tab === "properties" && <PropertyList a={a} />}
      {tab === "capabilities" && <CapabilitiesTab a={a} />}
      {tab === "recommendations" && <ResourceRecommendations resourceId={a.id} />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="container registry" names={[a.name]}
        onConfirm={async () => {
          await api.deleteRegistry(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Container registry '${a.name}' was deleted.`, "Delete succeeded");
          navigate("acr");
        }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : gap === "Import image" ? "Importing an image from another registry or source" : "Moving a resource to another resource group/subscription"} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
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
      <KV label="Registry name" value={a.name} />
      <KV label="Resource ID" value={a.id} />
      <KV label="Login server" value={api.loginServer(a.name)} />
      <KV label="Pricing plan" value={api.skuLabel(a.sku)} />
      <KV label="Admin user" value={p.adminUserEnabled ? "Enabled" : "Disabled"} />
      <KV label="Public network access" value={p.publicNetworkAccess} />
      <KV label="Zone redundancy" value={p.zoneRedundancy} />
      <KV label="Domain name label scope" value={p.domainNameLabelScope || "Unsecure"} />
      <KV label="Role assignment permissions mode" value={p.roleAssignmentMode || "RBAC Registry Permissions"} />
    </div>
  );
}

// ── Overview > Monitoring: a live snapshot read off this registry's OWN data plane + ARM
// child resources (repository/webhook/replication counts) — real current state, not a fake
// historical throughput chart (Vyomi doesn't meter push/pull bandwidth over time).
function MonitoringTab({ a }) {
  const repos = useAsync(() => api.listRepositories(), [a.id]);
  const webhooks = useAsync(() => api.listWebhooks(a.resourceGroup, a.name), [a.id]);
  const replications = useAsync(() => api.listReplications(a.resourceGroup, a.name), [a.id]);
  const stat = (label, v, loading) => (
    <div key={label} style={{ minWidth: 140 }}>
      <div style={{ fontSize: 28, fontWeight: 600 }}>{loading ? <Spinner size="tiny" /> : v}</div>
      <div className="vy-muted" style={{ fontSize: 13 }}>{label}</div>
    </div>
  );
  return (
    <div style={{ marginTop: 12 }}>
      <p style={{ fontSize: 13, maxWidth: 640 }}>A live snapshot of this registry's own state. Vyomi doesn't meter push/pull bandwidth over time, so no historical throughput chart is shown.</p>
      <div style={{ display: "flex", gap: 32, marginTop: 12 }}>
        {stat("Repositories", repos.data?.length ?? 0, repos.loading)}
        {stat("Webhooks", webhooks.data?.length ?? 0, webhooks.loading)}
        {stat("Geo-replications", replications.data?.length ?? 0, replications.loading)}
      </div>
    </div>
  );
}

// ── Overview > Capabilities: what this registry's REAL sku tier supports — computed live
// from a.sku, not a static reference table (azure.acr.overview_tabs).
const SKU_CAPABILITIES = [
  ["Admin user / Webhooks", () => true],
  ["ACR Tasks", (tier) => tier !== "Basic"],
  ["Content trust", (tier) => tier !== "Basic"],
  ["Repository-scoped permissions (Tokens / Scope maps)", (tier) => tier === "Premium"],
  ["Geo-replication", (tier) => tier === "Premium"],
  ["Customer-managed keys", (tier) => tier === "Premium"],
  ["Private endpoints / IP network rules", (tier) => tier === "Premium"],
  ["Zone redundancy", (tier) => tier === "Premium"],
  ["Connected registries / Cache rules", (tier) => tier === "Premium"],
  ["Dedicated data endpoints", (tier) => tier === "Premium"],
];
function CapabilitiesTab({ a }) {
  const tier = api.skuLabel(a.sku);
  return (
    <div style={{ marginTop: 12 }}>
      <p style={{ fontSize: 13 }}>What this registry's <b>{tier}</b> pricing plan supports.</p>
      <table className="vy-grid">
        <thead><tr><th>Capability</th><th>Available</th></tr></thead>
        <tbody>{SKU_CAPABILITIES.map(([label, fn]) => <tr key={label}><td>{label}</td><td>{fn(tier) ? "Yes" : "No"}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

// ── Access control (IAM) — Role assignments and Roles are real, scoped to this registry
// (plus its subscription/resource-group ancestors, real Azure's "inherited access" view) over
// the same generic Microsoft.Authorization/roleAssignments extension-resource engine the
// VM/NSG/Cosmos blades use (azure.acr.iam); assignments are still created at the subscription
// scope. Check access / My access / Deny assignments / Classic administrators stay honest gaps. ──
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  const assignments = useAsync(() => api.listRoleAssignments(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const roles = useAsync(() => api.listRoleDefinitions(), []);
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
          <CapabilityContainer id="azure.acr.iam" title="Role assignments">
            <BrowseGrid resourceName="role assignment" rowKey={(r) => r.id} filterPlaceholder="Search by name or email"
              items={assignments.data || []} loading={assignments.loading} error={assignments.error} onRefresh={assignments.reload}
              columns={[
                { key: "name", label: "Name", value: (r) => r.properties?.principalId },
                { key: "type", label: "Type", value: (r) => r.properties?.principalType || "--" },
                { key: "role", label: "Role", value: (r) => r.properties?.roleDefinitionId?.split("/").pop() || r.properties?.roleName },
                { key: "scope", label: "Scope", value: (r) => r.properties?.scope || "/" },
                { key: "condition", label: "Condition", value: () => "None" },
              ]}
            />
          </CapabilityContainer>
        </div>
      )}
      {tab === "roles" && (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id="azure.acr.iam" title="Roles">
            <BrowseGrid resourceName="role" rowKey={(r) => r.id || r.name} filterPlaceholder="Search by role name, description, permission, or ID"
              items={roles.data || []} loading={roles.loading} error={roles.error} onRefresh={roles.reload}
              columns={[
                { key: "name", label: "Name", value: (r) => r.properties?.roleName || r.name },
                { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
                { key: "type", label: "Type", value: (r) => r.properties?.type || "BuiltInRole" },
                { key: "category", label: "Category", value: () => "General" },
              ]}
            />
          </CapabilityContainer>
        </div>
      )}
      {tab === "deny" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Deny assignments" feature="Deny assignments" /></div>}
      {tab === "classic" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Classic administrators" feature="Classic administrators" /></div>}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access check">
          <DialogBody>
            <DialogTitle>{dlg === "mine" ? "My access" : "Check access"}</DialogTitle>
            <DialogContent><NotSimulated feature="Per-identity role-assignment resolution for this resource" note={`The registry's resource id is ${a.id}.`} /></DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
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
      const { id, name, type, resourceGroup, ...rest } = a;
      await api.createRegistry(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Tags</div>
      <p style={{ fontSize: 13 }}>Name/value pairs; the same tag can apply to multiple resources.</p>
      <TagRows tags={rows} onChange={setRows} resource={a.name} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={async () => { setRows([{ name: "", value: "" }]); await apply(); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Access keys (admin user + listCredentials/regenerateCredential) ───────────────────
function AccessKeys({ a, reload }) {
  const notify = useNotify();
  const enabled = !!a.properties?.adminUserEnabled;
  const creds = useAsync(() => (enabled ? api.listCredentials(a.resourceGroup, a.name) : Promise.resolve(null)), [a.resourceGroup, a.name, enabled]);
  const [show, setShow] = useState({ password: false, password2: false });
  const [busy, setBusy] = useState(false);
  const toggleAdmin = async (_, d) => {
    setBusy(true);
    try {
      await api.updateRegistry(a.resourceGroup, a.name, { properties: { adminUserEnabled: !!d.checked } });
      reload();
    } catch (e) { notify.error(e, "Saving admin user failed"); }
    finally { setBusy(false); }
  };
  const regen = async (which) => {
    try {
      await api.regenerateCredential(a.resourceGroup, a.name, which);
      notify.success(`${which === "password" ? "password" : "password2"} was regenerated.`, "Regenerated");
      creds.reload();
    } catch (e) { notify.error(e, "Regenerate failed"); }
  };
  const pw = (which, label) => {
    const val = creds.data?.passwords?.find((p) => p.name === which)?.value || "";
    return (
      <Field label={label}>
        <div style={{ display: "flex", gap: 4, maxWidth: 480 }}>
          <Input readOnly type={show[which] ? "text" : "password"} value={val} style={{ flex: 1 }} aria-label={label} />
          <Button icon={show[which] ? <EyeOff16Regular /> : <Eye16Regular />} onClick={() => setShow((s) => ({ ...s, [which]: !s[which] }))}>{show[which] ? "Hide" : "Show"}</Button>
          <Button onClick={() => regen(which)}>Regenerate</Button>
        </div>
      </Field>
    );
  };
  return (
    <CapabilityContainer id="azure.acr.admin_credentials" title="Access keys">
      <section className="vy-section" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Field label="Registry name"><Input readOnly value={a.name} style={{ maxWidth: 480 }} /></Field>
        <Field label="Login server"><Input readOnly value={api.loginServer(a.name)} style={{ maxWidth: 480 }} /></Field>
        <Checkbox label="Admin user" checked={enabled} disabled={busy} onChange={toggleAdmin} />
        {enabled ? (
          creds.loading ? <Loading /> : creds.error ? <ErrorBar error={creds.error} /> : (
            <>
              <Field label="Username"><Input readOnly value={creds.data?.username || a.name} style={{ maxWidth: 480 }} /></Field>
              {pw("password", "password")}
              {pw("password2", "password2")}
            </>
          )
        ) : <p className="vy-muted" style={{ fontSize: 13 }}>Enable the admin user to see its credentials.</p>}
      </section>
    </CapabilityContainer>
  );
}

// ── Properties ─────────────────────────────────────────────────────────────────────────
function Properties({ a }) {
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <PropertyList a={a} />
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this registry) ────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
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
            <DialogContent>
              <NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `Locks scoped to the ${(gap || "").toLowerCase()}`} />
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

// ── Repositories (data plane: OCI v2 / ACR v1 REST) + repository detail ───────────────
function Repositories({ query, self }) {
  if (query.repo) return <RepositoryDetail self={self} name={query.repo} />;
  return <RepositoriesList self={self} />;
}

function RepositoriesList({ self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listRepositories(), []);
  const rows = (data || []).map((name) => ({ name }));
  return (
    <CapabilityContainer id="azure.acr.repositories" title="Repositories">
      <BrowseGrid
        resourceName="repository" rowKey={(r) => r.name} filterPlaceholder="Search to filter repositories ..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteRepository(r.name);
          notify.success(`Deleted ${sel.length} repositor${sel.length === 1 ? "y" : "ies"}.`, "Delete succeeded");
          reload();
        }}
        csvName="repositories.csv"
        columns={[
          { key: "name", label: "Repositories", render: (r) => <Link href={`${self}/repositories?repo=${encodeURIComponent(r.name)}`}>{r.name}</Link> },
        ]}
      />
    </CapabilityContainer>
  );
}

function RepositoryDetail({ self, name }) {
  const notify = useNotify();
  const attrs = useAsync(() => api.getRepository(name), [name]);
  const tags = useAsync(() => api.listTags(name), [name]);
  const [del, setDel] = useState(false);
  const [filter, setFilter] = useState("");
  const backToList = () => navigate("acr", self.split("/")[2], self.split("/")[3], "repositories");
  const f = filter.trim().toLowerCase();
  const rows = (tags.data || []).filter((t) => !f || t.name.toLowerCase().includes(f)).sort((a, b) => b.lastUpdateTime.localeCompare(a.lastUpdateTime));
  if (attrs.loading) return <Loading />;
  if (attrs.error) return <><ErrorBar error={attrs.error} title="Failed to load the repository" /><Link href={`${self}/repositories`}>Back to Repositories</Link></>;
  const a = attrs.data || {};
  return (
    <CapabilityContainer id="azure.acr.repositories" title={name}>
      <div style={{ fontSize: 13, marginBottom: 8 }}><Link href={`${self}/repositories`}>Repositories</Link> <span className="vy-muted">&gt;</span> {name}</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Repository commands">
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { attrs.reload(); tags.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
      </div>
      <Essentials left={[["Repository", a.imageName || name], ["Last updated date", fmtDate(a.lastUpdateTime)]]}
        right={[["Tag count", a.tagCount ?? 0], ["Manifest count", a.manifestCount ?? 0]]} />
      <Input size="small" style={{ width: 260, margin: "8px 0" }} placeholder="Search to filter tags ..." value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Search to filter tags ..." />
      <Table size="small" aria-label="Tags" style={{ marginTop: 12 }}>
        <TableHeader><TableRow><TableHeaderCell>Tags</TableHeaderCell><TableHeaderCell>Digest</TableHeaderCell><TableHeaderCell>Last modified</TableHeaderCell></TableRow></TableHeader>
        <TableBody>
          {tags.loading ? <TableRow><TableCell colSpan={3}><Spinner size="tiny" /></TableCell></TableRow> : rows.length ? rows.map((t) => (
            <TableRow key={t.name}>
              <TableCell>{t.name}</TableCell>
              <TableCell style={{ fontFamily: "monospace", fontSize: 12 }}>{t.digest}</TableCell>
              <TableCell>{fmtDate(t.lastUpdateTime)}</TableCell>
            </TableRow>
          )) : <TableRow><TableCell colSpan={3} className="vy-muted">No results</TableCell></TableRow>}
        </TableBody>
      </Table>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="repository" names={[name]}
        onConfirm={async () => { await api.deleteRepository(name); notify.success(`Repository '${name}' was deleted.`, "Delete succeeded"); backToList(); }} />
    </CapabilityContainer>
  );
}

// ── Webhooks (Microsoft.ContainerRegistry/registries/webhooks) ────────────────────────
const WEBHOOK_ACTIONS = ["push", "delete", "quarantine", "chart_push", "chart_delete"];

function Webhooks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listWebhooks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.acr.webhooks" title="Webhooks">
      <BrowseGrid
        resourceName="webhook" rowKey={(r) => r.name}
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteWebhook(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} webhook${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="webhooks.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status", value: (r) => r.properties?.status || "enabled" },
          { key: "serviceUri", label: "Service URI", value: (r) => r.properties?.serviceUri },
          { key: "scope", label: "Scope", value: (r) => r.properties?.scope || "--" },
          { key: "actions", label: "Actions", value: (r) => (r.properties?.actions || []).join(", ") },
        ]}
      />
      <AddWebhookDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, body) => { await api.putWebhook(a.resourceGroup, a.name, name, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddWebhookDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [serviceUri, setServiceUri] = useState("");
  const [scope, setScope] = useState("");
  const [status, setStatus] = useState("enabled");
  const [actions, setActions] = useState(new Set(["push"]));
  const [busy, setBusy] = useState(false);
  const valid = /^[a-zA-Z0-9]{1,50}$/.test(name) && /^https?:\/\//.test(serviceUri) && actions.size > 0;
  const toggle = (act) => setActions((s) => { const n = new Set(s); n.has(act) ? n.delete(act) : n.add(act); return n; });
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name, { location: "eastus", properties: { serviceUri, scope, status, actions: [...actions] } });
      notify.success(`Webhook '${name}' was created.`, "Webhook created");
      setName(""); setServiceUri(""); setScope(""); onClose();
    } catch (e) { notify.error(e, "Failed to create webhook"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add webhook">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add webhook</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
              <Field label="Service URI" required><Input value={serviceUri} onChange={(_, d) => setServiceUri(d.value)} aria-label="Service URI" /></Field>
              <Field label="Scope" info="e.g. myapp:* to scope to a repository"><Input value={scope} onChange={(_, d) => setScope(d.value)} aria-label="Scope" /></Field>
              <Field label="Status"><RadioGroup layout="horizontal" value={status} onChange={(_, d) => setStatus(d.value)} aria-label="Status"><Radio value="enabled" label="Enabled" /><Radio value="disabled" label="Disabled" /></RadioGroup></Field>
              <Field label="Trigger"><div style={{ display: "flex", flexDirection: "column" }}>{WEBHOOK_ACTIONS.map((act) => <Checkbox key={act} label={act} checked={actions.has(act)} onChange={() => toggle(act)} />)}</div></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this registry) — the same generic mechanism the NSG/VM/Cosmos lenses
// use. Logs/metrics are stored and validated exactly as the real resource requires, but never
// delivered anywhere (core/capabilities/azure/acr.json azure.acr.monitoring). ──────────────
const DIAG_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;
function DiagnosticSettings({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDiagnosticSettings(a.id), [a.id]);
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const ws = workspaces.data || [];
  return (
    <CapabilityContainer id="azure.acr.monitoring" title={`${a.name} | Diagnostic settings`}>
      <BrowseGrid
        resourceName="diagnostic setting" rowKey={(r) => r.name} filterPlaceholder="Search diagnostic settings"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => { setAdd(true); setWorkspace(ws[0]?.id || ""); }}>Add diagnostic setting</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteDiagnosticSetting(a.id, r.name);
          notify.success(`Deleted ${sel.length} diagnostic setting${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="diagnostic-settings.csv"
        columns={[
          { key: "name", label: "Diagnostic setting name" },
          { key: "dest", label: "Destination details", value: (r) => (r.properties?.workspaceId ? "Log Analytics workspace" : r.properties?.storageAccountId ? "Storage account" : r.properties?.eventHubAuthorizationRuleId ? "Event hub" : "--") },
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
              await api.putDiagnosticSetting(a.id, name, {
                properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] },
              });
              notify.success(`Diagnostic setting '${name}' was created.`, "Create succeeded");
              setAdd(false); setName(""); reload();
            }}>Save</Button>
            <Button onClick={() => setAdd(false)}>Cancel</Button>
          </div>
        </section>
      )}
    </CapabilityContainer>
  );
}

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this registry) ──
const ACTIVITY_LOG_GAPS = ["Activity", "Edit columns", "Export Activity Logs", "Download as CSV", "Insights", "Feedback", "Pin current filters", "Reset filters"];

function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.acr.activity_log" title={`${a.name} | Activity log`}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        {ACTIVITY_LOG_GAPS.map((g) => <ToolbarButton key={g} onClick={() => setGap(g)}>{g}</ToolbarButton>)}
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
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
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `Activity log: ${gap}`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Export template (ARM/Bicep/Terraform all generated client-side from this registry's own
// live resource — same approach as the Storage account/VM blades' Export template) ─────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { registryName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.ContainerRegistry/registries", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('registryName')]" : a.name, location: a.location, sku: a.sku, properties: a.properties }],
  };
  const p = a.properties || {};
  const bicepName = a.name.replace(/[^a-zA-Z0-9]/g, "");
  const bicep = `resource ${bicepName} 'Microsoft.ContainerRegistry/registries@${api.ARM.apiVersion}' = {\n  name: '${a.name}'\n  location: '${a.location}'\n  sku: {\n    name: '${api.skuLabel(a.sku)}'\n  }\n  properties: {\n    adminUserEnabled: ${!!p.adminUserEnabled}\n    publicNetworkAccess: '${p.publicNetworkAccess || "Enabled"}'\n    zoneRedundancy: '${p.zoneRedundancy || "Disabled"}'\n  }\n}\n`;
  const terraform = `resource "azurerm_container_registry" "${a.name.replace(/[^a-zA-Z0-9]/g, "_")}" {\n  name                = "${a.name}"\n  resource_group_name = "${a.resourceGroup}"\n  location            = "${a.location}"\n  sku                 = "${api.skuLabel(a.sku)}"\n  admin_enabled       = ${!!p.adminUserEnabled}\n  public_network_access_enabled = ${p.publicNetworkAccess !== "Disabled"}\n}\n`;
  const text = tab === "arm" ? JSON.stringify(template, null, 2) : tab === "bicep" ? bicep : terraform;
  const ext = tab === "arm" ? "json" : tab === "bicep" ? "bicep" : "tf";
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    el.download = `${a.name}.${ext}`;
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
        {tab === "arm" && <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />}
        <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />
      </section>
    </>
  );
}

// ── Quick start — real docker/az-acr snippets generated from this registry's own live data
// (login server, admin-user state) — nothing to simulate beyond what's already real. ────────
function QuickStart({ a }) {
  const enabled = !!a.properties?.adminUserEnabled;
  const server = api.loginServer(a.name);
  const code = (text) => <pre style={{ background: "var(--colorNeutralBackground3)", padding: 10, borderRadius: 4, overflowX: "auto", fontSize: 12.5 }}>{text}</pre>;
  return (
    <>
      <div className="vy-panel-title">Quick start</div>
      <p style={{ fontSize: 13, maxWidth: 680 }}>Get started pushing and pulling images with this registry, using the Docker CLI, az acr, or any OCI-compliant client.</p>
      <section className="vy-section"><h3>Sign in to the registry</h3>
        {code(`az acr login --name ${a.name}`)}
        {enabled
          ? <p style={{ fontSize: 13 }}>Or with the admin account (Settings &gt; Access keys): <code>docker login {server}</code></p>
          : <p className="vy-muted" style={{ fontSize: 13 }}>Enable the admin user under Settings &gt; Access keys to sign in with a username/password instead of az acr login.</p>}
      </section>
      <section className="vy-section"><h3>Push an image</h3>{code(`docker tag myimage ${server}/myimage:v1\ndocker push ${server}/myimage:v1`)}</section>
      <section className="vy-section"><h3>Pull an image</h3>{code(`docker pull ${server}/myimage:v1`)}</section>
    </>
  );
}

// ── Events — real Microsoft.EventGrid/systemTopics (api.js), filtered to this registry's
// resource id (azure.acr.events). Delivery itself stays honest (see Webhooks). ──────────────
function EventsPanel({ a, rg }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listEventSystemTopics(rg), [rg]);
  const mine = (data || []).filter((t) => t.properties?.source === a.id);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  return (
    <CapabilityContainer id="azure.acr.events" title="Events">
      <p style={{ fontSize: 13, maxWidth: 640 }}>Event Grid system topics subscribed to this registry's push/delete/chart events.</p>
      <BrowseGrid resourceName="system topic" rowKey={(r) => r.id}
        items={mine} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => { setName(`${a.name}-events`); setAdd(true); }}>+ Event subscription</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteEventSystemTopic(rg, r.name); notify.success(`Deleted ${sel.length} system topic${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" },
          { key: "topicType", label: "Topic type", value: (r) => r.properties?.topicType },
          { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Create event subscription">
          <DialogBody>
            <DialogTitle>Create event subscription</DialogTitle>
            <DialogContent>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!/^[a-zA-Z0-9-]{3,50}$/.test(name)} onClick={async () => {
                try { await api.putEventSystemTopic(rg, name, a.id); notify.success(`Event subscription '${name}' was created.`, "Create succeeded"); setAdd(false); reload(); }
                catch (e) { notify.error(e, "Create failed"); }
              }}>Create</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Encryption — customer-managed key via an EXISTING Key Vault key (azure.acr.encryption):
// Premium-only (enforced server-side too, AzureArm._acr_validate_block) and requires a system
// assigned identity (to actually reach the vault) before it can be turned on. ────────────────
function Encryption({ a, reload }) {
  const notify = useNotify();
  const premium = api.skuLabel(a.sku) === "Premium";
  const hasIdentity = /systemassigned/i.test(a.identity?.type || "");
  const enabled = a.properties?.encryption?.status === "enabled";
  const vaults = useAsync(() => kv.listVaults(), []);
  const [vault, setVault] = useState("");
  const keys = useAsync(() => { if (!vault) return Promise.resolve([]); kv.setActiveVault(vault); return kv.listKeys(); }, [vault]);
  useEffect(() => () => kv.setActiveVault(""), []);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const keyNames = (keys.data || []).map((k) => kv.parseKid(k.kid).name);
  const disable = async () => {
    setBusy(true);
    try { await api.updateEncryption(a.resourceGroup, a.name, { status: "disabled" }); notify.success("Encryption was turned off.", "Save succeeded"); reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  const enable = async () => {
    setBusy(true);
    try {
      await api.updateEncryption(a.resourceGroup, a.name, { status: "enabled", keyVaultProperties: { identity: "[system]", keyIdentifier: `${kv.vaultUri(vault)}keys/${key}` } });
      notify.success("Encryption was turned on.", "Save succeeded"); reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.acr.encryption" title="Encryption">
      {!premium && <p className="vy-muted" style={{ fontSize: 13 }}>Customer-managed key encryption requires the Premium service tier.</p>}
      {premium && !hasIdentity && <p className="vy-muted" style={{ fontSize: 13 }}>Turn on a system assigned managed identity under Identity first — Vyomi uses it to reach the Key Vault key.</p>}
      {enabled ? (
        <>
          <p style={{ fontSize: 13 }}>Customer-managed key: <b>Enabled</b></p>
          <p style={{ fontSize: 13 }}>Key identifier: <code>{a.properties?.encryption?.keyVaultProperties?.keyIdentifier}</code></p>
          <Button disabled={busy} onClick={disable}>Disable</Button>
        </>
      ) : premium && hasIdentity ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 480 }}>
          <Field label="Key Vault"><Select value={vault} onChange={(_, d) => { setVault(d.value); setKey(""); }} aria-label="Key Vault">
            <option value="">Select a key vault</option>
            {(vaults.data || []).map((v) => <option key={v.id} value={v.name}>{v.name}</option>)}
          </Select></Field>
          <Field label="Key"><Select value={key} onChange={(_, d) => setKey(d.value)} disabled={!vault} aria-label="Key">
            <option value="">Select a key</option>
            {keyNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </Select></Field>
          <div><Button appearance="primary" disabled={busy || !vault || !key} onClick={enable}>Enable</Button></div>
        </div>
      ) : <p style={{ fontSize: 13 }}>Customer-managed key: <b>Disabled</b></p>}
    </CapabilityContainer>
  );
}

// ── Identity — System assigned managed identity mints a real, stable principalId/tenantId
// (azure_arm_core.AzureArm._apply_identity, generic over every catalog type). User assigned
// stays an honest gap (Vyomi has no Managed Identity resource of its own), same as App Service. ─
function Identity({ a, rg, name, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("systemassigned");
  const ident = a.identity || { type: "None" };
  const on = /systemassigned/i.test(ident.type || "");
  const [busy, setBusy] = useState(false);
  const toggle = async (enable) => {
    setBusy(true);
    try {
      await api.updateIdentity(rg, name, { type: enable ? "SystemAssigned" : "None" });
      notify.success(`System assigned managed identity was turned ${enable ? "on" : "off"} for '${name}'.`, "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.acr.identity" title="Identity">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Identity tabs">
        <Tab value="systemassigned">System assigned</Tab>
        <Tab value="userassigned">User assigned</Tab>
      </TabList>
      {tab === "systemassigned" && (
        <div style={{ marginTop: 12 }}>
          <p style={{ fontSize: 13, maxWidth: 640 }}>A system assigned managed identity is restricted to one per registry and is shared by the whole registry. It is deleted when the registry itself is deleted.</p>
          <Field label="Status"><RadioGroup value={on ? "On" : "Off"} onChange={(_, d) => toggle(d.value === "On")} aria-label="Status">
            <Radio value="On" label="On" disabled={busy} /><Radio value="Off" label="Off" disabled={busy} />
          </RadioGroup></Field>
          {on && (
            <div className="vy-props" style={{ marginTop: 8 }}>
              <KV label="Object (principal) ID" value={ident.principalId} />
              <KV label="Tenant ID" value={ident.tenantId} />
            </div>
          )}
        </div>
      )}
      {tab === "userassigned" && (
        <div style={{ marginTop: 12 }}>
          <NotSimulatedContainer feature="User assigned managed identities" note="Vyomi has no User Assigned Identity resource of its own to attach here." />
        </div>
      )}
    </CapabilityContainer>
  );
}

// ── Networking — disabling public network access is ENFORCED for real: this registry's own
// data-plane calls (push/pull/_catalog/…) are rejected while it's off (acr_network_denied,
// core/aws_wire_router.py / core/wire_ingress.py, keyed off the x-vyomi-registry header). ────
function Networking({ a, reload }) {
  const notify = useNotify();
  const premium = api.skuLabel(a.sku) === "Premium";
  const pna = a.properties?.publicNetworkAccess || "Enabled";
  const [busy, setBusy] = useState(false);
  const setAccess = async (val) => {
    setBusy(true);
    try { await api.updateNetworking(a.resourceGroup, a.name, { publicNetworkAccess: val }); notify.success(`Public network access was set to '${val}'.`, "Save succeeded"); reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.acr.networking" title="Networking">
      <p style={{ fontSize: 13, maxWidth: 640 }}>Disabling public network access actually blocks this registry's own push/pull endpoint — Vyomi has no private-endpoint path to let a caller back in.</p>
      <Field label="Public network access">
        <RadioGroup value={pna} onChange={(_, d) => setAccess(d.value)} aria-label="Public network access">
          <Radio value="Enabled" label="All networks" disabled={busy} />
          <Radio value="Disabled" label="Disabled" disabled={busy || !premium} />
        </RadioGroup>
        {!premium && <div className="vy-muted" style={{ fontSize: 12 }}>Disabling public network access requires the Premium service tier.</div>}
      </Field>
    </CapabilityContainer>
  );
}

// ── Geo-replications — real nested ARM child resources (Microsoft.ContainerRegistry/
// registries/replications), Premium-gated and region/uniqueness-validated server-side
// (AzureArm._acr_validate_block) — actual cross-region data redundancy isn't modeled (the
// registry's repositories are already a single process-global store, see azure_acr_core.py). ──
function GeoReplications({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listReplications(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [region, setRegion] = useState(LOCATIONS.find(([id]) => id !== a.location)?.[0] || "westus");
  return (
    <CapabilityContainer id="azure.acr.georeplications" title="Geo-replications">
      <BrowseGrid resourceName="replication" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteReplication(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} replication${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Replication" },
          { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
          { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Add replication">
          <DialogBody>
            <DialogTitle>Add replication</DialogTitle>
            <DialogContent>
              <Field label="Location" required><Select value={region} onChange={(_, d) => setRegion(d.value)} aria-label="Location">
                {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
              </Select></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={async () => {
                try { await api.putReplication(a.resourceGroup, a.name, region, { location: region }); notify.success(`Replication to '${locationLabel(region)}' was created.`, "Create succeeded"); setAdd(false); reload(); }
                catch (e) { notify.error(e, "Create failed"); }
              }}>Add</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Tasks (+ Run history) — real task definitions and run records (Microsoft.ContainerRegistry/
// registries/tasks + .../runs), Standard+-gated server-side. "Run now" records a genuine run,
// but Vyomi never executes the build itself (no container runtime, and a real build would need
// to pull base images over the real internet, which nothing-leaves-the-simulator forbids). ───
function Tasks({ a }) {
  const notify = useNotify();
  const tasks = useAsync(() => api.listTasks(a.resourceGroup, a.name), [a.id]);
  const runs = useAsync(() => api.listRuns(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const runTask = async (task) => {
    const runId = `run${Math.random().toString(36).slice(2, 8)}`;
    try {
      await api.putRun(a.resourceGroup, a.name, runId, { properties: {
        taskName: task.name, status: "Succeeded", runType: "QuickRun",
        startTime: new Date().toISOString(), finishTime: new Date().toISOString(),
      } });
      notify.success(`Run '${runId}' of task '${task.name}' succeeded.`, "Run succeeded");
      runs.reload();
    } catch (e) { notify.error(e, "Run failed"); }
  };
  return (
    <CapabilityContainer id="azure.acr.tasks" title="Tasks">
      <p style={{ fontSize: 13, maxWidth: 680 }}>Task definitions and run history are real, stored ARM resources — "Run now" records a real run, but Vyomi does not execute the build itself.</p>
      <BrowseGrid resourceName="task" rowKey={(r) => r.name}
        items={tasks.data || []} loading={tasks.loading} error={tasks.error} onRefresh={tasks.reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteTask(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} task${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); tasks.reload(); }}
        columns={[
          { key: "name", label: "Task" },
          { key: "status", label: "Status", value: (r) => r.properties?.status || "Enabled" },
          { key: "run", label: "", render: (r) => <Button size="small" icon={<Play16Regular />} onClick={() => runTask(r)}>Run now</Button> },
        ]}
      />
      <div className="vy-panel-title" style={{ marginTop: 20 }}>Run history</div>
      <BrowseGrid resourceName="run" rowKey={(r) => r.name}
        items={runs.data || []} loading={runs.loading} error={runs.error} onRefresh={runs.reload}
        columns={[
          { key: "name", label: "Run ID" },
          { key: "task", label: "Task", value: (r) => r.properties?.taskName },
          { key: "status", label: "Status", value: (r) => r.properties?.status },
          { key: "startTime", label: "Started", value: (r) => fmtDate(r.properties?.startTime) },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Add task">
          <DialogBody>
            <DialogTitle>Add task</DialogTitle>
            <DialogContent><Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field></DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!/^[a-zA-Z0-9-_]{1,50}$/.test(name)} onClick={async () => {
                try { await api.putTask(a.resourceGroup, a.name, name, { properties: { status: "Enabled" } }); notify.success(`Task '${name}' was created.`, "Create succeeded"); setAdd(false); setName(""); tasks.reload(); }
                catch (e) { notify.error(e, "Create failed"); }
              }}>Add</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Cache — real pull-through cache rule definitions, Premium-gated and target-repository-
// uniqueness-validated server-side; Vyomi never actually fetches from the upstream registry
// (nothing leaves the simulator). ──────────────────────────────────────────────────────────
function CacheRules({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listCacheRules(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [source, setSource] = useState("docker.io/library/ubuntu");
  const [target, setTarget] = useState("ubuntu-cache");
  return (
    <CapabilityContainer id="azure.acr.cache" title="Cache">
      <BrowseGrid resourceName="cache rule" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteCacheRule(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} cache rule${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Rule name" },
          { key: "source", label: "Source", value: (r) => r.properties?.sourceRepository },
          { key: "target", label: "Target repository", value: (r) => r.properties?.targetRepository },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Add cache rule">
          <DialogBody>
            <DialogTitle>Add cache rule</DialogTitle>
            <DialogContent>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Field label="Rule name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Rule name" /></Field>
                <Field label="Source" required info="e.g. docker.io/library/ubuntu"><Input value={source} onChange={(_, d) => setSource(d.value)} aria-label="Source" /></Field>
                <Field label="Target repository" required><Input value={target} onChange={(_, d) => setTarget(d.value)} aria-label="Target repository" /></Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!name || !source || !target} onClick={async () => {
                try { await api.putCacheRule(a.resourceGroup, a.name, name, { properties: { sourceRepository: source, targetRepository: target } }); notify.success(`Cache rule '${name}' was created.`, "Create succeeded"); setAdd(false); setName(""); reload(); }
                catch (e) { notify.error(e, "Create failed"); }
              }}>Add</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Connected registries — real nested ARM resources; Vyomi runs no edge/offline sync agent,
// so content never actually replicates to one. ──────────────────────────────────────────────
function ConnectedRegistries({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listConnectedRegistries(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [mode, setMode] = useState("ReadOnly");
  return (
    <CapabilityContainer id="azure.acr.connectedregistries" title="Connected registries">
      <BrowseGrid resourceName="connected registry" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteConnectedRegistry(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} connected registr${sel.length === 1 ? "y" : "ies"}.`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" },
          { key: "mode", label: "Mode", value: (r) => r.properties?.mode },
          { key: "state", label: "Connection state", value: (r) => r.properties?.connectionState || "Offline" },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Add connected registry">
          <DialogBody>
            <DialogTitle>Add connected registry</DialogTitle>
            <DialogContent>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
                <Field label="Mode" required><Select value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Mode">
                  <option value="ReadOnly">Read only</option><option value="ReadWrite">Read write</option>
                </Select></Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!/^[a-zA-Z0-9-_]{1,50}$/.test(name)} onClick={async () => {
                try { await api.putConnectedRegistry(a.resourceGroup, a.name, name, { properties: { mode, connectionState: "Offline" } }); notify.success(`Connected registry '${name}' was created.`, "Create succeeded"); setAdd(false); setName(""); reload(); }
                catch (e) { notify.error(e, "Create failed"); }
              }}>Add</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Scope maps — real nested ARM resources; `actions` entries are validated server-side
// (AzureArm._acr_scope_action_valid: "<repository>:<content|metadata>/<read|write|delete>"). ──
function ScopeMaps({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listScopeMaps(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [actions, setActions] = useState("repo1:content/read,content/write");
  return (
    <CapabilityContainer id="azure.acr.scopemaps" title="Scope maps">
      <BrowseGrid resourceName="scope map" rowKey={(r) => r.name}
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteScopeMap(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} scope map${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" },
          { key: "actions", label: "Repository permissions", value: (r) => (r.properties?.actions || []).join("; ") },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Create scope map">
          <DialogBody>
            <DialogTitle>Create scope map</DialogTitle>
            <DialogContent>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Field label="Scope map name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Scope map name" /></Field>
                <Field label="Repository permissions" required info="One per line: <repository>:<content|metadata>/<read|write|delete>[,...]">
                  <Textarea value={actions} onChange={(_, d) => setActions(d.value)} rows={4} aria-label="Repository permissions" />
                </Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!name || !actions.trim()} onClick={async () => {
                try {
                  await api.putScopeMap(a.resourceGroup, a.name, name, { properties: { actions: actions.split("\n").map((s) => s.trim()).filter(Boolean) } });
                  notify.success(`Scope map '${name}' was created.`, "Create succeeded");
                  setAdd(false); setName(""); reload();
                } catch (e) { notify.error(e, "Create failed"); }
              }}>Create</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Tokens — real nested ARM resources; a token's scopeMapId must reference a real scope map
// on this registry (AzureArm._acr_validate_block) — not wired to the data-plane's own auth
// (same gap as admin user credentials, azure.acr.admin_credentials). ────────────────────────
function Tokens({ a }) {
  const notify = useNotify();
  const tokens = useAsync(() => api.listTokens(a.resourceGroup, a.name), [a.id]);
  const scopeMaps = useAsync(() => api.listScopeMaps(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [scopeMapId, setScopeMapId] = useState("");
  const sm = scopeMaps.data || [];
  return (
    <CapabilityContainer id="azure.acr.tokens" title="Tokens">
      <BrowseGrid resourceName="token" rowKey={(r) => r.name}
        items={tokens.data || []} loading={tokens.loading} error={tokens.error} onRefresh={tokens.reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => { setScopeMapId(sm[0]?.id || ""); setAdd(true); }}>Add</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteToken(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} token${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); tokens.reload(); }}
        columns={[
          { key: "name", label: "Name" },
          { key: "scopeMap", label: "Scope map", value: (r) => r.properties?.scopeMapId?.split("/").pop() },
          { key: "status", label: "Status", value: (r) => r.properties?.status || "enabled" },
        ]}
      />
      <Dialog open={add} onOpenChange={(_, d) => !d.open && setAdd(false)}>
        <DialogSurface aria-label="Create token">
          <DialogBody>
            <DialogTitle>Create token</DialogTitle>
            <DialogContent>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Field label="Token name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Token name" /></Field>
                <Field label="Scope map" required>
                  {sm.length ? (
                    <Select value={scopeMapId} onChange={(_, d) => setScopeMapId(d.value)} aria-label="Scope map">
                      {sm.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </Select>
                  ) : <p style={{ margin: 0, fontSize: 13 }} className="vy-muted">Create a scope map first.</p>}
                </Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!name || !scopeMapId} onClick={async () => {
                try {
                  await api.putToken(a.resourceGroup, a.name, name, { properties: { scopeMapId, status: "enabled" } });
                  notify.success(`Token '${name}' was created.`, "Create succeeded");
                  setAdd(false); setName(""); tokens.reload();
                } catch (e) { notify.error(e, "Create failed"); }
              }}>Create</Button>
              <Button onClick={() => setAdd(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Retention (Preview) — ENFORCED for real: once enabled, an untagged manifest is purged
// after it has gone untagged for longer than `days` (core/azure_acr_core.py's purge_untagged,
// swept on every data-plane call via core/aws_wire_router.py's x-vyomi-registry header) — not
// a stored setting nobody acts on. ───────────────────────────────────────────────────────────
function Retention({ a, reload }) {
  const notify = useNotify();
  const policy = a.properties?.policies?.retentionPolicy || { days: 7, status: "disabled" };
  const [days, setDays] = useState(policy.days);
  const [status, setStatus] = useState(policy.status);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDays(policy.days); setStatus(policy.status); }, [policy.days, policy.status]);
  const save = async () => {
    setBusy(true);
    try { await api.updateRetention(a.resourceGroup, a.name, { days: Number(days), status }); notify.success("Retention policy was saved.", "Save succeeded"); reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.acr.retention" title="Retention (Preview)">
      <p style={{ fontSize: 13, maxWidth: 680 }}>Enforced for real: an untagged manifest is purged once it has gone untagged for longer than the configured number of days.</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 420 }}>
        <Field label="Status"><RadioGroup value={status} onChange={(_, d) => setStatus(d.value)} aria-label="Status"><Radio value="enabled" label="Enabled" /><Radio value="disabled" label="Disabled" /></RadioGroup></Field>
        <Field label="Days (untagged manifests expire after)"><Input type="number" min={0} value={String(days)} onChange={(_, d) => setDays(d.value)} disabled={status !== "enabled"} aria-label="Days" /></Field>
      </div>
      <div className="vy-cmdbar" style={{ marginTop: 12 }}><Button appearance="primary" disabled={busy} onClick={save}>Save</Button></div>
    </CapabilityContainer>
  );
}
