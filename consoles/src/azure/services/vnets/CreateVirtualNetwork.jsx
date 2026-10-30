/* Create a virtual network: Basics, Security, Address space, Tags, Review + create → one
 * native ARM PUT for the vnet, plus one native ARM PUT per initial subnet (real ARM has no
 * single call that creates both — the portal's wizard issues the same two calls). */
import { useState } from "react";
import { Button, Checkbox, Input, Link, Select } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./VnetBlade.jsx";

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,78}[a-zA-Z0-9_]$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const CIDR_RE = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\/\d{1,2}$/;

export default function CreateVirtualNetwork() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listVnets(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "vnet-cloudlearn", location: "eastus",
    encryption: false,
    addressPrefixes: ["10.0.0.0/16"],
    subnets: [{ name: "default", prefix: "10.0.0.0/24" }],
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Name must be 1-80 characters, starting with a letter or number, and may contain letters, numbers, underscores, periods and hyphens.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase() && v.resourceGroup.toLowerCase() === rg.toLowerCase()))
      e.push(`A virtual network named "${f.name}" already exists in resource group "${rg}".`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Name") || m.startsWith("A virtual"));

  const addressSpaceErrors = () => {
    const e = [];
    if (!f.addressPrefixes.length || f.addressPrefixes.some((p) => !CIDR_RE.test(p))) e.push("Address space must be valid IPv4 CIDR ranges (e.g. 10.0.0.0/16).");
    if (!f.subnets.length) e.push("At least one subnet is required.");
    else if (f.subnets.some((s) => !s.name || !CIDR_RE.test(s.prefix))) e.push("Every subnet needs a name and a valid IPv4 CIDR range.");
    return e;
  };

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription in which to create the new virtual network. Use resource groups to organize and manage your virtual network together with other resources.">
        <FormRow label="Subscription" required htmlFor="vnet-sub">
          <Select id="vnet-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="vnet-rg">
          {newRg === null ? (
            <>
              <Select id="vnet-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="vnet-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Virtual network name" required htmlFor="vnet-name">
          <Input id="vnet-name" value={f.name} onChange={set("name")} aria-label="Virtual network name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="vnet-region">
          <Select id="vnet-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const security = (
    <>
      <FormSection title="Virtual network encryption">
        <FormRow label="Virtual network encryption">
          <Checkbox checked={f.encryption} onChange={(_, d) => setF((x) => ({ ...x, encryption: !!d.checked }))} aria-label="Virtual network encryption" />
        </FormRow>
      </FormSection>
      <NotSimulatedContainer title="Azure Bastion" feature="Enable Azure Bastion" note="Deploying a Bastion host (Microsoft.Network/bastionHosts) is not modelled." />
      <NotSimulatedContainer title="Azure Firewall" feature="Enable Azure Firewall" note="Deploying an Azure Firewall (Microsoft.Network/azureFirewalls) is not modelled." />
      <NotSimulatedContainer title="Azure DDoS Network Protection" feature="Enable Azure DDoS Network Protection" note="Attaching a DDoS protection plan (Microsoft.Network/ddosProtectionPlans) is not modelled." />
    </>
  );

  const addPrefix = () => setF((x) => ({ ...x, addressPrefixes: [...x.addressPrefixes, ""] }));
  const setPrefix = (i, v) => setF((x) => ({ ...x, addressPrefixes: x.addressPrefixes.map((p, j) => (j === i ? v : p)) }));
  const delPrefix = (i) => setF((x) => ({ ...x, addressPrefixes: x.addressPrefixes.filter((_, j) => j !== i) }));
  const addSubnetRow = () => setF((x) => ({ ...x, subnets: [...x.subnets, { name: `subnet${x.subnets.length}`, prefix: "" }] }));
  const setSubnetRow = (i, k, v) => setF((x) => ({ ...x, subnets: x.subnets.map((s, j) => (j === i ? { ...s, [k]: v } : s)) }));
  const delSubnetRow = (i) => setF((x) => ({ ...x, subnets: x.subnets.filter((_, j) => j !== i) }));

  const addressSpace = (
    <>
      <FormSection title="Virtual network address space">
        <NotSimulatedContainer title="Allocate using IP address pools." feature="Allocate using IP address pools." note="Azure IPAM pool allocation is not modelled; address prefixes are entered directly." />
        <p style={{ fontSize: 13 }}>Starting address / Size; e.g. 10.0.0.0 - 10.0.255.255, /16 (65,536 addresses)</p>
        {f.addressPrefixes.map((p, i) => (
          <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
            <Input value={p} placeholder="10.0.0.0/16" onChange={(_, d) => setPrefix(i, d.value)} aria-label={`Address space ${i + 1}`} />
            <Button appearance="subtle" icon={<Delete20Regular />} aria-label="Delete address space" onClick={() => delPrefix(i)} disabled={f.addressPrefixes.length === 1} />
          </div>
        ))}
        <Button appearance="subtle" icon={<Add20Regular />} onClick={addPrefix}>Add IPv4 address space</Button>
        <h4 style={{ marginTop: 16 }}>Subnets</h4>
        <table className="vy-grid"><thead><tr><th>Subnets</th><th>IP address range</th><th>NAT gateway</th><th /></tr></thead>
          <tbody>
            {f.subnets.map((s, i) => (
              <tr key={i}>
                <td><Input size="small" value={s.name} onChange={(_, d) => setSubnetRow(i, "name", d.value)} aria-label={`Subnet name ${i + 1}`} /></td>
                <td><Input size="small" value={s.prefix} placeholder="10.0.0.0/24" onChange={(_, d) => setSubnetRow(i, "prefix", d.value)} aria-label={`Subnet address range ${i + 1}`} /></td>
                <td>None</td>
                <td><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete subnet" onClick={() => delSubnetRow(i)} disabled={f.subnets.length === 1} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Button appearance="subtle" icon={<Add20Regular />} onClick={addSubnetRow}>Add a subnet</Button>
      </FormSection>
      <NotSimulatedContainer title="Advertised address prefixes" feature="Advertised address prefixes" note="Custom BGP route advertisement is not modelled; no advertised gateway prefixes." />
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Virtual network" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Virtual network name", f.name || "--"], ["Region", locationLabel(f.location)]])}
        <h3>Security</h3>
        {dl([["Virtual network encryption", f.encryption ? "Enabled" : "Disabled"]])}
        <h3>Address space</h3>
        {dl([["Address space", f.addressPrefixes.join(", ")], ["Subnets", f.subnets.map((s) => `${s.name} (${s.prefix})`).join(", ")]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createVnet(rg, f.name, body());
      for (const s of f.subnets) await api.putSubnet(rg, f.name, s.name, { properties: { addressPrefix: s.prefix } });
      notify.success(`Deployment of virtual network '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("vnets", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create virtual network" closeHref="#/vnets" glyph={<Glyph id="vnets" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "security", label: "Security", content: security },
        { id: "addressspace", label: "Address space", content: addressSpace, validate: addressSpaceErrors },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
