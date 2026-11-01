/* Create a container registry: Basics, Networking, Encryption, Tags, Review + create →
 * one native ARM PUT. */
import { useState } from "react";
import { Checkbox, Input, Link, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "../keyvaults/KeyVaultBlade.jsx";

const NAME_RE = /^[a-zA-Z0-9]{5,50}$/;
const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateRegistry() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listRegistries(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", availabilityZones: false,
    pricingPlan: "Standard", domainNameLabelScope: "Unsecure", roleAssignmentMode: "RBAC Registry Permissions",
    connectivity: "Public access", customerManagedKey: false,
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Registry name must be between 5 and 50 characters, and contain only alphanumeric characters.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`A container registry named "${f.name}" already exists.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Registry name") || m.startsWith("A container registry"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription to manage deployed resources and costs. Use resource groups like folders to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="acr-sub">
          <Select id="acr-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="acr-rg">
          {newRg === null ? (
            <>
              <Select id="acr-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="acr-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Registry name" required htmlFor="acr-name" info=".azurecr.io; 5-50 alphanumeric characters">
          <Input id="acr-name" value={f.name} onChange={set("name")} aria-label="Registry name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Location" required htmlFor="acr-location">
          <Select id="acr-location" value={f.location} onChange={set("location")} aria-label="Location">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Use availability zones">
          <Checkbox checked={f.availabilityZones} disabled={f.pricingPlan !== "Premium"} onChange={chk("availabilityZones")} aria-label="Use availability zones" />
          {f.pricingPlan !== "Premium" && <div style={{ fontSize: 12, marginTop: 4 }} className="vy-muted">Requires Premium</div>}
        </FormRow>
        <FormRow label="Pricing plan" required htmlFor="acr-plan">
          <Select id="acr-plan" value={f.pricingPlan} onChange={set("pricingPlan")} aria-label="Pricing plan">
            <option value="Basic">Basic</option><option value="Standard">Standard</option><option value="Premium">Premium</option>
          </Select>
        </FormRow>
        <FormRow label="Domain name label scope" htmlFor="acr-dnls">
          <Select id="acr-dnls" value={f.domainNameLabelScope} onChange={set("domainNameLabelScope")} aria-label="Domain name label scope">
            <option value="Unsecure">Unsecure</option><option value="Tenant Reuse">Tenant Reuse</option>
            <option value="Subscription Reuse">Subscription Reuse</option><option value="Resource Group Reuse">Resource Group Reuse</option>
            <option value="No Reuse">No Reuse</option>
          </Select>
        </FormRow>
        <FormRow label="Role assignment permissions mode" htmlFor="acr-ram">
          <Select id="acr-ram" value={f.roleAssignmentMode} onChange={set("roleAssignmentMode")} aria-label="Role assignment permissions mode">
            <option value="RBAC Registry Permissions">RBAC Registry Permissions</option>
            <option value="RBAC Registry + ABAC Repository Permissions">RBAC Registry + ABAC Repository Permissions</option>
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <FormSection title="Network connectivity">
      <FormRow label="Connectivity">
        <RadioGroup value={f.connectivity} onChange={set("connectivity")} aria-label="Connectivity">
          <Radio value="Public access" label="Public access" />
          <Radio value="Private access" label="Private access" disabled={f.pricingPlan !== "Premium"} />
        </RadioGroup>
        {f.pricingPlan !== "Premium" && <div style={{ fontSize: 12, marginTop: 4 }} className="vy-muted">Private access requires Premium</div>}
      </FormRow>
    </FormSection>
  );

  const encryption = (
    <FormSection title="Encryption">
      <FormRow label="Customer-managed key">
        <RadioGroup value={f.customerManagedKey ? "Enabled" : "Disabled"} onChange={(_, d) => setF((x) => ({ ...x, customerManagedKey: d.value === "Enabled" }))} aria-label="Customer-managed key">
          <Radio value="Enabled" label="Enabled" disabled={f.pricingPlan !== "Premium"} />
          <Radio value="Disabled" label="Disabled" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Name/value pairs to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Container registry" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body(), p = b.properties;
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource group", rg || "--"], ["Registry name", f.name || "--"], ["Location", locationLabel(f.location)],
          ["Use availability zones", f.availabilityZones ? "Yes" : "No"], ["Pricing plan", f.pricingPlan],
          ["Domain name label scope", f.domainNameLabelScope], ["Role assignment permissions mode", f.roleAssignmentMode]])}
        <h3>Networking</h3>
        {dl([["Connectivity", f.connectivity]])}
        <h3>Encryption</h3>
        {dl([["Customer-managed key", p.encryption.status === "enabled" ? "Enabled" : "Disabled"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createRegistry(rg, f.name, body());
      notify.success(`Deployment of container registry '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("acr", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create container registry" closeHref="#/acr" glyph={<Glyph id="acr" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "networking", label: "Networking", content: networking },
        { id: "encryption", label: "Encryption", content: encryption },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
