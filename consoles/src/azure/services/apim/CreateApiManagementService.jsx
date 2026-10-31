/* Create an API Management service: Basics, Monitor + secure, Virtual network, Managed
 * identity, Protocol settings, Tags, Review + install → one native ARM PUT. */
import { useState } from "react";
import { Checkbox, Input, Link, Radio, RadioGroup, Select, Switch } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./ApimBlade.jsx";
import * as api from "./api.js";

const NAME_RE = /^[a-zA-Z](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const PRICING_TIERS = ["Basic v2", "Standard v2", "Premium v2", "Developer (no SLA)", "Basic", "Standard", "Premium", "Consumption"];

export default function CreateApiManagementService() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listServices(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", orgName: "", adminEmail: "",
    pricingTier: "Developer (no SLA)", units: 1,
    vnet: "None", systemAssignedIdentity: false,
    protocols: api.defaultProtocols(),
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name) || f.name.length < 1 || f.name.length > 50) e.push("Resource name must be 1-50 characters, start with a letter, and contain only letters, numbers and hyphens.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`An API Management service named "${f.name}" already exists.`);
    if (!f.orgName.trim()) e.push("Organization name is required.");
    if (!/^[^@]+@[^@]+\.[^@]+$/.test(f.adminEmail)) e.push("A valid administrator email is required.");
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Resource name") || m.startsWith("An API Management"));

  const basics = (
    <>
      <FormSection title="Project details">
        <FormRow label="Subscription" required htmlFor="apim-sub">
          <Select id="apim-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="apim-rg">
          {newRg === null ? (
            <>
              <Select id="apim-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="apim-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Region" required htmlFor="apim-region">
          <Select id="apim-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>({id.includes("us") ? "US" : id.includes("europe") || id === "uksouth" ? "Europe" : "Asia Pacific"}) {l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Resource name" required htmlFor="apim-name" info="Globally unique; forms {name}.azure-api.net">
          <Input id="apim-name" value={f.name} onChange={set("name")} aria-label="Resource name" contentAfter=".azure-api.net" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Organization name" required htmlFor="apim-org">
          <Input id="apim-org" value={f.orgName} onChange={set("orgName")} aria-label="Organization name" style={{ width: "100%" }} />
        </FormRow>
        <FormRow label="Administrator email" required htmlFor="apim-email">
          <Input id="apim-email" type="email" value={f.adminEmail} onChange={set("adminEmail")} aria-label="Administrator email" style={{ width: "100%" }} />
        </FormRow>
      </FormSection>
      <FormSection title="Pricing tier">
        <FormRow label="Pricing tier" required htmlFor="apim-tier">
          {/* Developer has no scale-out (always exactly 1 unit) and Consumption has no scale
              units at all — ENFORCED on the ARM PUT/PATCH (azure_arm_core._apim_tier_block,
              azure.apim.scaletier), so the Units control mirrors that here. */}
          <Select id="apim-tier" value={f.pricingTier} onChange={(e, d) => setF((x) => ({ ...x, pricingTier: d.value, units: d.value === "Developer (no SLA)" ? 1 : x.units }))} aria-label="Pricing tier">
            {PRICING_TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
          </Select>
        </FormRow>
        {f.pricingTier !== "Consumption" && f.pricingTier !== "Developer (no SLA)" && (
          <FormRow label="Units" htmlFor="apim-units">
            <Input id="apim-units" type="number" min={1} max={10} value={String(f.units)} onChange={(_, d) => setF((x) => ({ ...x, units: Number(d.value) || 1 }))} aria-label="Units" />
          </FormRow>
        )}
      </FormSection>
    </>
  );

  const monitor = (
    <NotSimulatedContainer title="Monitor + secure"
      feature="Wiring a new service to Log Analytics, Application Insights or Defender for APIs"
      note="These checkboxes provision separate monitoring/security resources in real Azure; Vyomi does not model that cross-resource wiring." />
  );

  const vnetSection = (
    <FormSection title="Network connectivity">
      <FormRow label="Connectivity type">
        <RadioGroup value={f.vnet} onChange={set("vnet")} aria-label="Connectivity type">
          <Radio value="None" label="None" />
          <Radio value="Virtual network" label="Virtual network" />
          <Radio value="Private endpoint" label="Private endpoint" />
        </RadioGroup>
      </FormRow>
      {f.vnet !== "None" && <NotSimulatedContainer feature={`Deploying into a ${f.vnet.toLowerCase()}`} />}
    </FormSection>
  );

  const identity = (
    <FormSection title="System assigned managed identity">
      <FormRow label="Status">
        <Checkbox checked={f.systemAssignedIdentity} onChange={(_, d) => setF((x) => ({ ...x, systemAssignedIdentity: !!d.checked }))} aria-label="Status" />
      </FormRow>
    </FormSection>
  );

  const protocolTable = (side) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: 360 }}>
      {api.PROTOCOL_KEYS.filter(([, , s]) => s === side).map(([key, label]) => (
        <div key={key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{label}</span>
          <Switch checked={f.protocols[key] === "True"} onChange={(_, d) => setF((x) => ({ ...x, protocols: { ...x.protocols, [key]: d.checked ? "True" : "False" } }))} aria-label={`${label} (${side} side)`} />
        </div>
      ))}
    </div>
  );

  const protocolSettings = (
    <>
      <FormSection title="Client side"><FormRow label="Client side protocols and ciphers">{protocolTable("client")}</FormRow></FormSection>
      <FormSection title="Backend side"><FormRow label="Backend side protocols and ciphers">{protocolTable("backend")}</FormRow></FormSection>
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Name/value pairs to categorize resources and view consolidated billing.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="API Management service" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Resource name", f.name || "--"], ["Region", locationLabel(f.location)],
          ["Organization name", f.orgName || "--"], ["Administrator email", f.adminEmail || "--"], ["Pricing tier", f.pricingTier], ["Units", String(f.units)]])}
        <h3>Managed identity</h3>
        {dl([["System assigned managed identity", f.systemAssignedIdentity ? "On" : "Off"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createService(rg, f.name, body());
      notify.success(`Deployment of API Management service '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("apim", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create API Management service" closeHref="#/apim" glyph={<Glyph id="apim" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "monitor", label: "Monitor + secure", content: monitor },
        { id: "vnet", label: "Virtual network", content: vnetSection },
        { id: "identity", label: "Managed identity", content: identity },
        { id: "protocol", label: "Protocol settings", content: protocolSettings },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
      reviewLabel="Review + install"
    />
  );
}
