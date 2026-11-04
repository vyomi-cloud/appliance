/* Create a Kubernetes cluster: Basics, Node pools, Networking, Integrations, Monitoring,
 * Security, Advanced, Tags, Review + create → one native ARM PUT (cluster) followed by one
 * PUT per declared node pool (the real nested Microsoft.ContainerService/.../agentPools
 * resource — see api.js). */
import { useState } from "react";
import { Button, Checkbox, Input, Link, Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./ClusterBlade.jsx";

const NAME_RE = /^[a-zA-Z0-9](?!.*--)[a-zA-Z0-9-]{0,61}[a-zA-Z0-9]$/;
const RG_RE = /^[-\w._()]{1,90}$/;

function NodePoolRows({ pools, onChange }) {
  const [draft, setDraft] = useState(null);
  const add = () => setDraft({ name: `nodepool${pools.length + 1}`, mode: "System", vmSize: "Standard_DS2_v2", osSku: "Ubuntu", count: 3, zones: "", maxPods: 30 });
  const save = () => { onChange([...pools, draft]); setDraft(null); };
  return (
    <div>
      <Table size="small" aria-label="Node pools" style={{ maxWidth: 920 }}>
        <TableHeader><TableRow>
          <TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Mode</TableHeaderCell><TableHeaderCell>Node size</TableHeaderCell>
          <TableHeaderCell>OS SKU</TableHeaderCell><TableHeaderCell>Node count</TableHeaderCell><TableHeaderCell>Availability zones</TableHeaderCell>
          <TableHeaderCell>Max pods / node</TableHeaderCell><TableHeaderCell style={{ width: 40 }} />
        </TableRow></TableHeader>
        <TableBody>
          {pools.map((p, i) => (
            <TableRow key={p.name + i}>
              <TableCell>{p.name}</TableCell><TableCell>{p.mode}</TableCell><TableCell>{p.vmSize}</TableCell>
              <TableCell>{p.osSku}</TableCell><TableCell>{p.count}</TableCell><TableCell>{p.zones || "None"}</TableCell>
              <TableCell>{p.maxPods}</TableCell>
              <TableCell>{pools.length > 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete node pool ${p.name}`} onClick={() => onChange(pools.filter((_, j) => j !== i))} />}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {draft ? (
        <div style={{ display: "flex", gap: 8, alignItems: "end", marginTop: 8, flexWrap: "wrap" }}>
          <Field label="Name"><Input size="small" value={draft.name} onChange={(_, d) => setDraft({ ...draft, name: d.value })} aria-label="Node pool name" /></Field>
          <Field label="Mode"><Select size="small" value={draft.mode} onChange={(_, d) => setDraft({ ...draft, mode: d.value })} aria-label="Node pool mode"><option>System</option><option>User</option></Select></Field>
          <Field label="Node size"><Input size="small" value={draft.vmSize} onChange={(_, d) => setDraft({ ...draft, vmSize: d.value })} aria-label="Node pool node size" /></Field>
          <Field label="Node count"><Input size="small" type="number" value={String(draft.count)} onChange={(_, d) => setDraft({ ...draft, count: Number(d.value) || 1 })} aria-label="Node pool node count" /></Field>
          <Button appearance="primary" size="small" onClick={save}>Add</Button>
          <Button size="small" onClick={() => setDraft(null)}>Cancel</Button>
        </div>
      ) : <Button style={{ marginTop: 8 }} onClick={add}>Add node pool</Button>}
    </div>
  );
}
const Field = ({ label, children }) => <div style={{ display: "flex", flexDirection: "column", gap: 2 }}><label style={{ fontSize: 12 }}>{label}</label>{children}</div>;

export default function CreateKubernetesCluster() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listClusters(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", preset: "Production Standard", location: "eastus",
    availabilityZones: "None", pricingTier: "Standard", longTermSupport: false, kubernetesVersion: "",
    autoUpgrade: "Enabled with patch (recommended)", nodeSecurityChannel: "Node Image", authMode: "Local accounts with Kubernetes RBAC",
    nodeAutoProvisioning: false, nodePools: [{ name: "nodepool1", mode: "System", vmSize: "Standard_DS2_v2", osSku: "Ubuntu", count: 3, zones: "", maxPods: 30 }],
    virtualNodes: false, osDiskEncryption: "(Default) Encryption at-rest with a platform-managed key",
    privateCluster: false, authorizedIpRanges: "", networkConfig: "Azure CNI Overlay", byoVnet: false, dnsPrefix: "", cilium: true,
    containerRegistry: "None", istio: false, azurePolicy: false,
    containerInsights: true, prometheus: true, grafana: true, alertRules: true,
    defender: false, imageCleaner: false, oidcIssuer: true, workloadIdentity: true,
    infraResourceGroup: "",
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;
  const dnsPrefix = f.dnsPrefix || (f.name ? `${f.name}-dns` : "");

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Cluster name must be 1-63 characters, alphanumeric and hyphens, starting and ending with alphanumeric.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`A kubernetes service named "${f.name}" already exists.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Cluster name") || m.startsWith("A kubernetes"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription to manage deployed resources and costs. Use resource groups to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="aks-sub">
          <Select id="aks-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="aks-rg">
          {newRg === null ? (
            <>
              <Select id="aks-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="aks-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Cluster details">
        <FormRow label="Cluster preset configuration" htmlFor="aks-preset">
          <Select id="aks-preset" value={f.preset} onChange={set("preset")} aria-label="Cluster preset configuration">
            <option>Production Standard</option><option>Dev/Test</option><option>Production Economy</option><option>Production Enterprise</option>
          </Select>
        </FormRow>
        <FormRow label="Kubernetes cluster name" required htmlFor="aks-name" info="1-63 chars; letters, numbers, hyphens">
          <Input id="aks-name" value={f.name} onChange={set("name")} aria-label="Kubernetes cluster name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="aks-region">
          <Select id="aks-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Fleet Manager" htmlFor="aks-fleet">
          <Select id="aks-fleet" value="None" aria-label="Fleet Manager"><option>None</option></Select>
        </FormRow>
        <FormRow label="Availability zones" htmlFor="aks-zones">
          <Select id="aks-zones" value={f.availabilityZones} onChange={set("availabilityZones")} aria-label="Availability zones">
            <option>None</option><option>Zone 1,2,3</option>
          </Select>
        </FormRow>
        <FormRow label="AKS pricing tier" htmlFor="aks-tier">
          <Select id="aks-tier" value={f.pricingTier} onChange={set("pricingTier")} aria-label="AKS pricing tier">
            <option value="Free">Free</option><option value="Standard">Standard</option><option value="Premium">Premium</option>
          </Select>
        </FormRow>
        <FormRow label="Enable long-term support"><Checkbox checked={f.longTermSupport} onChange={chk("longTermSupport")} aria-label="Enable long-term support" /></FormRow>
        <FormRow label="Kubernetes version" htmlFor="aks-version">
          <Select id="aks-version" value={f.kubernetesVersion} onChange={set("kubernetesVersion")} aria-label="Kubernetes version">
            <option value="">(default)</option><option value="1.29.2">1.29.2 (default)</option><option value="1.28.5">1.28.5</option><option value="1.27.9">1.27.9</option>
          </Select>
        </FormRow>
        <FormRow label="Automatic upgrade" htmlFor="aks-autoupgrade">
          <Select id="aks-autoupgrade" value={f.autoUpgrade} onChange={set("autoUpgrade")} aria-label="Automatic upgrade">
            <option>Enabled with patch (recommended)</option><option>Enabled with stable</option><option>Enabled with rapid</option><option>Enabled with node image</option><option>Disabled</option>
          </Select>
        </FormRow>
        <FormRow label="Automatic upgrade scheduler"><Input readOnly value="Every week on Sunday (recommended)" aria-label="Automatic upgrade scheduler" /></FormRow>
        <FormRow label="Node security channel type" htmlFor="aks-secchannel">
          <Select id="aks-secchannel" value={f.nodeSecurityChannel} onChange={set("nodeSecurityChannel")} aria-label="Node security channel type">
            <option>None</option><option>Unmanaged</option><option>Security Patch</option><option>Node Image</option>
          </Select>
        </FormRow>
        <FormRow label="Security channel scheduler"><Input readOnly value="Every week on Sunday (recommended)" aria-label="Security channel scheduler" /></FormRow>
      </FormSection>
      <FormSection title="Authentication and Authorization">
        <FormRow label="Authentication and Authorization" htmlFor="aks-auth">
          <Select id="aks-auth" value={f.authMode} onChange={set("authMode")} aria-label="Authentication and Authorization">
            <option>Local accounts with Kubernetes RBAC</option>
            <option>Microsoft Entra ID authentication with Kubernetes RBAC</option>
            <option>Microsoft Entra ID authentication with Azure RBAC</option>
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const nodePools = (
    <>
      <FormSection title="Node auto provisioning">
        <FormRow label="Enable node auto-provisioning"><Checkbox checked={f.nodeAutoProvisioning} onChange={chk("nodeAutoProvisioning")} aria-label="Enable node auto-provisioning" /></FormRow>
      </FormSection>
      <FormSection title="Node pools">
        <FormRow label="Node pools"><NodePoolRows pools={f.nodePools} onChange={(p) => setF((x) => ({ ...x, nodePools: p }))} /></FormRow>
      </FormSection>
      <FormSection title="Enable virtual nodes">
        <FormRow label="Enable virtual nodes"><Checkbox checked={f.virtualNodes} onChange={chk("virtualNodes")} aria-label="Enable virtual nodes" /></FormRow>
      </FormSection>
      <FormSection title="Node pool OS disk encryption">
        <FormRow label="Encryption type" htmlFor="aks-encryption">
          <Select id="aks-encryption" value={f.osDiskEncryption} onChange={set("osDiskEncryption")} aria-label="Encryption type">
            <option>(Default) Encryption at-rest with a platform-managed key</option>
            <option>Encryption at-rest with a customer-managed key</option>
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <>
      <FormSection title="Private access">
        <FormRow label="Enable private cluster"><Checkbox checked={f.privateCluster} onChange={chk("privateCluster")} aria-label="Enable private cluster" /></FormRow>
      </FormSection>
      <FormSection title="Public access">
        <FormRow label="Set authorized IP ranges">
          <Checkbox checked={!!f.authorizedIpRanges} onChange={(_, d) => setF((x) => ({ ...x, authorizedIpRanges: d.checked ? x.authorizedIpRanges || "0.0.0.0/0" : "" }))} aria-label="Set authorized IP ranges" />
        </FormRow>
      </FormSection>
      <FormSection title="Container networking">
        <FormRow label="Network configuration">
          <RadioGroup value={f.networkConfig} onChange={set("networkConfig")} aria-label="Network configuration">
            <Radio value="Azure CNI Overlay" label="Azure CNI Overlay" />
            <Radio value="Azure CNI Node Subnet" label="Azure CNI Node Subnet" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Bring your own Azure virtual network"><Checkbox checked={f.byoVnet} onChange={chk("byoVnet")} aria-label="Bring your own Azure virtual network" /></FormRow>
        <FormRow label="DNS name prefix" required htmlFor="aks-dns">
          <Input id="aks-dns" value={f.dnsPrefix} placeholder={dnsPrefix} onChange={set("dnsPrefix")} aria-label="DNS name prefix" />
        </FormRow>
        <FormRow label="Enable Cilium dataplane and network policy engine"><Checkbox checked={f.cilium} onChange={chk("cilium")} aria-label="Enable Cilium dataplane and network policy engine" /></FormRow>
        <FormRow label="Load balancer"><Input readOnly value="Standard" aria-label="Load balancer" /></FormRow>
      </FormSection>
    </>
  );

  const integrations = (
    <>
      <FormSection title="Azure Container Registry">
        <FormRow label="Container registry" htmlFor="aks-acr">
          <Select id="aks-acr" value={f.containerRegistry} onChange={set("containerRegistry")} aria-label="Container registry"><option>None</option></Select>
        </FormRow>
      </FormSection>
      <FormSection title="Service mesh">
        <FormRow label="Enable Istio"><Checkbox checked={f.istio} onChange={chk("istio")} aria-label="Enable Istio" /></FormRow>
      </FormSection>
      <FormSection title="Azure Policy">
        <FormRow label="Azure Policy"><Checkbox checked={f.azurePolicy} onChange={chk("azurePolicy")} aria-label="Azure Policy" /></FormRow>
      </FormSection>
    </>
  );

  const monitoring = (
    <>
      <FormSection title="Container Insights">
        <FormRow label="Enable Container Insights"><Checkbox checked={f.containerInsights} onChange={chk("containerInsights")} aria-label="Enable Container Insights" /></FormRow>
      </FormSection>
      <FormSection title="Managed Prometheus">
        <FormRow label="Enable Prometheus metrics"><Checkbox checked={f.prometheus} onChange={chk("prometheus")} aria-label="Enable Prometheus metrics" /></FormRow>
      </FormSection>
      <FormSection title="Managed Grafana">
        <FormRow label="Enable Grafana"><Checkbox checked={f.grafana} onChange={chk("grafana")} aria-label="Enable Grafana" /></FormRow>
      </FormSection>
      <FormSection title="Alerts">
        <FormRow label="Enable recommended alert rules"><Checkbox checked={f.alertRules} onChange={chk("alertRules")} aria-label="Enable recommended alert rules" /></FormRow>
      </FormSection>
    </>
  );

  const security = (
    <>
      <FormSection title="Microsoft Defender for Cloud">
        <FormRow label="Enable Microsoft Defender"><Checkbox checked={f.defender} onChange={chk("defender")} aria-label="Enable Microsoft Defender" /></FormRow>
      </FormSection>
      <FormSection title="Image cleaner">
        <FormRow label="Enable image cleaner"><Checkbox checked={f.imageCleaner} onChange={chk("imageCleaner")} aria-label="Enable image cleaner" /></FormRow>
      </FormSection>
      <FormSection title="Workload identity">
        <FormRow label="Enable OIDC issuer"><Checkbox checked={f.oidcIssuer} onChange={chk("oidcIssuer")} aria-label="Enable OIDC issuer" /></FormRow>
        <FormRow label="Enable workload identity"><Checkbox checked={f.workloadIdentity} onChange={chk("workloadIdentity")} aria-label="Enable workload identity" /></FormRow>
      </FormSection>
    </>
  );

  const advanced = (
    <FormSection title="Infrastructure resource group">
      <FormRow label="Infrastructure resource group" htmlFor="aks-infrarg">
        <Input id="aks-infrarg" value={f.infraResourceGroup} placeholder={`MC_${rg || "rg"}_${f.name || "cluster"}_${f.location}`} onChange={set("infraResourceGroup")} aria-label="Infrastructure resource group" />
      </FormRow>
    </FormSection>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Kubernetes service" />
    </>
  );

  const body = () => ({ ...api.toArmBody(f), properties: { ...api.toArmBody(f).properties, dnsPrefix } });
  const review = () => {
    const b = body(), p = b.properties;
    const yes = (v) => (v ? "Enabled" : "Disabled");
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Kubernetes cluster name", f.name || "--"],
          ["Region", locationLabel(f.location)], ["AKS pricing tier", f.pricingTier], ["Kubernetes version", p.kubernetesVersion || "default"]])}
        <h3>Node pools</h3>
        {dl([["Node pools", f.nodePools.map((n) => `${n.name} (${n.count}× ${n.vmSize})`).join(", ")]])}
        <h3>Networking</h3>
        {dl([["Network configuration", f.networkConfig], ["DNS name prefix", dnsPrefix]])}
        <h3>Integrations</h3>
        {dl([["Azure Policy", yes(f.azurePolicy)], ["Istio", yes(f.istio)]])}
        <h3>Monitoring</h3>
        {dl([["Container Insights", yes(f.containerInsights)], ["Managed Prometheus", yes(f.prometheus)]])}
        <h3>Security</h3>
        {dl([["Microsoft Defender", yes(f.defender)], ["Workload identity", yes(f.workloadIdentity)]])}
        <h3>Advanced</h3>
        {dl([["Infrastructure resource group", p.nodeResourceGroup || "(default)"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      const b = body();
      await api.createCluster(rg, f.name, b);
      for (const pool of f.nodePools) {
        await api.putNodePool(rg, f.name, pool.name, {
          properties: { mode: pool.mode, vmSize: pool.vmSize, osSKU: pool.osSku, count: pool.count, maxPods: pool.maxPods,
            availabilityZones: pool.zones ? pool.zones.split(",").map((z) => z.trim()).filter(Boolean) : undefined, type: "VirtualMachineScaleSets" },
        });
      }
      notify.success(`Deployment of kubernetes service '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("aks", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Kubernetes cluster" closeHref="#/aks" glyph={<Glyph id="aks" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "nodepools", label: "Node pools", content: nodePools },
        { id: "networking", label: "Networking", content: networking },
        { id: "integrations", label: "Integrations", content: integrations },
        { id: "monitoring", label: "Monitoring", content: monitoring },
        { id: "security", label: "Security", content: security },
        { id: "advanced", label: "Advanced", content: advanced },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
