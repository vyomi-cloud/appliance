/* Create a configuration store: Basics, Networking, Tags, Review + create → one native
 * ARM PUT. */
import { useState } from "react";
import { Checkbox, Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./ConfigStoreBlade.jsx";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9-]{3,48}[A-Za-z0-9]$/;
const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateStore() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listStores(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", pricingTier: "Free",
    publicAccess: true,
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Resource name must be 5-50 characters, and contain only letters, numbers and hyphens; it cannot start or end with a hyphen.");
    else if ((existing.data || []).some((s) => s.name.toLowerCase() === f.name.toLowerCase())) e.push(`A configuration store named "${f.name}" already exists.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Resource name") || m.startsWith("A configuration store"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription in which to create the new configuration store. Use resource groups to organize and manage your resources together with other resources.">
        <FormRow label="Subscription" required htmlFor="ac-sub">
          <Select id="ac-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="ac-rg">
          {newRg === null ? (
            <>
              <Select id="ac-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="ac-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Resource name" required htmlFor="ac-name" info="5-50 chars; letters, numbers, hyphens; globally unique">
          <Input id="ac-name" value={f.name} onChange={set("name")} aria-label="Resource name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="ac-region">
          <Select id="ac-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>({id.includes("us") ? "US" : id.includes("europe") || id === "uksouth" ? "Europe" : "Asia Pacific"}) {l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Pricing tier" htmlFor="ac-tier">
          <Select id="ac-tier" value={f.pricingTier} onChange={set("pricingTier")} aria-label="Pricing tier">
            <option value="Free">Free</option><option value="Standard">Standard</option>
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <>
      <FormSection title="Network connectivity">
        <FormRow label="Enable public access">
          <Checkbox checked={f.publicAccess} onChange={(_, d) => setF((x) => ({ ...x, publicAccess: !!d.checked }))} aria-label="Enable public access" />
        </FormRow>
      </FormSection>
      <NotSimulatedContainer title="Private endpoint" feature="Private endpoint connections for a configuration store" />
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Configuration store" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Resource name", f.name || "--"], ["Region", locationLabel(f.location)], ["Pricing tier", f.pricingTier]])}
        <h3>Networking</h3>
        {dl([["Enable public access", f.publicAccess ? "Yes" : "No"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createStore(rg, f.name, body());
      notify.success(`Deployment of configuration store '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("appconfiguration", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create a configuration store" closeHref="#/appconfiguration" glyph={<Glyph id="appconfiguration" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "networking", label: "Networking", content: networking },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
