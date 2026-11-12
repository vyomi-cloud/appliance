/* Create a network security group: Basics, Tags, Review + create → one native ARM PUT. */
import { useState } from "react";
import { Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "./NsgBlade.jsx";

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,78}[a-zA-Z0-9_]$/;
const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateNetworkSecurityGroup() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listNsgs(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({ resourceGroup: DEFAULT_RG, name: "nsg-cloudlearn", location: "eastus", tags: [{ name: "", value: "" }] });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Name must be 1-80 characters, starting with a letter or number, and may contain letters, numbers, underscores, periods and hyphens.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase() && v.resourceGroup.toLowerCase() === rg.toLowerCase()))
      e.push(`A network security group named "${f.name}" already exists in resource group "${rg}".`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Name") || m.startsWith("A network"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription in which to create the new network security group. Use resource groups to organize and manage your network security group together with other resources.">
        <FormRow label="Subscription" required htmlFor="nsg-sub">
          <Select id="nsg-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="nsg-rg">
          {newRg === null ? (
            <>
              <Select id="nsg-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="nsg-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Name" required htmlFor="nsg-name">
          <Input id="nsg-name" value={f.name} onChange={set("name")} aria-label="Name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="nsg-region">
          <Select id="nsg-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Network security group" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Name", f.name || "--"], ["Region", locationLabel(f.location)]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createNsg(rg, f.name, body());
      notify.success(`Deployment of network security group '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("nsgs", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create network security group" closeHref="#/nsgs" glyph={<Glyph id="nsgs" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
