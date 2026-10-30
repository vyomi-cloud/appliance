/* Subnets, Peerings and Service endpoints — real ARM nested-child-resource panels, plus the
 * honest Connected devices gap. Exported for use from VnetBlade.jsx. */
import { useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { parseId } from "../../kit/arm.js";
import * as api from "./api.js";

const SIZES = ["/24 (256 addresses)", "/23 (512 addresses)", "/22 (1024 addresses)", "/26 (64 addresses)", "/27 (32 addresses)", "/28 (16 addresses)", "/29 (8 addresses)"];
const PURPOSES = {
  Default: null,
  "Virtual Network Gateway": "GatewaySubnet",
  "Azure Bastion": "AzureBastionSubnet",
  "Azure Firewall": "AzureFirewallSubnet",
  "Azure Firewall Management (forced tunneling)": "AzureFirewallManagementSubnet",
  "Azure Route Server": "RouteServerSubnet",
};
const SERVICES = ["Microsoft.Storage", "Microsoft.Sql", "Microsoft.AzureActiveDirectory", "Microsoft.KeyVault", "Microsoft.ServiceBus", "Microsoft.EventHub", "Microsoft.CosmosDB", "Microsoft.Web"];

// ── Subnets ────────────────────────────────────────────────────────────────────────────
export function SubnetsPanel({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listSubnets(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const nsgs = useAsync(() => api.listNsgs(), []);
  const [add, setAdd] = useState(null); // { gateway: bool } | null
  const [manage, setManage] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Subnets</div>
      <BrowseGrid
        resourceName="subnet" rowKey={(r) => r.id} filterPlaceholder="Search subnets"
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd({ gateway: false })}>Subnet</ToolbarButton>
          <ToolbarButton onClick={() => setAdd({ gateway: true })}>Gateway subnet</ToolbarButton>
          <ToolbarButton onClick={() => setManage(true)}>Manage users</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteSubnet(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} subnet${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="subnets.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "ipv4", label: "IPv4", value: (r) => r.properties?.addressPrefix || "--" },
          { key: "ipv6", label: "IPv6", value: () => "--" },
          { key: "available", label: "Available IPs", value: (r) => availableIps(r.properties?.addressPrefix) },
          { key: "delegated", label: "Delegated to", value: (r) => r.properties?.delegations?.[0]?.properties?.serviceName || "--" },
          { key: "nsg", label: "Security group", value: (r) => (r.properties?.networkSecurityGroup ? r.properties.networkSecurityGroup.id.split("/").pop() : "--") },
          { key: "rt", label: "Route table", value: () => "--" },
        ]}
      />
      {add && <AddSubnetDialog a={a} existing={rows} nsgs={nsgs.data || []} gateway={add.gateway} onClose={() => setAdd(null)}
        onCreate={async (subnetName, body) => { await api.putSubnet(a.resourceGroup, a.name, subnetName, body); reload(); }} />}
      <Dialog open={manage} onOpenChange={(_, d) => !d.open && setManage(false)}>
        <DialogSurface aria-label="Manage users">
          <DialogBody><DialogTitle>Manage users</DialogTitle>
            <DialogContent><NotSimulatedContainer feature="Managing users (a role-assignment shortcut) for this subnet" /></DialogContent>
            <DialogActions><Button onClick={() => setManage(false)}>Close</Button></DialogActions></DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function availableIps(prefix) {
  if (!prefix) return "--";
  const bits = Number(prefix.split("/")[1]);
  if (!Number.isFinite(bits)) return "--";
  return Math.max(0, 2 ** (32 - bits) - 5); // Azure reserves 5 addresses per subnet
}

function AddSubnetDialog({ a, existing, nsgs, gateway, onClose, onCreate }) {
  const notify = useNotify();
  const prefixes = a.properties?.addressSpace?.addressPrefixes || ["10.0.0.0/16"];
  const [purpose, setPurpose] = useState(gateway ? "Virtual Network Gateway" : "Default");
  const [name, setName] = useState(gateway ? "GatewaySubnet" : "");
  const [range, setRange] = useState(prefixes[0]);
  const [includeIpv4, setIncludeIpv4] = useState(true);
  const [start, setStart] = useState("");
  const [size, setSize] = useState(SIZES[0]);
  const [privateSubnet, setPrivateSubnet] = useState(false);
  const [nsgId, setNsgId] = useState("");
  const [busy, setBusy] = useState(false);
  const reserved = PURPOSES[purpose];
  const effectiveName = reserved || name;
  const bits = Number(size.match(/\/(\d+)/)?.[1] || 24);
  const computedRange = start ? `${start}/${bits}` : "";
  const errors = [];
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,78}[a-zA-Z0-9_]$/.test(effectiveName)) errors.push("name");
  else if (existing.some((s) => s.name === effectiveName)) errors.push("duplicate name");
  if (includeIpv4 && !start) errors.push("starting address");
  const valid = errors.length === 0;
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(effectiveName, {
        properties: {
          ...(includeIpv4 ? { addressPrefix: computedRange } : {}),
          defaultOutboundAccess: !privateSubnet,
          ...(nsgId ? { networkSecurityGroup: { id: nsgId } } : {}),
        },
      });
      onClose();
    } catch (e) { notify.error(e, "Failed to add subnet"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add a subnet">
        <DialogBody>
          <DialogTitle>Add a subnet</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <section className="vy-section"><h3>Add a subnet</h3>
                <Field label="Subnet purpose">
                  <Select value={purpose} disabled={gateway} onChange={(_, d) => { setPurpose(d.value); if (PURPOSES[d.value]) setName(PURPOSES[d.value]); }} aria-label="Subnet purpose">
                    {Object.keys(PURPOSES).map((p) => <option key={p}>{p}</option>)}
                  </Select>
                </Field>
                <Field label="Name" required>
                  <Input value={effectiveName} disabled={!!reserved} onChange={(_, d) => setName(d.value)} aria-label="Name" />
                </Field>
              </section>
              <section className="vy-section"><h3>IPv4</h3>
                <Checkbox label="Include an IPv4 address space" checked={includeIpv4} onChange={(_, d) => setIncludeIpv4(!!d.checked)} />
                {includeIpv4 && <>
                  <Field label="IPv4 address range"><Select value={range} onChange={(_, d) => setRange(d.value)} aria-label="IPv4 address range">{prefixes.map((p) => <option key={p}>{p}</option>)}</Select></Field>
                  <Field label="Starting address" required><Input value={start} placeholder="10.0.1.0" onChange={(_, d) => setStart(d.value)} aria-label="Starting address" /></Field>
                  <Field label="Size"><Select value={size} onChange={(_, d) => setSize(d.value)} aria-label="Size">{SIZES.map((s) => <option key={s}>{s}</option>)}</Select></Field>
                  <Field label="Subnet address range"><Input value={computedRange} readOnly aria-label="Subnet address range" /></Field>
                </>}
              </section>
              <section className="vy-section"><h3>Private subnet</h3>
                <Checkbox label="Enable private subnet (no default outbound access)" checked={privateSubnet} onChange={(_, d) => setPrivateSubnet(!!d.checked)} />
              </section>
              <section className="vy-section"><h3>Security</h3>
                <NotSimulatedContainer title="NAT gateway" feature="NAT gateway" note="Microsoft.Network/natGateways is not modelled; nothing exists to associate." />
                <Field label="Network security group">
                  <Select value={nsgId} onChange={(_, d) => setNsgId(d.value)} aria-label="Network security group">
                    <option value="">None</option>
                    {nsgs.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </Select>
                </Field>
                <NotSimulatedContainer title="Route table" feature="Route table" note="Microsoft.Network/routeTables is not modelled; nothing exists to associate." />
              </section>
              <NotSimulatedContainer title="Service Endpoints" feature="Services" note="Configure service endpoints from the virtual network's Service endpoints page instead." />
              <NotSimulatedContainer title="Subnet Delegation" feature="Delegate subnet to a service" note="Per-service subnet delegation is not modelled." />
              {errors.length > 0 && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12 }}>Fix: {errors.join(", ")}</div>}
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

// ── Peerings ───────────────────────────────────────────────────────────────────────────
export function PeeringsPanel({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listPeerings(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const allVnets = useAsync(() => api.listVnets(), []);
  const [add, setAdd] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Peerings</div>
      <BrowseGrid
        resourceName="peering" rowKey={(r) => r.id} filterPlaceholder="Filter by name..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
          <ToolbarButton onClick={reload}>Sync</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deletePeering(a.resourceGroup, a.name, r.name);
          notify.success(`Deleted ${sel.length} peering${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="peerings.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "sync", label: "Peering sync status", value: (r) => r.properties?.peeringSyncLevel || "--" },
          { key: "state", label: "Peering state", value: (r) => r.properties?.peeringState || "--" },
          { key: "remote", label: "Remote virtual network name", value: (r) => r.properties?.remoteVirtualNetwork?.id?.split("/").pop() || "--" },
          { key: "remoteaddr", label: "Remote virtual network address space", value: (r) => (r.properties?.remoteAddressSpace?.addressPrefixes || []).join(", ") || "--" },
          { key: "gw", label: "Gateway transit", value: (r) => (r.properties?.allowGatewayTransit ? "Enabled" : "Disabled") },
        ]}
      />
      {add && <AddPeeringDialog a={a} existing={rows} others={(allVnets.data || []).filter((v) => !(v.name === a.name && v.resourceGroup === a.resourceGroup))} onClose={() => setAdd(false)} onCreated={reload} />}
    </>
  );
}

function AddPeeringDialog({ a, existing, others, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [remoteKey, setRemoteKey] = useState(others[0] ? `${others[0].resourceGroup}/${others[0].name}` : "");
  const [forwardedTraffic, setForwardedTraffic] = useState(false);
  const [gatewayTransit, setGatewayTransit] = useState(false);
  const [remoteGateways, setRemoteGateways] = useState(false);
  const [busy, setBusy] = useState(false);
  const remote = others.find((v) => `${v.resourceGroup}/${v.name}` === remoteKey);
  const errors = [];
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,78}[a-zA-Z0-9_]$/.test(name)) errors.push("name");
  else if (existing.some((p) => p.name === name)) errors.push("duplicate name");
  if (!remote) errors.push("remote virtual network");
  const valid = errors.length === 0;
  const go = async () => {
    setBusy(true);
    try {
      await api.addPeeringBothSides(a.resourceGroup, a.name, name, remote.resourceGroup, remote.name, `${remote.name}-to-${a.name}`,
        { allowForwardedTraffic: forwardedTraffic, allowGatewayTransit: gatewayTransit, useRemoteGateways: remoteGateways });
      notify.success(`Peering '${name}' was added.`, "Peering added");
      onCreated(); onClose();
    } catch (e) { notify.error(e, "Failed to add peering"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add peering">
        <DialogBody>
          <DialogTitle>Add peering</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="This virtual network"><Input value={a.name} readOnly aria-label="This virtual network" /></Field>
              <Field label="Peering link name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Peering link name" /></Field>
              <Field label="Remote virtual network" required>
                <Select value={remoteKey} onChange={(_, d) => setRemoteKey(d.value)} aria-label="Remote virtual network">
                  {others.map((v) => <option key={`${v.resourceGroup}/${v.name}`} value={`${v.resourceGroup}/${v.name}`}>{v.name} ({v.resourceGroup})</option>)}
                </Select>
              </Field>
              <Checkbox label="Allow forwarded traffic" checked={forwardedTraffic} onChange={(_, d) => setForwardedTraffic(!!d.checked)} />
              <Checkbox label="Allow gateway transit" checked={gatewayTransit} onChange={(_, d) => setGatewayTransit(!!d.checked)} />
              <Checkbox label="Use remote gateways" checked={remoteGateways} onChange={(_, d) => setRemoteGateways(!!d.checked)} />
              {errors.length > 0 && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12 }}>Fix: {errors.join(", ")}</div>}
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

// ── Service endpoints ──────────────────────────────────────────────────────────────────
export function ServiceEndpointsPanel({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listSubnets(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const subnets = data || [];
  const rows = subnets.flatMap((s) => (s.properties?.serviceEndpoints || []).map((e) => ({ id: `${s.name}/${e.service}`, subnet: s.name, ...e })));
  return (
    <>
      <div className="vy-panel-title">Service endpoints</div>
      <BrowseGrid
        resourceName="service endpoint" rowKey={(r) => r.id}
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        csvName="service-endpoints.csv"
        columns={[
          { key: "service", label: "Service" },
          { key: "subnet", label: "Subnet" },
          { key: "status", label: "Status", value: () => "Available" },
          { key: "locations", label: "Locations", value: (r) => ((r.locations || []).includes("*") ? "All networks" : (r.locations || []).join(", ")) },
        ]}
      />
      {add && <AddServiceEndpointDialog a={a} subnets={subnets} onClose={() => setAdd(false)} onCreated={reload} />}
    </>
  );
}

function AddServiceEndpointDialog({ a, subnets, onClose, onCreated }) {
  const notify = useNotify();
  const [subnetName, setSubnetName] = useState(subnets[0]?.name || "");
  const [service, setService] = useState(SERVICES[0]);
  const [busy, setBusy] = useState(false);
  const subnet = subnets.find((s) => s.name === subnetName);
  const valid = !!subnet && !(subnet.properties?.serviceEndpoints || []).some((e) => e.service === service);
  const go = async () => {
    setBusy(true);
    try {
      await api.addServiceEndpoint(a.resourceGroup, a.name, subnetName, subnet, service);
      notify.success(`Service endpoint '${service}' was added to '${subnetName}'.`, "Service endpoint added");
      onCreated(); onClose();
    } catch (e) { notify.error(e, "Failed to add service endpoint"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add service endpoint">
        <DialogBody>
          <DialogTitle>Add service endpoint</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Subnet" required>
                <Select value={subnetName} onChange={(_, d) => setSubnetName(d.value)} aria-label="Subnet">
                  {subnets.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
                </Select>
              </Field>
              <Field label="Services" required>
                <Select value={service} onChange={(_, d) => setService(d.value)} aria-label="Services">
                  {SERVICES.map((s) => <option key={s}>{s}</option>)}
                </Select>
              </Field>
              {!valid && subnet && <div style={{ fontSize: 12 }}>That service endpoint already exists on this subnet.</div>}
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

// ── Connected devices — any network interface attached to one of this vnet's subnets
// (a real ARM read; see api.listConnectedDevices). Honest gap: the real portal also
// discovers non-NIC clients (live DHCP leases, ARP entries) Vyomi has no table for. ───────
export function ConnectedDevicesPanel({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listConnectedDevices(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.vnets.connected_devices" title={`${a.name} | Connected devices`}>
      <BrowseGrid
        resourceName="device" rowKey={(r) => r.id} filterPlaceholder="Search connected devices"
        items={rows} loading={loading} error={error} onRefresh={reload}
        csvName="connected-devices.csv"
        columns={[
          { key: "device", label: "Device", value: (r) => r.name },
          { key: "type", label: "Type", value: () => "Network interface" },
          { key: "ip", label: "IP address", value: (r) => r.properties?.ipConfigurations?.[0]?.properties?.privateIPAddress || "--" },
          { key: "subnet", label: "Subnet", value: (r) => parseId(r.properties?.ipConfigurations?.[0]?.properties?.subnet?.id || "").name || "--" },
        ]}
      />
    </CapabilityContainer>
  );
}
