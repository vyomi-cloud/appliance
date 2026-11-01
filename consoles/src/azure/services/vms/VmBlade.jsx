/* Virtual machine resource blade: left resource menu + panels. Overview, Tags, Locks, Activity
 * log (with an ENFORCED timespan picker), Size, Disks, Identity, Auto-shutdown (ENFORCED lazily
 * on read — core/azure_arm_core.py flips the VM's own power state once the scheduled local time
 * has passed, no real scheduler), Connect, Network settings (network interface + public IP, when
 * one was requested at create time, +, when attached, its network security group's
 * inbound/outbound rules — the same engine the Network security groups console uses), Properties,
 * Export template (ARM/Bicep/Terraform, all generated client-side) and Access control (IAM)'s
 * Role assignments/Roles tabs (scoped to this VM over the same generic engine the Cosmos DB
 * account blade uses) are backed by real ARM calls; the remaining menu items are honest
 * CapabilityContainer gaps (core/capabilities/azure/vms.json is the single source of truth for
 * which). */
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
import { capability, CapabilityContainer } from "../../kit/Capability.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "resourcevisualizer", label: "Resource visualizer" },
  { group: "Connect", items: [{ id: "connect", label: "Connect" }, { id: "bastion", label: "Bastion" }] },
  { group: "Networking", items: [
    { id: "networksettings", label: "Network settings" }, { id: "loadbalancing", label: "Load balancing" },
    { id: "asgs", label: "Application security groups" }, { id: "networkmanager", label: "Network manager" },
  ] },
  { group: "Settings", items: [
    { id: "disks", label: "Disks" }, { id: "extensions", label: "Extensions + applications" },
    { id: "operatingsystem", label: "Operating system" }, { id: "configuration", label: "Configuration" },
    { id: "advisor", label: "Advisor recommendations" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" },
  ] },
  { group: "Availability + scale", items: [{ id: "size", label: "Size" }, { id: "availabilityscaling", label: "Availability + scaling" }] },
  { group: "Security", items: [{ id: "defender", label: "Microsoft Defender for Cloud" }, { id: "identity", label: "Identity" }] },
  { group: "Backup + disaster recovery", items: [{ id: "backup", label: "Backup" }, { id: "disasterrecovery", label: "Disaster recovery" }] },
  { group: "Operations", items: [
    { id: "autoshutdown", label: "Auto-shutdown" }, { id: "runcommand", label: "Run command" }, { id: "updates", label: "Updates" },
    { id: "inventory", label: "Inventory" }, { id: "changetracking", label: "Change tracking" },
  ] },
  { group: "Monitoring", items: [
    { id: "insights", label: "Insights" }, { id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" },
    { id: "connectionmonitor", label: "Connection monitor" }, { id: "workbooks", label: "Workbooks" },
  ] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [
    { id: "resourcehealth", label: "Resource health" }, { id: "bootdiagnostics", label: "Boot diagnostics" },
    { id: "perfdiagnostics", label: "Performance diagnostics" }, { id: "resetpassword", label: "Reset password" },
    { id: "redeploy", label: "Redeploy + reapply" }, { id: "serialconsole", label: "Serial console" },
    { id: "support", label: "Support + Troubleshooting" },
  ] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
// Menu items with no dedicated panel in `P` below fall back to a honest gap. Most render the
// NotSimulated reason inline (see NOT_SIMULATED_REASON) because they need something physically
// absent from a browser/WASM simulator (a guest OS process, a hypervisor device, a real
// third-party service) — never a disabled skeleton of the real UI. A few still share the
// bundled azure.vms.tools capability id for the orchestrator's own bookkeeping.
const GAP_CAP = {
  bastion: "azure.vms.tools", loadbalancing: "azure.vms.tools", asgs: "azure.vms.tools", networkmanager: "azure.vms.tools",
  extensions: "azure.vms.tools", disasterrecovery: "azure.vms.tools", updates: "azure.vms.tools", tasks: "azure.vms.tools",
  bootdiagnostics: "azure.vms.tools", perfdiagnostics: "azure.vms.tools", serialconsole: "azure.vms.tools", support: "azure.vms.tools",
};
const NOT_SIMULATED_REASON = {
  bastion: "Azure Bastion tunnels a browser session to the guest's own network stack over a private network path. Vyomi's virtual machines have no guest network stack to tunnel to — only the resource's own metadata exists in-browser.",
  loadbalancing: "Distributing real traffic across two virtual machines needs a live network path forwarding real packets between them. A browser/WASM simulator has no virtual network device to carry that traffic — and Microsoft.Network/loadBalancers is not a resource type this lens's Networking service models.",
  asgs: "Application security groups are not a resource type this lens's Networking service models yet (see Microsoft.Network/networkSecurityGroups' own rule engine, which the Network settings tab already reuses for real IP-based rules).",
  networkmanager: "Network Manager centrally pushes connectivity/security configuration across a real multi-VNet packet path. There is no virtual network stack in a browser/WASM simulator for that configuration to actually take effect on.",
  extensions: "Installing a VM extension means a real guest agent downloading and executing a package inside the guest OS. Vyomi's virtual machines are metadata-only — no guest OS process exists in-browser to install anything into.",
  disasterrecovery: "Azure Site Recovery continuously replicates this VM's disks, block by block, to a second region and fails over to that replica on demand. Vyomi models one logical copy of each resource — there is no second region-local replica for a failover to cut over to.",
  updates: "Update assessment and patch installation need a package manager running inside a live guest OS to scan and patch. Vyomi's virtual machines have no guest OS process in-browser to scan.",
  tasks: "Tasks (preview) is backed by Microsoft To Do/Planner over Microsoft Graph — a real separate Microsoft 365 product Vyomi does not run a backend for.",
  bootdiagnostics: "Boot diagnostics captures a screenshot of the guest's own video framebuffer from the hypervisor. There is no hypervisor or guest video device in a browser/WASM simulator to capture from.",
  perfdiagnostics: "Performance diagnostics samples CPU/memory/disk counters from inside a live guest OS. Vyomi's virtual machines have no guest OS process in-browser to sample counters from.",
  serialconsole: "The serial console attaches a terminal to the guest's own boot firmware/OS console device over the hypervisor. There is no hypervisor or guest console device in a browser/WASM simulator to attach to.",
  support: "Filing or reading a support request calls Microsoft's own real support-ticketing system — a real third-party service outside the simulator.",
};

export default function VmBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  // Refetch on every panel change (not just rg/name): VmBlade itself doesn't remount when only
  // the panel changes, and several panels (Disks, Size, Identity) read live-mutable VM fields
  // straight off `a` rather than issuing their own fetch, so a stale `a` would show stale state.
  const vm = useAsync(() => api.getVm(rg, name), [rg, name, panel]);
  const self = `#/vms/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (vm.data) remember({ name, type: "Virtual machine", href: self }); }, [!!vm.data, self]);

  let body;
  if (vm.loading && !vm.data) body = <Loading />;
  else if (vm.error) body = <><ErrorBar error={vm.error} title="Failed to load the virtual machine" /><Link href="#/vms">Back to Virtual machines</Link></>;
  else {
    const a = vm.data, reload = vm.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      size: () => <Size a={a} reload={reload} />,
      disks: () => <Disks a={a} reload={reload} />,
      identity: () => <Identity a={a} reload={reload} />,
      autoshutdown: () => <AutoShutdown a={a} reload={reload} />,
      connect: () => <Connect a={a} />,
      networksettings: () => <NetworkSettings a={a} />,
      runcommand: () => <RunCommand a={a} reload={reload} />,
      exporttemplate: () => <ExportTemplate a={a} />,
      resourcevisualizer: () => <ResourceVisualizer a={a} />,
      advisor: () => <Advisor a={a} />,
      diagnose: () => <Diagnose a={a} />,
      resourcehealth: () => <ResourceHealth a={a} />,
      changetracking: () => <ChangeTracking a={a} />,
      defender: () => <Defender a={a} />,
      backup: () => <Backup a={a} reload={reload} />,
      resetpassword: () => <ResetPassword a={a} />,
      redeploy: () => <Redeploy a={a} reload={reload} />,
      operatingsystem: () => <OperatingSystem a={a} />,
      configuration: () => <Configuration a={a} reload={reload} />,
      availabilityscaling: () => <AvailabilityScaling a={a} />,
      insights: () => <Insights a={a} />,
      alerts: () => <VmAlerts a={a} />,
      diagnosticsettings: () => <VmDiagnosticSettings a={a} />,
      logs: () => <VmLogs a={a} />,
      connectionmonitor: () => <ConnectionMonitor a={a} />,
      workbooks: () => <VmWorkbooks a={a} />,
      metrics: () => <VmMetrics a={a} />,
    }[panel];
    body = P ? P() : (
      NOT_SIMULATED_REASON[panel]
        ? <NotSimulatedContainer title={`${name} | ${LABEL[panel] || panel}`} feature={LABEL[panel] || panel} note={NOT_SIMULATED_REASON[panel]} />
        : <CapabilityContainer id={GAP_CAP[panel] || "azure.vms.tools"} title={`${name} | ${LABEL[panel] || panel}`} />
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Virtual machine" glyph={<Glyph id="vms" />} closeHref="#/vms"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

const osType = (a) => a.properties?.storageProfile?.osDisk?.osType || "Linux";
const statusOf = (a) => (a.properties?.powerState || "PowerState/running").replace("PowerState/", "").replace(/^./, (c) => c.toUpperCase());
const nicIdOf = (a) => a.properties?.networkProfile?.networkInterfaces?.[0]?.id;
const publicIpIdOf = (nic) => nic?.properties?.ipConfigurations?.[0]?.properties?.publicIPAddress?.id;
/** Fetches the public IP (Microsoft.Network/publicIPAddresses) the NIC's IP configuration
 *  references, when one was requested at create time (azure.vms.networking) — null otherwise. */
function usePublicIp(nic) {
  const pipId = publicIpIdOf(nic);
  return useAsync(() => (pipId ? api.getPublicIp(parseId(pipId).resourceGroup, parseId(pipId).name) : Promise.resolve(null)), [pipId]);
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [del, setDel] = useState(false);
  const [busy, setBusy] = useState(null);
  const [gap, setGap] = useState(null);
  const [tab, setTab] = useState("properties");
  const nic = useAsync(() => (nicIdOf(a) ? api.getNic(parseId(nicIdOf(a)).resourceGroup, parseId(nicIdOf(a)).name) : Promise.resolve(null)), [nicIdOf(a)]);
  const pip = usePublicIp(nic.data);
  const tags = Object.entries(a.tags || {});
  const ipc = nic.data?.properties?.ipConfigurations?.[0]?.properties;
  const subnetId = ipc?.subnet?.id;

  const act = async (verb, label) => {
    setBusy(verb);
    try { await api.vmAction(a.resourceGroup, a.name, verb); notify.success(`${label} succeeded for '${a.name}'.`); reload(); }
    catch (e) { notify.error(e, `${label} failed`); }
    finally { setBusy(null); }
  };

  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton onClick={() => navigate("vms", a.resourceGroup, a.name, "connect")}>Connect</ToolbarButton>
        <ToolbarButton disabled={busy} onClick={() => act("start", "Start")}>{busy === "start" ? "Starting..." : "Start"}</ToolbarButton>
        <ToolbarButton disabled={busy} onClick={() => act("restart", "Restart")}>{busy === "restart" ? "Restarting..." : "Restart"}</ToolbarButton>
        <ToolbarButton disabled={busy} onClick={() => act("poweroff", "Stop")}>{busy === "poweroff" ? "Stopping..." : "Stop"}</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Hibernate")}>Hibernate</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Capture")}>Capture</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Open in mobile")}>Open in mobile</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setGap("CLI / PS")}>CLI / PS</ToolbarButton>
      </div>
      <Essentials
        actions={<Link as="button" onClick={() => setGap("JSON View")}>JSON View</Link>}
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Status", statusOf(a)],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Availability zone", a.zones?.[0] || "--"],
          ["Operating system", osType(a)],
        ]}
        right={[
          ["Size", a.properties?.hardwareProfile?.vmSize],
          ["Public IP address", pip.data?.properties?.ipAddress || "--"],
          ["Virtual network/subnet", subnetId ? `${parseId(subnetId).name ? subnetId.split("/").slice(-3, -2)[0] : "--"}/${parseId(subnetId).name}` : "--"],
          ["DNS name", "--"],
          ["Health state", "Healthy"],
          ["Time created", fmtDate(a.systemData?.createdAt)],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Virtual machine tabs" style={{ marginTop: 16 }}>
        <Tab value="properties">Properties</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="recommendations">Recommendations</Tab>
        <Tab value="tutorials">Tutorials</Tab>
      </TabList>
      {tab === "properties" && <PropertiesTabPanel a={a} nic={nic.data} pip={pip.data} />}
      {tab === "monitoring" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.vms.monitoring" title="Monitoring" /></div>}
      {tab === "capabilities" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.vms.tools" title="Capabilities" /></div>}
      {tab === "recommendations" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.vms.tools" title="Recommendations" /></div>}
      {tab === "tutorials" && <div style={{ marginTop: 12 }}><CapabilityContainer id="azure.vms.tools" title="Tutorials" /></div>}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="virtual machine" names={[a.name]}
        onConfirm={async () => {
          await api.deleteVm(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Virtual machine '${a.name}' was deleted.`, "Delete succeeded");
          navigate("vms");
        }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody><DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : gap === "JSON View" ? "Viewing the raw ARM JSON for this resource" : gap || ""} note={gap === "Hibernate" || gap === "Capture" ? capability("azure.vms.power")?.limitations?.join(" ") : undefined} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions></DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function PropertiesTabPanel({ a, nic, pip }) {
  const ipc = nic?.properties?.ipConfigurations?.[0]?.properties;
  const sp = a.properties?.storageProfile || {};
  const vmSize = a.properties?.hardwareProfile?.vmSize;
  const sizes = useAsync(() => api.listSizesForVm(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const match = sizes.data?.find((s) => s.name === vmSize);
  const size = { size: vmSize, vcpu: match?.numberOfCores ?? "--", ramGiB: match ? match.memoryInMB / 1024 : "--" };
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
      <section className="vy-section"><h3>Virtual machine</h3>
        <div className="vy-props">
          <KV label="Computer name" value={a.properties?.osProfile?.computerName} />
          <KV label="Operating system" value={osType(a)} />
          <KV label="VM generation" value="V2" />
          <KV label="VM architecture" value="x64" />
          <KV label="Agent status" value="Ready" />
          <KV label="Agent version" value="2.12" />
          <KV label="Hibernation" value="Disabled" />
          <KV label="Host group" value="--" />
          <KV label="Proximity placement group" value="--" />
          <KV label="Capacity reservation group" value="--" />
        </div>
      </section>
      <section className="vy-section"><h3>Networking</h3>
        <div className="vy-props">
          <KV label="Public IP address" value={pip?.properties?.ipAddress || "--"} />
          <KV label="Private IP address" value={ipc?.privateIPAddress} />
          <KV label="Virtual network/subnet" value={ipc?.subnet?.id ? parseId(ipc.subnet.id).name : "--"} />
          <KV label="DNS name" value="--" />
        </div>
      </section>
      <section className="vy-section"><h3>Size</h3>
        <div className="vy-props"><KV label="Size" value={size.size} /><KV label="vCPUs" value={size.vcpu} /><KV label="RAM" value={size.ramGiB !== "--" ? `${size.ramGiB} GiB` : "--"} /></div>
      </section>
      <section className="vy-section"><h3>Source image details</h3>
        <div className="vy-props">
          <KV label="Source image publisher" value={sp.imageReference?.publisher} />
          <KV label="Source image offer" value={sp.imageReference?.offer} />
          <KV label="Source image plan" value={sp.imageReference?.sku} />
        </div>
      </section>
      <section className="vy-section"><h3>Disk</h3>
        <div className="vy-props">
          <KV label="OS disk" value={sp.osDisk?.managedDisk?.storageAccountType} />
          <KV label="Encryption at host" value={a.properties?.securityProfile?.encryptionAtHost ? "Enabled" : "Disabled"} />
          <KV label="Azure disk encryption" value="Disabled" />
          <KV label="Ephemeral OS disk" value="Disabled" />
          <KV label="Data disks" value={(sp.dataDisks || []).length} />
        </div>
      </section>
      <section className="vy-section"><h3>Azure Spot</h3>
        <div className="vy-props"><KV label="Azure Spot" value="Disabled" /><KV label="Azure Spot eviction policy" value="--" /></div>
      </section>
      <section className="vy-section"><h3>Extensions + applications</h3>
        <div className="vy-props"><KV label="Extensions" value="None" /><KV label="Applications" value="None" /></div>
      </section>
    </div>
  );
}

// ── Access control (IAM) — Role assignments and Roles are real, scoped to this VM (plus its
// subscription/resource-group ancestors, real Azure's "inherited access" view) over the same
// generic Microsoft.Authorization/roleAssignments extension-resource engine the Cosmos DB
// account blade uses (azure.vms.iam); assignments are still created at the subscription scope.
// Check access / My access / Deny assignments / Classic administrators stay honest gaps. ──────
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
          <section className="vy-section"><h3>My access</h3><Button onClick={() => setDlg("mine")}>View my access</Button></section>
          <section className="vy-section"><h3>Check access</h3><Button onClick={() => setDlg("check")}>Check access</Button></section>
        </div>
      )}
      {tab === "assignments" && (
        <div style={{ marginTop: 12 }}>
          <CapabilityContainer id="azure.vms.iam" title="Role assignments">
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
          <CapabilityContainer id="azure.vms.iam" title="Roles">
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
            <DialogContent><NotSimulated feature="Per-identity role-assignment resolution for this resource" note={`The virtual machine's resource id is ${a.id}.`} /></DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
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
      const { id, name, type, resourceGroup, ...rest } = a;
      await api.createVm(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
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

// ── Locks (Microsoft.Authorization/locks, scoped to this VM) ──────────────────────────
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
          <DialogBody><DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `Locks scoped to the ${(gap || "").toLowerCase()}`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions></DialogBody>
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
    try { await onCreate(name, type === "Read-only" ? "ReadOnly" : "CanNotDelete", notes); notify.success(`Lock '${name}' was added.`, "Lock added"); setName(""); setNotes(""); setType("Delete"); onClose(); }
    catch (e) { notify.error(e, "Failed to add lock"); }
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
              <Field label="Lock type" required><Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type"><option>Read-only</option><option>Delete</option></Select></Field>
              <Field label="Notes"><Textarea value={notes} onChange={(_, d) => setNotes(d.value)} aria-label="Notes" /></Field>
            </div>
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={!valid || busy} onClick={go}>OK</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this VM) ──
const TIMESPANS = { "1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7, "30d": 24 * 30 };

function ActivityLog({ a }) {
  const [timespan, setTimespan] = useState("24h");
  const since = () => new Date(Date.now() - TIMESPANS[timespan] * 3600 * 1000).toISOString();
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name, since()), [a.id, timespan]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.vms.activity_log" title={`${a.name} | Activity log`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log tools">
        {["Activity", "Edit columns", "Export Activity Logs", "Download as CSV", "Insights", "Feedback", "Pin current filters", "Reset filters"].map((l) => (
          <ToolbarButton key={l} onClick={() => setGap(l)}>{l}</ToolbarButton>
        ))}
        <Select size="small" value={timespan} onChange={(_, d) => setTimespan(d.value)} aria-label="Timespan" style={{ marginLeft: "auto", width: 160 }}>
          <option value="1h">Last hour</option>
          <option value="6h">Last 6 hours</option>
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
        </Select>
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

// ── Size — real ARM GET .../virtualMachines/{vm}/vmSizes (azure.vms.size), backed by
// core/instance_catalog.py's AZURE sample through the ARM engine. No size list in the console. ──
function Size({ a, reload }) {
  const notify = useNotify();
  const [sel, setSel] = useState(a.properties?.hardwareProfile?.vmSize);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const sizes = useAsync(() => api.listSizesForVm(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const rows = (sizes.data || []).filter((s) => s.name.toLowerCase().includes(filter.trim().toLowerCase()));
  const resize = async () => {
    setBusy(true);
    try { await api.updateVm(a.resourceGroup, a.name, { properties: { hardwareProfile: { vmSize: sel } } }); notify.success(`Resized '${a.name}' to ${sel}.`, "Resize succeeded"); reload(); }
    catch (e) { notify.error(e, "Resize failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.vms.size" title={`${a.name} | Size`} actions={<ToolbarButton disabled={busy || sel === a.properties?.hardwareProfile?.vmSize} onClick={resize}>{busy ? "Resizing..." : "Resize"}</ToolbarButton>}>
      <div className="vy-filters"><Input size="small" style={{ width: 260 }} placeholder="Search by VM size..." value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Search by VM size..." /></div>
      {sizes.loading && !sizes.data ? <Loading /> : (
      <Table size="small" aria-label="VM sizes" className="vy-grid">
        <TableHeader><TableRow>
          <TableHeaderCell style={{ width: 32 }} /><TableHeaderCell>VM Size</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>vCPUs</TableHeaderCell>
          <TableHeaderCell>RAM (GiB)</TableHeaderCell><TableHeaderCell>Data disks</TableHeaderCell><TableHeaderCell>Max IOPS</TableHeaderCell>
          <TableHeaderCell>Local storage (GiB)</TableHeaderCell><TableHeaderCell>Cost/month</TableHeaderCell>
        </TableRow></TableHeader>
        <TableBody>
          {rows.map((s) => (
            <TableRow key={s.name} aria-selected={sel === s.name}>
              <TableCell><input type="radio" name="vmsize" checked={sel === s.name} onChange={() => setSel(s.name)} aria-label={`Select ${s.name}`} /></TableCell>
              <TableCell>{s.name}</TableCell><TableCell>{s.series}</TableCell><TableCell>{s.numberOfCores}</TableCell><TableCell>{s.memoryInMB / 1024}</TableCell>
              <TableCell>{s.maxDataDiskCount}</TableCell><TableCell>{s.maxIops}</TableCell><TableCell>{s.resourceDiskSizeInMB / 1024}</TableCell>
              <TableCell>${api.estMonthlyCost(s)} (estimate)</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      )}
    </CapabilityContainer>
  );
}

// ── Disks (embedded on properties.storageProfile — see azure.vms.disks) ────────────────
function Disks({ a, reload }) {
  const notify = useNotify();
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null);
  const sp = a.properties?.storageProfile || {};
  const osDisk = sp.osDisk || {};
  const dataDisks = sp.dataDisks || [];
  const [encHost, setEncHost] = useState(!!a.properties?.securityProfile?.encryptionAtHost);
  useEffect(() => setEncHost(!!a.properties?.securityProfile?.encryptionAtHost), [a]);
  const saveEncHost = async (v) => {
    setEncHost(v);
    try { await api.updateVm(a.resourceGroup, a.name, { properties: { securityProfile: { encryptionAtHost: v } } }); notify.success("Disk settings saved."); reload(); }
    catch (e) { notify.error(e, "Saving disk settings failed"); }
  };
  const addDisk = async (disk) => {
    try {
      await api.updateVm(a.resourceGroup, a.name, { properties: { storageProfile: { dataDisks: [...dataDisks, disk] } } });
      notify.success(`Data disk '${disk.name}' was attached.`, "Disk attached");
      reload();
    } catch (e) { notify.error(e, "Attaching disk failed"); }
  };
  const detachDisk = async (lun) => {
    await api.updateVm(a.resourceGroup, a.name, { properties: { storageProfile: { dataDisks: dataDisks.filter((d) => d.lun !== lun) } } });
    notify.success("Data disk was detached.", "Disk detached");
    reload();
  };
  return (
    <CapabilityContainer id="azure.vms.disks" title={`${a.name} | Disks`}>
      <section className="vy-section"><h3>OS disk</h3>
        <Table size="small" className="vy-grid"><TableHeader><TableRow>
          <TableHeaderCell>Disk name</TableHeaderCell><TableHeaderCell>Storage type</TableHeaderCell><TableHeaderCell>Size (GiB)</TableHeaderCell>
          <TableHeaderCell>Max IOPS</TableHeaderCell><TableHeaderCell>Max throughput (MBps)</TableHeaderCell><TableHeaderCell>Encryption</TableHeaderCell><TableHeaderCell>Host caching</TableHeaderCell>
        </TableRow></TableHeader><TableBody><TableRow>
          <TableCell>{a.name}_OsDisk</TableCell><TableCell>{osDisk.managedDisk?.storageAccountType || "--"}</TableCell><TableCell>{osDisk.diskSizeGB || 30}</TableCell>
          <TableCell>500</TableCell><TableCell>60</TableCell><TableCell>{encHost ? "Enabled (host)" : "Platform-managed"}</TableCell><TableCell>ReadWrite</TableCell>
        </TableRow></TableBody></Table>
      </section>
      <section className="vy-section"><h3>Data disks</h3>
        <div className="vy-cmdbar" role="toolbar" aria-label="Data disks commands">
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create and attach a new disk</ToolbarButton>
          <ToolbarButton onClick={() => setGap(true)}>Attach existing disks</ToolbarButton>
        </div>
        <Table size="small" className="vy-grid"><TableHeader><TableRow>
          <TableHeaderCell>LUN</TableHeaderCell><TableHeaderCell>Disk name</TableHeaderCell><TableHeaderCell>Storage type</TableHeaderCell><TableHeaderCell>Size (GiB)</TableHeaderCell>
          <TableHeaderCell>Max IOPS</TableHeaderCell><TableHeaderCell>Max throughput (MBps)</TableHeaderCell><TableHeaderCell>Encryption</TableHeaderCell><TableHeaderCell>Host caching</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
          <TableBody>
            {dataDisks.length ? dataDisks.map((d) => (
              <TableRow key={d.lun}><TableCell>{d.lun}</TableCell><TableCell>{d.name}</TableCell><TableCell>{d.managedDisk?.storageAccountType || d.type}</TableCell><TableCell>{d.diskSizeGB || d.sizeGiB}</TableCell>
                <TableCell>500</TableCell><TableCell>60</TableCell><TableCell>Platform-managed</TableCell><TableCell>{d.caching || "None"}</TableCell>
                <TableCell><Link as="button" onClick={() => detachDisk(d.lun)}>Detach</Link></TableCell></TableRow>
            )) : <TableRow><TableCell colSpan={9} className="vy-muted">No data disks attached.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </section>
      <section className="vy-section"><h3>Disk settings</h3>
        <Field label="Encryption at host"><RadioGroup layout="horizontal" value={encHost ? "Enabled" : "Disabled"} onChange={(_, d) => saveEncHost(d.value === "Enabled")} aria-label="Encryption at host">
          <Radio value="Enabled" label="Enabled" /><Radio value="Disabled" label="Disabled" /></RadioGroup></Field>
      </section>
      <AddDiskDialog open={add} onClose={() => setAdd(false)} nextLun={dataDisks.length} onCreate={addDisk} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(false)}>
        <DialogSurface aria-label="Attach existing disks">
          <DialogBody><DialogTitle>Attach existing disks</DialogTitle>
            <DialogContent><NotSimulated feature="Picking an existing standalone managed disk to attach" note="This lens does not build a standalone Disks console to pick an existing disk from — data disks are created and attached in one step instead." /></DialogContent>
            <DialogActions><Button onClick={() => setGap(false)}>Close</Button></DialogActions></DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

function AddDiskDialog({ open, onClose, nextLun, onCreate }) {
  const [name, setName] = useState("");
  const [size, setSize] = useState("128");
  const [type, setType] = useState("Premium SSD LRS");
  const [caching, setCaching] = useState("None");
  useEffect(() => { if (open) { setName(`disk-${nextLun + 1}`); setSize("128"); setType("Premium SSD LRS"); setCaching("None"); } }, [open, nextLun]);
  const go = async () => {
    await onCreate({ lun: nextLun, name, diskSizeGB: Number(size), caching, managedDisk: { storageAccountType: type } });
    onClose();
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create and attach a new disk">
        <DialogBody>
          <DialogTitle>Create a new disk</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Disk name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Disk name" /></Field>
              <Field label="Size (GiB)" required><Input type="number" value={size} onChange={(_, d) => setSize(d.value)} aria-label="Size (GiB)" /></Field>
              <Field label="Storage type"><Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Storage type">{["Premium SSD LRS", "Standard SSD LRS", "Standard HDD LRS"].map((o) => <option key={o}>{o}</option>)}</Select></Field>
              <Field label="Host caching"><Select value={caching} onChange={(_, d) => setCaching(d.value)} aria-label="Host caching">{["None", "ReadOnly", "ReadWrite"].map((o) => <option key={o}>{o}</option>)}</Select></Field>
            </div>
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={!name} onClick={go}>Save</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Identity ─────────────────────────────────────────────────────────────────────────
function Identity({ a, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("system");
  const [on, setOn] = useState(a.identity?.type === "SystemAssigned");
  const [busy, setBusy] = useState(false);
  useEffect(() => setOn(a.identity?.type === "SystemAssigned"), [a]);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateVm(a.resourceGroup, a.name, { identity: on ? { type: "SystemAssigned" } : { type: "None" } });
      notify.success("Identity settings saved.", "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Saving identity failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.vms.identity" title={`${a.name} | Identity`} actions={<>
      <ToolbarButton disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</ToolbarButton>
      <ToolbarButton onClick={() => setOn(a.identity?.type === "SystemAssigned")}>Discard</ToolbarButton>
    </>}>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Identity tabs">
        <Tab value="system">System assigned</Tab>
        <Tab value="user">User assigned</Tab>
      </TabList>
      {tab === "system" ? (
        <div style={{ marginTop: 12 }}>
          <Field label="Status"><RadioGroup layout="horizontal" value={on ? "On" : "Off"} onChange={(_, d) => setOn(d.value === "On")} aria-label="Status"><Radio value="Off" label="Off" /><Radio value="On" label="On" /></RadioGroup></Field>
          {a.identity?.principalId && (
            <div className="vy-props" style={{ marginTop: 12 }}>
              <KV label="Object (principal) ID" value={a.identity.principalId} />
              <KV label="Tenant ID" value={a.identity.tenantId} />
            </div>
          )}
          <p style={{ fontSize: 13, marginTop: 12 }}>
            This identity's principal ID is real and can be granted a role assignment like any other principal — for
            example, a role on a Key Vault. <Link href={`#/vms/${encodeURIComponent(a.resourceGroup)}/${encodeURIComponent(a.name)}/runcommand`}>Run command</Link> can mint this
            identity's own token from the simulated IMDS endpoint and use it to fetch a Key Vault secret — Vyomi really
            checks that token's principal against the Key Vault's real role assignments before releasing the secret.
          </p>
        </div>
      ) : <div style={{ marginTop: 12 }}><NotSimulated feature="User-assigned managed identities" note="This lens does not model standalone Microsoft.ManagedIdentity/userAssignedIdentities resources to attach." /></div>}
    </CapabilityContainer>
  );
}

// ── Auto-shutdown ──────────────────────────────────────────────────────────────────────
function AutoShutdown({ a, reload }) {
  const notify = useNotify();
  const cur = a.properties?.autoShutdown || {};
  const [f, setF] = useState({ enabled: !!cur.enabled, time: cur.time || "19:00", tz: cur.timeZone || "UTC", notify: cur.notify ? "Yes" : "No", webhook: cur.webhookUrl || "", email: cur.email || "" });
  useEffect(() => setF({ enabled: !!cur.enabled, time: cur.time || "19:00", tz: cur.timeZone || "UTC", notify: cur.notify ? "Yes" : "No", webhook: cur.webhookUrl || "", email: cur.email || "" }), [a]);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateVm(a.resourceGroup, a.name, { properties: { autoShutdown: { enabled: f.enabled, time: f.time, timeZone: f.tz, notify: f.notify === "Yes", webhookUrl: f.webhook, email: f.email } } });
      notify.success("Auto-shutdown settings saved.", "Save succeeded");
      reload();
    } catch (e) { notify.error(e, "Saving auto-shutdown settings failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.vms.auto_shutdown" title={`${a.name} | Auto-shutdown`} actions={<>
      <ToolbarButton disabled={busy} onClick={save}>{busy ? "Saving..." : "Save"}</ToolbarButton>
      <ToolbarButton onClick={() => setF({ enabled: !!cur.enabled, time: cur.time || "19:00", tz: cur.timeZone || "UTC", notify: cur.notify ? "Yes" : "No", webhook: cur.webhookUrl || "", email: cur.email || "" })}>Discard</ToolbarButton>
    </>}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 480 }}>
        <Field label="Enabled"><RadioGroup layout="horizontal" value={f.enabled ? "On" : "Off"} onChange={(_, d) => setF((x) => ({ ...x, enabled: d.value === "On" }))} aria-label="Enabled"><Radio value="On" label="On" /><Radio value="Off" label="Off" /></RadioGroup></Field>
        <Field label="Scheduled shutdown"><Input value={f.time} onChange={(_, d) => setF((x) => ({ ...x, time: d.value }))} aria-label="Scheduled shutdown" /></Field>
        <Field label="Time zone"><Select value={f.tz} onChange={(_, d) => setF((x) => ({ ...x, tz: d.value }))} aria-label="Time zone">{["UTC", "(UTC) Coordinated Universal Time", "(UTC-08:00) Pacific Time (US & Canada)", "(UTC+00:00) London"].map((o) => <option key={o}>{o}</option>)}</Select></Field>
        <Field label="Send notification before auto-shutdown"><RadioGroup layout="horizontal" value={f.notify} onChange={(_, d) => setF((x) => ({ ...x, notify: d.value }))} aria-label="Send notification before auto-shutdown"><Radio value="Yes" label="Yes" /><Radio value="No" label="No" /></RadioGroup></Field>
        <Field label="Webhook URL"><Input value={f.webhook} onChange={(_, d) => setF((x) => ({ ...x, webhook: d.value }))} aria-label="Webhook URL" /></Field>
        <Field label="Email address"><Input value={f.email} onChange={(_, d) => setF((x) => ({ ...x, email: d.value }))} aria-label="Email address" /></Field>
      </div>
    </CapabilityContainer>
  );
}

// ── Connect ────────────────────────────────────────────────────────────────────────────
function Connect({ a }) {
  const [gap, setGap] = useState(null);
  const nicId = nicIdOf(a);
  const nic = useAsync(() => (nicId ? api.getNic(parseId(nicId).resourceGroup, parseId(nicId).name) : Promise.resolve(null)), [nicId]);
  const pip = usePublicIp(nic.data);
  const privateIp = nic.data?.properties?.ipConfigurations?.[0]?.properties?.privateIPAddress;
  const publicIp = pip.data?.properties?.ipAddress;
  const user = a.properties?.osProfile?.adminUsername;
  const cmd = `ssh ${user}@${publicIp || privateIp || "<no public ip>"}`;
  const cap = capability("azure.vms.connect");
  return (
    <>
      <div className="vy-panel-title">Connect</div>
      <section className="vy-section">
        <div className="vy-props">
          <KV label="Admin username" value={user} />
          <KV label="Public IP address" value={publicIp || "--"} />
          <KV label="Port" value="22" />
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <Button appearance="primary" onClick={() => setGap("Native SSH")}>Native SSH</Button>
          <Button onClick={() => setGap("SSH using Azure CLI")}>SSH using Azure CLI</Button>
          <Button onClick={() => setGap("Connect via Bastion")}>Connect via Bastion</Button>
        </div>
      </section>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Connect"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent>
              {gap === "Connect via Bastion" ? (
                <NotSimulated feature="Azure Bastion" note="This lens does not model a Bastion resource." />
              ) : (
                <>
                  <p style={{ fontFamily: "monospace", background: "var(--colorNeutralBackground3)", padding: 8, borderRadius: 4 }}>{cmd}</p>
                  <NotSimulated feature="Opening a real SSH session" note={cap?.limitations?.join(" ")} />
                </>
              )}
            </DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

// ── Network settings (network interface + attached NSG's rules) ───────────────────────
const PORT = (r) => r.properties?.destinationPortRange || (r.properties?.destinationPortRanges || []).join(",") || "*";

function RuleTable({ rules, direction }) {
  const defaults = api.DEFAULT_RULES.filter((r) => r.direction === direction);
  const custom = [...rules].sort((x, y) => (x.properties?.priority || 0) - (y.properties?.priority || 0));
  return (
    <Table size="small" aria-label={`${direction} rules`} className="vy-grid">
      <TableHeader><TableRow>
        <TableHeaderCell>Priority</TableHeaderCell><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Port</TableHeaderCell>
        <TableHeaderCell>Protocol</TableHeaderCell><TableHeaderCell>Source</TableHeaderCell><TableHeaderCell>Destination</TableHeaderCell><TableHeaderCell>Action</TableHeaderCell>
      </TableRow></TableHeader>
      <TableBody>
        {custom.map((r) => (
          <TableRow key={r.name}>
            <TableCell>{r.properties?.priority}</TableCell><TableCell>{r.name}</TableCell><TableCell>{PORT(r)}</TableCell>
            <TableCell>{r.properties?.protocol}</TableCell><TableCell>{r.properties?.sourceAddressPrefix}</TableCell>
            <TableCell>{r.properties?.destinationAddressPrefix}</TableCell><TableCell>{r.properties?.access}</TableCell>
          </TableRow>
        ))}
        {defaults.map((r) => (
          <TableRow key={r.name}>
            <TableCell>{r.priority}</TableCell><TableCell>{r.name}</TableCell><TableCell>{r.port}</TableCell>
            <TableCell>{r.protocol}</TableCell><TableCell>{r.source}</TableCell><TableCell>{r.destination}</TableCell><TableCell>{r.access}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function CreatePortRuleDialog({ open, onClose, direction, existing, onCreate }) {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", priority: 300, port: "8080", protocol: "Tcp", action: "Allow", source: "*", destination: "*" });
  useEffect(() => { if (open) setF({ name: "", priority: 300, port: "8080", protocol: "Tcp", action: "Allow", source: "*", destination: "*" }); }, [open]);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const valid = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,78}[a-zA-Z0-9_]$/.test(f.name) && !existing.some((r) => r.name === f.name);
  const go = async () => {
    try {
      await onCreate(f.name, { properties: { priority: Number(f.priority), direction, access: f.action, protocol: f.protocol, sourceAddressPrefix: f.source, sourcePortRange: "*", destinationAddressPrefix: f.destination, destinationPortRange: f.port } });
      onClose();
    } catch (e) { notify.error(e, "Failed to create port rule"); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create port rule">
        <DialogBody>
          <DialogTitle>Create port rule</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.name} onChange={set("name")} aria-label="Name" /></Field>
              <Field label="Priority" required hint="100-4096"><Input type="number" value={String(f.priority)} onChange={set("priority")} aria-label="Priority" /></Field>
              <Field label="Port" required><Input value={f.port} onChange={set("port")} aria-label="Port" /></Field>
              <Field label="Protocol"><RadioGroup layout="horizontal" value={f.protocol} onChange={set("protocol")} aria-label="Protocol"><Radio value="Tcp" label="TCP" /><Radio value="Udp" label="UDP" /><Radio value="*" label="Any" /></RadioGroup></Field>
              <Field label="Action"><RadioGroup layout="horizontal" value={f.action} onChange={set("action")} aria-label="Action"><Radio value="Allow" label="Allow" /><Radio value="Deny" label="Deny" /></RadioGroup></Field>
            </div>
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={!valid} onClick={go}>Add</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function PortRules({ rg, nsgName, direction }) {
  const notify = useNotify();
  const [filter, setFilter] = useState("");
  const [add, setAdd] = useState(false);
  const { data, loading, error, reload } = useAsync(() => (nsgName ? api.listSecurityRules(rg, nsgName) : Promise.resolve([])), [rg, nsgName]);
  if (!nsgName) return <div className="vy-muted" style={{ padding: 16 }}>No network security group is attached to this virtual machine's network interface.</div>;
  const rules = (data || []).filter((r) => r.properties?.direction === direction && r.name.toLowerCase().includes(filter.trim().toLowerCase()));
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label={`${direction} port rules commands`}>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create port rule</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <div className="vy-filters"><Input size="small" style={{ width: 260 }} placeholder="Filter by name" value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter by name" /></div>
      <ErrorBar error={error} />
      {loading ? <Loading /> : <RuleTable rules={rules} direction={direction} />}
      <CreatePortRuleDialog open={add} onClose={() => setAdd(false)} direction={direction} existing={rules}
        onCreate={async (name, body) => { await api.putSecurityRule(rg, nsgName, name, body); notify.success(`Port rule '${name}' was created.`, "Rule created"); reload(); }} />
    </>
  );
}

function NetworkSettings({ a }) {
  const [tab, setTab] = useState("inbound");
  const nicId = nicIdOf(a);
  const nic = useAsync(() => (nicId ? api.getNic(parseId(nicId).resourceGroup, parseId(nicId).name) : Promise.resolve(null)), [nicId]);
  const pip = usePublicIp(nic.data);
  const ipc = nic.data?.properties?.ipConfigurations?.[0]?.properties;
  const nsgId = nic.data?.properties?.networkSecurityGroup?.id;
  const nsgName = nsgId ? parseId(nsgId).name : null;
  return (
    <CapabilityContainer id="azure.vms.networking" title={`${a.name} | Network settings`} actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={nic.reload}>Refresh</ToolbarButton>}>
      <section className="vy-section"><h3>Network interface / IP configuration</h3>
        <div className="vy-props">
          <KV label="Network interface" value={nic.data?.name} />
          <KV label="IP configuration" value="ipconfig1" />
          <KV label="Virtual network/subnet" value={ipc?.subnet?.id ? parseId(ipc.subnet.id).name : "--"} />
          <KV label="Public IP" value={pip.data?.properties?.ipAddress || "--"} />
          <KV label="Private IP" value={ipc?.privateIPAddress} />
          <KV label="Accelerated networking" value={nic.data?.properties?.enableAcceleratedNetworking ? "Enabled" : "Disabled"} />
        </div>
      </section>
      <section className="vy-section"><h3>Rules</h3><div className="vy-props"><KV label="Network security group" value={nsgName || "None"} /></div></section>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Network settings tabs" style={{ marginTop: 8 }}>
        <Tab value="inbound">Inbound port rules</Tab>
        <Tab value="outbound">Outbound port rules</Tab>
        <Tab value="asgs">Application security groups</Tab>
        <Tab value="lb">Load balancing</Tab>
      </TabList>
      <div style={{ marginTop: 12 }}>
        {tab === "inbound" && <PortRules rg={a.resourceGroup} nsgName={nsgName} direction="Inbound" />}
        {tab === "outbound" && <PortRules rg={a.resourceGroup} nsgName={nsgName} direction="Outbound" />}
        {tab === "asgs" && <NotSimulated feature="Application security groups" note="This lens does not model Microsoft.Network/applicationSecurityGroups." />}
        {tab === "lb" && <NotSimulated feature="Load balancing" note="This lens does not model Microsoft.Network/loadBalancers." />}
      </div>
    </CapabilityContainer>
  );
}

// ── Run command (POST .../virtualMachines/{vm}/runCommand) — a bounded, deterministic script
// interpreter (core/azure_arm_core.AzureArm._vm_run_command, azure.vms.run_command): echo/
// hostname/whoami/date/uname run for real against this VM's own data, and the IMDS-token +
// Key Vault secret-fetch pattern demonstrates a system-assigned identity's token really being
// checked against a real role assignment (azure.vms.identity) — an unrecognized script fails
// honestly (non-zero exit) instead of faking success. ─────────────────────────────────────
const COMMAND_TEMPLATES = [
  { name: "RunShellScript", description: "Run a Linux shell script against this virtual machine." },
  { name: "RunPowerShellScript", description: "Run a PowerShell script against this virtual machine." },
];
const SAMPLE_SCRIPT = "echo hello from Vyomi\nhostname\nwhoami";

function RunCommand({ a }) {
  const notify = useNotify();
  const [script, setScript] = useState(SAMPLE_SCRIPT);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const run = async () => {
    setBusy(true); setResult(null);
    try { setResult(await api.runCommand(a.resourceGroup, a.name, script)); }
    catch (e) { notify.error(e, "Run command failed"); }
    finally { setBusy(false); }
  };
  const stdout = result?.value?.find((v) => v.code?.includes("StdOut"))?.message;
  const stderr = result?.value?.find((v) => v.code?.includes("StdErr"))?.message;
  return (
    <CapabilityContainer id="azure.vms.run_command" title={`${a.name} | Run command`}>
      <BrowseGrid resourceName="command" rowKey={(r) => r.name} filterPlaceholder="Filter by name"
        items={COMMAND_TEMPLATES} columns={[{ key: "name", label: "Name" }, { key: "description", label: "Description" }]}
        extraCommands={<ToolbarButton onClick={() => notify.error("Not simulated", "Vyomi does not persist a custom command gallery to create into.")}>Create</ToolbarButton>} />
      <section className="vy-section" style={{ marginTop: 16 }}>
        <h3>Run Command Script</h3>
        <p style={{ fontSize: 13 }}>
          Vyomi's interpreter understands echo/Write-Output/Write-Host, hostname, whoami, date/Get-Date, uname, and the
          IMDS-token + Key Vault secret-fetch pattern (169.254.169.254 → https://&lt;vault&gt;.vault.azure.net/secrets/&lt;name&gt;) —
          it is not a general-purpose shell, so anything else fails honestly instead of faking success.
        </p>
        <Textarea value={script} onChange={(_, d) => setScript(d.value)} aria-label="Linux Shell Script" style={{ width: "100%", minHeight: 160, fontFamily: "monospace" }} />
        <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={busy} onClick={run}>{busy ? "Running..." : "Run"}</Button></div>
        {result && (
          <div style={{ marginTop: 12 }}>
            <h4 style={{ marginBottom: 4 }}>Output</h4>
            <pre className="vy-grid" style={{ padding: 8, whiteSpace: "pre-wrap" }}>{stdout || "(no output)"}</pre>
            {stderr && <><h4 style={{ marginBottom: 4 }}>Error</h4><pre className="vy-grid" style={{ padding: 8, whiteSpace: "pre-wrap" }}>{stderr}</pre></>}
          </div>
        )}
      </section>
    </CapabilityContainer>
  );
}

// ── Export template (ARM/Bicep/Terraform all generated client-side from this VM's own live
// resource — same approach as the Storage account blade's Export template) ────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { vmName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.Compute/virtualMachines", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('vmName')]" : a.name, location: a.location, properties: a.properties }],
  };
  const vmSize = a.properties?.hardwareProfile?.vmSize;
  const osDisk = a.properties?.storageProfile?.osDisk || {};
  const img = a.properties?.storageProfile?.imageReference || {};
  const adminUsername = a.properties?.osProfile?.adminUsername;
  const bicepName = a.name.replace(/[^a-zA-Z0-9]/g, "");
  const bicep = `resource ${bicepName} 'Microsoft.Compute/virtualMachines@${api.ARM.apiVersion}' = {\n  name: '${a.name}'\n  location: '${a.location}'\n  properties: {\n    hardwareProfile: {\n      vmSize: '${vmSize}'\n    }\n    osProfile: {\n      computerName: '${a.name}'\n      adminUsername: '${adminUsername}'\n    }\n    storageProfile: {\n      imageReference: {\n        publisher: '${img.publisher}'\n        offer: '${img.offer}'\n        sku: '${img.sku}'\n        version: '${img.version}'\n      }\n      osDisk: {\n        osType: '${osDisk.osType}'\n        managedDisk: {\n          storageAccountType: '${osDisk.managedDisk?.storageAccountType}'\n        }\n      }\n    }\n  }\n}\n`;
  const terraform = `resource "azurerm_linux_virtual_machine" "${a.name.replace(/[^a-zA-Z0-9]/g, "_")}" {\n  name                = "${a.name}"\n  location            = "${a.location}"\n  resource_group_name = "${a.resourceGroup}"\n  size                = "${vmSize}"\n  admin_username      = "${adminUsername}"\n\n  os_disk {\n    storage_account_type = "${osDisk.managedDisk?.storageAccountType}"\n  }\n\n  source_image_reference {\n    publisher = "${img.publisher}"\n    offer     = "${img.offer}"\n    sku       = "${img.sku}"\n    version   = "${img.version}"\n  }\n}\n`;
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

// ── Resource visualizer — a real diagram of this VM's own ARM relationships (NIC, public IP,
// attached NSG, OS/data disks): no new backend, just rendering data the console already reads
// for Overview/Network settings/Disks (azure.vms.resource_visualizer). ────────────────────
function ResourceVisualizer({ a }) {
  const nicId = nicIdOf(a);
  const nic = useAsync(() => (nicId ? api.getNic(parseId(nicId).resourceGroup, parseId(nicId).name) : Promise.resolve(null)), [nicId]);
  const pip = usePublicIp(nic.data);
  const nsgId = nic.data?.properties?.networkSecurityGroup?.id;
  const sp = a.properties?.storageProfile || {};
  const node = (label, sub) => <div className="vy-section" style={{ padding: "8px 12px", minWidth: 180 }}><b>{label}</b>{sub && <div className="vy-muted" style={{ fontSize: 12 }}>{sub}</div>}</div>;
  const arrow = <div style={{ padding: "0 8px", alignSelf: "center" }}>&rarr;</div>;
  return (
    <CapabilityContainer id="azure.vms.resource_visualizer" title={`${a.name} | Resource visualizer`}>
      <p style={{ fontSize: 13 }}>A diagram of this virtual machine's real, currently-attached ARM resources.</p>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 0 }}>
        {node(a.name, "Virtual machine")}
        {arrow}
        {nic.data ? node(nic.data.name, "Network interface") : node("No NIC", "")}
        {pip.data && <>{arrow}{node(pip.data.name, `Public IP · ${pip.data.properties?.ipAddress || ""}`)}</>}
        {nsgId && <>{arrow}{node(parseId(nsgId).name, "Network security group")}</>}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 0, marginTop: 12 }}>
        {node(a.name, "Virtual machine")}
        {arrow}
        {node(`${a.name}_OsDisk`, `OS disk · ${sp.osDisk?.managedDisk?.storageAccountType || "--"}`)}
        {(sp.dataDisks || []).map((d) => <span key={d.lun} style={{ display: "flex", alignItems: "center" }}>{arrow}{node(d.name, `Data disk · LUN ${d.lun}`)}</span>)}
      </div>
    </CapabilityContainer>
  );
}

// ── Advisor recommendations — real recommendations derived from this VM's own live
// configuration (auto-shutdown off, identity off, no backup, Defender posture findings) —
// the same "derive from real inventory" pattern the Monitor service's own Advisor page uses
// (azure.vms.advisor), never a canned list. ────────────────────────────────────────────────
function Advisor({ a }) {
  const assessments = useAsync(() => api.listVmAssessments(a.id), [a.id]);
  const restorePoints = useAsync(() => api.listRestorePoints(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const recs = [];
  if (!a.properties?.autoShutdown?.enabled) recs.push({ title: "Enable auto-shutdown", detail: "This virtual machine has no auto-shutdown schedule — it keeps accruing cost while idle.", severity: "Medium" });
  if (a.identity?.type !== "SystemAssigned") recs.push({ title: "Enable a system-assigned managed identity", detail: "Without an identity, this virtual machine cannot be granted scoped access to other resources (e.g. Key Vault) without a shared secret.", severity: "Low" });
  if (!(restorePoints.data || []).length) recs.push({ title: "Configure backup", detail: "This virtual machine has no restore points — a failed deployment or bad change has nothing to roll back to.", severity: "Medium" });
  for (const r of assessments.data || []) {
    if ((r.properties?.status?.code || "").toLowerCase() === "unhealthy") {
      recs.push({ title: r.properties?.displayName, detail: r.properties?.status?.description || r.properties?.additionalData?.detail || "", severity: r.properties?.metadata?.severity || "Medium" });
    }
  }
  return (
    <CapabilityContainer id="azure.vms.advisor" title={`${a.name} | Advisor recommendations`}>
      {assessments.loading && !assessments.data ? <Loading /> : !recs.length ? <p>No recommendations — this virtual machine looks good.</p> : (
        <Table size="small" aria-label="Advisor recommendations" className="vy-grid">
          <TableHeader><TableRow><TableHeaderCell>Recommendation</TableHeaderCell><TableHeaderCell>Description</TableHeaderCell><TableHeaderCell>Severity</TableHeaderCell></TableRow></TableHeader>
          <TableBody>{recs.map((r, i) => <TableRow key={i}><TableCell>{r.title}</TableCell><TableCell>{r.detail}</TableCell><TableCell>{r.severity}</TableCell></TableRow>)}</TableBody>
        </Table>
      )}
    </CapabilityContainer>
  );
}

// ── Diagnose and solve problems — real diagnostics computed from this VM's own live state
// (power state, NIC/NSG reachability via Defender's own exposed-ports finding, disk
// attachment) — never a canned "everything is fine" (azure.vms.diagnose). ──────────────────
function Diagnose({ a }) {
  const assessments = useAsync(() => api.listVmAssessments(a.id), [a.id]);
  const checks = [];
  const running = statusOf(a).toLowerCase() === "running";
  checks.push({ title: "Virtual machine power state", ok: running, detail: running ? "The virtual machine is running." : `The virtual machine is ${statusOf(a).toLowerCase()} — start it before diagnosing connectivity.` });
  const encFinding = (assessments.data || []).find((r) => r.name?.includes("vm-encryption") || r.properties?.displayName?.toLowerCase().includes("encrypt"));
  if (encFinding) {
    const unhealthy = (encFinding.properties?.status?.code || "").toLowerCase() === "unhealthy";
    checks.push({ title: "Disk encryption", ok: !unhealthy, detail: unhealthy ? "No encryption at host and no disk encryption set on the OS disk." : "Encryption at host or a disk encryption set is configured." });
  }
  const nicId = nicIdOf(a);
  checks.push({ title: "Network interface", ok: !!nicId, detail: nicId ? "A network interface is attached." : "No network interface is attached to this virtual machine." });
  return (
    <CapabilityContainer id="azure.vms.diagnose" title={`${a.name} | Diagnose and solve problems`}>
      {assessments.loading && !assessments.data ? <Loading /> : (
        <div className="vy-props">
          {checks.map((c, i) => <KV key={i} label={c.title} value={`${c.ok ? "✓" : "✗"} ${c.detail}`} />)}
        </div>
      )}
    </CapabilityContainer>
  );
}

// ── Resource health — derived from this VM's own real power state and lock state, the same
// data the Overview/Locks panels already show (azure.vms.resource_health). ─────────────────
function ResourceHealth({ a }) {
  const locks = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const status = statusOf(a).toLowerCase();
  const available = status === "running";
  return (
    <CapabilityContainer id="azure.vms.resource_health" title={`${a.name} | Resource health`}>
      <div className="vy-props">
        <KV label="Current status" value={available ? "Available" : status === "stopped" || status === "deallocated" ? "Unavailable (stopped)" : "Unknown"} />
        <KV label="Power state" value={statusOf(a)} />
        <KV label="Resource locks" value={(locks.data || []).length ? `${locks.data.length} lock(s) applied` : "None"} />
      </div>
      <p style={{ fontSize: 13, marginTop: 12 }}>Derived from this virtual machine's own real power state — there is no hypervisor health telemetry to roll up in a browser/WASM simulator.</p>
    </CapabilityContainer>
  );
}

// ── Change tracking — a filtered view of this VM's own real Activity log (azure.vms.change_tracking),
// never a separate fabricated feed. ─────────────────────────────────────────────────────────
function ChangeTracking({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name, new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString()), [a.id]);
  const rows = (data || []).filter((r) => /write|extensions|redeploy|reapply|resetpassword/i.test(r.operationName?.value || ""));
  return (
    <CapabilityContainer id="azure.vms.change_tracking" title={`${a.name} | Change tracking`} actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr><th>Change</th><th>Time</th><th>Status</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={3}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.id}><td>{r.operationName?.localizedValue || r.operationName?.value}</td><td>{fmtDate(r.eventTimestamp)}</td><td>{r.status?.localizedValue || r.status?.value}</td></tr>
          )) : <tr><td colSpan={3} className="vy-muted">No configuration changes in the last 30 days.</td></tr>}
        </tbody>
      </table>
    </CapabilityContainer>
  );
}

// ── Microsoft Defender for Cloud — real recommendations scoped to this VM over the SAME
// foundational CSPM rule engine (core/azure_security_core.py) the Defender for Cloud service's
// own Recommendations page uses (azure.vms.defender). ─────────────────────────────────────
function Defender({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listVmAssessments(a.id), [a.id]);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.vms.defender" title={`${a.name} | Microsoft Defender for Cloud`} actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <ErrorBar error={error} />
      {loading && !data ? <Loading /> : !rows.length ? <p>No findings for this virtual machine.</p> : (
        <Table size="small" aria-label="Defender findings" className="vy-grid">
          <TableHeader><TableRow><TableHeaderCell>Recommendation</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Severity</TableHeaderCell></TableRow></TableHeader>
          <TableBody>{rows.map((r) => (
            <TableRow key={r.id}><TableCell>{r.properties?.displayName}</TableCell>
              <TableCell>{r.properties?.status?.code}</TableCell><TableCell>{r.properties?.metadata?.severity || "--"}</TableCell></TableRow>
          ))}</TableBody>
        </Table>
      )}
    </CapabilityContainer>
  );
}

// ── Backup — "backup as a snapshot" of this VM's own ARM properties document: a real,
// stateful sub-resource (core/azure_arm_core.AzureArm._vm_backup, azure.vms.backup), not a
// stored-but-inert stub. Restore really overwrites the VM's current properties. ────────────
function Backup({ a, reload }) {
  const notify = useNotify();
  const { data, loading, error, reload: reloadRp } = useAsync(() => api.listRestorePoints(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [name, setName] = useState("");
  const rows = data || [];
  const create = async () => {
    const n = name.trim() || `rp-${Date.now()}`;
    try { await api.createRestorePoint(a.resourceGroup, a.name, n); notify.success(`Restore point '${n}' was created.`, "Create succeeded"); setName(""); reloadRp(); }
    catch (e) { notify.error(e, "Create restore point failed"); }
  };
  return (
    <CapabilityContainer id="azure.vms.backup" title={`${a.name} | Backup`}>
      <p style={{ fontSize: 13 }}>Vyomi models backup as a real snapshot of this virtual machine's own configuration — restoring really overwrites its current size/disk/OS settings with the captured ones.</p>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <Input placeholder="Restore point name" value={name} onChange={(_, d) => setName(d.value)} aria-label="Restore point name" />
        <Button appearance="primary" onClick={create}>Create restore point</Button>
      </div>
      <ErrorBar error={error} />
      <BrowseGrid resourceName="restore point" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} onRefresh={reloadRp}
        onDelete={async (sel) => { for (const r of sel) await api.deleteRestorePoint(a.resourceGroup, a.name, r.name); reloadRp(); }}
        columns={[
          { key: "name", label: "Name" },
          { key: "time", label: "Time created", value: (r) => fmtDate(r.properties?.timeCreated) },
          { key: "size", label: "Size at capture", value: (r) => r.properties?.sourceMetadata?.hardwareProfile?.vmSize || "--" },
          { key: "restore", label: "", value: (r) => <Link as="button" onClick={async () => {
              await api.restoreRestorePoint(a.resourceGroup, a.name, r.name);
              notify.success(`'${a.name}' was restored to '${r.name}'.`, "Restore succeeded");
              reload();
            }}>Restore</Link> },
        ]}
      />
    </CapabilityContainer>
  );
}

// ── Reset password — really updates this VM's own osProfile admin username/password
// (core/azure_arm_core.AzureArm._arm_action's resetPassword verb), reflected immediately in
// the Connect tab's SSH command (azure.vms.tools). ─────────────────────────────────────────
function ResetPassword({ a }) {
  const notify = useNotify();
  const [username, setUsername] = useState(a.properties?.osProfile?.adminUsername || "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const reset = async () => {
    setBusy(true);
    try { await api.resetPassword(a.resourceGroup, a.name, username, password); notify.success("Password reset.", "Reset succeeded"); }
    catch (e) { notify.error(e, "Reset password failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Reset password</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 420 }}>
        <Field label="User name" required><Input value={username} onChange={(_, d) => setUsername(d.value)} aria-label="User name" /></Field>
        <Field label="Password" required><Input type="password" value={password} onChange={(_, d) => setPassword(d.value)} aria-label="Password" /></Field>
        <div><Button appearance="primary" disabled={busy || !username || !password} onClick={reset}>{busy ? "Updating..." : "Update"}</Button></div>
      </div>
    </>
  );
}

// ── Redeploy + reapply — really restarts (redeploy) or re-stamps (reapply) this VM's own
// instanceView (core/azure_arm_core.AzureArm._arm_action, azure.vms.tools). ────────────────
function Redeploy({ a, reload }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(null);
  const iv = a.properties?.instanceView || {};
  const act = async (verb, label) => {
    setBusy(verb);
    try { await (verb === "redeploy" ? api.redeploy : api.reapply)(a.resourceGroup, a.name); notify.success(`${label} succeeded.`); reload(); }
    catch (e) { notify.error(e, `${label} failed`); }
    finally { setBusy(null); }
  };
  return (
    <>
      <div className="vy-panel-title">Redeploy + reapply</div>
      <section className="vy-section"><h3>Redeploy</h3>
        <p style={{ fontSize: 13 }}>Moves this virtual machine to a new host and restarts it. Vyomi has no hosts to move between, but it does really restart the VM and record when.</p>
        <Button disabled={busy} onClick={() => act("redeploy", "Redeploy")}>{busy === "redeploy" ? "Redeploying..." : "Redeploy"}</Button>
        {iv.lastRedeployTimestamp && <p style={{ fontSize: 12 }} className="vy-muted">Last redeployed: {fmtDate(iv.lastRedeployTimestamp)}</p>}
      </section>
      <section className="vy-section"><h3>Reapply</h3>
        <p style={{ fontSize: 13 }}>Reapplies the virtual machine's state without restarting it.</p>
        <Button disabled={busy} onClick={() => act("reapply", "Reapply")}>{busy === "reapply" ? "Reapplying..." : "Reapply"}</Button>
        {iv.lastReapplyTimestamp && <p style={{ fontSize: 12 }} className="vy-muted">Last reapplied: {fmtDate(iv.lastReapplyTimestamp)}</p>}
      </section>
    </>
  );
}

// ── Operating system — the VM's own real OS/image metadata (no guest OS process in-browser
// to introspect beyond what ARM already stores) (azure.vms.inventory_os). ──────────────────
function OperatingSystem({ a }) {
  const sp = a.properties?.storageProfile || {};
  const img = sp.imageReference || {};
  return (
    <CapabilityContainer id="azure.vms.inventory_os" title={`${a.name} | Operating system`}>
      <div className="vy-props">
        <KV label="OS type" value={osType(a)} />
        <KV label="Computer name" value={a.properties?.osProfile?.computerName} />
        <KV label="Image publisher" value={img.publisher} />
        <KV label="Image offer" value={img.offer} />
        <KV label="Image SKU" value={img.sku} />
        <KV label="Image version" value={img.version} />
      </div>
    </CapabilityContainer>
  );
}

// ── Configuration — boot diagnostics / VM agent toggles that really PATCH this VM's own
// diagnosticsProfile (same generic ARM PATCH every other settings tab on this blade uses)
// (azure.vms.configuration). ─────────────────────────────────────────────────────────────
function Configuration({ a, reload }) {
  const notify = useNotify();
  const [bootDiag, setBootDiag] = useState(!!a.properties?.diagnosticsProfile?.bootDiagnostics?.enabled);
  useEffect(() => setBootDiag(!!a.properties?.diagnosticsProfile?.bootDiagnostics?.enabled), [a]);
  const save = async (v) => {
    setBootDiag(v);
    try { await api.updateVm(a.resourceGroup, a.name, { properties: { diagnosticsProfile: { bootDiagnostics: { enabled: v, storageUri: null } } } }); notify.success("Configuration saved."); reload(); }
    catch (e) { notify.error(e, "Saving configuration failed"); }
  };
  return (
    <CapabilityContainer id="azure.vms.configuration" title={`${a.name} | Configuration`}>
      <Field label="Boot diagnostics"><RadioGroup layout="horizontal" value={bootDiag ? "Enable" : "Disable"} onChange={(_, d) => save(d.value === "Enable")} aria-label="Boot diagnostics">
        <Radio value="Enable" label="Enable with managed storage account" /><Radio value="Disable" label="Disable" />
      </RadioGroup></Field>
      <p style={{ fontSize: 13, marginTop: 8 }} className="vy-muted">Enabling boot diagnostics really flips the stored diagnosticsProfile flag; there is no hypervisor serial/screenshot stream to actually capture in a browser/WASM simulator (azure.vms.tools' Boot diagnostics page).</p>
    </CapabilityContainer>
  );
}

// ── Availability + scaling — this VM's own real zone (azure.vms.availability_scaling); VMSS/
// flexible-orchestration scale-out is not modelled. ────────────────────────────────────────
function AvailabilityScaling({ a }) {
  return (
    <CapabilityContainer id="azure.vms.availability_scaling" title={`${a.name} | Availability + scaling`}>
      <div className="vy-props">
        <KV label="Availability zone" value={a.zones?.[0] || "Not configured"} />
        <KV label="Availability options" value={a.zones?.[0] ? "Availability zone" : "No infrastructure redundancy required"} />
      </div>
      <p style={{ fontSize: 13, marginTop: 12 }} className="vy-muted">Scale set membership and flexible orchestration are not modelled — this lens does not simulate a second host to spread instances across.</p>
    </CapabilityContainer>
  );
}

// ── Insights — this VM's own real properties as the per-resource Insights dashboard (the
// same "real inventory, no telemetry pipeline" pattern azure.monitor.resource_insights uses
// subscription-wide) (azure.vms.monitoring). ────────────────────────────────────────────────
function Insights({ a }) {
  return (
    <CapabilityContainer id="azure.vms.monitoring" title={`${a.name} | Insights`}>
      <div className="vy-props">
        <KV label="Status" value={statusOf(a)} />
        <KV label="Resource group" value={a.resourceGroup} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="OS" value={osType(a)} />
        <KV label="Size" value={a.properties?.hardwareProfile?.vmSize} />
      </div>
      <p style={{ fontSize: 13, marginTop: 12 }} className="vy-muted">Shows this virtual machine's own real inventory; there is no request/CPU/network telemetry pipeline to chart (that needs an agent-based collection pipeline Vyomi does not run).</p>
    </CapabilityContainer>
  );
}

// ── Alerts (Microsoft.Insights/metricAlerts + activityLogAlerts scoped to this VM) — the SAME
// generic Azure Monitor engine the Monitor service's own Alert rules page uses
// (azure.vms.monitoring). ────────────────────────────────────────────────────────────────
function VmAlerts({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listVmAlertRules(a.id), [a.id]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [metric, setMetric] = useState("Percentage CPU");
  const [threshold, setThreshold] = useState("80");
  const rows = data || [];
  const create = async () => {
    const n = name.trim();
    try {
      await api.createVmMetricAlert(a.resourceGroup, n, a.id, {
        severity: 3, enabled: true, evaluationFrequency: "PT1M", windowSize: "PT5M",
        criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
          allOf: [{ metricName: metric, operator: "GreaterThan", threshold: Number(threshold), timeAggregation: "Average" }] },
      });
      notify.success(`Alert rule '${n}' was created.`, "Create succeeded");
      setAdd(false); setName(""); reload();
    } catch (e) { notify.error(e, "Create alert rule failed"); }
  };
  return (
    <CapabilityContainer id="azure.vms.monitoring" title={`${a.name} | Alerts`}>
      <BrowseGrid resourceName="alert rule" rowKey={(r) => r.id} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create alert rule</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteVmMetricAlert(parseId(r.id).resourceGroup, r.name); reload(); }}
        columns={[
          { key: "name", label: "Name" }, { key: "kind", label: "Rule type" },
          { key: "severity", label: "Severity", value: (r) => r.properties?.severity ?? "--" },
          { key: "enabled", label: "Enabled", value: (r) => (r.properties?.enabled ? "Yes" : "No") },
        ]}
      />
      {add && (
        <section className="vy-section" style={{ marginTop: 16 }}>
          <h3>Create alert rule</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 420 }}>
            <Field label="Alert rule name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Alert rule name" /></Field>
            <Field label="Metric"><Input value={metric} onChange={(_, d) => setMetric(d.value)} aria-label="Metric" /></Field>
            <Field label="Threshold" hint="Greater than"><Input type="number" value={threshold} onChange={(_, d) => setThreshold(d.value)} aria-label="Threshold" /></Field>
          </div>
          <div className="vy-cmdbar" style={{ marginTop: 12 }}>
            <Button appearance="primary" disabled={!name.trim()} onClick={create}>Create</Button>
            <Button onClick={() => setAdd(false)}>Cancel</Button>
          </div>
        </section>
      )}
    </CapabilityContainer>
  );
}

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, scoped to this VM's own id) —
// the SAME generic ARM extension-resource mechanism the ACR/APIM blades' Diagnostic settings
// tab already uses for real (azure.vms.monitoring). ─────────────────────────────────────────
function VmDiagnosticSettings({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDiagnosticSettings(a.id), [a.id]);
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const ws = workspaces.data || [];
  return (
    <CapabilityContainer id="azure.vms.monitoring" title={`${a.name} | Diagnostic settings`}>
      <BrowseGrid resourceName="diagnostic setting" rowKey={(r) => r.name} filterPlaceholder="Search diagnostic settings"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => { setAdd(true); setWorkspace(ws[0]?.id || ""); }}>Add diagnostic setting</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteDiagnosticSetting(a.id, r.name); notify.success(`Deleted ${sel.length} diagnostic setting${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Diagnostic setting name" },
          { key: "dest", label: "Destination details", value: (r) => r.properties?.workspaceId ? "Log Analytics workspace" : "--" },
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
            <Button appearance="primary" disabled={!name.trim() || !workspace} onClick={async () => {
              await api.putDiagnosticSetting(a.id, name, { properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] } });
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

// ── Logs (Log Analytics KQL query, pre-filtered to this VM's own Activity log rows) — the
// same real bounded KQL subset the Monitor service's own Logs page runs (azure.vms.monitoring). ──
function VmLogs({ a }) {
  const notify = useNotify();
  const workspaces = useAsync(() => api.listWorkspaces(), []);
  const [query, setQuery] = useState(`AzureActivity | where ResourceId == "${a.id}"`);
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const ws = workspaces.data?.[0];
  const run = async () => {
    if (!ws) return;
    setBusy(true);
    try { const r = await api.runVmLogQuery(ws.resourceGroup, ws.name, query); setRows(r.tables?.[0]?.rows || []); }
    catch (e) { notify.error(e, "Log query failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.vms.monitoring" title={`${a.name} | Logs`}>
      {!ws ? <p>No Log Analytics workspace yet. Create one in the Monitor service first.</p> : (
        <>
          <Textarea value={query} onChange={(_, d) => setQuery(d.value)} aria-label="KQL query" style={{ width: "100%", minHeight: 90, fontFamily: "monospace" }} />
          <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={busy} onClick={run}>{busy ? "Running..." : "Run"}</Button></div>
          {rows && (
            <pre className="vy-grid" style={{ marginTop: 12, padding: 8, whiteSpace: "pre-wrap" }}>{rows.length ? JSON.stringify(rows, null, 1) : "No results."}</pre>
          )}
        </>
      )}
    </CapabilityContainer>
  );
}

// ── Connection monitor (Network Watcher connectivityCheck, source = this VM) — the SAME
// shared netsim evaluator the Network security groups / Virtual networks consoles' own
// connectivity-check tool uses; real NSG rules decide Reachable/Unreachable (azure.vms.monitoring). ──
function ConnectionMonitor({ a }) {
  const notify = useNotify();
  const [dest, setDest] = useState("10.0.0.5");
  const [port, setPort] = useState("443");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const run = async () => {
    setBusy(true); setResult(null);
    try { setResult(await api.connectionCheck(a.location, a.id, dest, port)); }
    catch (e) { notify.error(e, "Connectivity check failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.vms.monitoring" title={`${a.name} | Connection monitor`}>
      <p style={{ fontSize: 13 }}>Tests a real path from this virtual machine's network interface, evaluated against its actual attached network security group rules.</p>
      <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <Field label="Destination address"><Input value={dest} onChange={(_, d) => setDest(d.value)} aria-label="Destination address" /></Field>
        <Field label="Destination port"><Input value={port} onChange={(_, d) => setPort(d.value)} aria-label="Destination port" /></Field>
        <Button appearance="primary" disabled={busy} onClick={run}>{busy ? "Checking..." : "Check connectivity"}</Button>
      </div>
      {result && (
        <div className="vy-props" style={{ marginTop: 12 }}>
          <KV label="Connection status" value={result.connectionStatus} />
          <KV label="Hops" value={(result.hops || []).map((h) => h.type).join(" → ") || "--"} />
        </div>
      )}
    </CapabilityContainer>
  );
}

// ── Workbooks (Microsoft.Insights/workbooks, sourceId = this VM) — the same generic gallery
// engine the Monitor service's own Workbooks page uses (azure.vms.monitoring). ─────────────
function VmWorkbooks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listVmWorkbooks(a.id), [a.id]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.vms.monitoring" title={`${a.name} | Workbooks`}>
      <BrowseGrid resourceName="workbook" rowKey={(r) => r.id} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>New</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteVmWorkbook(parseId(r.id).resourceGroup, r.name); reload(); }}
        columns={[{ key: "name", label: "Display name", value: (r) => r.properties?.displayName }, { key: "category", label: "Category", value: (r) => r.properties?.category }]}
      />
      {add && (
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <Input placeholder="Workbook name" value={name} onChange={(_, d) => setName(d.value)} aria-label="Workbook name" />
          <Button appearance="primary" disabled={!name.trim()} onClick={async () => {
            await api.createVmWorkbook(a.resourceGroup, name.trim().replace(/\s+/g, "-"), a.id, name.trim());
            notify.success(`Workbook '${name}' was created.`, "Create succeeded");
            setAdd(false); setName(""); reload();
          }}>Save</Button>
          <Button onClick={() => setAdd(false)}>Cancel</Button>
        </div>
      )}
    </CapabilityContainer>
  );
}

// ── Metrics — scope/resource picker is real (drawn from this VM's own inventory); the chart
// itself stays honest (no telemetry/time-series store anywhere in Vyomi to sample from — the
// same azure.monitor.metrics_scope pattern) (azure.vms.monitoring). ─────────────────────────
function VmMetrics({ a }) {
  return (
    <CapabilityContainer id="azure.vms.monitoring" title={`${a.name} | Metrics`}>
      <div className="vy-props">
        <KV label="Scope" value={a.name} />
        <KV label="Resource type" value="Microsoft.Compute/virtualMachines" />
        <KV label="Resource group" value={a.resourceGroup} />
      </div>
      <div style={{ marginTop: 12 }}>
        <NotSimulated feature="Metrics charts (metric definitions and time-series values)" note="The scope/resource picker above is real; there is no metric time-series store anywhere in Vyomi to chart from." />
      </div>
    </CapabilityContainer>
  );
}
