/* Vnet blade panels backed by the network-service engine (core/azure_netsvc_core.py): Private endpoints,
 * Bastion, Firewall, DDoS protection -- real ARM resources, deployed the way the portal's wizards do. */
import { useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as ns from "./netsvc.js";
import { listSubnets } from "./api.js";

function Modal({ title, onClose, onGo, goLabel = "Create", valid = true, busy, children }) {
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={title}>
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}>{children}</div></DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={onGo}>{goLabel}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
const useRun = (notify, done) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, ok, failTitle) => {
    setBusy(true);
    try { await fn(); notify.success(ok, "Succeeded"); done(); } catch (e) { notify.error(e, failTitle); } finally { setBusy(false); }
  };
  return [busy, run];
};

// ── Private endpoints ────────────────────────────────────────────────────────────────────
export function PrivateEndpointsPanel({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => ns.listPrivateEndpoints(a.id), [a.id]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.vnets.private_endpoints" title={`${a.name} | Private endpoints`}>
      <BrowseGrid
        resourceName="private endpoint" rowKey={(r) => r.id} filterPlaceholder="Search private endpoints"
        items={data || []} loading={loading} error={error} onRefresh={reload} csvName="private-endpoints.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await ns.PE.remove(ns.rgOf(r.id), r.name); notify.success(`Deleted ${sel.length} private endpoint(s).`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" },
          { key: "state", label: "Connection state", value: (r) => ns.connectionsOf(r)[0]?.properties?.privateLinkServiceConnectionState?.status || "--" },
          { key: "subnet", label: "Subnet", value: (r) => (r.properties?.subnet?.id || "").split("/").pop() },
          { key: "target", label: "Resource", value: (r) => (ns.connectionsOf(r)[0]?.properties?.privateLinkServiceId || "").split("/").pop() },
          { key: "group", label: "Sub-resource", value: (r) => (ns.connectionsOf(r)[0]?.properties?.groupIds || []).join(", ") },
          { key: "ip", label: "Private IP", value: (r) => r.properties?.customDnsConfigs?.[0]?.ipAddresses?.[0] || "--" },
          { key: "fqdn", label: "FQDN", value: (r) => r.properties?.customDnsConfigs?.[0]?.fqdn || "--" },
        ]}
      />
      {add && <CreatePrivateEndpoint a={a} onClose={() => setAdd(false)} onDone={reload} />}
    </CapabilityContainer>
  );
}

function CreatePrivateEndpoint({ a, onClose, onDone }) {
  const notify = useNotify();
  const subnets = useAsync(() => listSubnets(a.resourceGroup, a.name), [a.id]);
  const targets = useAsync(() => ns.listTargets(), []);
  const [name, setName] = useState("pe-" + a.name);
  const [subnet, setSubnet] = useState("");
  const [target, setTarget] = useState("");
  const [group, setGroup] = useState("");
  const [manual, setManual] = useState(false);
  const [busy, run] = useRun(notify, () => { onDone(); onClose(); });
  const t = (targets.data || []).find((x) => x.id === target);
  const groups = t ? ns.GROUPS[t.type] : [];
  const sn = subnet || subnets.data?.[0]?.id || "";
  return (
    <Modal title="Create a private endpoint" valid={!!name && !!sn && !!t && !!(group || groups[0])} busy={busy} onClose={onClose}
      onGo={() => run(() => ns.createPrivateEndpoint(a.resourceGroup, name, a.location, sn, t.id, group || groups[0], manual), `Private endpoint '${name}' was created.`, "Failed to create private endpoint")}>
      <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Private endpoint name" /></Field>
      <Field label="Subnet" required>
        <Select value={sn} onChange={(_, d) => setSubnet(d.value)} aria-label="Subnet">{(subnets.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
      </Field>
      <Field label="Resource" required>
        <Select value={target} onChange={(_, d) => { setTarget(d.value); setGroup(""); }} aria-label="Target resource">
          <option value="">Select a resource</option>
          {(targets.data || []).map((x) => <option key={x.id} value={x.id}>{x.name} ({x.type.split("/").pop()})</option>)}
        </Select>
      </Field>
      <Field label="Target sub-resource" required>
        <Select value={group || groups[0] || ""} onChange={(_, d) => setGroup(d.value)} aria-label="Target sub-resource">{groups.map((g) => <option key={g}>{g}</option>)}</Select>
      </Field>
      <Checkbox checked={manual} onChange={(_, d) => setManual(!!d.checked)} label="Connect by requesting approval (manual connection)" />
    </Modal>
  );
}

// ── Bastion ────────────────────────────────────────────────────────────────────────────
export function BastionPanel({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => ns.listBastions(a.id), [a.id]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.vnets.bastion" title={`${a.name} | Bastion`}>
      <BrowseGrid
        resourceName="bastion host" rowKey={(r) => r.id} items={data || []} loading={loading} error={error} onRefresh={reload} csvName="bastions.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Deploy Bastion</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await ns.BASTION.remove(ns.rgOf(r.id), r.name); notify.success(`Deleted ${sel.length} bastion host(s).`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" }, { key: "sku", label: "SKU", value: (r) => r.sku?.name },
          { key: "dns", label: "DNS name", value: (r) => r.properties?.dnsName }, { key: "units", label: "Instances", value: (r) => r.properties?.scaleUnits ?? "--" },
          { key: "tunnel", label: "Native client support", value: (r) => (r.properties?.enableTunneling ? "Enabled" : "Disabled") },
          { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState },
        ]}
      />
      {add && <DeployBastion a={a} onClose={() => setAdd(false)} onDone={reload} />}
    </CapabilityContainer>
  );
}
function DeployBastion({ a, onClose, onDone }) {
  const notify = useNotify();
  const subnets = useAsync(() => listSubnets(a.resourceGroup, a.name), [a.id]);
  const [f, setF] = useState({ name: a.name + "-bastion", sku: "Standard", tunneling: false, ipConnect: false, scaleUnits: 2 });
  const [busy, run] = useRun(notify, () => { onDone(); onClose(); });
  const bs = (subnets.data || []).find((s) => s.name === "AzureBastionSubnet");
  const prefix = bs ? bs.properties?.addressPrefix : ns.freeBlock(a, subnets.data, 26);
  return (
    <Modal title="Deploy Azure Bastion" goLabel="Deploy" valid={!!f.name && !!prefix} busy={busy} onClose={onClose}
      onGo={() => run(() => ns.deployBastion(a, { ...f, prefix }), `Bastion host '${f.name}' was deployed.`, "Failed to deploy Bastion")}>
      <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Bastion name" /></Field>
      <Field label="Tier"><Select value={f.sku} onChange={(_, d) => setF({ ...f, sku: d.value })} aria-label="Tier">{["Developer", "Basic", "Standard", "Premium"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
      <Field label="AzureBastionSubnet address range" hint={bs ? "Existing subnet" : "Created for you (must be /26 or larger)"}><Input value={prefix || ""} readOnly aria-label="AzureBastionSubnet range" /></Field>
      {f.sku !== "Basic" && f.sku !== "Developer" && <>
        <Field label="Instance count"><Input type="number" min={2} max={50} value={String(f.scaleUnits)} onChange={(_, d) => setF({ ...f, scaleUnits: Number(d.value) })} aria-label="Instance count" /></Field>
        <Checkbox checked={f.tunneling} onChange={(_, d) => setF({ ...f, tunneling: !!d.checked })} label="Native client support" />
        <Checkbox checked={f.ipConnect} onChange={(_, d) => setF({ ...f, ipConnect: !!d.checked })} label="IP-based connection" />
      </>}
    </Modal>
  );
}

// ── Firewall ──────────────────────────────────────────────────────────────────────────
export function FirewallPanel({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => ns.listFirewalls(a.id), [a.id]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.vnets.firewall" title={`${a.name} | Firewall`}>
      <BrowseGrid
        resourceName="firewall" rowKey={(r) => r.id} items={data || []} loading={loading} error={error} onRefresh={reload} csvName="firewalls.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Deploy Firewall</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await ns.FIREWALL.remove(ns.rgOf(r.id), r.name); notify.success(`Deleted ${sel.length} firewall(s).`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Name" }, { key: "tier", label: "Tier", value: (r) => r.properties?.sku?.tier },
          { key: "ip", label: "Private IP", value: (r) => r.properties?.ipConfigurations?.[0]?.properties?.privateIPAddress },
          { key: "policy", label: "Firewall policy", value: (r) => (r.properties?.firewallPolicy?.id || "").split("/").pop() || "--" },
          { key: "ti", label: "Threat intelligence", value: (r) => r.properties?.threatIntelMode },
          { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState },
        ]}
      />
      {add && <DeployFirewall a={a} onClose={() => setAdd(false)} onDone={reload} />}
    </CapabilityContainer>
  );
}
function DeployFirewall({ a, onClose, onDone }) {
  const notify = useNotify();
  const subnets = useAsync(() => listSubnets(a.resourceGroup, a.name), [a.id]);
  const policies = useAsync(() => ns.POLICY.list(), []);
  const [f, setF] = useState({ name: a.name + "-fw", tier: "Standard", policyId: "" });
  const [busy, run] = useRun(notify, () => { onDone(); onClose(); });
  const existing = (n) => (subnets.data || []).find((s) => s.name === n)?.properties?.addressPrefix;
  const prefix = existing("AzureFirewallSubnet") || ns.freeBlock(a, subnets.data, 26);
  const mgmt = existing("AzureFirewallManagementSubnet") || ns.freeBlock(a, [...(subnets.data || []), { properties: { addressPrefix: prefix } }], 26);
  const pols = (policies.data || []).filter((p) => (p.properties?.sku?.tier || "Standard") === f.tier);
  return (
    <Modal title="Deploy Azure Firewall" goLabel="Deploy" valid={!!f.name && !!prefix} busy={busy} onClose={onClose}
      onGo={() => run(() => ns.deployFirewall(a, { ...f, prefix, mgmtPrefix: mgmt }), `Firewall '${f.name}' was deployed.`, "Failed to deploy Azure Firewall")}>
      <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Firewall name" /></Field>
      <Field label="Firewall SKU"><Select value={f.tier} onChange={(_, d) => setF({ ...f, tier: d.value, policyId: "" })} aria-label="Firewall SKU">{["Basic", "Standard", "Premium"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
      <Field label="Firewall policy"><Select value={f.policyId} onChange={(_, d) => setF({ ...f, policyId: d.value })} aria-label="Firewall policy"><option value="">None (classic rules)</option>{pols.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
      <Field label="AzureFirewallSubnet address range"><Input value={prefix || ""} readOnly aria-label="AzureFirewallSubnet range" /></Field>
    </Modal>
  );
}

// ── DDoS protection ──────────────────────────────────────────────────────────────────
export function DdosPanel({ a, reload: reloadVnet }) {
  const notify = useNotify();
  const plans = useAsync(() => ns.DDOS.list(), [a.id]);
  const cur = a.properties?.enableDdosProtection ? a.properties?.ddosProtectionPlan?.id : "";
  const [pick, setPick] = useState(cur || "");
  const [name, setName] = useState("ddos-plan-1");
  const [busy, run] = useRun(notify, () => { plans.reload(); reloadVnet && reloadVnet(); });
  return (
    <CapabilityContainer id="azure.vnets.ddos" title={`${a.name} | DDoS protection`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 480 }}>
        <div>DDoS protection: <b>{cur ? "Enabled" : "Disabled"}</b>{cur && <> &mdash; plan {cur.split("/").pop()}</>}</div>
        <Field label="DDoS protection plan">
          <Select value={pick} onChange={(_, d) => setPick(d.value)} aria-label="DDoS protection plan">
            <option value="">Disable</option>{(plans.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        <div style={{ display: "flex", gap: 8 }}>
          <Button appearance="primary" disabled={busy || pick === cur} onClick={() => run(() => ns.setDdos(a, pick), pick ? "DDoS protection was enabled." : "DDoS protection was disabled.", "Failed to update DDoS protection")}>Save</Button>
        </div>
        <Field label="Create a new plan"><div style={{ display: "flex", gap: 8 }}>
          <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="New DDoS plan name" />
          <Button disabled={busy || !name} onClick={() => run(() => ns.DDOS.put(ns.rgOf(a.id), name, { location: a.location }), `DDoS protection plan '${name}' was created.`, "Failed to create plan")}>Create</Button>
        </div></Field>
        <BrowseGrid resourceName="plan" rowKey={(r) => r.id} items={plans.data || []} loading={plans.loading} error={plans.error} onRefresh={plans.reload} csvName="ddos-plans.csv"
          onDelete={async (sel) => { for (const r of sel) await ns.DDOS.remove(ns.rgOf(r.id), r.name); plans.reload(); }}
          columns={[{ key: "name", label: "Plan" }, { key: "vn", label: "Protected virtual networks", value: (r) => (r.properties?.virtualNetworks || []).length }]} />
      </div>
    </CapabilityContainer>
  );
}
