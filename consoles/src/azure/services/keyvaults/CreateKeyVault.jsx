/* Create a key vault: Basics, Access configuration, Networking, Tags, Review + create →
 * one native ARM PUT. */
import { useState } from "react";
import { Checkbox, Input, Link, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./KeyVaultBlade.jsx";

const NAME_RE = /^[a-zA-Z0-9-]{3,24}$/;
const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateKeyVault() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listVaults(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", pricingTier: "Standard",
    retentionDays: 90, purgeProtection: false,
    permissionModel: "rbac", vmDeployment: false, armDeployment: false, diskEncryption: false,
    networkAccess: "all",
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Vault name must be between 3 and 24 characters, and contain only alphanumeric characters and hyphens.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`A key vault named "${f.name}" already exists.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Vault name") || m.startsWith("A key vault"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription in which to create the new key vault. Use resource groups to organize and manage your key vault together with other resources.">
        <FormRow label="Subscription" required htmlFor="kv-sub">
          <Select id="kv-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="kv-rg">
          {newRg === null ? (
            <>
              <Select id="kv-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="kv-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Key vault name" required htmlFor="kv-name" info="3-24 chars; letters, numbers, hyphens; globally unique">
          <Input id="kv-name" value={f.name} onChange={set("name")} aria-label="Key vault name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="kv-region">
          <Select id="kv-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>({id.includes("us") ? "US" : id.includes("europe") || id === "uksouth" ? "Europe" : "Asia Pacific"}) {l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Pricing tier" htmlFor="kv-tier">
          <Select id="kv-tier" value={f.pricingTier} onChange={set("pricingTier")} aria-label="Pricing tier">
            <option value="Standard">Standard</option><option value="Premium">Premium</option>
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Recovery options">
        <FormRow label="Soft-delete"><Input readOnly value="Enabled" aria-label="Soft-delete" /></FormRow>
        <FormRow label="Days to retain deleted vaults" htmlFor="kv-retention">
          <Input id="kv-retention" type="number" min={7} max={90} value={String(f.retentionDays)} onChange={(_, d) => setF((x) => ({ ...x, retentionDays: Number(d.value) || 90 }))} aria-label="Days to retain deleted vaults" />
        </FormRow>
        <FormRow label="Purge protection">
          <RadioGroup value={f.purgeProtection ? "on" : "off"} onChange={(_, d) => setF((x) => ({ ...x, purgeProtection: d.value === "on" }))} aria-label="Purge protection">
            <Radio value="off" label="Disable purge protection (allow key vault and objects to be purged during retention period)" />
            <Radio value="on" label="Enable purge protection (enforce a mandatory retention period for deleted vaults and vault objects)" />
          </RadioGroup>
        </FormRow>
      </FormSection>
    </>
  );

  const accessConfig = (
    <>
      <FormSection title="Configure data plane access for this key vault">
        <FormRow label="Permission model">
          <RadioGroup value={f.permissionModel} onChange={set("permissionModel")} aria-label="Permission model">
            <Radio value="rbac" label="Azure role-based access control (recommended)" />
            <Radio value="policy" label="Vault access policy" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      <FormSection title="Resource access">
        <FormRow label="Azure Virtual Machines for deployment"><Checkbox checked={f.vmDeployment} onChange={chk("vmDeployment")} aria-label="Azure Virtual Machines for deployment" /></FormRow>
        <FormRow label="Azure Resource Manager for template deployment"><Checkbox checked={f.armDeployment} onChange={chk("armDeployment")} aria-label="Azure Resource Manager for template deployment" /></FormRow>
        <FormRow label="Azure Disk Encryption for volume encryption"><Checkbox checked={f.diskEncryption} onChange={chk("diskEncryption")} aria-label="Azure Disk Encryption for volume encryption" /></FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <>
      <FormSection title="Network connectivity">
        <FormRow label="Enable public access">
          <Checkbox checked={f.networkAccess !== "disabled"} onChange={(_, d) => setF((x) => ({ ...x, networkAccess: d.checked ? "all" : "disabled" }))} aria-label="Enable public access" />
        </FormRow>
      </FormSection>
      {f.networkAccess !== "disabled" && (
        <FormSection title="Public Access">
          <FormRow label="Allow access from">
            <RadioGroup value={f.networkAccess} onChange={set("networkAccess")} aria-label="Allow access from">
              <Radio value="all" label="All networks" />
              <Radio value="selected" label="Selected networks" />
            </RadioGroup>
          </FormRow>
        </FormSection>
      )}
      <NotSimulatedContainer title="Private endpoint" feature="Private endpoint connections for a key vault" />
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Key vault" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body(), p = b.properties;
    const yes = (v) => (v ? "Enabled" : "Disabled");
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Key vault name", f.name || "--"], ["Region", locationLabel(f.location)],
          ["Pricing tier", f.pricingTier], ["Days to retain deleted vaults", String(f.retentionDays)], ["Purge protection", yes(p.enablePurgeProtection)]])}
        <h3>Access configuration</h3>
        {dl([["Permission model", f.permissionModel === "rbac" ? "Azure role-based access control" : "Vault access policy"],
          ["Azure Virtual Machines for deployment", yes(p.enabledForDeployment)], ["Azure Resource Manager for template deployment", yes(p.enabledForTemplateDeployment)],
          ["Azure Disk Encryption for volume encryption", yes(p.enabledForDiskEncryption)]])}
        <h3>Networking</h3>
        {dl([["Allow access from", { all: "All networks", selected: "Selected networks", disabled: "Disabled" }[f.networkAccess]]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createVault(rg, f.name, body());
      notify.success(`Deployment of key vault '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("keyvaults", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create a key vault" closeHref="#/keyvaults" glyph={<Glyph id="keyvaults" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "access", label: "Access configuration", content: accessConfig },
        { id: "networking", label: "Networking", content: networking },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
