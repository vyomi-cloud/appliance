/* Network security group resource blade: left resource menu + panels. Overview, Tags,
 * Inbound/Outbound security rules, Locks, Activity log, Properties, Export template,
 * Diagnostic settings, Access control (IAM) (Role assignments/Roles/Check access real; Deny
 * assignments/Classic administrators honest) and the Network interfaces / Subnets
 * association + Associate picker are backed by real ARM calls; the remaining menu items are
 * honest CapabilityContainer gaps (core/capabilities/azure/nsgs.json is the single source of
 * truth for which). */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
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
import NetworkWatcherTools from "./NetworkWatcher.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Settings", items: [
    { id: "inbound", label: "Inbound security rules" }, { id: "outbound", label: "Outbound security rules" },
    { id: "nics", label: "Network interfaces" }, { id: "subnets", label: "Subnets" },
    { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" },
  ] },
  { group: "Monitoring", items: [
    { id: "alerts", label: "Alerts" }, { id: "diagnosticsettings", label: "Diagnostic settings" },
    { id: "logs", label: "Logs" }, { id: "flowlogs", label: "NSG flow logs" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "effectivesecurityrules", label: "Effective security rules" }, { id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const GAP_CAP = {
  tasks: "azure.nsgs.tools", support: "azure.nsgs.tools", effectivesecurityrules: "azure.nsgs.tools",
};

export default function NsgBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const nsg = useAsync(() => api.getNsg(rg, name), [rg, name]);
  const self = `#/nsgs/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (nsg.data) remember({ name, type: "Network security group", href: self }); }, [!!nsg.data, self]);

  let body;
  if (nsg.loading && !nsg.data) body = <Loading />;
  else if (nsg.error) body = <><ErrorBar error={nsg.error} title="Failed to load the network security group" /><Link href="#/nsgs">Back to Network security groups</Link></>;
  else {
    const a = nsg.data, reload = nsg.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      inbound: () => <RuleList key="inbound" rg={rg} name={name} direction="Inbound" />,
      outbound: () => <RuleList key="outbound" rg={rg} name={name} direction="Outbound" />,
      nics: () => <NetworkInterfaces a={a} />,
      subnets: () => <Subnets a={a} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      diagnosticsettings: () => <DiagnosticSettings a={a} />,
      diagnose: () => <Diagnose />,
      alerts: () => <NotSimulatedContainer title={`${name} | Alerts`} feature="Alerts" />,
      logs: () => <NotSimulatedContainer title={`${name} | Logs`} feature="Logs" />,
      flowlogs: () => <NotSimulatedContainer title={`${name} | NSG flow logs`} feature="NSG flow logs" />,
    }[panel];
    body = P ? P() : (
      <CapabilityContainer id={GAP_CAP[panel] || "azure.nsgs.tools"} title={`${name} | ${LABEL[panel] || panel}`} />
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Network security group" glyph={<Glyph id="nsgs" />} closeHref="#/nsgs"
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
  const rules = useAsync(() => api.listSecurityRules(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const tags = Object.entries(a.tags || {});
  const custom = rules.data || [];
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
        ]}
        right={[
          ["Custom security rules", custom.length],
          ["Associated with", "0 subnets, 0 network interfaces"],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <section className="vy-section"><h3>Inbound Security Rules</h3><RuleTable rg={a.resourceGroup} name={a.name} direction="Inbound" rules={custom} loading={rules.loading} readOnly /></section>
      <section className="vy-section"><h3>Outbound Security Rules</h3><RuleTable rg={a.resourceGroup} name={a.name} direction="Outbound" rules={custom} loading={rules.loading} readOnly /></section>

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="network security group" names={[a.name]}
        onConfirm={async () => {
          await api.deleteNsg(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Network security group '${a.name}' was deleted.`, "Delete succeeded");
          navigate("nsgs");
        }} />
    </>
  );
}

// ── Diagnose and solve problems: the Network Watcher tiles (IP flow verify, Next hop) are
// real; its other diagnostic tiles stay an honest gap (azure.nsgs.tools). ─────────────────
function Diagnose() {
  return (
    <>
      <div className="vy-panel-title">Diagnose and solve problems</div>
      <NetworkWatcherTools />
      <div style={{ marginTop: 16 }}>
        <NotSimulatedContainer title="Other diagnostic tools" feature="Tasks, Effective security rules, Support + Troubleshooting and the remaining Diagnose and solve problems tiles" />
      </div>
    </>
  );
}

// ── Access control (IAM): Role assignments / Roles / Check access are real ARM reads and a
// real decision call scoped to this NSG (plus its subscription/resource-group ancestors);
// Deny assignments and Classic administrators stay honest — core/capabilities/azure/nsgs.json
// azure.nsgs.iam. ────────────────────────────────────────────────────────────────────────
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  const [principal, setPrincipal] = useState("");
  const [action, setAction] = useState("Microsoft.Network/networkSecurityGroups/write");
  const [decision, setDecision] = useState(null);
  const roleAssignments = useAsync(() => api.listRoleAssignments(a.id), [a.id]);
  const roleDefinitions = useAsync(() => api.listRoleDefinitions(), []);
  return (
    <CapabilityContainer id="azure.nsgs.iam" title="Access control (IAM)">
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
      await api.createNsg(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
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

// ── Inbound / Outbound security rules (Microsoft.Network/.../securityRules, real ARM
// child resources — see core/azure_arm_core.py) ─────────────────────────────────────────
const PORT = (r) => r.properties?.destinationPortRange || (r.properties?.destinationPortRanges || []).join(",") || "*";

function RuleTable({ rules, direction, readOnly, hideDefaults, onDelete, sel, onToggle }) {
  const defaults = hideDefaults ? [] : api.DEFAULT_RULES.filter((r) => r.direction === direction);
  const custom = [...rules].sort((x, y) => (x.properties?.priority || 0) - (y.properties?.priority || 0));
  return (
    <Table size="small" aria-label={`${direction} security rules`} className="vy-grid">
      <TableHeader><TableRow>
        {!readOnly && <TableHeaderCell style={{ width: 32 }} />}
        <TableHeaderCell>Priority</TableHeaderCell><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Port</TableHeaderCell>
        <TableHeaderCell>Protocol</TableHeaderCell><TableHeaderCell>Source</TableHeaderCell><TableHeaderCell>Destination</TableHeaderCell><TableHeaderCell>Action</TableHeaderCell>
      </TableRow></TableHeader>
      <TableBody>
        {custom.map((r) => (
          <TableRow key={r.name}>
            {!readOnly && <TableCell><input type="checkbox" checked={sel?.has(r.name) || false} onChange={() => onToggle(r.name)} aria-label={`Select ${r.name}`} /></TableCell>}
            <TableCell>{r.properties?.priority}</TableCell><TableCell>{r.name}</TableCell><TableCell>{PORT(r)}</TableCell>
            <TableCell>{r.properties?.protocol}</TableCell><TableCell>{r.properties?.sourceAddressPrefix}</TableCell>
            <TableCell>{r.properties?.destinationAddressPrefix}</TableCell><TableCell>{r.properties?.access}</TableCell>
          </TableRow>
        ))}
        {defaults.map((r) => (
          <TableRow key={r.name}>
            {!readOnly && <TableCell />}
            <TableCell>{r.priority}</TableCell><TableCell>{r.name}</TableCell><TableCell>{r.port}</TableCell>
            <TableCell>{r.protocol}</TableCell><TableCell>{r.source}</TableCell><TableCell>{r.destination}</TableCell><TableCell>{r.access}</TableCell>
          </TableRow>
        ))}
        {!custom.length && !defaults.length && <TableRow><TableCell colSpan={readOnly ? 7 : 8} className="vy-muted">No security rules to display</TableCell></TableRow>}
      </TableBody>
    </Table>
  );
}

const SERVICE_PRESETS = {
  HTTP: { protocol: "Tcp", port: "80" }, HTTPS: { protocol: "Tcp", port: "443" }, SSH: { protocol: "Tcp", port: "22" },
  RDP: { protocol: "Tcp", port: "3389" }, "MS SQL": { protocol: "Tcp", port: "1433" }, MySQL: { protocol: "Tcp", port: "3306" }, PostgreSQL: { protocol: "Tcp", port: "5432" },
};

function RuleList({ rg, name, direction }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listSecurityRules(rg, name), [rg, name]);
  const [add, setAdd] = useState(false);
  const [hideDefaults, setHideDefaults] = useState(false);
  const [sel, setSel] = useState(new Set());
  const [del, setDel] = useState(false);
  const [gap, setGap] = useState(null);
  const [filter, setFilter] = useState("");
  const rules = (data || []).filter((r) => r.properties?.direction === direction && r.name.toLowerCase().includes(filter.trim().toLowerCase()));
  const toggle = (n) => setSel((s) => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x; });
  return (
    <>
      <div className="vy-panel-title">{direction} security rules</div>
      <div className="vy-cmdbar" role="toolbar" aria-label={`${direction} security rules commands`}>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
        <ToolbarButton onClick={() => setHideDefaults((v) => !v)}>{hideDefaults ? "Show default rules" : "Hide default rules"}</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} disabled={!sel.size} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton onClick={() => setGap(true)}>Give feedback</ToolbarButton>
      </div>
      <div className="vy-filters">
        <Input size="small" style={{ width: 260 }} placeholder="Filter by name" value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter by name" />
      </div>
      <ErrorBar error={error} />
      {loading ? <Loading /> : <RuleTable rules={rules} direction={direction} hideDefaults={hideDefaults} sel={sel} onToggle={toggle} />}
      <AddRuleDialog open={add} direction={direction} existing={rules} onClose={() => setAdd(false)}
        onCreate={async (ruleName, body) => {
          await api.putSecurityRule(rg, name, ruleName, body);
          notify.success(`Security rule '${ruleName}' was added.`, "Rule added");
          reload();
        }} />
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="security rule" names={[...sel]} confirmText={sel.size > 1 ? "delete" : undefined}
        onConfirm={async () => {
          for (const n of sel) await api.deleteSecurityRule(rg, name, n);
          notify.success(`Deleted ${sel.size} security rule${sel.size === 1 ? "" : "s"}.`, "Delete succeeded");
          setSel(new Set()); reload();
        }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label="Feedback">
          <DialogBody><DialogTitle>Give feedback</DialogTitle><DialogContent><NotSimulated feature="Sending product feedback" /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions></DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function AddRuleDialog({ open, direction, existing, onClose, onCreate }) {
  const notify = useNotify();
  const sourceOpts = direction === "Inbound" ? ["Any", "IP Addresses", "My IP address", "Service Tag", "Application security group"] : ["Any", "IP Addresses", "Service Tag", "Application security group"];
  const destOpts = direction === "Inbound" ? ["Any", "IP Addresses", "Service Tag", "Application security group"] : ["Any", "IP Addresses", "My IP address", "Service Tag", "Application security group"];
  const init = { source: "Any", sourceRange: "*", destination: "Any", service: "Custom", destRange: "8080", protocol: "Any", action: "Allow", priority: 100, name: "", description: "" };
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setF(init); }, [open]);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const setService = (_, d) => {
    const preset = SERVICE_PRESETS[d.value];
    setF((x) => ({ ...x, service: d.value, ...(preset ? { protocol: preset.protocol, destRange: preset.port } : {}) }));
  };
  const priorityNum = Number(f.priority);
  const errors = [];
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,78}[a-zA-Z0-9_]$/.test(f.name)) errors.push("name");
  else if (existing.some((r) => r.name === f.name)) errors.push("duplicate name");
  if (!(priorityNum >= 100 && priorityNum <= 4096)) errors.push("priority");
  if (!f.sourceRange) errors.push("source port ranges");
  if (!f.destRange) errors.push("destination port ranges");
  const valid = errors.length === 0;
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.name, {
        properties: {
          priority: priorityNum, direction, access: f.action,
          protocol: f.protocol === "Any" ? "*" : f.protocol,
          sourceAddressPrefix: f.source === "Any" ? "*" : f.sourceRange,
          sourcePortRange: f.sourceRange,
          destinationAddressPrefix: f.destination === "Any" ? "*" : f.destRange,
          destinationPortRange: f.destRange,
          description: f.description || undefined,
        },
      });
      onClose();
    } catch (e) { notify.error(e, "Failed to add security rule"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={`Add ${direction.toLowerCase()} security rule`}>
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add {direction.toLowerCase()} security rule</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Source"><Select value={f.source} onChange={set("source")} aria-label="Source">{sourceOpts.map((o) => <option key={o}>{o}</option>)}</Select></Field>
              <Field label="Source port ranges" required><Input value={f.sourceRange} onChange={set("sourceRange")} aria-label="Source port ranges" /></Field>
              <Field label="Destination"><Select value={f.destination} onChange={set("destination")} aria-label="Destination">{destOpts.map((o) => <option key={o}>{o}</option>)}</Select></Field>
              <Field label="Service">
                <Select value={f.service} onChange={setService} aria-label="Service">
                  {["Custom", "HTTP", "HTTPS", "SSH", "RDP", "MS SQL", "MySQL", "PostgreSQL"].map((o) => <option key={o}>{o}</option>)}
                </Select>
              </Field>
              <Field label="Destination port ranges" required><Input value={f.destRange} onChange={set("destRange")} aria-label="Destination port ranges" /></Field>
              <Field label="Protocol"><RadioGroup layout="horizontal" value={f.protocol} onChange={set("protocol")} aria-label="Protocol">
                <Radio value="Any" label="Any" /><Radio value="Tcp" label="TCP" /><Radio value="Udp" label="UDP" /><Radio value="Icmpv4" label="ICMPv4" />
              </RadioGroup></Field>
              <Field label="Action"><RadioGroup layout="horizontal" value={f.action} onChange={set("action")} aria-label="Action"><Radio value="Allow" label="Allow" /><Radio value="Deny" label="Deny" /></RadioGroup></Field>
              <Field label="Priority" required hint="100-4096"><Input type="number" min={100} max={4096} value={String(f.priority)} onChange={set("priority")} aria-label="Priority" /></Field>
              <Field label="Name" required><Input value={f.name} onChange={set("name")} aria-label="Name" /></Field>
              <Field label="Description"><Textarea value={f.description} onChange={set("description")} aria-label="Description" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Add</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Network interfaces / Subnets (NSG associations) — real ARM reads, scanned subscription-
// wide and matched by properties.networkSecurityGroup.id (see api.js). The "Associate"
// picker lists every NIC/subnet in the subscription that has no NSG of its own yet and
// PATCHes/PUTs the chosen one's networkSecurityGroup to point at THIS NSG — a real ARM
// mutation, same constraint the real portal's Associate dialog enforces. ─────────────────
function AssociateDialog({ open, onClose, resourceType, items, loading, onAssociate }) {
  const notify = useNotify();
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setChoice(""); }, [open]);
  const go = async () => {
    const picked = items.find((r) => r.id === choice);
    if (!picked) return;
    setBusy(true);
    try {
      await onAssociate(picked);
      notify.success(`'${picked.name}' was associated with this network security group.`, "Associate succeeded");
      onClose();
    } catch (e) { notify.error(e, "Failed to associate"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Associate">
        <DialogBody>
          <DialogTitle>Associate {resourceType}</DialogTitle>
          <DialogContent>
            {loading ? <Spinner size="tiny" /> : items.length ? (
              <Field label={`Choose a ${resourceType} with no network security group yet`}>
                <Select value={choice} onChange={(_, d) => setChoice(d.value)} aria-label={resourceType}>
                  <option value="">Select a {resourceType}</option>
                  {items.map((r) => <option key={r.id} value={r.id}>{r.vnetName ? `${r.vnetName} / ${r.name}` : r.name}</option>)}
                </Select>
              </Field>
            ) : <p>No {resourceType} without a network security group was found in this subscription.</p>}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!choice || busy} onClick={go}>Associate</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

const nicPublicIp = (r) => r.properties?.ipConfigurations?.[0]?.properties?.publicIPAddress?.id;
const nicPrivateIp = (r) => r.properties?.ipConfigurations?.[0]?.properties?.privateIPAddress;
const nicVm = (r) => r.properties?.virtualMachine?.id;

function NetworkInterfaces({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listNetworkInterfacesForNsg(a.id), [a.id]);
  const [assoc, setAssoc] = useState(false);
  const candidates = useAsync(() => (assoc ? api.listUnassociatedNics() : Promise.resolve([])), [assoc]);
  return (
    <CapabilityContainer id="azure.nsgs.associations" title={`${a.name} | Network interfaces`}>
      <BrowseGrid
        resourceName="network interface" rowKey={(r) => r.id} filterPlaceholder="Search network interfaces"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton onClick={() => setAssoc(true)}>Associate</ToolbarButton>}
        csvName="network-interfaces.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "publicip", label: "Public IP address", value: (r) => (nicPublicIp(r) ? parseId(nicPublicIp(r)).name : "--") },
          { key: "privateip", label: "Private IP address", value: (r) => nicPrivateIp(r) || "--" },
          { key: "vm", label: "Virtual machine", value: (r) => (nicVm(r) ? parseId(nicVm(r)).name : "--") },
        ]}
      />
      <AssociateDialog open={assoc} onClose={() => setAssoc(false)} resourceType="network interface"
        items={candidates.data || []} loading={candidates.loading}
        onAssociate={async (nic) => { await api.associateNic(nic, a.id); reload(); }} />
    </CapabilityContainer>
  );
}

function Subnets({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listSubnetsForNsg(a.id), [a.id]);
  const [assoc, setAssoc] = useState(false);
  const candidates = useAsync(() => (assoc ? api.listUnassociatedSubnets() : Promise.resolve([])), [assoc]);
  return (
    <CapabilityContainer id="azure.nsgs.associations" title={`${a.name} | Subnets`}>
      <BrowseGrid
        resourceName="subnet" rowKey={(r) => r.id} filterPlaceholder="Search subnets"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton onClick={() => setAssoc(true)}>Associate</ToolbarButton>}
        csvName="subnets.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "range", label: "Address range", value: (r) => r.properties?.addressPrefix || (r.properties?.addressPrefixes || []).join(", ") || "--" },
          { key: "vnet", label: "Virtual network", value: (r) => r.vnetName },
        ]}
      />
      <AssociateDialog open={assoc} onClose={() => setAssoc(false)} resourceType="subnet"
        items={candidates.data || []} loading={candidates.loading}
        onAssociate={async (subnet) => { await api.associateSubnet(subnet, a.id); reload(); }} />
    </CapabilityContainer>
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
        <KV label="Provisioning state" value={a.properties?.provisioningState} />
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this NSG) ──────────────────────────
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

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this NSG) — the same generic mechanism apim/cosmos's lenses use. Logs/
// metrics are stored and validated exactly as the real resource requires, but never
// delivered anywhere (core/capabilities/azure/nsgs.json azure.nsgs.monitoring). ──────────
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
    <CapabilityContainer id="azure.nsgs.monitoring" title={`${a.name} | Diagnostic settings`}>
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

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this NSG) ──
function ActivityLog({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name), [a.id]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.nsgs.activity_log" title={`${a.name} | Activity log`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log tools">
        {["Edit columns", "Export Activity Logs", "Download as CSV", "Insights", "Feedback", "Pin current filters", "Reset filters"].map((l) => (
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

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { nsgName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.Network/networkSecurityGroups", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('nsgName')]" : a.name, location: a.location, properties: a.properties }],
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
        {tab !== "arm" && <CapabilityContainer id="azure.nsgs.export_template" title={`${tab === "bicep" ? "Bicep" : "Terraform"} template export`} />}
      </section>
    </>
  );
}
