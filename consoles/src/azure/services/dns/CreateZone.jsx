/* Create DNS zone: Basics, Tags, Review + create → one native ARM PUT.
 * Vyomi models public and private zones as the SAME resource (zoneType), so the "zone type"
 * choice below replaces the real portal's separate "Create Private DNS zone" experience —
 * see azure.dns.zone.private. */
import { useState } from "react";
import { Input, Link, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, listResourceGroups } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, InfoBar } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./TagRows.jsx";
import * as api from "./api.js";

const NAME_RE = /^(\*\.)?[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?(\.[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?)+$/i;
const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateZone() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listZones(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({ resourceGroup: DEFAULT_RG, name: "", zoneType: "Public", tags: [{ name: "", value: "" }] });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!f.name) e.push("The name field is required.");
    else if (!NAME_RE.test(f.name) || f.name.length > 253) e.push("Enter a valid DNS zone name.");
    else if ((existing.data || []).some((z) => z.name.toLowerCase() === f.name.toLowerCase())) e.push(`A DNS zone named '${f.name}' already exists in this subscription.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Enter") || m.startsWith("A DNS zone"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription in which to create the new DNS zone. Choose a new or existing resource group to organize and manage your DNS zone together with other resources.">
        <FormRow label="Subscription" required htmlFor="dns-sub">
          <Select id="dns-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="dns-rg">
          {newRg === null ? (
            <>
              <Select id="dns-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="dns-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance details">
        <FormRow label="Name" required htmlFor="dns-name">
          <Input id="dns-name" value={f.name} onChange={set("name")} placeholder="www.contoso.com" aria-label="Name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Resource group location" htmlFor="dns-loc">
          <Input id="dns-loc" readOnly value="global" aria-label="Resource group location" />
        </FormRow>
        <FormRow label="Zone type" required>
          <RadioGroup value={f.zoneType} onChange={set("zoneType")} aria-label="Zone type">
            <Radio value="Public" label="Public: resolvable on the internet, with Vyomi-issued name servers" />
            <Radio value="Private" label="Private: resolvable only from virtual networks you link to this zone" />
          </RadioGroup>
        </FormRow>
        <InfoBar>Vyomi models public and private zones as the same resource type (zoneType), see azure.dns.zone.private.</InfoBar>
      </FormSection>
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="DNS zone" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Name", f.name || "--"], ["Resource group location", "global"], ["Zone type", f.zoneType]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createZone(rg, f.name, body());
      notify.success(`Deployment of DNS zone '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("dns", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create DNS zone" closeHref="#/dns" glyph={<Glyph id="dns" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
