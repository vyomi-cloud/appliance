/* Container registry resource blade: left resource menu + panels. Overview, Tags, Access
 * keys, Repositories (+ repository detail), Webhooks, Locks, Properties, Access control (IAM)
 * (Role assignments/Roles real; Deny assignments/Classic administrators honest), Diagnostic
 * settings and Export template (ARM/Bicep/Terraform) are backed by real native calls (ARM
 * control plane + the registry's own OCI/ACR REST data plane); everything else in the menu is
 * an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular, Eye16Regular, EyeOff16Regular } from "@fluentui/react-icons";
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
import * as api from "./api.js";
import { TagRows } from "../keyvaults/KeyVaultBlade.jsx";
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
// Blade menu items with no detail captured in the spec beyond their title fall under the
// shared "tools" capability id (core/capabilities/azure/acr.json) — never a hand-written
// disclaimer. Diagnostic settings is wired for real (azure.acr.monitoring); the other
// Monitoring-group items (Insights, Alerts, Metrics, Logs) stay an explicit honest gap.

export default function RegistryBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const reg = useAsync(() => api.getRegistry(rg, name), [rg, name]);
  const self = `#/acr/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (reg.data) remember({ name, type: "Container registry", href: self }); }, [!!reg.data, self]);

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
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{LABEL[panel] || panel}</div>
        <CapabilityContainer id="azure.acr.tools" title={LABEL[panel] || panel} />
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
      {tab === "monitoring" && <CapabilityContainer id="azure.acr.overview_tabs" title="Monitoring" />}
      {tab === "properties" && <PropertyList a={a} />}
      {tab === "capabilities" && <CapabilityContainer id="azure.acr.overview_tabs" title="Capabilities" />}
      {tab === "recommendations" && <CapabilityContainer id="azure.acr.overview_tabs" title="Recommendations" />}

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
