/* Service Bus namespace resource blade: left resource menu + panels. Overview, Activity log,
 * Tags, Shared access policies, Scale, Locks, Queues, Topics, Properties and Export template
 * are backed by native ARM calls (+ the Service Bus data plane for queue message counts);
 * everything else in the menu renders its honest capability level via CapabilityContainer
 * (core/capabilities/azure/servicebus.json — never a hand-written disclaimer). */
import { useEffect, useMemo, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList,
  Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular, Save20Regular } from "@fluentui/react-icons";
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
  { id: "events", label: "Events" },
  { group: "Settings", items: [
    { id: "saspolicies", label: "Shared access policies" },
    { id: "scale", label: "Scale" },
    { id: "georecovery", label: "Geo-Recovery" },
    { id: "networking", label: "Networking" },
    { id: "encryption", label: "Encryption" },
    { id: "identity", label: "Identity" },
    { id: "properties", label: "Properties" },
    { id: "locks", label: "Locks" },
  ] },
  { group: "Entities", items: [
    { id: "queues", label: "Queues" },
    { id: "topics", label: "Topics" },
  ] },
  { group: "Monitoring", items: [
    { id: "insights", label: "Insights" },
    { id: "alerts", label: "Alerts" },
    { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" },
    { id: "logs", label: "Logs" },
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
// Panels with no built handler below render their honest capability level (always
// not_simulated for these — core/capabilities/azure/servicebus.json).
const CAP_FOR_PANEL = {
  diagnose: "azure.servicebus.namespace.tools", events: "azure.servicebus.namespace.tools",
  tasks: "azure.servicebus.namespace.tools", resourcehealth: "azure.servicebus.namespace.tools",
  support: "azure.servicebus.namespace.tools",
  networking: "azure.servicebus.namespace.networking", encryption: "azure.servicebus.namespace.encryption",
  insights: "azure.servicebus.namespace.monitoring", metrics: "azure.servicebus.namespace.monitoring",
};

export default function NamespaceBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const ns = useAsync(() => api.getNamespace(rg, name), [rg, name]);
  const self = `#/servicebus/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (ns.data) remember({ name, type: "Service Bus namespace", href: self }); }, [!!ns.data, self]);

  let body;
  if (ns.loading && !ns.data) body = <Loading />;
  else if (ns.error) body = <><ErrorBar error={ns.error} title="Failed to load the namespace" /><Link href="#/servicebus">Back to Service Bus</Link></>;
  else {
    const a = ns.data, reload = ns.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog a={a} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      saspolicies: () => <SasPolicies a={a} />,
      scale: () => <Scale a={a} reload={reload} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      queues: () => <Queues a={a} self={self} />,
      topics: () => <Topics a={a} self={self} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      identity: () => <Identity a={a} reload={reload} />,
      diagnosticsettings: () => <DiagnosticSettings a={a} />,
      alerts: () => <Alerts a={a} />,
      logs: () => <LogsPanel a={a} />,
      georecovery: () => <GeoRecovery a={a} reload={reload} />,
    }[panel];
    body = P ? P() : <CapabilityContainer id={CAP_FOR_PANEL[panel] || "azure.servicebus.namespace.tools"} title={`${a.name} | ${LABEL[panel] || panel}`} />;
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Service Bus Namespace" glyph={<Glyph id="servicebus" />} closeHref="#/servicebus"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── shared: queue/topic rows with real message counts over the data plane ──────────────
function useQueueRows(rg, ns) {
  return useAsync(async () => {
    const queues = await api.listQueues(rg, ns);
    return Promise.all(queues.map(async (qr) => {
      const name = qr.name;
      const [active, dead] = await Promise.all([
        api.peekMessages(name).catch(() => []),
        api.peekDeadLetter(name).catch(() => []),
      ]);
      return { ...qr, _active: active.length, _dead: dead.length };
    }));
  }, [rg, ns]);
}
function useTopicRows(rg, ns) {
  return useAsync(() => api.listTopics(rg, ns), [rg, ns]);
}

const fmtSize = (mb) => (mb >= 1024 && mb % 1024 === 0 ? `${mb / 1024} GB` : `${mb || 0} MB`);

function MiniTable({ columns, rows, empty }) {
  return (
    <table className="vy-grid" style={{ marginTop: 8 }}>
      <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>
        {rows.length ? rows : <tr><td colSpan={columns.length} className="vy-muted">{empty}</td></tr>}
      </tbody>
    </table>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [tab, setTab] = useState("queues");
  const [del, setDel] = useState(false);
  const [createQ, setCreateQ] = useState(false);
  const [createT, setCreateT] = useState(false);
  const p = a.properties || {};
  const qrows = useQueueRows(a.resourceGroup, a.name);
  const trows = useTopicRows(a.resourceGroup, a.name);
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setCreateQ(true)}>Queue</ToolbarButton>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setCreateT(true)}>Topic</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); qrows.reload(); trows.reload(); }}>Refresh</ToolbarButton>
        <ToolbarButton>Feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Status", p.status || "Active"],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Host name", `${a.name}.servicebus.windows.net`],
          ["Pricing tier", api.skuLabel(a.sku)],
          ["Created", fmtDate(a.systemData?.createdAt)],
          ["Updated", fmtDate(a.systemData?.lastModifiedAt)],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="queues">Queues</Tab>
        <Tab value="topics">Topics</Tab>
      </TabList>
      {tab === "queues" && (
        <section className="vy-section" style={{ marginTop: 12 }}><h3>Queues</h3>
          <MiniTable columns={["Name", "Status", "Max size", "Active message count", "Dead-letter message count"]} empty="No queues"
            rows={(qrows.data || []).map((r) => (
              <tr key={r.name}>
                <td><Link href={`${self}/queues/${encodeURIComponent(r.name)}`}>{r.name}</Link></td>
                <td>{r.properties?.status || "Active"}</td>
                <td>{fmtSize(r.properties?.maxSizeInMegabytes)}</td>
                <td>{r._active}</td>
                <td>{r._dead}</td>
              </tr>
            ))}
          />
        </section>
      )}
      {tab === "topics" && (
        <section className="vy-section" style={{ marginTop: 12 }}><h3>Topics</h3>
          <MiniTable columns={["Name", "Status", "Max size", "Subscription count"]} empty="No topics"
            rows={(trows.data || []).map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>{r.properties?.status || "Active"}</td>
                <td>{fmtSize(r.properties?.maxSizeInMegabytes)}</td>
                <td>0</td>
              </tr>
            ))}
          />
        </section>
      )}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="namespace" names={[a.name]}
        onConfirm={async () => {
          await api.deleteNamespace(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Namespace '${a.name}' was deleted.`, "Delete succeeded");
          navigate("servicebus");
        }} />
      <CreateQueueDialog open={createQ} onClose={() => setCreateQ(false)} a={a} onCreated={() => qrows.reload()} />
      <CreateTopicDialog open={createT} onClose={() => setCreateT(false)} a={a} onCreated={() => trows.reload()} />
    </>
  );
}

// ── Access control (IAM): Role assignments / Roles / Check access are real ARM reads and a
// real decision call scoped to this namespace (plus its subscription/resource-group
// ancestors); Deny assignments and Classic administrators stay honest — same pattern as
// consoles/src/azure/services/nsgs/NsgBlade.jsx — core/capabilities/azure/servicebus.json
// azure.servicebus.namespace.iam. ────────────────────────────────────────────────────────
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  const [principal, setPrincipal] = useState("");
  const [action, setAction] = useState("Microsoft.ServiceBus/namespaces/write");
  const [decision, setDecision] = useState(null);
  const roleAssignments = useAsync(() => api.listRoleAssignments(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const roleDefinitions = useAsync(() => api.listRoleDefinitions(), []);
  return (
    <CapabilityContainer id="azure.servicebus.namespace.iam" title="Access control (IAM)">
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
            <Button onClick={() => { setDecision(null); setDlg("check"); }}>Check access</Button>
          </section>
        </div>
      )}
      {tab === "assignments" && (
        <section className="vy-section" style={{ marginTop: 12 }}>
          <BrowseGrid resourceName="role assignment" rowKey={(r) => r.id} filterPlaceholder="Search by name or email"
            items={roleAssignments.data || []} loading={roleAssignments.loading} error={roleAssignments.error} onRefresh={roleAssignments.reload}
            columns={[
              { key: "name", label: "Name", value: (r) => r.properties?.principalId },
              { key: "type", label: "Type", value: (r) => r.properties?.principalType || "--" },
              { key: "role", label: "Role", value: (r) => r.properties?.roleName || (r.properties?.roleDefinitionId || "").split("/").pop() },
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
      {tab === "deny" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Deny assignments" feature="Deny assignments" /></div>}
      {tab === "classic" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Classic administrators" feature="Classic administrators" /></div>}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access check">
          <DialogBody>
            <DialogTitle>{dlg === "mine" ? "My access" : "Check access"}</DialogTitle>
            <DialogContent>
              {dlg === "mine" ? (
                <NotSimulated feature="Per-identity 'my access' resolution" note="Vyomi has no signed-in identity to resolve — use Check access with a principal id instead." />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 360 }}>
                  <Field label="Find"><Input value={principal} onChange={(_, d) => setPrincipal(d.value)} placeholder="Principal (object) id" aria-label="Principal ID" /></Field>
                  <Field label="Action"><Input value={action} onChange={(_, d) => setAction(d.value)} aria-label="Action" /></Field>
                  <Button appearance="primary" disabled={!principal} onClick={async () => {
                    const [r] = await api.checkAccess(a.id, principal, action);
                    setDecision(r);
                  }}>Check access</Button>
                  {decision && (
                    <section className="vy-section">
                      <b>{decision.accessDecision}</b>
                      {decision.roles?.length > 0 && <div>Granted by: {decision.roles.join(", ")}</div>}
                    </section>
                  )}
                </div>
              )}
            </DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
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
      await api.createNamespace(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
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

// ── Shared access policies (Microsoft.ServiceBus/namespaces/authorizationRules) ────────
function SasPolicies({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listSasPolicies(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [sel, setSel] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Shared access policies</div>
      <BrowseGrid
        resourceName="policy" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (xs) => { for (const r of xs) await api.deleteSasPolicy(a.resourceGroup, a.name, r.name); reload(); }}
        csvName="sas-policies.csv"
        columns={[
          { key: "policy", label: "Policy", render: (r) => <Link as="button" onClick={() => setSel(r.name)}>{r.name}</Link> },
          { key: "claims", label: "Claims", value: (r) => (r.properties?.rights || []).join(", ") },
        ]}
      />
      <AddSasPolicyDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, rights) => { await api.putSasPolicy(a.resourceGroup, a.name, name, rights); reload(); }} />
      <SasPolicyDialog name={sel} a={a} onClose={() => setSel(null)} />
    </>
  );
}

function AddSasPolicyDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [rights, setRights] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const toggle = (r) => setRights((s) => { const n = new Set(s); n.has(r) ? n.delete(r) : n.add(r); return n; });
  const valid = /^[a-zA-Z0-9._-]{1,50}$/.test(name) && rights.size > 0;
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name, [...rights]);
      notify.success(`SAS policy '${name}' was created.`, "Policy created");
      setName(""); setRights(new Set()); onClose();
    } catch (e) { notify.error(e, "Failed to create policy"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add SAS Policy">
        <DialogBody>
          <DialogTitle>Add SAS Policy</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Policy name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Policy name" /></Field>
              <Checkbox label="Manage" checked={rights.has("Manage")} onChange={() => toggle("Manage")} />
              <Checkbox label="Send" checked={rights.has("Send")} onChange={() => toggle("Send")} />
              <Checkbox label="Listen" checked={rights.has("Listen")} onChange={() => toggle("Listen")} />
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

function SasPolicyDialog({ name, a, onClose }) {
  const { data } = useAsync(async () => (name ? api.listSasKeys(a.resourceGroup, a.name, name) : null), [name]);
  if (!name) return null;
  const keys = data?.keys || [];
  const primary = keys[0]?.value || "", secondary = keys[1]?.value || "";
  return (
    <Dialog open={!!name} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="SAS Policy">
        <DialogBody>
          <DialogTitle>{name}</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Primary Key"><Input readOnly value={primary} aria-label="Primary Key" /></Field>
              <Field label="Secondary Key"><Input readOnly value={secondary} aria-label="Secondary Key" /></Field>
              <Field label="Primary Connection String"><Input readOnly value={api.sasConnectionString(a.name, name, primary)} aria-label="Primary Connection String" /></Field>
              <Field label="Secondary Connection String"><Input readOnly value={api.sasConnectionString(a.name, name, secondary)} aria-label="Secondary Connection String" /></Field>
            </div>
          </DialogContent>
          <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Scale ──────────────────────────────────────────────────────────────────────────────
function Scale({ a, reload }) {
  const notify = useNotify();
  const [tier, setTier] = useState(api.skuLabel(a.sku));
  const [busy, setBusy] = useState(false);
  useEffect(() => setTier(api.skuLabel(a.sku)), [a]);
  const dirty = tier !== api.skuLabel(a.sku);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateNamespace(a.resourceGroup, a.name, { sku: { name: tier, tier } });
      notify.success(`Scale for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving scale failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Scale</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Scale commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setTier(api.skuLabel(a.sku))}>Discard</ToolbarButton>
      </div>
      <CapabilityContainer id="azure.servicebus.namespace.scale" title="Scale">
        <RadioGroup value={tier} onChange={(_, d) => setTier(d.value)} aria-label="Pricing tier">
          <Radio value="Basic" label="Basic" />
          <Radio value="Standard" label="Standard" />
          <Radio value="Premium" label="Premium" />
        </RadioGroup>
      </CapabilityContainer>
    </>
  );
}

// ── Properties ─────────────────────────────────────────────────────────────────────────
function Properties({ a }) {
  const p = a.properties || {};
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <div className="vy-props">
        <KV label="Name" value={a.name} />
        <KV label="Status" value={p.status || "Active"} />
        <KV label="Pricing tier" value={api.skuLabel(a.sku)} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="Host name" value={`${a.name}.servicebus.windows.net`} />
        <KV label="Resource ID" value={a.id} />
        <KV label="Created" value={fmtDate(a.systemData?.createdAt)} />
        <KV label="Updated" value={fmtDate(a.systemData?.lastModifiedAt)} />
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this namespace) ───────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [scopeView, setScopeView] = useState(null); // "subscription" | "resourcegroup" | null
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <CapabilityContainer id="azure.servicebus.namespace.locks" title="Locks">
        <BrowseGrid
          resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
          items={rows} loading={loading} error={error} onRefresh={reload}
          extraCommands={<>
            <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
            <ToolbarButton onClick={() => setScopeView("subscription")}>Subscription</ToolbarButton>
            <ToolbarButton onClick={() => setScopeView("resourcegroup")}>Resource group</ToolbarButton>
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
      <ScopeLocksDialog scope={scopeView} a={a} onClose={() => setScopeView(null)} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature="Sending product feedback" /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// Locks' "Subscription" / "Resource group" scope-switcher buttons — real locks at that wider
// scope (the SAME Microsoft.Authorization/locks engine the Subscription/Resource group
// blades' own Locks panels use), read-only here since they're managed from those blades.
function ScopeLocksDialog({ scope, a, onClose }) {
  const { data, loading, error } = useAsync(
    () => (scope === "subscription" ? api.listLocksAtSubscription() : scope === "resourcegroup" ? api.listLocksAtResourceGroup(a.resourceGroup) : null),
    [scope, a.resourceGroup],
  );
  if (!scope) return null;
  const rows = data || [];
  return (
    <Dialog open={!!scope} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={scope === "subscription" ? "Subscription locks" : "Resource group locks"}>
        <DialogBody>
          <DialogTitle>{scope === "subscription" ? "Subscription locks" : "Resource group locks"}</DialogTitle>
          <DialogContent>
            <ErrorBar error={error} />
            {loading ? <Loading /> : (
              <table className="vy-grid">
                <thead><tr><th>Lock name</th><th>Lock type</th><th>Notes</th></tr></thead>
                <tbody>
                  {rows.length ? rows.map((r) => (
                    <tr key={r.name}><td>{r.name}</td><td>{r.properties?.level === "ReadOnly" ? "Read-only" : "Delete"}</td><td>{r.properties?.notes || "--"}</td></tr>
                  )) : <tr><td colSpan={3} className="vy-muted">No locks to display</td></tr>}
                </tbody>
              </table>
            )}
          </DialogContent>
          <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
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

// ── Queues ─────────────────────────────────────────────────────────────────────────────
function Queues({ a, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useQueueRows(a.resourceGroup, a.name);
  const [create, setCreate] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Queues</div>
      <BrowseGrid
        resourceName="queue" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setCreate(true)}>Queue</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) { await api.deleteQueueArm(a.resourceGroup, a.name, r.name); await api.deleteQueueEntity(r.name); }
          notify.success(`Deleted ${sel.length} queue${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="queues.csv"
        columns={[
          { key: "name", label: "Name", render: (r) => <Link href={`${self}/queues/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
          { key: "status", label: "Status", value: (r) => r.properties?.status || "Active" },
          { key: "maxSize", label: "Max size", value: (r) => fmtSize(r.properties?.maxSizeInMegabytes) },
          { key: "active", label: "Active message count", value: (r) => r._active },
          { key: "dead", label: "Dead-letter message count", value: (r) => r._dead },
          { key: "scheduled", label: "Scheduled message count", value: () => 0 },
        ]}
        emptyAction={<Link as="button" onClick={() => setCreate(true)}>Create queue</Link>}
      />
      <CreateQueueDialog open={create} onClose={() => setCreate(false)} a={a} onCreated={reload} />
    </>
  );
}

function CreateQueueDialog({ open, onClose, a, onCreated }) {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", maxSizeGb: "1", maxDeliveryCount: "10", ttlValue: "14", ttlUnit: "Days", lockValue: "30", lockUnit: "Seconds", autoDelete: false, duplicateDetection: false, deadLetterOnExpiry: false, partitioning: false, sessions: false, forwarding: false });
  const [busy, setBusy] = useState(false);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const valid = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,259}$/.test(f.name);
  const go = async () => {
    setBusy(true);
    try {
      const body = api.queueArmBody(f);
      body.properties.status = "Active";
      await api.putQueueArm(a.resourceGroup, a.name, f.name, body);
      await api.createQueueEntity(f.name);
      notify.success(`Queue '${f.name}' was created.`, "Create succeeded");
      setF((x) => ({ ...x, name: "" })); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create queue"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create queue">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create queue</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.name} onChange={set("name")} aria-label="Name" /></Field>
              <Field label="Max queue size">
                <Select value={`${f.maxSizeGb} GB`} onChange={(_, d) => setF((x) => ({ ...x, maxSizeGb: d.value.split(" ")[0] }))} aria-label="Max queue size">
                  {["1 GB", "2 GB", "3 GB", "4 GB", "5 GB"].map((o) => <option key={o}>{o}</option>)}
                </Select>
              </Field>
              <Field label="Max delivery count"><Input type="number" min={1} max={2000} value={f.maxDeliveryCount} onChange={set("maxDeliveryCount")} aria-label="Max delivery count" /></Field>
              <Field label="Message time to live">
                <div style={{ display: "flex", gap: 6 }}>
                  <Input type="number" min={0} style={{ width: 90 }} value={f.ttlValue} onChange={set("ttlValue")} aria-label="Message time to live value" />
                  <Select value={f.ttlUnit} onChange={set("ttlUnit")} aria-label="Message time to live unit">
                    {["Days", "Hours", "Minutes", "Seconds"].map((u) => <option key={u}>{u}</option>)}
                  </Select>
                </div>
              </Field>
              <Field label="Lock duration">
                <div style={{ display: "flex", gap: 6 }}>
                  <Input type="number" min={0} style={{ width: 90 }} value={f.lockValue} onChange={set("lockValue")} aria-label="Lock duration value" />
                  <Select value={f.lockUnit} onChange={set("lockUnit")} aria-label="Lock duration unit">
                    {["Days", "Hours", "Minutes", "Seconds"].map((u) => <option key={u}>{u}</option>)}
                  </Select>
                </div>
              </Field>
              <Checkbox label="Enable auto-delete on idle queue" checked={f.autoDelete} onChange={chk("autoDelete")} />
              <Checkbox label="Enable duplicate detection" checked={f.duplicateDetection} onChange={chk("duplicateDetection")} />
              <Checkbox label="Enable dead lettering on message expiration" checked={f.deadLetterOnExpiry} onChange={chk("deadLetterOnExpiry")} />
              <Checkbox label="Enable partitioning" checked={f.partitioning} onChange={chk("partitioning")} />
              <Checkbox label="Enable sessions" checked={f.sessions} onChange={chk("sessions")} />
              <Checkbox label="Forward messages to queue/topic" checked={f.forwarding} onChange={chk("forwarding")} />
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

// ── Topics ─────────────────────────────────────────────────────────────────────────────
function Topics({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useTopicRows(a.resourceGroup, a.name);
  const [create, setCreate] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Topics</div>
      <BrowseGrid
        resourceName="topic" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setCreate(true)}>Topic</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteTopicArm(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} topic${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="topics.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status", value: (r) => r.properties?.status || "Active" },
          { key: "maxSize", label: "Max size", value: (r) => fmtSize(r.properties?.maxSizeInMegabytes) },
          { key: "subs", label: "Subscription count", value: () => 0 },
        ]}
        emptyAction={<Link as="button" onClick={() => setCreate(true)}>Create topic</Link>}
      />
      <CreateTopicDialog open={create} onClose={() => setCreate(false)} a={a} onCreated={reload} />
    </>
  );
}

function CreateTopicDialog({ open, onClose, a, onCreated }) {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", maxSizeGb: "1", ttlValue: "14", ttlUnit: "Days", autoDelete: false, duplicateDetection: false, partitioning: false, ordering: false });
  const [busy, setBusy] = useState(false);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const valid = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,259}$/.test(f.name);
  const go = async () => {
    setBusy(true);
    try {
      const body = api.topicArmBody(f);
      body.properties.status = "Active";
      await api.putTopicArm(a.resourceGroup, a.name, f.name, body);
      notify.success(`Topic '${f.name}' was created.`, "Create succeeded");
      setF((x) => ({ ...x, name: "" })); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create topic"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create topic">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create topic</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.name} onChange={set("name")} aria-label="Name" /></Field>
              <Field label="Max topic size">
                <Select value={`${f.maxSizeGb} GB`} onChange={(_, d) => setF((x) => ({ ...x, maxSizeGb: d.value.split(" ")[0] }))} aria-label="Max topic size">
                  {["1 GB", "2 GB", "3 GB", "4 GB", "5 GB"].map((o) => <option key={o}>{o}</option>)}
                </Select>
              </Field>
              <Field label="Message time to live">
                <div style={{ display: "flex", gap: 6 }}>
                  <Input type="number" min={0} style={{ width: 90 }} value={f.ttlValue} onChange={set("ttlValue")} aria-label="Message time to live value" />
                  <Select value={f.ttlUnit} onChange={set("ttlUnit")} aria-label="Message time to live unit">
                    {["Days", "Hours", "Minutes", "Seconds"].map((u) => <option key={u}>{u}</option>)}
                  </Select>
                </div>
              </Field>
              <Checkbox label="Enable auto-delete on idle topic" checked={f.autoDelete} onChange={chk("autoDelete")} />
              <Checkbox label="Enable duplicate detection" checked={f.duplicateDetection} onChange={chk("duplicateDetection")} />
              <Checkbox label="Enable partitioning" checked={f.partitioning} onChange={chk("partitioning")} />
              <Checkbox label="Support ordering" checked={f.ordering} onChange={chk("ordering")} />
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

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this namespace) ──
// Edit columns / Download as CSV / Reset filters are real (client-side over the rows the
// real ARM activity-log read returned, like the Locks panel's BrowseGrid toolbar above) —
// only the actions that need a separate Azure product (Insights workbook, portal telemetry,
// dashboard pinning) or a per-event detail flyout stay an honest "Not simulated" gap.
const ACTIVITY_LOG_COLUMNS = [
  { key: "operationName", label: "Operation name", value: (r) => r.operationName?.localizedValue || r.operationName?.value, csv: (r) => r.operationName?.value },
  { key: "status", label: "Status", value: (r) => r.status?.localizedValue || r.status?.value, csv: (r) => r.status?.value },
  { key: "time", label: "Time", value: (r) => fmtDate(r.eventTimestamp) },
  { key: "timestamp", label: "Time stamp", value: (r) => r.eventTimestamp },
  { key: "subscription", label: "Subscription", value: (r) => r.subscriptionId },
  { key: "caller", label: "Event initiated by", value: (r) => r.caller },
];

function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const [gap, setGap] = useState(null);
  const [filter, setFilter] = useState("");
  const [visible, setVisible] = useState(() => new Set(ACTIVITY_LOG_COLUMNS.map((c) => c.key)));
  const [editCols, setEditCols] = useState(false);
  const rows = data || [];
  const shownCols = ACTIVITY_LOG_COLUMNS.filter((c) => visible.has(c.key));
  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return rows;
    return rows.filter((r) => ACTIVITY_LOG_COLUMNS.some((c) => String(c.value(r) ?? "").toLowerCase().includes(f)));
  }, [rows, filter]);
  return (
    <CapabilityContainer id="azure.servicebus.namespace.activitylog" title={`${a.name} | Activity log`}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton onClick={() => setGap("Activity")}>Activity</ToolbarButton>
        <ToolbarButton onClick={() => setEditCols(true)}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!filtered.length}
          onClick={() => downloadCsv("activity-log.csv", shownCols, filtered)}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Insights")}>Insights</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Pin current filters")}>Pin current filters</ToolbarButton>
        <ToolbarButton onClick={() => setFilter("")}>Reset filters</ToolbarButton>
      </div>
      <div className="vy-filters">
        <Input size="small" style={{ width: 280 }} placeholder="Filter by operation, status or caller..."
          value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter by operation, status or caller..." />
      </div>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr>{shownCols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={shownCols.length || 1}><Spinner size="tiny" /></td></tr> : filtered.length ? filtered.map((r) => (
            <tr key={r.id}>{shownCols.map((c) => <td key={c.key}>{c.value(r)}</td>)}</tr>
          )) : <tr><td colSpan={shownCols.length || 1} className="vy-muted">No events to display</td></tr>}
        </tbody>
      </table>
      <Dialog open={editCols} onOpenChange={(_, d) => setEditCols(d.open)}>
        <DialogSurface aria-label="Edit columns">
          <DialogBody>
            <DialogTitle>Edit columns</DialogTitle>
            <DialogContent>
              {ACTIVITY_LOG_COLUMNS.map((c) => (
                <div key={c.key}><Checkbox label={c.label} checked={visible.has(c.key)}
                  onChange={(_, d) => setVisible((v) => { const n = new Set(v); d.checked ? n.add(c.key) : n.delete(c.key); return n; })} /></div>
              ))}
            </DialogContent>
            <DialogActions><Button appearance="primary" onClick={() => setEditCols(false)}>Save</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody><CapabilityContainer id="azure.servicebus.namespace.listactions" title={gap || ""} /></DialogBody>
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
    ...(params ? { parameters: { namespaceName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.ServiceBus/namespaces", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('namespaceName')]" : a.name, location: a.location, sku: a.sku, properties: a.properties }],
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
      <CapabilityContainer id="azure.servicebus.namespace.exporttemplate" title="Template">
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        {tab === "arm" && <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
        {tab !== "arm" && <NotSimulatedContainer feature={`${tab === "bicep" ? "Bicep" : "Terraform"} template export`} />}
      </CapabilityContainer>
    </>
  );
}

// ── Identity: system-assigned managed identity, the same generic ARM identity merge every
// lens resource's PUT/PATCH can carry (core/azure_arm_core.py "18. Generic top-level
// 'identity' block") — core/capabilities/azure/servicebus.json azure.servicebus.namespace.identity.
function Identity({ a, reload }) {
  const notify = useNotify();
  const [on, setOn] = useState(a.identity?.type === "SystemAssigned");
  const [busy, setBusy] = useState(false);
  useEffect(() => setOn(a.identity?.type === "SystemAssigned"), [a]);
  const dirty = on !== (a.identity?.type === "SystemAssigned");
  const save = async () => {
    setBusy(true);
    try {
      await api.updateNamespace(a.resourceGroup, a.name, { identity: on ? { type: "SystemAssigned" } : { type: "None" } });
      notify.success("Identity settings saved.", "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Saving identity failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.servicebus.namespace.identity" title={`${a.name} | Identity`} actions={<>
      <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
      <ToolbarButton disabled={!dirty} onClick={() => setOn(a.identity?.type === "SystemAssigned")}>Discard</ToolbarButton>
    </>}>
      <TabList selectedValue="system" aria-label="Identity tabs">
        <Tab value="system">System assigned</Tab>
        <Tab value="user">User assigned</Tab>
      </TabList>
      <div style={{ marginTop: 12 }}>
        <Field label="Status">
          <RadioGroup layout="horizontal" value={on ? "On" : "Off"} onChange={(_, d) => setOn(d.value === "On")} aria-label="Status">
            <Radio value="Off" label="Off" /><Radio value="On" label="On" />
          </RadioGroup>
        </Field>
        {on && a.identity?.principalId && <p style={{ fontSize: 13 }}>Object (principal) ID: <code>{a.identity.principalId}</code></p>}
      </div>
    </CapabilityContainer>
  );
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, scoped to this namespace) ──
// Clone of consoles/src/azure/services/apim/DiagnosticSettings.jsx's pattern — the SAME
// generic extension-resource mechanism any lens resource's Diagnostic settings blade uses.
const DIAG_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;
function DiagnosticSettings({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDiagnosticSettings(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const ws = workspaces.data || [];
  return (
    <CapabilityContainer id="azure.servicebus.namespace.diagnosticsettings" title={`${a.name} | Diagnostic settings`}>
      <BrowseGrid
        resourceName="diagnostic setting" rowKey={(r) => r.name} filterPlaceholder="Search diagnostic settings"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => { setAdd(true); setWorkspace(ws[0]?.id || ""); }}>Add diagnostic setting</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteDiagnosticSetting(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} diagnostic setting${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="diagnostic-settings.csv"
        columns={[
          { key: "name", label: "Diagnostic setting name" },
          { key: "dest", label: "Destination details", value: (r) => r.properties?.workspaceId ? "Log Analytics workspace" : r.properties?.storageAccountId ? "Storage account" : r.properties?.eventHubAuthorizationRuleId ? "Event hub" : "--" },
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
              await api.putDiagnosticSetting(a.resourceGroup, a.name, name, {
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

// ── Alert rules (Microsoft.Insights/metricAlerts, filtered to properties.scopes containing
// this namespace's id) — the rule round-trips exactly as configured and ENABLED/disabled is
// real, but nothing evaluates it (no metrics pipeline), so it never fires — see
// core/capabilities/azure/servicebus.json azure.servicebus.namespace.alerts. ───────────────
const ALERT_NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._ ]{0,254}$/;
function Alerts({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listAlertsForNamespace(a.resourceGroup, a.id), [a.resourceGroup, a.id]);
  const [add, setAdd] = useState(false);
  const [f, setF] = useState({ name: "", metric: api.ALERT_METRICS[0], operator: "GreaterThan", threshold: "0", severity: "3" });
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.servicebus.namespace.alerts" title={`${a.name} | Alerts`}>
      <BrowseGrid
        resourceName="alert rule" rowKey={(r) => r.id} filterPlaceholder="Search alert rules"
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>New alert rule</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteAlert(a.resourceGroup, r.name);
          notify.success(`Deleted ${sel.length} alert rule${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="alert-rules.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "condition", label: "Condition", value: (r) => { const c = (r.properties?.criteria?.allOf || [])[0]; return c ? `${c.metricName} ${c.operator} ${c.threshold}` : "--"; } },
          { key: "severity", label: "Severity", value: (r) => r.properties?.severity },
          { key: "status", label: "Status", value: (r) => r.properties?.enabled ? "Enabled" : "Disabled" },
        ]}
      />
      {add && (
        <section className="vy-section" style={{ marginTop: 16 }}>
          <h3>Create alert rule</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 480 }}>
            <Field label="Alert rule name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Alert rule name" /></Field>
            <Field label="Signal (metric)">
              <Select value={f.metric} onChange={(_, d) => setF((x) => ({ ...x, metric: d.value }))} aria-label="Signal">
                {api.ALERT_METRICS.map((m) => <option key={m}>{m}</option>)}
              </Select>
            </Field>
            <Field label="Operator">
              <Select value={f.operator} onChange={(_, d) => setF((x) => ({ ...x, operator: d.value }))} aria-label="Operator">
                {api.ALERT_OPERATORS.map((o) => <option key={o}>{o}</option>)}
              </Select>
            </Field>
            <Field label="Threshold value"><Input type="number" value={f.threshold} onChange={(_, d) => setF((x) => ({ ...x, threshold: d.value }))} aria-label="Threshold value" /></Field>
            <Field label="Severity">
              <Select value={f.severity} onChange={(_, d) => setF((x) => ({ ...x, severity: d.value }))} aria-label="Severity">
                {[0, 1, 2, 3, 4].map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
            </Field>
          </div>
          <div className="vy-cmdbar" style={{ marginTop: 12 }}>
            <Button appearance="primary" disabled={!ALERT_NAME_RE.test(f.name)} onClick={async () => {
              await api.putAlert(a.resourceGroup, f.name, {
                location: "global",
                properties: {
                  severity: Number(f.severity), enabled: true, scopes: [a.id],
                  evaluationFrequency: "PT5M", windowSize: "PT15M",
                  criteria: {
                    "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
                    allOf: [{ name: "1", metricName: f.metric, metricNamespace: "Microsoft.ServiceBus/namespaces",
                             operator: f.operator, threshold: Number(f.threshold) || 0, timeAggregation: "Average" }],
                  },
                },
              });
              notify.success(`Alert rule '${f.name}' was created.`, "Create succeeded");
              setAdd(false); setF((x) => ({ ...x, name: "" })); reload();
            }}>Create alert rule</Button>
            <Button onClick={() => setAdd(false)}>Cancel</Button>
          </div>
        </section>
      )}
    </CapabilityContainer>
  );
}

// ── Logs: a Log Analytics query scoped to this namespace, defaulted to its own AzureActivity
// rows — the real "Logs" blade on any Azure resource opens the same query editor with the
// resource as context (core/capabilities/azure/servicebus.json azure.servicebus.namespace.logs). ──
function LogsPanel({ a }) {
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [workspace, setWorkspace] = useState("");
  const [query, setQuery] = useState(`AzureActivity\n| where ResourceId == "${a.id}"\n| take 20`);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);
  const ws = workspaces.data || [];
  useEffect(() => { if (ws.length && !workspace) setWorkspace(ws[0].id); }, [ws.length]);
  const run = async () => {
    const w = ws.find((x) => x.id === workspace);
    if (!w) return;
    setRunning(true); setError(null);
    try { setResult(await api.runLogQuery(w.resourceGroup, w.name, query)); }
    catch (e) { setError(e); setResult(null); }
    finally { setRunning(false); }
  };
  const table = result?.tables?.[0];
  return (
    <CapabilityContainer id="azure.servicebus.namespace.logs" title={`${a.name} | Logs`}>
      {workspaces.loading ? <Loading /> : !ws.length ? (
        <p>No Log Analytics workspace yet. <Link href="#/loganalytics">Create one</Link> first, then add it as a Diagnostic setting destination.</p>
      ) : (
        <>
          <Field label="Scope">
            <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
              {ws.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <Textarea value={query} onChange={(_, d) => setQuery(d.value)} rows={4} resize="vertical"
            style={{ width: "100%", fontFamily: "monospace", marginTop: 8 }} aria-label="KQL query" />
          <div className="vy-cmdbar" role="toolbar" aria-label="Logs commands" style={{ marginTop: 8 }}>
            <Button appearance="primary" disabled={running || !workspace} onClick={run}>Run</Button>
          </div>
          <ErrorBar error={error} title="Query failed" />
          {table && (table.rows.length ? (
            <Table size="small" aria-label="Query results">
              <TableHeader><TableRow>{table.columns.map((c) => <TableHeaderCell key={c.name}>{c.name}</TableHeaderCell>)}</TableRow></TableHeader>
              <TableBody>
                {table.rows.map((row, i) => (
                  <TableRow key={i}>{row.map((cell, j) => <TableCell key={j}>{cell === null || cell === undefined ? "" : String(cell)}</TableCell>)}</TableRow>
                ))}
              </TableBody>
            </Table>
          ) : <p>No results found.</p>)}
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Geo-disaster recovery (Microsoft.ServiceBus/namespaces/{ns}/disasterRecoveryConfigs):
// pairing + role + failover are real ARM state (core/azure_arm_core.AzureArm.
// _servicebus_georecovery) — core/capabilities/azure/servicebus.json azure.servicebus.namespace.georecovery.
function GeoRecovery({ a, reload }) {
  const notify = useNotify();
  const { data, loading, error, reload: reloadDr } = useAsync(() => api.listGeoRecovery(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const namespaces = useAsync(() => api.listNamespaces(), []);
  const [pairOpen, setPairOpen] = useState(false);
  const [alias, setAlias] = useState("");
  const [partner, setPartner] = useState("");
  const pairing = (data || [])[0];
  const partners = (namespaces.data || []).filter((n) => n.id.toLowerCase() !== a.id.toLowerCase() && (n.sku?.tier || n.sku?.name) === "Premium");
  const refresh = () => { reloadDr(); reload(); };
  return (
    <CapabilityContainer id="azure.servicebus.namespace.georecovery" title={`${a.name} | Geo-disaster recovery`}>
      <ErrorBar error={error} />
      {loading ? <Loading /> : pairing ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="vy-props">
            <KV label="Alias name" value={pairing.name} />
            <KV label="Role" value={pairing.properties.role} />
            <KV label="Partner namespace" value={pairing.properties.partnerNamespace.split("/").pop()} />
            <KV label="Pending replication operations" value={pairing.properties.pendingReplicationOperationsCount} />
          </div>
          <div className="vy-cmdbar" role="toolbar" aria-label="Geo-disaster recovery commands">
            {pairing.properties.role === "Secondary" && (
              <ToolbarButton appearance="primary" onClick={async () => {
                await api.failoverGeoRecovery(a.resourceGroup, a.name, pairing.name);
                notify.success(`'${a.name}' is now the Primary namespace.`, "Failover succeeded");
                refresh();
              }}>Failover</ToolbarButton>
            )}
            <ToolbarButton icon={<Delete20Regular />} onClick={async () => {
              await api.breakGeoRecoveryPairing(a.resourceGroup, a.name, pairing.name);
              notify.success("The disaster recovery pairing was deleted.", "Delete succeeded");
              refresh();
            }}>Delete</ToolbarButton>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <p style={{ fontSize: 13 }}>Pair this namespace with another Premium-tier namespace for geo-disaster recovery. If there is an outage you can fail over to the secondary namespace.</p>
          <Button appearance="primary" disabled={(a.sku?.tier || a.sku?.name) !== "Premium"} onClick={() => setPairOpen(true)}>Initiate Disaster Recovery Pairing</Button>
          {(a.sku?.tier || a.sku?.name) !== "Premium" && <p style={{ fontSize: 13 }}>Geo-disaster recovery requires a Premium-tier namespace.</p>}
        </div>
      )}
      <Dialog open={pairOpen} onOpenChange={(_, d) => !d.open && setPairOpen(false)}>
        <DialogSurface aria-label="Initiate Disaster Recovery Pairing">
          <DialogBody>
            <DialogTitle>Initiate Disaster Recovery Pairing</DialogTitle>
            <DialogContent>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 360 }}>
                <Field label="Alias" required><Input value={alias} onChange={(_, d) => setAlias(d.value)} aria-label="Alias" /></Field>
                <Field label="Secondary namespace" required>
                  {partners.length ? (
                    <Select value={partner} onChange={(_, d) => setPartner(d.value)} aria-label="Secondary namespace">
                      <option value="">Choose a namespace...</option>
                      {partners.map((n) => <option key={n.id} value={n.id}>{n.name} ({locationLabel(n.location)})</option>)}
                    </Select>
                  ) : <p style={{ margin: 0 }}>No other Premium-tier namespace available to pair with yet.</p>}
                </Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!alias || !partner} onClick={async () => {
                await api.pairGeoRecovery(a.resourceGroup, a.name, alias, partner);
                notify.success(`Disaster recovery pairing '${alias}' was created.`, "Create succeeded");
                setPairOpen(false); setAlias(""); setPartner(""); refresh();
              }}>Create</Button>
              <Button onClick={() => setPairOpen(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}
