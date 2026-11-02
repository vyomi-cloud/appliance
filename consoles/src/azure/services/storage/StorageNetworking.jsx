/* Storage account | Networking — firewall + virtual network rules + resource instances +
 * exceptions + routing + custom domain, all stored on properties.networkAcls /
 * routingPreference / customDomain over ARM. The Blob data plane ENFORCES networkAcls
 * (core/azure_storage_net.py): see the capability registry for the caller concepts. */
import { useEffect, useState } from "react";
import { Button, Checkbox, Field, Input, Radio, RadioGroup, Select, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading } from "../../kit/common.jsx";
import * as vnetApi from "../vnets/api.js";
import * as api from "./api.js";

const DEFAULT_ACLS = { defaultAction: "Allow", bypass: "AzureServices", ipRules: [], virtualNetworkRules: [], resourceAccessRules: [] };

export default function Networking({ a, reload }) {
  const p = a.properties || {};
  const notify = useNotify();
  const [tab, setTab] = useState("public");
  const init = () => ({
    scope: p.publicNetworkAccess === "Disabled" ? "disabled" : p.networkAcls?.defaultAction === "Deny" ? "selected" : "all",
    acls: { ...DEFAULT_ACLS, ...(p.networkAcls || {}) },
    routing: p.routingPreference?.routingChoice || "MicrosoftRouting",
    pubMs: !!p.routingPreference?.publishMicrosoftEndpoints, pubInet: !!p.routingPreference?.publishInternetEndpoints,
    domain: p.customDomain?.name || "", subDomain: !!p.customDomain?.useSubDomainName,
  });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  const [ip, setIp] = useState("");
  const [subnetId, setSubnetId] = useState("");
  const [resId, setResId] = useState("");
  useEffect(() => setF(init()), [a]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const acls = f.acls;
  const setAcls = (patch) => setF((x) => ({ ...x, acls: { ...x.acls, ...patch } }));
  const subnets = useAsync(async () => {
    const out = [];
    for (const v of await vnetApi.listVnets()) for (const s of await vnetApi.listSubnets(v.resourceGroup, v.name)) out.push({ id: s.id, label: `${v.name} / ${s.name}`, vnet: v.name });
    return out;
  }, [a.id]);
  const bypass = String(acls.bypass || "None").split(",").map((s) => s.trim()).filter(Boolean);
  const toggleBypass = (k, on) => { const s = new Set(bypass.filter((x) => x !== "None")); on ? s.add(k) : s.delete(k); setAcls({ bypass: s.size ? [...s].join(", ") : "None" }); };

  const save = async () => {
    setBusy(true);
    try {
      const props = {
        publicNetworkAccess: f.scope === "disabled" ? "Disabled" : "Enabled",
        networkAcls: { ...acls, defaultAction: f.scope === "selected" ? "Deny" : "Allow" },
        routingPreference: { routingChoice: f.routing, publishMicrosoftEndpoints: f.pubMs, publishInternetEndpoints: f.pubInet },
      };
      if (f.domain || p.customDomain?.name) props.customDomain = { name: f.domain, useSubDomainName: f.subDomain };
      await api.updateStorageAccount(a.resourceGroup, a.name, { properties: props });
      notify.success(`Networking settings on '${a.name}' were saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving networking settings failed"); }
    finally { setBusy(false); }
  };
  const saveBar = (
    <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Save</ToolbarButton>
  );
  const addIp = (v) => { if (!v) return; setAcls({ ipRules: [...(acls.ipRules || []), { value: v, action: "Allow" }] }); setIp(""); };
  const selected = f.scope === "selected";

  return (
    <>
      <div className="vy-panel-title">{a.name} | Networking</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Networking tabs">
        <Tab value="public">Public access</Tab>
        <Tab value="private">Private access</Tab>
        <Tab value="advanced">Advanced</Tab>
      </TabList>
      {tab === "public" && <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
        <CapabilityContainer id="azure.storage.networking" title="Public network access" actions={saveBar}>
          <div className="vy-form-row"><span className="vy-label">Public network access scope</span>
            <RadioGroup value={f.scope} onChange={(_, d) => setF((x) => ({ ...x, scope: d.value }))} aria-label="Public network access scope">
              <Radio value="all" label="Enabled from all networks" />
              <Radio value="selected" label="Enabled from selected virtual networks and IP addresses" />
              <Radio value="disabled" label="Disabled" />
            </RadioGroup>
          </div>
        </CapabilityContainer>
        {selected && <>
          <CapabilityContainer id="azure.storage.networking.vnets" title="Virtual networks">
            <ErrorBar error={subnets.error} />
            <table className="vy-grid">
              <thead><tr><th>Virtual network / subnet</th><th>Subnet id</th><th /></tr></thead>
              <tbody>
                {(acls.virtualNetworkRules || []).length ? acls.virtualNetworkRules.map((r, i) => (
                  <tr key={r.id}><td>{r.id.split("/virtualNetworks/")[1]?.replace("/subnets/", " / ")}</td><td className="vy-mono">{r.id}</td>
                    <td><Button appearance="subtle" icon={<Delete20Regular />} aria-label="Remove virtual network rule" onClick={() => setAcls({ virtualNetworkRules: acls.virtualNetworkRules.filter((_, j) => j !== i) })} /></td></tr>
                )) : <tr><td colSpan={3} className="vy-muted">No virtual network rules.</td></tr>}
              </tbody>
            </table>
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "end" }}>
              <Field label="Add existing virtual network subnet" style={{ minWidth: 320 }}>
                <Select value={subnetId} onChange={(_, d) => setSubnetId(d.value)} aria-label="Subnet to add">
                  <option value="">Select a subnet</option>
                  {(subnets.data || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </Select>
              </Field>
              <Button icon={<Add20Regular />} disabled={!subnetId} onClick={() => { setAcls({ virtualNetworkRules: [...(acls.virtualNetworkRules || []), { id: subnetId, action: "Allow" }] }); setSubnetId(""); }}>Add virtual network rule</Button>
            </div>
          </CapabilityContainer>
          <CapabilityContainer id="azure.storage.networking.firewall" title="Firewall">
            <table className="vy-grid">
              <thead><tr><th>Address range</th><th /></tr></thead>
              <tbody>
                {(acls.ipRules || []).length ? acls.ipRules.map((r, i) => (
                  <tr key={r.value}><td className="vy-mono">{r.value}</td>
                    <td><Button appearance="subtle" icon={<Delete20Regular />} aria-label={`Remove ${r.value}`} onClick={() => setAcls({ ipRules: acls.ipRules.filter((_, j) => j !== i) })} /></td></tr>
                )) : <tr><td colSpan={2} className="vy-muted">No address ranges.</td></tr>}
              </tbody>
            </table>
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "end" }}>
              <Field label="IP address or CIDR"><Input value={ip} onChange={(_, d) => setIp(d.value)} placeholder="for example, 203.0.113.0/24" aria-label="IP address or CIDR" /></Field>
              <Button icon={<Add20Regular />} disabled={!ip} onClick={() => addIp(ip)}>Add IP range</Button>
              <Button onClick={() => addIp("127.0.0.1")}>Add your client IP address</Button>
            </div>
          </CapabilityContainer>
          <CapabilityContainer id="azure.storage.networking.resources" title="Resource instances">
            <table className="vy-grid">
              <thead><tr><th>Resource id</th><th>Tenant</th><th /></tr></thead>
              <tbody>
                {(acls.resourceAccessRules || []).length ? acls.resourceAccessRules.map((r, i) => (
                  <tr key={r.resourceId}><td className="vy-mono">{r.resourceId}</td><td className="vy-mono">{r.tenantId}</td>
                    <td><Button appearance="subtle" icon={<Delete20Regular />} aria-label="Remove resource instance" onClick={() => setAcls({ resourceAccessRules: acls.resourceAccessRules.filter((_, j) => j !== i) })} /></td></tr>
                )) : <tr><td colSpan={3} className="vy-muted">No resource instances.</td></tr>}
              </tbody>
            </table>
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "end" }}>
              <Field label="Resource id"><Input value={resId} onChange={(_, d) => setResId(d.value)} aria-label="Resource instance id" style={{ minWidth: 380 }} /></Field>
              <Button icon={<Add20Regular />} disabled={!resId} onClick={() => { setAcls({ resourceAccessRules: [...(acls.resourceAccessRules || []), { resourceId: resId, tenantId: "00000000-0000-0000-0000-000000000000" }] }); setResId(""); }}>Add resource instance</Button>
            </div>
          </CapabilityContainer>
          <CapabilityContainer id="azure.storage.networking.exceptions" title="Exceptions">
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <Checkbox checked={bypass.includes("AzureServices")} onChange={(_, d) => toggleBypass("AzureServices", d.checked)} label="Allow Azure services on the trusted services list to access this storage account" />
              <Checkbox checked={bypass.includes("Logging")} onChange={(_, d) => toggleBypass("Logging", d.checked)} label="Allow read access to storage logging from any network" />
              <Checkbox checked={bypass.includes("Metrics")} onChange={(_, d) => toggleBypass("Metrics", d.checked)} label="Allow read access to storage metrics from any network" />
            </div>
          </CapabilityContainer>
        </>}
      </div>}
      {tab === "private" && <CapabilityContainer id="azure.storage.networking.privateendpoints" title="Private endpoint connections" />}
      {tab === "advanced" && <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 12 }}>
        <CapabilityContainer id="azure.storage.networking.routing" title="Network routing" actions={saveBar}>
          <div className="vy-form-row"><span className="vy-label">Routing preference</span>
            <RadioGroup layout="horizontal" value={f.routing} onChange={(_, d) => setF((x) => ({ ...x, routing: d.value }))} aria-label="Routing preference">
              <Radio value="MicrosoftRouting" label="Microsoft network routing" /><Radio value="InternetRouting" label="Internet routing" />
            </RadioGroup>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <Checkbox checked={f.pubMs} onChange={(_, d) => setF((x) => ({ ...x, pubMs: d.checked }))} label="Publish Microsoft network routing endpoints" />
            <Checkbox checked={f.pubInet} onChange={(_, d) => setF((x) => ({ ...x, pubInet: d.checked }))} label="Publish Internet routing endpoints" />
          </div>
          {(f.pubMs || f.pubInet) && <div style={{ marginTop: 8 }}>
            {a.properties?.routingPreference?.publishMicrosoftEndpoints && <KV label="Microsoft routing Blob endpoint" value={`https://${a.name}-microsoftrouting.blob.core.windows.net/`} />}
            {a.properties?.routingPreference?.publishInternetEndpoints && <KV label="Internet routing Blob endpoint" value={`https://${a.name}-internetrouting.blob.core.windows.net/`} />}
          </div>}
        </CapabilityContainer>
        <CapabilityContainer id="azure.storage.networking.customdomain" title="Custom domain" actions={saveBar}>
          <Field label="Domain name" hint="Leave empty to remove the custom domain mapping."><Input value={f.domain} onChange={(_, d) => setF((x) => ({ ...x, domain: d.value }))} placeholder="www.contoso.com" aria-label="Custom domain name" /></Field>
          <Checkbox checked={f.subDomain} onChange={(_, d) => setF((x) => ({ ...x, subDomain: d.checked }))} label="Use indirect CNAME validation" />
        </CapabilityContainer>
      </div>}
    </>
  );
}
