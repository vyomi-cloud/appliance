/* Service Bus namespace Networking: public network access, selected-networks firewall (IP
 * rules + default action) and private endpoint connections, all native ARM
 * (namespaces/{ns}, networkRuleSets/default, privateEndpointConnections). ENFORCED on the
 * Service Bus data plane the console drives: Disabled / Deny rejects it (see
 * core/azure_arm_core.py servicebus_network_denied). */
import { useEffect, useState } from "react";
import { Button, Checkbox, Field, Input, Radio, RadioGroup, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const modeOf = (ns, rs) => ((ns.properties || {}).publicNetworkAccess === "Disabled" || rs?.publicNetworkAccess === "Disabled") ? "disabled"
  : rs?.defaultAction === "Deny" ? "selected" : "all";

export default function Networking({ a, reload }) {
  const [tab, setTab] = useState("public");
  const rs = useAsync(() => api.getNetworkRuleSet(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  return (
    <>
      <div className="vy-panel-title">{a.name} | Networking</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Networking tabs">
        <Tab value="public">Public access</Tab>
        <Tab value="private">Private endpoint connections</Tab>
      </TabList>
      <div style={{ marginTop: 12 }}>
        {rs.loading && !rs.data ? <Loading /> : <ErrorBar error={rs.error} />}
        {tab === "public" && rs.data && <PublicAccess a={a} rs={rs.data.properties || {}} reloadAll={() => { rs.reload(); reload(); }} />}
        {tab === "private" && <PrivateEndpoints a={a} />}
      </div>
    </>
  );
}

function PublicAccess({ a, rs, reloadAll }) {
  const notify = useNotify();
  const cur = modeOf(a, rs);
  const [mode, setMode] = useState(cur);
  const [ips, setIps] = useState((rs.ipRules || []).map((r) => r.ipMask));
  const [newIp, setNewIp] = useState("");
  const [trusted, setTrusted] = useState(!!rs.trustedServiceAccessEnabled);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setMode(cur); setIps((rs.ipRules || []).map((r) => r.ipMask)); setTrusted(!!rs.trustedServiceAccessEnabled); }, [cur, JSON.stringify(rs.ipRules), rs.trustedServiceAccessEnabled]);
  const premium = (a.sku?.tier || a.sku?.name) === "Premium";
  const save = async () => {
    setBusy(true);
    try {
      await api.putNetworkRuleSet(a.resourceGroup, a.name, {
        publicNetworkAccess: mode === "disabled" ? "Disabled" : "Enabled",
        defaultAction: mode === "all" ? "Allow" : "Deny",
        trustedServiceAccessEnabled: trusted,
        ipRules: mode === "selected" ? ips.map((ipMask) => ({ ipMask, action: "Allow" })) : [],
        virtualNetworkRules: rs.virtualNetworkRules || [],
      });
      await api.updateNamespace(a.resourceGroup, a.name, { properties: { publicNetworkAccess: mode === "disabled" ? "Disabled" : "Enabled" } });
      notify.success(`Networking for '${a.name}' was saved.`, "Saved");
      reloadAll();
    } catch (e) { notify.error(e, "Saving networking failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="azure.servicebus.namespace.networking" title="Public network access">
      {!premium && <div style={{ marginBottom: 8 }}>Private endpoints require the Premium tier; the firewall below applies to every tier.</div>}
      <RadioGroup value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Public network access">
        <Radio value="all" label="All networks" />
        <Radio value="selected" label="Selected networks" />
        <Radio value="disabled" label="Disabled" />
      </RadioGroup>
      {mode === "selected" && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontWeight: 600 }}>IP firewall: addresses and CIDR ranges allowed</div>
          {ips.map((ip) => (
            <div key={ip} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
              <span>{ip}</span>
              <Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Remove ${ip}`} onClick={() => setIps(ips.filter((x) => x !== ip))} />
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "end" }}>
            <Field label="Add IP address or CIDR"><Input value={newIp} onChange={(_, d) => setNewIp(d.value)} aria-label="Add IP address or CIDR" /></Field>
            <Button disabled={!newIp.trim()} onClick={() => { setIps([...new Set([...ips, newIp.trim()])]); setNewIp(""); }}>Add</Button>
          </div>
        </div>
      )}
      {mode !== "disabled" && <div style={{ marginTop: 12 }}><Checkbox checked={trusted} onChange={(_, d) => setTrusted(!!d.checked)} label="Allow trusted Microsoft services to bypass this firewall" /></div>}
      <div style={{ marginTop: 12 }}><Button appearance="primary" disabled={busy} onClick={save}>Save</Button></div>
    </CapabilityContainer>
  );
}

function PrivateEndpoints({ a }) {
  const notify = useNotify();
  const pecs = useAsync(() => api.listPrivateEndpointConnections(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [name, setName] = useState("");
  const [subnet, setSubnet] = useState("");
  const set = async (r, status) => {
    try {
      await api.putPrivateEndpointConnection(a.resourceGroup, a.name, r.name, { ...r.properties, privateLinkServiceConnectionState: { status, description: `${status} from the console` } });
      pecs.reload();
    } catch (e) { notify.error(e, `${status} failed`); }
  };
  return (
    <CapabilityContainer id="azure.servicebus.namespace.private_endpoints" title="Private endpoint connections">
      <ErrorBar error={pecs.error} />
      <BrowseGrid
        resourceName="private endpoint connection" rowKey={(r) => r.name} filterPlaceholder="Filter by name..."
        items={pecs.data || []} loading={pecs.loading} onRefresh={pecs.reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(!add)}>Private endpoint</ToolbarButton>
          <ToolbarButton onClick={async () => { for (const r of (pecs.data || [])) await set(r, "Approved"); }}>Approve all</ToolbarButton>
        </>}
        onDelete={async (sel) => { for (const r of sel) await api.deletePrivateEndpointConnection(a.resourceGroup, a.name, r.name); pecs.reload(); }}
        columns={[
          { key: "name", label: "Connection name" },
          { key: "state", label: "Connection state", value: (r) => r.properties?.privateLinkServiceConnectionState?.status || "Pending" },
          { key: "pe", label: "Private endpoint", value: (r) => (r.properties?.privateEndpoint?.id || "").split("/").pop() || "--" },
          { key: "act", label: "Actions", render: (r) => (
            <span style={{ display: "flex", gap: 4 }}>
              <Button size="small" onClick={() => set(r, "Approved")}>Approve</Button>
              <Button size="small" onClick={() => set(r, "Rejected")}>Reject</Button>
            </span>) },
        ]}
      />
      {add && (
        <div style={{ display: "flex", gap: 8, alignItems: "end", marginTop: 12 }}>
          <Field label="Name"><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Private endpoint name" /></Field>
          <Field label="Subnet resource ID"><Input value={subnet} onChange={(_, d) => setSubnet(d.value)} aria-label="Subnet resource ID" style={{ minWidth: 360 }} /></Field>
          <Button appearance="primary" disabled={!/^[A-Za-z0-9._-]{1,80}$/.test(name)} onClick={async () => {
            try {
              await api.putPrivateEndpointConnection(a.resourceGroup, a.name, `${name}.${Math.random().toString(16).slice(2, 10)}`, {
                privateEndpoint: { id: `/subscriptions/${a._sub || ""}/resourceGroups/${a.resourceGroup}/providers/Microsoft.Network/privateEndpoints/${name}` },
                privateLinkServiceConnectionState: { status: "Approved", description: "Auto-approved" }, ...(subnet ? { subnet: { id: subnet } } : {}),
              });
              setAdd(false); setName(""); setSubnet(""); pecs.reload();
            } catch (e) { notify.error(e, "Creating the private endpoint failed"); }
          }}>Create</Button>
        </div>
      )}
    </CapabilityContainer>
  );
}
