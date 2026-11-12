/* Service-endpoint virtual network rules + IP firewall rules for Storage accounts and SQL servers, over real ARM
 * (validated in core/azure_netsvc_core.py: subnet exists and carries the matching service endpoint; IP rules are public IPv4). */
import { useState } from "react";
import { Button, Field, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { listAllSubnets, PrivateEndpointConnectionsPanel } from "./PrivateEndpoints.jsx";

const sapi = { "api-version": "2023-01-01" };
const sqlq = { "api-version": "2023-05-01-preview" };

/** Make sure the chosen subnet carries `service` (what the portal's "Enable service endpoint" does), then return its id. */
export async function ensureEndpoint(subnetId, service) {
  const sn = await restJson("GET", subnetId, { query: { "api-version": "2023-11-01" } });
  const eps = sn.properties?.serviceEndpoints || [];
  if (!eps.some((e) => e.service === service)) {
    await restJson("PUT", subnetId, { query: { "api-version": "2023-11-01" }, body: { properties: { ...sn.properties, serviceEndpoints: [...eps, { service, locations: ["*"] }] } } });
  }
  return subnetId;
}

export function AddVnetDialog({ onAdd, onClose, service }) {
  const subnets = useAsync(listAllSubnets, []);
  const [sel, setSel] = useState("");
  const id = sel || subnets.data?.[0]?.id || "";
  return (
    <div className="vy-section" style={{ display: "flex", gap: 8, alignItems: "flex-end", margin: "8px 0" }}>
      <Field label="Virtual network / subnet" style={{ minWidth: 280 }}>
        <Select value={id} onChange={(_, d) => setSel(d.value)} aria-label="Virtual network subnet">{(subnets.data || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</Select>
      </Field>
      <Button appearance="primary" disabled={!id} onClick={async () => { await onAdd(await ensureEndpoint(id, service)); onClose(); }}>Add (enables the {service} service endpoint)</Button>
      <Button onClick={onClose}>Cancel</Button>
    </div>
  );
}

export function StorageVnetRules({ a, reload }) {
  const notify = useNotify();
  const [adding, setAdding] = useState(false);
  const rules = a.properties?.networkAcls?.virtualNetworkRules || [];
  const save = async (next) => {
    try {
      await restJson("PATCH", a.id, { query: sapi, body: { properties: { networkAcls: { ...(a.properties?.networkAcls || {}), virtualNetworkRules: next } } } });
      notify.success("Virtual network rules were saved.", "Saved"); reload?.();
    } catch (e) { notify.error(e, "Saving failed"); }
  };
  return (
    <CapabilityContainer id="azure.storage.vnet_rules" title="Virtual networks">
      <BrowseGrid
        resourceName="virtual network rule" rowKey={(r) => r.id} items={rules} csvName="vnet-rules.csv" filterPlaceholder="Filter virtual networks"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Add existing virtual network</ToolbarButton>}
        onDelete={async (sel) => save(rules.filter((r) => !sel.some((s) => s.id === r.id)))}
        columns={[
          { key: "vnet", label: "Virtual network", value: (r) => r.id.split("/virtualNetworks/")[1]?.split("/")[0] },
          { key: "subnet", label: "Subnet", value: (r) => r.id.split("/").pop() },
          { key: "state", label: "Status", value: (r) => r.state || "Succeeded" },
        ]}
      />
      {adding && <AddVnetDialog service="Microsoft.Storage" onClose={() => setAdding(false)} onAdd={(id) => save([...rules, { id, action: "Allow" }])} />}
    </CapabilityContainer>
  );
}

export function StorageIpRules({ a, reload }) {
  const notify = useNotify();
  const [v, setV] = useState("");
  const rules = a.properties?.networkAcls?.ipRules || [];
  const save = async (next, msg) => {
    try {
      await restJson("PATCH", a.id, { query: sapi, body: { properties: { networkAcls: { ...(a.properties?.networkAcls || {}), ipRules: next } } } });
      notify.success(msg, "Saved"); setV(""); reload?.();
    } catch (e) { notify.error(e, "Saving failed"); }
  };
  return (
    <CapabilityContainer id="azure.storage.vnet_rules" title="Firewall">
      <BrowseGrid
        resourceName="address range" rowKey={(r) => r.value} items={rules} csvName="ip-rules.csv" filterPlaceholder="Filter address ranges"
        onDelete={async (sel) => save(rules.filter((r) => !sel.some((s) => s.value === r.value)), "Address ranges were removed.")}
        columns={[{ key: "value", label: "Address range" }, { key: "action", label: "Action", value: (r) => r.action || "Allow" }]}
      />
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 8 }}>
        <Field label="IPv4 address or CIDR"><Input value={v} onChange={(_, d) => setV(d.value)} placeholder="20.1.2.0/24" aria-label="IP address or CIDR" /></Field>
        <Button disabled={!v} onClick={() => save([...rules, { value: v, action: "Allow" }], "Address range was added.")}>Add IP range</Button>
      </div>
    </CapabilityContainer>
  );
}

export function SqlVnetRules({ a }) {
  const notify = useNotify();
  const rules = useAsync(async () => (await restJson("GET", `${a.id}/virtualNetworkRules`, { query: sqlq })).value || [], [a.id]);
  const [adding, setAdding] = useState(false);
  const add = async (id) => {
    const name = `rule-${id.split("/virtualNetworks/")[1].replace(/\//g, "-").replace("subnets-", "")}`.slice(0, 120);
    try { await restJson("PUT", `${a.id}/virtualNetworkRules/${name}`, { query: sqlq, body: { properties: { virtualNetworkSubnetId: id, ignoreMissingVnetServiceEndpoint: false } } }); rules.reload(); notify.success("Virtual network rule was added.", "Saved"); }
    catch (e) { notify.error(e, "Failed to add virtual network rule"); }
  };
  return (
    <CapabilityContainer id="azure.sql.vnet_rules" title="Virtual networks">
      <BrowseGrid
        resourceName="virtual network rule" rowKey={(r) => r.id} items={rules.data || []} loading={rules.loading} error={rules.error} onRefresh={rules.reload} csvName="sql-vnet-rules.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Add existing virtual network</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await restJson("DELETE", r.id, { query: sqlq }); rules.reload(); }}
        columns={[
          { key: "name", label: "Rule name" },
          { key: "subnet", label: "Subnet", value: (r) => (r.properties?.virtualNetworkSubnetId || "").split("/virtualNetworks/")[1] },
          { key: "state", label: "State", value: (r) => r.properties?.state || "Ready" },
        ]}
      />
      {adding && <AddVnetDialog service="Microsoft.Sql" onClose={() => setAdding(false)} onAdd={add} />}
    </CapabilityContainer>
  );
}

const cq = { "api-version": "2024-05-15" };
/** Cosmos DB account: public network access, selected-network rules (vnet + IP) and private endpoint connections. */
export function CosmosNetworking({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const [adding, setAdding] = useState(false);
  const [ip, setIp] = useState("");
  const vr = p.virtualNetworkRules || [];
  const ipr = p.ipRules || [];
  const save = async (props, msg) => {
    try { await restJson("PATCH", a.id, { query: cq, body: { properties: props } }); notify.success(msg, "Saved"); setIp(""); reload?.(); }
    catch (e) { notify.error(e, "Saving failed"); }
  };
  const mode = p.publicNetworkAccess === "Disabled" ? "Disabled" : p.isVirtualNetworkFilterEnabled || ipr.length ? "Selected networks" : "All networks";
  return (
    <>
      <CapabilityContainer id="azure.cosmos.network_rules" title="Public network access">
        <Field label="Public network access">
          <Select value={mode} aria-label="Public network access" onChange={(_, d) => save(d.value === "Disabled" ? { publicNetworkAccess: "Disabled" } : { publicNetworkAccess: "Enabled", isVirtualNetworkFilterEnabled: d.value === "Selected networks" }, "Network access was updated.")}>
            <option>All networks</option><option>Selected networks</option><option>Disabled</option>
          </Select>
        </Field>
        <BrowseGrid resourceName="virtual network rule" rowKey={(r) => r.id} items={vr} csvName="cosmos-vnet-rules.csv" filterPlaceholder="Filter virtual networks"
          extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Add existing virtual network</ToolbarButton>}
          onDelete={async (sel) => save({ virtualNetworkRules: vr.filter((r) => !sel.some((s) => s.id === r.id)) }, "Virtual network rules were saved.")}
          columns={[{ key: "vnet", label: "Virtual network", value: (r) => r.id.split("/virtualNetworks/")[1]?.split("/")[0] }, { key: "subnet", label: "Subnet", value: (r) => r.id.split("/").pop() }]} />
        {adding && <AddVnetDialog service="Microsoft.AzureCosmosDB" onClose={() => setAdding(false)} onAdd={(id) => save({ isVirtualNetworkFilterEnabled: true, virtualNetworkRules: [...vr, { id, ignoreMissingVNetServiceEndpoint: false }] }, "Virtual network rule was added.")} />}
        <BrowseGrid resourceName="IP rule" rowKey={(r) => r.ipAddressOrRange} items={ipr} csvName="cosmos-ip-rules.csv" filterPlaceholder="Filter IP rules"
          onDelete={async (sel) => save({ ipRules: ipr.filter((r) => !sel.some((s) => s.ipAddressOrRange === r.ipAddressOrRange)) }, "IP rules were saved.")}
          columns={[{ key: "ipAddressOrRange", label: "IP address or range" }]} />
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 8 }}>
          <Field label="IPv4 address or CIDR"><Input value={ip} onChange={(_, d) => setIp(d.value)} aria-label="IP address or CIDR" /></Field>
          <Button disabled={!ip} onClick={() => save({ ipRules: [...ipr, { ipAddressOrRange: ip }] }, "IP rule was added.")}>Add IP rule</Button>
        </div>
      </CapabilityContainer>
      <PrivateEndpointConnectionsPanel target={{ id: a.id, name: a.name, type: "Microsoft.DocumentDB/databaseAccounts", location: a.location }} />
    </>
  );
}
