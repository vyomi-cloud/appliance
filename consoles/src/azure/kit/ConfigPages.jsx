/* Configuration pages that are plain ARM properties / child resources, validated by core/azure_cfgext_core.py:
 * AKS (KEDA, Networking authorized IP ranges, Extensions + applications), Cosmos DB (CORS, Dedicated Gateway,
 * Data encryption / CMK), Service Bus (Encryption, Networking), App Configuration (Encryption).
 * Every save goes over the native ARM wire; the capability registry says exactly what is and is not enforced. */
import { useState } from "react";
import { Button, Checkbox, Field, Input, Select, Textarea } from "@fluentui/react-components";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading } from "./common.jsx";
import { AddVnetDialog } from "./NetworkRules.jsx";

const q = (v) => ({ "api-version": v });

function useSave(reload) {
  const notify = useNotify();
  return async (fn, ok) => {
    try { await fn(); notify.success(ok, "Saved"); await reload?.(); return true; } catch (e) { notify.error(e, "Saving failed"); return false; }
  };
}

// ── AKS ───────────────────────────────────────────────────────────────────────────────
const AKS_V = q("2024-09-02-preview");

export function AksKeda({ a, reload }) {
  const save = useSave(reload);
  const on = !!a.properties?.workloadAutoScalerProfile?.keda?.enabled;
  const set = (enabled) => save(() => restJson("PATCH", a.id, { query: AKS_V, body: { properties: { workloadAutoScalerProfile: { keda: { enabled } } } } }),
    `KEDA was ${enabled ? "enabled" : "disabled"} on '${a.name}'.`);
  return (
    <CapabilityContainer id="azure.aks.keda" title={`${a.name} | Application scaling`}>
      <KV label="Kubernetes version" value={a.properties?.kubernetesVersion || "-"} />
      <KV label="KEDA (event-driven autoscaling)" value={on ? "Enabled" : "Disabled"} />
      <div style={{ marginTop: 8 }}>
        <Button appearance="primary" aria-label={on ? "Disable KEDA" : "Enable KEDA"} onClick={() => set(!on)}>{on ? "Disable KEDA" : "Enable KEDA"}</Button>
      </div>
      <p className="vy-muted" style={{ fontSize: 13 }}>KEDA needs Kubernetes 1.23 or later, as in Azure. ScaledObjects can be applied from Run command; Vyomi stores them but runs no scaler.</p>
    </CapabilityContainer>
  );
}

export function AksNetworkingSettings({ a, reload }) {
  const save = useSave(reload);
  const np = a.properties?.networkProfile || {};
  const api = a.properties?.apiServerAccessProfile || {};
  const [ranges, setRanges] = useState((api.authorizedIPRanges || []).join("\n"));
  const list = ranges.split(/[\s,]+/).filter(Boolean);
  return (
    <>
      <CapabilityContainer id="azure.aks.networking_settings" title={`${a.name} | Networking`}>
        <KV label="Network plugin" value={np.networkPlugin || "kubenet"} />
        <KV label="Network policy" value={np.networkPolicy || "None"} />
        <KV label="Load balancer SKU" value={np.loadBalancerSku || "standard"} />
        <KV label="Outbound type" value={np.outboundType || "loadBalancer"} />
        <KV label="Service CIDR" value={np.serviceCidr || "10.0.0.0/16"} />
        <KV label="DNS service IP" value={np.dnsServiceIP || "10.0.0.10"} />
        <KV label="Pod CIDR" value={np.podCidr || "10.244.0.0/16"} />
        <KV label="Private cluster" value={api.enablePrivateCluster ? "Yes" : "No"} />
        <p className="vy-muted" style={{ fontSize: 13 }}>The network plugin, CIDRs and outbound type are fixed when the cluster is created (Networking tab of the create wizard), as in Azure.</p>
      </CapabilityContainer>
      <section className="vy-form-section">
        <h3>API server authorized IP ranges</h3>
        <Field label="Authorized IP ranges (CIDR, one per line)">
          <Textarea value={ranges} onChange={(_, d) => setRanges(d.value)} rows={4} aria-label="Authorized IP ranges" disabled={!!api.enablePrivateCluster} />
        </Field>
        <Button appearance="primary" style={{ marginTop: 8 }} aria-label="Save authorized IP ranges"
          onClick={() => save(() => restJson("PATCH", a.id, { query: AKS_V, body: { properties: { apiServerAccessProfile: { authorizedIPRanges: list } } } }), "Authorized IP ranges were saved.")}>Save</Button>
      </section>
    </>
  );
}

const EXT_TYPES = ["microsoft.flux", "microsoft.azuremonitor.containers", "microsoft.dapr", "microsoft.azurekeyvaultsecretsprovider", "microsoft.azuredefender.kubernetes",
  "microsoft.openservicemesh", "microsoft.azureml.kubernetes", "microsoft.web.appservice", "microsoft.azurebackup.kubernetes", "microsoft.containerstorage"];
const EXT_V = q("2023-05-01");

export function AksExtensions({ a }) {
  const save = useSave();
  const base = `${a.id}/providers/Microsoft.KubernetesConfiguration/extensions`;
  const list = useAsync(async () => (await restJson("GET", base, { query: EXT_V })).value || [], [a.id]);
  const [f, setF] = useState({ name: "", extensionType: EXT_TYPES[2], version: "", releaseTrain: "Stable" });
  const add = async () => {
    const ok = await save(() => restJson("PUT", `${base}/${f.name}`, { query: EXT_V, body: { properties: {
      extensionType: f.extensionType, releaseTrain: f.releaseTrain, autoUpgradeMinorVersion: !f.version, ...(f.version ? { version: f.version } : {}), scope: { cluster: { releaseNamespace: f.extensionType.split(".").pop() } } } } }),
    `Extension '${f.name}' was installed.`);
    if (ok) { setF({ ...f, name: "", version: "" }); list.reload(); }
  };
  return (
    <CapabilityContainer id="azure.aks.extensions" title={`${a.name} | Extensions + applications`}>
      <ErrorBar error={list.error} />
      {list.loading && !list.data ? <Loading /> : (
        <table className="vy-grid" aria-label="Cluster extensions">
          <thead><tr><th>Name</th><th>Type</th><th>Version</th><th>Release train</th><th>Provisioning state</th><th /></tr></thead>
          <tbody>{(list.data || []).length ? list.data.map((e) => (
            <tr key={e.name}><td>{e.name}</td><td>{e.properties?.extensionType}</td><td>{e.properties?.installedVersion}</td><td>{e.properties?.releaseTrain}</td><td>{e.properties?.provisioningState}</td>
              <td><Button size="small" aria-label={`Uninstall ${e.name}`} onClick={async () => { await save(() => restJson("DELETE", `${base}/${e.name}`, { query: EXT_V }), `Extension '${e.name}' was uninstalled.`); list.reload(); }}>Uninstall</Button></td></tr>
          )) : <tr><td colSpan={6} className="vy-muted">No extensions installed.</td></tr>}</tbody>
        </table>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 12, flexWrap: "wrap" }}>
        <Field label="Extension type"><Select value={f.extensionType} onChange={(_, d) => setF((x) => ({ ...x, extensionType: d.value }))} aria-label="Extension type">{EXT_TYPES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
        <Field label="Extension name"><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Extension name" /></Field>
        <Field label="Version (blank = auto upgrade)"><Input value={f.version} onChange={(_, d) => setF((x) => ({ ...x, version: d.value }))} aria-label="Extension version" /></Field>
        <Field label="Release train"><Select value={f.releaseTrain} onChange={(_, d) => setF((x) => ({ ...x, releaseTrain: d.value }))} aria-label="Release train"><option>Stable</option><option>Preview</option></Select></Field>
        <Button appearance="primary" disabled={!f.name} onClick={add} aria-label="Install extension">Install</Button>
      </div>
    </CapabilityContainer>
  );
}

// ── Cosmos DB ──────────────────────────────────────────────────────────────────────────
const COSMOS_V = q("2024-05-15");

export function CosmosCors({ a, reload }) {
  const save = useSave(reload);
  const [rules, setRules] = useState(a.properties?.cors || []);
  const edit = (i, k, v) => setRules((r) => r.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  return (
    <CapabilityContainer id="azure.cosmos.cors" title={`${a.name} | CORS`}>
      <InfoBar>Allowed origins are comma separated (https://app.example.com, https://*.example.org, or *).</InfoBar>
      <table className="vy-grid" aria-label="CORS rules">
        <thead><tr><th>Allowed origins</th><th>Allowed methods</th><th>Allowed headers</th><th>Max age (s)</th><th /></tr></thead>
        <tbody>{rules.length ? rules.map((r, i) => (
          <tr key={i}>
            <td><Input value={r.allowedOrigins || ""} onChange={(_, d) => edit(i, "allowedOrigins", d.value)} aria-label={`Allowed origins ${i + 1}`} /></td>
            <td><Input value={r.allowedMethods || ""} onChange={(_, d) => edit(i, "allowedMethods", d.value)} aria-label={`Allowed methods ${i + 1}`} /></td>
            <td><Input value={r.allowedHeaders || ""} onChange={(_, d) => edit(i, "allowedHeaders", d.value)} aria-label={`Allowed headers ${i + 1}`} /></td>
            <td><Input type="number" value={String(r.maxAgeInSeconds ?? "")} onChange={(_, d) => edit(i, "maxAgeInSeconds", d.value === "" ? undefined : Number(d.value))} aria-label={`Max age ${i + 1}`} /></td>
            <td><Button size="small" aria-label={`Delete CORS rule ${i + 1}`} onClick={() => setRules((x) => x.filter((_, j) => j !== i))}>Delete</Button></td>
          </tr>
        )) : <tr><td colSpan={5} className="vy-muted">No CORS rules.</td></tr>}</tbody>
      </table>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <Button onClick={() => setRules((r) => [...r, { allowedOrigins: "" }])} aria-label="Add CORS rule">Add rule</Button>
        <Button appearance="primary" aria-label="Save CORS rules" onClick={() => save(() => restJson("PATCH", a.id, { query: COSMOS_V, body: { properties: { cors: rules } } }), "CORS rules were saved.")}>Save</Button>
      </div>
    </CapabilityContainer>
  );
}

export function CosmosDedicatedGateway({ a }) {
  const save = useSave();
  const path = `${a.id}/services/SqlDedicatedGateway`;
  const gw = useAsync(() => restJson("GET", path, { query: COSMOS_V }).catch(() => null), [a.id]);
  const [size, setSize] = useState("Cosmos.D4s");
  const [count, setCount] = useState("1");
  const cur = gw.data?.properties;
  return (
    <CapabilityContainer id="azure.cosmos.dedicatedgateway" title={`${a.name} | Dedicated Gateway`}>
      {gw.loading && !gw.data ? <Loading /> : cur ? (
        <>
          <KV label="Status" value={cur.status} />
          <KV label="Gateway size" value={cur.instanceSize} />
          <KV label="Number of instances" value={String(cur.instanceCount)} />
          <KV label="Dedicated gateway endpoint" value={cur.sqlDedicatedGatewayEndpoint} />
          <div style={{ marginTop: 8 }}><Button aria-label="Deprovision dedicated gateway" onClick={async () => { await save(() => restJson("DELETE", path, { query: COSMOS_V }), "The dedicated gateway was deprovisioned."); gw.reload(); }}>Deprovision</Button></div>
        </>
      ) : <p className="vy-muted">No dedicated gateway is provisioned for this account.</p>}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 12 }}>
        <Field label="Gateway size"><Select value={size} onChange={(_, d) => setSize(d.value)} aria-label="Gateway size"><option>Cosmos.D4s</option><option>Cosmos.D8s</option><option>Cosmos.D16s</option></Select></Field>
        <Field label="Number of instances"><Input type="number" value={count} onChange={(_, d) => setCount(d.value)} aria-label="Number of instances" /></Field>
        <Button appearance="primary" aria-label={cur ? "Update dedicated gateway" : "Provision dedicated gateway"}
          onClick={async () => { await save(() => restJson("PUT", path, { query: COSMOS_V, body: { properties: { serviceType: "SqlDedicatedGateway", instanceSize: size, instanceCount: Number(count) } } }), "The dedicated gateway was provisioned."); gw.reload(); }}>{cur ? "Update" : "Provision"}</Button>
      </div>
    </CapabilityContainer>
  );
}

export function CosmosDataEncryption({ a, reload }) {
  const save = useSave(reload);
  const cur = a.properties?.keyVaultKeyUri || "";
  const [uri, setUri] = useState(cur);
  const [sys, setSys] = useState(true);
  return (
    <CapabilityContainer id="azure.cosmos.dataencryption" title={`${a.name} | Data Encryption`}>
      <KV label="Encryption key" value={cur ? "Customer-managed key" : "Service-managed key"} />
      <Field label="Key Vault key URI" style={{ maxWidth: 560 }}><Input value={uri} onChange={(_, d) => setUri(d.value)} placeholder="https://<vault>.vault.azure.net/keys/<name>" aria-label="Key Vault key URI" /></Field>
      <Checkbox checked={sys} onChange={(_, d) => setSys(!!d.checked)} label="Use the system-assigned identity to access the key" />
      <div style={{ marginTop: 8 }}>
        <Button appearance="primary" disabled={!uri} aria-label="Save encryption key"
          onClick={() => save(async () => {
            if (!a.identity || String(a.identity.type || "None") === "None") await restJson("PATCH", a.id, { query: COSMOS_V, body: { identity: { type: "SystemAssigned" } } });
            await restJson("PATCH", a.id, { query: COSMOS_V, body: { properties: { keyVaultKeyUri: uri, defaultIdentity: sys ? "SystemAssignedIdentity" : a.properties?.defaultIdentity } } });
          }, cur ? "The customer-managed key was rotated." : "The customer-managed key was saved.")}>{cur ? "Rotate key" : "Save"}</Button>
      </div>
      <p className="vy-muted" style={{ fontSize: 13 }}>As in Azure, once an account uses a customer-managed key it cannot go back to a service-managed key.</p>
    </CapabilityContainer>
  );
}

// ── Service Bus ────────────────────────────────────────────────────────────────────────
const SB_V = q("2022-10-01-preview");

export function SbEncryption({ a, reload }) {
  const save = useSave(reload);
  const premium = String(a.sku?.name || "").toLowerCase() === "premium";
  const cur = a.properties?.encryption?.keyVaultProperties?.[0];
  const [f, setF] = useState({ vault: cur?.keyVaultUri || "", key: cur?.keyName || "", infra: !!a.properties?.encryption?.requireInfrastructureEncryption });
  return (
    <CapabilityContainer id="azure.servicebus.namespace.encryption" title={`${a.name} | Encryption`}>
      {!premium && <InfoBar intent="warning">Customer-managed keys are only available on Premium namespaces.</InfoBar>}
      <KV label="Encryption" value={cur ? `Customer-managed key (${cur.keyName})` : "Microsoft-managed key"} />
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", margin: "8px 0" }}>
        <Field label="Key vault URI"><Input value={f.vault} onChange={(_, d) => setF((x) => ({ ...x, vault: d.value }))} placeholder="https://<vault>.vault.azure.net" aria-label="Key vault URI" /></Field>
        <Field label="Key name"><Input value={f.key} onChange={(_, d) => setF((x) => ({ ...x, key: d.value }))} aria-label="Key name" /></Field>
        <Checkbox checked={f.infra} onChange={(_, d) => setF((x) => ({ ...x, infra: !!d.checked }))} label="Enable infrastructure double encryption" />
      </div>
      <Button appearance="primary" disabled={!premium || !f.vault || !f.key} aria-label="Save encryption"
        onClick={() => save(async () => {
          if (!a.identity || String(a.identity.type || "None") === "None") await restJson("PATCH", a.id, { query: SB_V, body: { identity: { type: "SystemAssigned" } } });
          await restJson("PATCH", a.id, { query: SB_V, body: { properties: { encryption: { keySource: "Microsoft.KeyVault", requireInfrastructureEncryption: f.infra, keyVaultProperties: [{ keyName: f.key, keyVaultUri: f.vault }] } } } });
        }, "Encryption settings were saved.")}>Save</Button>
    </CapabilityContainer>
  );
}

export function SbNetworking({ a }) {
  const save = useSave();
  const premium = String(a.sku?.name || "").toLowerCase() === "premium";
  const path = `${a.id}/networkRuleSets/default`;
  const rs = useAsync(() => restJson("GET", path, { query: SB_V }).catch(() => null), [a.id]);
  const p = rs.data?.properties || { defaultAction: "Allow", publicNetworkAccess: "Enabled", ipRules: [], virtualNetworkRules: [] };
  const [ip, setIp] = useState("");
  const [adding, setAdding] = useState(false);
  const put = async (next, ok) => { if (await save(() => restJson("PUT", path, { query: SB_V, body: { properties: { ...p, ...next } } }), ok)) rs.reload(); };
  return (
    <CapabilityContainer id="azure.servicebus.namespace.networking" title={`${a.name} | Networking`}>
      {!premium && <InfoBar intent="warning">Network rule sets (IP firewall and virtual network rules) are only available on Premium namespaces.</InfoBar>}
      <ErrorBar error={rs.error} />
      <Field label="Public network access" style={{ maxWidth: 360 }}>
        <Select value={p.publicNetworkAccess} disabled={!premium} aria-label="Public network access" onChange={(_, d) => put({ publicNetworkAccess: d.value }, "Public network access was saved.")}>
          <option>Enabled</option><option>Disabled</option></Select>
      </Field>
      <Field label="Default action" style={{ maxWidth: 360, marginTop: 8 }}>
        <Select value={p.defaultAction} disabled={!premium} aria-label="Default action" onChange={(_, d) => put({ defaultAction: d.value }, "Default action was saved.")}>
          <option value="Allow">Allow from all networks</option><option value="Deny">Selected networks</option></Select>
      </Field>
      <h3 style={{ marginTop: 12 }}>Virtual networks</h3>
      <table className="vy-grid" aria-label="Virtual network rules">
        <thead><tr><th>Virtual network</th><th>Subnet</th><th /></tr></thead>
        <tbody>{(p.virtualNetworkRules || []).length ? p.virtualNetworkRules.map((r) => {
          const id = r.subnet?.id || "";
          return <tr key={id}><td>{id.split("/virtualNetworks/")[1]?.split("/")[0]}</td><td>{id.split("/").pop()}</td>
            <td><Button size="small" aria-label={`Remove ${id.split("/").pop()}`} onClick={() => put({ virtualNetworkRules: p.virtualNetworkRules.filter((x) => x !== r) }, "Virtual network rule was removed.")}>Remove</Button></td></tr>;
        }) : <tr><td colSpan={3} className="vy-muted">No virtual network rules.</td></tr>}</tbody>
      </table>
      <div style={{ marginTop: 8 }}>
        {adding ? <AddVnetDialog service="Microsoft.ServiceBus" onClose={() => setAdding(false)} onAdd={(id) => put({ virtualNetworkRules: [...(p.virtualNetworkRules || []), { subnet: { id }, ignoreMissingVnetServiceEndpoint: false }] }, "Virtual network rule was added.")} />
          : <Button disabled={!premium} onClick={() => setAdding(true)} aria-label="Add existing virtual network">Add existing virtual network</Button>}
      </div>
      <h3 style={{ marginTop: 12 }}>Firewall</h3>
      <table className="vy-grid" aria-label="IP rules">
        <thead><tr><th>Address range</th><th /></tr></thead>
        <tbody>{(p.ipRules || []).length ? p.ipRules.map((r) => (
          <tr key={r.ipMask}><td>{r.ipMask}</td><td><Button size="small" aria-label={`Remove ${r.ipMask}`} onClick={() => put({ ipRules: p.ipRules.filter((x) => x !== r) }, "IP rule was removed.")}>Remove</Button></td></tr>
        )) : <tr><td colSpan={2} className="vy-muted">No IP rules.</td></tr>}</tbody>
      </table>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginTop: 8 }}>
        <Field label="Add IP address or CIDR"><Input value={ip} onChange={(_, d) => setIp(d.value)} aria-label="IP address or CIDR" /></Field>
        <Button disabled={!premium || !ip} onClick={async () => { await put({ ipRules: [...(p.ipRules || []), { ipMask: ip, action: "Allow" }] }, "IP rule was added."); setIp(""); }} aria-label="Add IP rule">Add</Button>
      </div>
    </CapabilityContainer>
  );
}

// ── App Configuration ──────────────────────────────────────────────────────────────────
const AC_V = q("2024-05-01");

export function AppConfigEncryption({ a, reload }) {
  const save = useSave(reload);
  const cur = a.properties?.encryption?.keyVaultProperties;
  const [uri, setUri] = useState(cur?.keyIdentifier || "");
  const ok = ["standard", "premium"].includes(String(a.sku?.name || "").toLowerCase());
  return (
    <CapabilityContainer id="azure.appconfiguration.encryption" title={`${a.name} | Encryption`}>
      {!ok && <InfoBar intent="warning">Customer-managed keys require a Standard or Premium configuration store.</InfoBar>}
      <KV label="Encryption" value={cur?.keyIdentifier ? "Customer-managed key" : "Microsoft-managed key"} />
      <Field label="Key identifier" style={{ maxWidth: 560 }}><Input value={uri} onChange={(_, d) => setUri(d.value)} placeholder="https://<vault>.vault.azure.net/keys/<name>" aria-label="Key identifier" /></Field>
      <div style={{ marginTop: 8 }}>
        <Button appearance="primary" disabled={!ok || !uri} aria-label="Save encryption key"
          onClick={() => save(async () => {
            if (!a.identity || String(a.identity.type || "None") === "None") await restJson("PATCH", a.id, { query: AC_V, body: { identity: { type: "SystemAssigned" } } });
            await restJson("PATCH", a.id, { query: AC_V, body: { properties: { encryption: { keyVaultProperties: { keyIdentifier: uri } } } } });
          }, "The customer-managed key was saved.")}>Save</Button>
        {cur?.keyIdentifier && <Button style={{ marginLeft: 8 }} aria-label="Remove encryption key" onClick={() => save(() => restJson("PATCH", a.id, { query: AC_V, body: { properties: { encryption: { keyVaultProperties: null } } } }), "Reverted to a Microsoft-managed key.")}>Use Microsoft-managed key</Button>}
      </div>
    </CapabilityContainer>
  );
}
