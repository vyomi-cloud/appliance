/* Virtual network resource blade: left resource menu + panels. Overview, Tags, Address
 * space, DNS servers, Subnets (incl. NAT gateway / route table association), Peerings,
 * Service endpoints, Locks, Activity log, Topology, Properties, Export template (ARM, Bicep,
 * Terraform) and Access control (IAM)'s Role assignments/Roles/Check access (real ARM reads +
 * decision, resource-scoped to this vnet) are backed by real ARM calls; the remaining menu
 * items are honest CapabilityContainer gaps (core/capabilities/azure/vnets.json is the single
 * source of truth for which). */
import { useEffect, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel, parseId } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { SubnetsPanel, PeeringsPanel, ServiceEndpointsPanel, ConnectedDevicesPanel, TopologyPanel } from "./Networking.jsx";
import NetworkWatcherTools, { ConnectionTroubleshootPanel } from "./NetworkWatcher.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "resourcevisualizer", label: "Resource visualizer" },
  { group: "Settings", items: [
    { id: "addressspace", label: "Address space" }, { id: "connecteddevices", label: "Connected devices" },
    { id: "subnets", label: "Subnets" }, { id: "bastion", label: "Bastion" },
    { id: "ddosprotection", label: "DDoS protection" }, { id: "firewall", label: "Firewall" },
    { id: "defender", label: "Microsoft Defender for Cloud" }, { id: "networkmanager", label: "Network manager" },
    { id: "dnsservers", label: "DNS servers" }, { id: "peerings", label: "Peerings" },
    { id: "serviceendpoints", label: "Service endpoints" }, { id: "privateendpoints", label: "Private endpoints" },
    { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" },
  ] },
  { group: "Monitoring", items: [
    { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" },
    { id: "connectiontroubleshoot", label: "Connection troubleshoot" }, { id: "topology", label: "Topology" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const GAP_CAP = {
  bastion: "azure.vnets.network_appliances", ddosprotection: "azure.vnets.network_appliances", firewall: "azure.vnets.network_appliances",
  defender: "azure.vnets.network_appliances", networkmanager: "azure.vnets.network_appliances", privateendpoints: "azure.vnets.network_appliances",
  connecteddevices: "azure.vnets.connected_devices",
};

export default function VnetBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const vnet = useAsync(() => api.getVnet(rg, name), [rg, name]);
  const self = `#/vnets/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (vnet.data) remember({ name, type: "Virtual network", href: self }); }, [!!vnet.data, self]);

  let body;
  if (vnet.loading && !vnet.data) body = <Loading />;
  else if (vnet.error) body = <><ErrorBar error={vnet.error} title="Failed to load the virtual network" /><Link href="#/vnets">Back to Virtual networks</Link></>;
  else {
    const a = vnet.data, reload = vnet.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      addressspace: () => <AddressSpace a={a} reload={reload} />,
      dnsservers: () => <DnsServers a={a} reload={reload} />,
      subnets: () => <SubnetsPanel a={a} />,
      peerings: () => <PeeringsPanel a={a} />,
      serviceendpoints: () => <ServiceEndpointsPanel a={a} />,
      connecteddevices: () => <ConnectedDevicesPanel a={a} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      topology: () => <TopologyPanel a={a} />,
      diagnose: () => <Diagnose />,
      connectiontroubleshoot: () => <ConnectionTroubleshootPanel />,
      diagnosticsettings: () => <DiagnosticSettings a={a} />,
      logs: () => <LogsPanel a={a} />,
      alerts: () => <Alerts a={a} />,
      metrics: () => <Metrics a={a} />,
      tasks: () => <Tasks a={a} />,
      resourcevisualizer: () => <ResourceVisualizer a={a} />,
      support: () => <Support self={self} />,
    }[panel];
    body = P ? P() : (
      <CapabilityContainer id={GAP_CAP[panel] || "azure.vnets.tools"} title={`${name} | ${LABEL[panel] || panel}`} />
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Virtual network" glyph={<Glyph id="vnets" />} closeHref="#/vnets"
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
  const [del, setDel] = useState(false);
  const [tab, setTab] = useState("topology");
  const tags = Object.entries(a.tags || {});
  const prefixes = (a.properties?.addressSpace?.addressPrefixes || []).join(", ");
  const dns = (a.properties?.dhcpOptions?.dnsServers || []).length ? a.properties.dhcpOptions.dnsServers.join(", ") : "Default (Azure-provided)";
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton disabled>Move</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton disabled>Give feedback</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="topology">Topology</Tab>
        <Tab value="properties">Properties</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="recommendations">Recommendations</Tab>
        <Tab value="tutorials">Tutorials</Tab>
      </TabList>
      <div style={{ marginTop: 12 }}>
        {tab === "topology" && <TopologyPanel a={a} />}
        {tab === "properties" && <Properties a={a} />}
        {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
        {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}
        {tab === "tutorials" && <NotSimulatedContainer feature="Tutorials" />}
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Address space", prefixes],
          ["DNS servers", dns],
          ["Flow timeout", `${a.properties?.flowTimeoutInMinutes || 4} minutes`],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="virtual network" names={[a.name]}
        onConfirm={async () => {
          await api.deleteVnet(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Virtual network '${a.name}' was deleted.`, "Delete succeeded");
          navigate("vnets");
        }} />
    </>
  );
}

// ── Diagnose and solve problems: the Network Watcher tiles (IP flow verify, Next hop,
// Connection troubleshoot) are real (azure.vnets.network_watcher). Resource visualizer, Tasks
// and Support + Troubleshooting are real too (see below). The remaining diagnostic tiles stay
// an honest gap — azure.vnets.tools — they run against Microsoft's own AI-driven diagnostics
// backend (VPN/ExpressRoute/DNS recommendation engines), not a deterministic local ARM read. ──
function Diagnose() {
  return (
    <>
      <div className="vy-panel-title">Diagnose and solve problems</div>
      <NetworkWatcherTools />
      <div style={{ marginTop: 16 }}>
        <NotSimulatedContainer title="Other diagnostic tools" feature="The remaining Diagnose and solve problems tiles"
          note="Azure's AI-driven troubleshooting recommendations (VPN/ExpressRoute/DNS diagnostics) run against Microsoft's own analytics backend, not a deterministic local ARM read — outside what a local simulator can model." />
      </div>
    </>
  );
}

// ── Access control (IAM): Role assignments / Roles / Check access are real ARM reads and a
// real decision call scoped to this virtual network (plus its subscription/resource-group
// ancestors); Deny assignments and Classic administrators stay honest —
// core/capabilities/azure/vnets.json azure.vnets.iam. ─────────────────────────────────────
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  const [principal, setPrincipal] = useState("");
  const [action, setAction] = useState("Microsoft.Network/virtualNetworks/write");
  const [decision, setDecision] = useState(null);
  const roleAssignments = useAsync(() => api.listRoleAssignments(a.id), [a.id]);
  const roleDefinitions = useAsync(() => api.listRoleDefinitions(), []);
  return (
    <CapabilityContainer id="azure.vnets.iam" title="Access control (IAM)">
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
          <section className="vy-section"><h3>Check access</h3><Button onClick={() => { setDecision(null); setDlg("check"); }}>Check access</Button></section>
        </div>
      )}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access check">
          <DialogBody>
            <DialogTitle>{dlg === "mine" ? "My access" : "Check access"}</DialogTitle>
            <DialogContent>
              {dlg === "mine" ? (
                <NotSimulated feature="Per-identity 'my access' resolution" note="Vyomi has no signed-in identity to resolve — use Check access with a principal id instead." />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 360 }}>
                  <Field label="Find">
                    <Input value={principal} onChange={(_, d) => setPrincipal(d.value)} placeholder="Principal (object) id" aria-label="Principal ID" />
                  </Field>
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
      const { id, name, type, resourceGroup, ...rest } = a;
      await api.createVnet(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
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

// ── Address space ──────────────────────────────────────────────────────────────────────
function AddressSpace({ a, reload }) {
  const notify = useNotify();
  const init = () => (a.properties?.addressSpace?.addressPrefixes || ["10.0.0.0/16"]).map((p) => ({ prefix: p }));
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const count = (cidr) => { const bits = Number((cidr.split("/")[1] || 32)); return Number.isFinite(bits) ? 2 ** (32 - bits) : "--"; };
  const save = async () => {
    setBusy(true);
    try {
      await api.createVnet(a.resourceGroup, a.name, { location: a.location, tags: a.tags, properties: { ...a.properties, addressSpace: { addressPrefixes: rows.map((r) => r.prefix).filter(Boolean) } } });
      notify.success(`Address space on '${a.name}' was updated.`, "Address space saved");
      reload();
    } catch (e) { notify.error(e, "Saving address space failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Address space</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Address space commands">
        <ToolbarButton appearance="primary" disabled={busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton onClick={() => setRows(init())}>Discard</ToolbarButton>
      </div>
      <Table size="small" aria-label="Address space" style={{ maxWidth: 560, marginTop: 8 }}>
        <TableHeader><TableRow><TableHeaderCell>Address range</TableHeaderCell><TableHeaderCell>Address count</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={i}>
              <TableCell><Input size="small" value={r.prefix} onChange={(_, d) => setRows((xs) => xs.map((x, j) => (j === i ? { prefix: d.value } : x)))} aria-label={`Address range ${i + 1}`} /></TableCell>
              <TableCell>{count(r.prefix)}</TableCell>
              <TableCell>{rows.length > 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete address range" onClick={() => setRows((xs) => xs.filter((_, j) => j !== i))} />}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Button appearance="subtle" icon={<Add20Regular />} style={{ marginTop: 8 }} onClick={() => setRows((xs) => [...xs, { prefix: "" }])}>Add additional address range</Button>
    </>
  );
}

// ── DNS servers ────────────────────────────────────────────────────────────────────────
function DnsServers({ a, reload }) {
  const notify = useNotify();
  const existing = a.properties?.dhcpOptions?.dnsServers || [];
  const [mode, setMode] = useState(existing.length ? "custom" : "default");
  const [ip, setIp] = useState(existing[0] || "");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setMode(existing.length ? "custom" : "default"); setIp(existing[0] || ""); }, [a]);
  const save = async () => {
    setBusy(true);
    try {
      const dnsServers = mode === "custom" && ip ? [ip] : [];
      await api.createVnet(a.resourceGroup, a.name, { location: a.location, tags: a.tags, properties: { ...a.properties, dhcpOptions: { dnsServers } } });
      notify.success(`DNS servers on '${a.name}' were updated.`, "DNS servers saved");
      reload();
    } catch (e) { notify.error(e, "Saving DNS servers failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">DNS servers</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="DNS servers commands">
        <ToolbarButton appearance="primary" disabled={busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton onClick={() => { setMode(existing.length ? "custom" : "default"); setIp(existing[0] || ""); }}>Discard</ToolbarButton>
      </div>
      <RadioGroup value={mode} onChange={(_, d) => setMode(d.value)} aria-label="DNS servers" style={{ marginTop: 12 }}>
        <Radio value="default" label="Default (Azure-provided)" />
        <Radio value="custom" label="Custom" />
      </RadioGroup>
      {mode === "custom" && <Field label="IP Address" style={{ maxWidth: 320, marginTop: 8 }}><Input value={ip} onChange={(_, d) => setIp(d.value)} aria-label="IP Address" /></Field>}
    </>
  );
}

// ── Properties ─────────────────────────────────────────────────────────────────────────
function Properties({ a }) {
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <div className="vy-props">
        <KV label="Name" value={a.name} />
        <KV label="Resource ID" value={a.id} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="Address space" value={(a.properties?.addressSpace?.addressPrefixes || []).join(", ")} />
        <KV label="Provisioning state" value={a.properties?.provisioningState} />
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this vnet) ────────────────────────
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
        emptyAction={<span>This resource has no locks.</span>}
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
            <DialogContent><NotSimulatedContainer feature={gap === "Feedback" ? "Sending product feedback" : `Locks scoped to the ${(gap || "").toLowerCase()}`} /></DialogContent>
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

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this vnet) ──
function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.vnets.activity_log" title={`${a.name} | Activity log`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log tools">
        {["Activity", "Edit columns", "Export Activity Logs", "Download as CSV", "Insights", "Feedback", "Pin current filters", "Reset filters"].map((l) => (
          <ToolbarButton key={l} onClick={() => setGap(l)}>{l}</ToolbarButton>
        ))}
      </div>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody><DialogTitle>{gap}</DialogTitle><DialogContent><NotSimulatedContainer feature={gap || ""} /></DialogContent>
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

// ── Export template — all three tabs are generated client-side from this resource's live
// ARM state (same source, three serializations); no linked/nested templates or deployment
// history, same honest scope as every other service in this lens. ────────────────────────
const bicepSymbol = (name) => name.replace(/[^a-zA-Z0-9]/g, "_").replace(/^(\d)/, "_$1");

function toBicep(a, params) {
  const prefixes = a.properties?.addressSpace?.addressPrefixes || [];
  const lines = [];
  if (params) lines.push(`param vnetName string = '${a.name}'`, "");
  lines.push(`resource ${bicepSymbol(a.name)} 'Microsoft.Network/virtualNetworks@${api.ARM.apiVersion}' = {`);
  lines.push(`  name: ${params ? "vnetName" : `'${a.name}'`}`);
  lines.push(`  location: '${a.location}'`);
  lines.push(`  properties: {`);
  lines.push(`    addressSpace: {`);
  lines.push(`      addressPrefixes: [`);
  prefixes.forEach((p) => lines.push(`        '${p}'`));
  lines.push(`      ]`);
  lines.push(`    }`);
  lines.push(`  }`);
  lines.push(`}`);
  return lines.join("\n");
}

function toTerraform(a, params) {
  const prefixes = a.properties?.addressSpace?.addressPrefixes || [];
  const lines = [];
  if (params) lines.push(`variable "vnet_name" {`, `  default = "${a.name}"`, `}`, "");
  lines.push(`resource "azurerm_virtual_network" "${bicepSymbol(a.name)}" {`);
  lines.push(`  name                = ${params ? "var.vnet_name" : `"${a.name}"`}`);
  lines.push(`  location            = "${a.location}"`);
  lines.push(`  resource_group_name = "${a.resourceGroup}"`);
  lines.push(`  address_space       = [${prefixes.map((p) => `"${p}"`).join(", ")}]`);
  lines.push(`}`);
  return lines.join("\n");
}

function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { vnetName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.Network/virtualNetworks", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('vnetName')]" : a.name, location: a.location, properties: a.properties }],
  };
  const byTab = { arm: [JSON.stringify(template, null, 2), "json"], bicep: [toBicep(a, params), "bicep"], terraform: [toTerraform(a, params), "tf"] };
  const [text, ext] = byTab[tab];
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
        <label><input type="checkbox" checked={params} onChange={(e) => setParams(e.target.checked)} /> Include parameters</label>
        <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />
      </section>
    </>
  );
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this vnet) — the same generic mechanism the NSG lens wires. Logs/metrics
// are stored and validated exactly as the real resource requires, but never delivered
// anywhere (core/capabilities/azure/vnets.json azure.vnets.monitoring). ──────────────────
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
    <CapabilityContainer id="azure.vnets.monitoring" title={`${a.name} | Diagnostic settings`}>
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

// ── Logs (Microsoft.OperationalInsights/workspaces/{ws}/api/query) — the same ARM pass-
// through the Azure Portal's resource-scoped Logs blade uses, carrying a small real KQL
// subset (core/azure_operationalinsights_core.py). AzureActivity rows are the real per-
// resource Activity log entries this vnet's own Activity log tab reads. ──────────────────
function LogsPanel({ a }) {
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [workspace, setWorkspace] = useState("");
  const [query, setQuery] = useState(`AzureActivity\n| where ResourceId == '${a.id}'\n| take 50`);
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
    <CapabilityContainer id="azure.vnets.monitoring" title={`${a.name} | Logs`}>
      {workspaces.loading ? <Loading /> : !ws.length ? (
        <p>No Log Analytics workspace yet. <Link href="#/monitor/createloganalyticsworkspace">Create one</Link>, then configure a diagnostic setting on this virtual network to send its logs there.</p>
      ) : (
        <>
          <Field label="Scope"><Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
            {ws.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </Select></Field>
          <Textarea value={query} onChange={(_, d) => setQuery(d.value)} rows={4} resize="vertical" style={{ width: "100%", fontFamily: "monospace", marginTop: 8 }} aria-label="KQL query" />
          <div className="vy-cmdbar" style={{ marginTop: 8 }}><Button appearance="primary" disabled={running || !workspace} onClick={run}>Run</Button></div>
          <ErrorBar error={error} title="Query failed" />
          {table && (table.rows.length ? (
            <Table size="small" aria-label="Query results" style={{ marginTop: 8 }}>
              <TableHeader><TableRow>{table.columns.map((c) => <TableHeaderCell key={c.name}>{c.name}</TableHeaderCell>)}</TableRow></TableHeader>
              <TableBody>{table.rows.map((row, i) => <TableRow key={i}>{row.map((cell, j) => <TableCell key={j}>{cell === null || cell === undefined ? "" : String(cell)}</TableCell>)}</TableRow>)}</TableBody>
            </Table>
          ) : <p>No results found.</p>)}
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Alerts — metric alert / activity log alert rules whose own `scopes` names this vnet
// (core/azure_monitor_core.py, the same resources the Monitor service's Alerts page lists
// subscription-wide). Vyomi stores alert rules but runs no live metric-evaluation loop, same
// honest limitation as azure.monitor.alert_rules. ────────────────────────────────────────
function Alerts({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listAlertsForResource(a.id), [a.id]);
  return (
    <CapabilityContainer id="azure.vnets.monitoring" title={`${a.name} | Alerts`}
      actions={<>
        <ToolbarButton icon={<Add20Regular />} as="a" href="#/monitor/createalertrule">Create alert rule</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </>}>
      <p style={{ fontSize: 12 }}>Vyomi stores alert rules but runs no live metric-evaluation loop, so no alert has ever fired for this virtual network.</p>
      <BrowseGrid resourceName="alert rule" rowKey={(r) => r.id} filterPlaceholder="Search alert rules"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        columns={[
          { key: "name", label: "Name" },
          { key: "kind", label: "Type" },
          { key: "severity", label: "Severity", value: (r) => (r.severity != null ? r.severity : "--") },
          { key: "enabled", label: "Enabled", value: (r) => (r.enabled ? "Yes" : "No") },
        ]}
      />
    </CapabilityContainer>
  );
}

// ── Metrics — Microsoft.Network/virtualNetworks publishes no real-time telemetry Vyomi can
// emulate (core/azure_monitor_core.py: "Not modelled: metric definitions / metrics"; see the
// Monitor service's azure.monitor.metrics_charts). Instead of a stored/random chart, this is a
// REAL derived series: this vnet's own management-operation count per hour, read back from
// its Activity log — never synthetic data. ───────────────────────────────────────────────
function Metrics({ a }) {
  const log = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const subnets = useAsync(() => api.listSubnets(a.resourceGroup, a.name), [a.id]);
  const peerings = useAsync(() => api.listPeerings(a.resourceGroup, a.name), [a.id]);
  const events = log.data || [];
  const now = Date.now();
  const buckets = Array.from({ length: 12 }, (_, i) => {
    const hoursAgo = 11 - i;
    const start = now - (hoursAgo + 1) * 3600000, end = now - hoursAgo * 3600000;
    const count = events.filter((e) => { const t = Date.parse(e.eventTimestamp); return t >= start && t < end; }).length;
    return { label: `${hoursAgo}h`, count };
  });
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const addressCount = (a.properties?.addressSpace?.addressPrefixes || []).reduce((n, p) => {
    const bits = Number(p.split("/")[1]);
    return n + (Number.isFinite(bits) ? 2 ** (32 - bits) : 0);
  }, 0);
  return (
    <CapabilityContainer id="azure.vnets.monitoring" title={`${a.name} | Metrics`}>
      <p style={{ fontSize: 12 }}>Vyomi has no metric-value data plane for this resource type; the chart below is a real derived series instead — management-operation counts per hour from this virtual network's own Activity log (never synthetic/random data).</p>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 120, marginTop: 12, borderBottom: "1px solid var(--colorNeutralStroke2)" }}>
        {buckets.map((b, i) => (
          <div key={i} title={`${b.count} operation${b.count === 1 ? "" : "s"}, ~${b.label} ago`}
            style={{ width: 20, height: `${Math.max(2, (b.count / max) * 100)}%`, background: "var(--colorBrandBackground)" }} />
        ))}
      </div>
      <p style={{ fontSize: 11 }} className="vy-muted">Management operations per hour, last 12 hours (most recent on the right).</p>
      <Essentials
        left={[["Subnets", subnets.data?.length ?? "--"], ["Peerings", peerings.data?.length ?? "--"]]}
        right={[["Address space size", addressCount ? `${addressCount} addresses` : "--"], ["Flow timeout", `${a.properties?.flowTimeoutInMinutes || 4} minutes`]]}
      />
    </CapabilityContainer>
  );
}

// ── Tasks (preview) — lightweight per-resource task tracking. Real Azure's "Tasks (preview)"
// resource-menu item isn't a documented ARM resource provider Vyomi can model against; it's
// the same kind of console-local, per-user bookkeeping as "Pin to dashboard", so it's built as
// a browser-local (localStorage) list, keyed to this vnet's resource id. ─────────────────
const tasksKey = (id) => `vyomi.tasks.${id}`;
const loadTasks = (id) => { try { return JSON.parse(localStorage.getItem(tasksKey(id)) || "[]"); } catch { return []; } };
const saveTasks = (id, tasks) => localStorage.setItem(tasksKey(id), JSON.stringify(tasks));
const newTaskId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

function Tasks({ a }) {
  const [tasks, setTasks] = useState(() => loadTasks(a.id));
  const [title, setTitle] = useState("");
  const commit = (next) => { setTasks(next); saveTasks(a.id, next); };
  const add = () => { if (!title.trim()) return; commit([...tasks, { id: newTaskId(), title: title.trim(), done: false, created: new Date().toISOString() }]); setTitle(""); };
  const toggle = (id) => commit(tasks.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));
  const remove = (id) => commit(tasks.filter((t) => t.id !== id));
  return (
    <>
      <div className="vy-panel-title">Tasks</div>
      <p style={{ fontSize: 12 }} className="vy-muted">Lightweight per-resource task tracking, stored in this browser (a console preference, like "Pin to dashboard") — not an ARM resource.</p>
      <div style={{ display: "flex", gap: 8, maxWidth: 480 }}>
        <Input value={title} onChange={(_, d) => setTitle(d.value)} placeholder="New task" aria-label="New task title" onKeyDown={(e) => e.key === "Enter" && add()} />
        <Button appearance="primary" onClick={add}>Add</Button>
      </div>
      <Table size="small" aria-label="Tasks" style={{ marginTop: 12, maxWidth: 640 }}>
        <TableHeader><TableRow><TableHeaderCell style={{ width: 32 }} /><TableHeaderCell>Title</TableHeaderCell><TableHeaderCell>Created</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
        <TableBody>
          {tasks.map((t) => (
            <TableRow key={t.id}>
              <TableCell><input type="checkbox" checked={t.done} onChange={() => toggle(t.id)} aria-label={`Mark "${t.title}" done`} /></TableCell>
              <TableCell style={{ textDecoration: t.done ? "line-through" : "none" }}>{t.title}</TableCell>
              <TableCell>{fmtDate(t.created)}</TableCell>
              <TableCell><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete "${t.title}"`} onClick={() => remove(t.id)} /></TableCell>
            </TableRow>
          ))}
          {!tasks.length && <TableRow><TableCell colSpan={4} className="vy-muted">No tasks yet.</TableCell></TableRow>}
        </TableBody>
      </Table>
    </>
  );
}

// ── Resource visualizer — a real, structured map of this vnet's subnets and the resources
// inside them (the same ARM reads the Subnets/Connected devices/Peerings panels use); Vyomi
// renders cards instead of Azure's interactive canvas diagram (azure.vnets.tools). ────────
function ResourceVisualizer({ a }) {
  const subnets = useAsync(() => api.listSubnets(a.resourceGroup, a.name), [a.id]);
  const devices = useAsync(() => api.listConnectedDevices(a.resourceGroup, a.name), [a.id]);
  const peerings = useAsync(() => api.listPeerings(a.resourceGroup, a.name), [a.id]);
  if (subnets.loading || devices.loading || peerings.loading) return <Loading />;
  const devicesIn = (subnetId) => (devices.data || []).filter((n) =>
    (n.properties?.ipConfigurations || []).some((c) => (c.properties?.subnet?.id || "").toLowerCase() === subnetId.toLowerCase()));
  return (
    <CapabilityContainer id="azure.vnets.tools" title={`${a.name} | Resource visualizer`}>
      <p style={{ fontSize: 12 }} className="vy-muted">A real, structured map of this virtual network's subnets and the resources inside them — rendered as cards rather than Azure's interactive canvas diagram.</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 12 }}>
        {(subnets.data || []).map((s) => (
          <div key={s.id} className="vy-section" style={{ minWidth: 220 }}>
            <h4 style={{ marginTop: 0 }}>{s.name}</h4>
            <div className="vy-muted" style={{ fontSize: 12 }}>{s.properties?.addressPrefix}</div>
            <ul style={{ paddingLeft: 16, margin: "8px 0 0" }}>
              {devicesIn(s.id).map((d) => <li key={d.id}>{d.name}</li>)}
              {!devicesIn(s.id).length && <li className="vy-muted">No connected devices</li>}
            </ul>
          </div>
        ))}
        {!subnets.data?.length && <p className="vy-muted">No subnets yet.</p>}
      </div>
      {!!(peerings.data || []).length && (
        <div style={{ marginTop: 16 }}>
          <h4>Peered virtual networks</h4>
          <ul>{peerings.data.map((p) => (
            <li key={p.id}>{p.properties?.remoteVirtualNetwork?.id ? parseId(p.properties.remoteVirtualNetwork.id).name : p.name} — {p.properties?.peeringState}</li>
          ))}</ul>
        </div>
      )}
    </CapabilityContainer>
  );
}

// ── Support + Troubleshooting — a real navigational hub (Diagnose and solve problems,
// Resource health) plus one honest, narrowly-scoped gap: filing an actual Microsoft support
// ticket needs Microsoft's own support ticketing service (azure.vnets.tools). ─────────────
function Support({ self }) {
  const [gap, setGap] = useState(false);
  return (
    <>
      <div className="vy-panel-title">Support + Troubleshooting</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480, marginTop: 12 }}>
        <section className="vy-section">
          <h3>Diagnose and solve problems</h3>
          <p style={{ fontSize: 13 }}>Run Vyomi's network diagnostics (IP flow verify, Next hop, Connection troubleshoot) against this virtual network.</p>
          <Link href={`${self}/diagnose`}>Go to Diagnose and solve problems</Link>
        </section>
        <section className="vy-section">
          <h3>Resource health</h3>
          <p style={{ fontSize: 13 }}>This virtual network is <b>Available</b> — Vyomi has no fault-injection model, so every simulated resource always reports healthy.</p>
        </section>
        <section className="vy-section">
          <h3>New support request</h3>
          <Button onClick={() => setGap(true)}>New support request</Button>
        </section>
      </div>
      <Dialog open={gap} onOpenChange={(_, d) => !d.open && setGap(false)}>
        <DialogSurface aria-label="New support request">
          <DialogBody>
            <DialogTitle>New support request</DialogTitle>
            <DialogContent><NotSimulatedContainer feature="Filing a Microsoft support ticket" note="Creating a real support case needs Microsoft's own support ticketing service — outside anything a local simulator can model." /></DialogContent>
            <DialogActions><Button onClick={() => setGap(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
