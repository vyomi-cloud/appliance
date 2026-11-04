/* Create a Log Analytics workspace: Basics, Networking, Tags, Review + create → one native
 * ARM PUT (core/azure_operationalinsights_core.py). */
import { useState } from "react";
import { Input, Link, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./WorkspaceBlade.jsx";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9-]{2,61}[A-Za-z0-9]$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const TIERS = ["Free", "PerGB2018", "Standard", "Premium", "Standalone", "PerNode", "CapacityReservation"];
const CAPACITY_LEVELS = [100, 200, 300, 400, 500, 1000, 2000, 5000, 10000, 25000, 50000];

export default function CreateWorkspace() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listWorkspaces(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: `law-${Math.random().toString(36).slice(2, 8)}`, location: "eastus",
    pricingTier: "PerGB2018", capacityLevel: "100", retentionInDays: "30",
    publicIngestion: "Enabled", publicQuery: "Enabled", tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Name must be 4-63 characters of letters, digits and hyphens, and start and end with a letter or digit.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase() && v.resourceGroup.toLowerCase() === rg.toLowerCase())) e.push(`A workspace named "${f.name}" already exists in "${rg}".`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Name must") || m.startsWith("A workspace"));

  const basics = (
    <>
      <FormSection title="Project Details" description="Select the subscription to manage deployed resources and costs. Use resource groups like folders to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="law-sub">
          <Select id="law-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="law-rg">
          {newRg === null ? (
            <>
              <Select id="law-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="law-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Name" required htmlFor="law-name" info="4-63 chars, letters/digits/hyphens">
          <Input id="law-name" value={f.name} onChange={set("name")} aria-label="Name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="law-location">
          <Select id="law-location" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Pricing tier" required htmlFor="law-tier">
          <Select id="law-tier" value={f.pricingTier} onChange={set("pricingTier")} aria-label="Pricing tier">
            {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
          </Select>
        </FormRow>
        {f.pricingTier === "CapacityReservation" && (
          <FormRow label="Capacity reservation level (GB)" htmlFor="law-cap">
            <Select id="law-cap" value={f.capacityLevel} onChange={set("capacityLevel")} aria-label="Capacity reservation level (GB)">
              {CAPACITY_LEVELS.map((c) => <option key={c} value={String(c)}>{c}</option>)}
            </Select>
          </FormRow>
        )}
        <FormRow label="Retention (days)" htmlFor="law-retention" info={f.pricingTier === "Free" ? "Fixed at 7 days on Free" : "4-730 days"}>
          <Input id="law-retention" type="number" min={f.pricingTier === "Free" ? 7 : 4} max={f.pricingTier === "Free" ? 7 : 730}
            disabled={f.pricingTier === "Free"} value={f.pricingTier === "Free" ? "7" : f.retentionInDays} onChange={set("retentionInDays")} aria-label="Retention (days)" />
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <FormSection title="Network access">
      <FormRow label="Public access to data ingestion">
        <RadioGroup value={f.publicIngestion} onChange={set("publicIngestion")} aria-label="Public access to data ingestion">
          <Radio value="Enabled" label="Enabled" /><Radio value="Disabled" label="Disabled" />
        </RadioGroup>
      </FormRow>
      <FormRow label="Public access to query">
        <RadioGroup value={f.publicQuery} onChange={set("publicQuery")} aria-label="Public access to query">
          <Radio value="Enabled" label="Enabled" /><Radio value="Disabled" label="Disabled" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const tags = (
    <FormSection title="Tags">
      <p style={{ fontSize: 13 }}>Name/value pairs to categorize resources and view consolidated billing.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Log Analytics workspace" />
    </FormSection>
  );

  const body = () => api.workspaceArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Name", f.name || "--"],
          ["Region", locationLabel(f.location)], ["Pricing tier", f.pricingTier], ["Retention (days)", b.properties.retentionInDays]])}
        <h3>Networking</h3>
        {dl([["Public access to data ingestion", f.publicIngestion], ["Public access to query", f.publicQuery]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createWorkspace(rg, f.name, body());
      notify.success(`Deployment of workspace '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("loganalytics", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Log Analytics workspace" closeHref="#/loganalytics" glyph={<Glyph id="loganalytics" />}
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
