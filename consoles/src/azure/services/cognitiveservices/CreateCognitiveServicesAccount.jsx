/* Create an Azure AI services resource: Basics, Network, Identity, Tags, Review + create →
 * one native ARM PUT (Microsoft.CognitiveServices/accounts). */
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
import { TagRows } from "./CognitiveServicesAccountBlade.jsx";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const SUBDOMAIN_RE = /^[A-Za-z0-9][A-Za-z0-9-]{0,62}[A-Za-z0-9]$/;

export default function CreateCognitiveServicesAccount() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listAccounts(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, type: "Azure OpenAI", name: "", location: "eastus", pricingTier: "S0",
    networkAccess: "all", customSubDomainName: "", identity: false,
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;
  const kind = api.TYPE_TO_KIND[f.type] || "OpenAI";
  const tiers = api.KINDS[kind] || ["S0"];

  const setType = (_, d) => {
    const k = api.TYPE_TO_KIND[d.value] || "OpenAI";
    setF((x) => ({ ...x, type: d.value, pricingTier: (api.KINDS[k] || ["S0"])[0] }));
  };

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Name must be 2-64 characters of letters, digits, hyphens and underscores, starting with a letter or digit.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`An account named "${f.name}" already exists.`);
    return e;
  };
  const networkErrors = () => (f.customSubDomainName && !SUBDOMAIN_RE.test(f.customSubDomainName) ? ["Custom subdomain name must be 2-64 letters, digits and hyphens; it must not start or end with a hyphen."] : []);
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Name") || m.startsWith("An account"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription in which to create the new resource. Use resource groups to organize and manage this resource together with other resources.">
        <FormRow label="Subscription" required htmlFor="cs-sub">
          <Select id="cs-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="cs-rg">
          {newRg === null ? (
            <>
              <Select id="cs-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="cs-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Type" required htmlFor="cs-type">
          <Select id="cs-type" value={f.type} onChange={setType} aria-label="Type">
            {Object.keys(api.TYPE_TO_KIND).map((t) => <option key={t} value={t}>{t}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Name" required htmlFor="cs-name" info="2-64 chars; letters, digits, hyphens and underscores; globally unique">
          <Input id="cs-name" value={f.name} onChange={set("name")} aria-label="Name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="cs-region">
          <Select id="cs-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>({id.includes("us") ? "US" : id.includes("europe") || id === "uksouth" ? "Europe" : "Asia Pacific"}) {l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Pricing tier" required htmlFor="cs-tier">
          <Select id="cs-tier" value={f.pricingTier} onChange={set("pricingTier")} aria-label="Pricing tier">
            {tiers.map((t) => <option key={t} value={t}>{t}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const network = (
    <FormSection title="Network connectivity">
      <FormRow label="Allow access from">
        <RadioGroup value={f.networkAccess} onChange={set("networkAccess")} aria-label="Allow access from">
          <Radio value="all" label="All networks" />
          <Radio value="selected" label="Selected networks" />
          <Radio value="disabled" label="Disabled" />
        </RadioGroup>
      </FormRow>
      <FormRow label="Custom subdomain name" htmlFor="cs-subdomain" info="Required to use token-based (Microsoft Entra ID) authentication and some endpoints (e.g. Azure OpenAI)">
        <Input id="cs-subdomain" value={f.customSubDomainName} onChange={set("customSubDomainName")} aria-label="Custom subdomain name" style={{ width: "100%" }} />
      </FormRow>
    </FormSection>
  );

  const identity = (
    <FormSection title="System assigned managed identity">
      <FormRow label="Status">
        <Checkbox checked={f.identity} onChange={chk("identity")} aria-label="Status" />
      </FormRow>
    </FormSection>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Azure AI services" />
    </>
  );

  const body = () => api.toArmBody({ ...f, kind });
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Type", f.type], ["Name", f.name || "--"], ["Region", locationLabel(f.location)], ["Pricing tier", f.pricingTier]])}
        <h3>Network</h3>
        {dl([["Allow access from", { all: "All networks", selected: "Selected networks", disabled: "Disabled" }[f.networkAccess]], ["Custom subdomain name", f.customSubDomainName || "(none)"]])}
        <h3>Identity</h3>
        {dl([["System assigned managed identity", f.identity ? "On" : "Off"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createAccount(rg, f.name, body());
      notify.success(`Deployment of '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("cognitiveservices", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create an Azure AI services resource" closeHref="#/cognitiveservices" glyph={<Glyph id="cognitiveservices" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "network", label: "Network", content: network, validate: networkErrors },
        { id: "identity", label: "Identity", content: identity },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
