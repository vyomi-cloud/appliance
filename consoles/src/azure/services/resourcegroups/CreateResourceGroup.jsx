/* Create a resource group: Basics, Tags, Review + create → one native ARM PUT. */
import { useState } from "react";
import { Input, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { LOCATIONS, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./ResourceGroupBlade.jsx";

const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateResourceGroup() {
  const notify = useNotify();
  const sub = useSubscription();
  const existing = useAsync(() => api.listGroups(), [sub.id]);
  const [f, setF] = useState({ name: "", location: "eastus", tags: [{ name: "", value: "" }] });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));

  const basicsErrors = () => {
    const e = [];
    if (!RG_RE.test(f.name)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters, and cannot end with a period.");
    else if ((existing.data || []).some((g) => g.name.toLowerCase() === f.name.toLowerCase())) e.push(`Resource group "${f.name}" already exists.`);
    return e;
  };
  const nameError = f.name && basicsErrors()[0];

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription to manage deployed resources and costs. Use resource groups like folders to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="rg-sub">
          <Select id="rg-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group name" required htmlFor="rg-name" info="1-90 chars; alphanumeric, underscore, parentheses, hyphen, period">
          <Input id="rg-name" value={f.name} onChange={set("name")} aria-label="Resource group name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
      </FormSection>
      <FormSection title="Resource details">
        <FormRow label="Region" required htmlFor="rg-region">
          <Select id="rg-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>({id.includes("us") ? "US" : id.includes("europe") || id === "uksouth" ? "Europe" : "Asia Pacific"}) {l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Resource group" />
    </>
  );

  const body = () => ({ location: f.location, tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])) });
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource group name", f.name || "--"], ["Region", locationLabel(f.location)]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createGroup(f.name, body());
      notify.success(`Successfully created resource group '${f.name}'.`, "Deployment succeeded");
      navigate("resourcegroups", f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create a resource group" closeHref="#/resourcegroups" glyph={<Glyph id="resourcegroups" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
