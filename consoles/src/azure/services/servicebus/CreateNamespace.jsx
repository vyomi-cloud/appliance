/* Create a Service Bus namespace: Basics, Advanced, Networking, Tags, Review + create →
 * one native ARM PUT. */
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
import { TagRows } from "./NamespaceBlade.jsx";

const NAME_RE = /^[a-zA-Z][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]$/;
const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateNamespace() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listNamespaces(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", pricingTier: "Standard",
    messagingUnits: "1", partitions: "1", minTls: "1.2", localAuth: "Enabled",
    connectivity: "Public access", tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Namespace name must be between 6 and 50 characters, start with a letter, end with a letter or number, and contain only alphanumeric characters and hyphens.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`A namespace named "${f.name}" already exists.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Namespace name") || m.startsWith("A namespace"));

  const basics = (
    <>
      <FormSection title="Project Details" description="Select the subscription to manage deployed resources and costs. Use resource groups like folders to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="sb-sub">
          <Select id="sb-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="sb-rg">
          {newRg === null ? (
            <>
              <Select id="sb-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="sb-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Namespace details">
        <FormRow label="Namespace name" required htmlFor="sb-name" info=".servicebus.windows.net; 6-50 chars">
          <Input id="sb-name" value={f.name} onChange={set("name")} aria-label="Namespace name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Location" required htmlFor="sb-location">
          <Select id="sb-location" value={f.location} onChange={set("location")} aria-label="Location">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Pricing tier" required htmlFor="sb-tier">
          <Select id="sb-tier" value={f.pricingTier} onChange={set("pricingTier")} aria-label="Pricing tier">
            <option value="Basic">Basic</option><option value="Standard">Standard</option><option value="Premium">Premium</option>
          </Select>
        </FormRow>
        {f.pricingTier === "Premium" && (
          <>
            <FormRow label="Messaging units" htmlFor="sb-mu">
              <Select id="sb-mu" value={f.messagingUnits} onChange={set("messagingUnits")} aria-label="Messaging units">
                {["1", "2", "4", "8", "16"].map((u) => <option key={u} value={u}>{u}</option>)}
              </Select>
            </FormRow>
            <FormRow label="Partitions" htmlFor="sb-part">
              <Select id="sb-part" value={f.partitions} onChange={set("partitions")} aria-label="Partitions">
                {["1", "2", "4"].map((u) => <option key={u} value={u}>{u}</option>)}
              </Select>
            </FormRow>
          </>
        )}
      </FormSection>
    </>
  );

  const advanced = (
    <FormSection title="Advanced">
      <FormRow label="Minimum TLS version">
        <RadioGroup value={f.minTls} onChange={set("minTls")} aria-label="Minimum TLS version">
          <Radio value="1.0" label="1.0" /><Radio value="1.1" label="1.1" /><Radio value="1.2" label="1.2" />
        </RadioGroup>
      </FormRow>
      <FormRow label="Local Authentication">
        <RadioGroup value={f.localAuth} onChange={set("localAuth")} aria-label="Local Authentication">
          <Radio value="Enabled" label="Enabled" /><Radio value="Disabled" label="Disabled" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const networking = (
    <FormSection title="Network connectivity">
      <FormRow label="Connectivity method">
        <RadioGroup value={f.connectivity} onChange={set("connectivity")} aria-label="Connectivity method">
          <Radio value="Public access" label="Public access" /><Radio value="Private access" label="Private access" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const tags = (
    <FormSection title="Tags">
      <p style={{ fontSize: 13 }}>Name/value pairs to categorize resources and view consolidated billing.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Service Bus namespace" />
    </FormSection>
  );

  const body = () => api.namespaceArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Namespace name", f.name || "--"],
          ["Location", locationLabel(f.location)], ["Pricing tier", f.pricingTier]])}
        <h3>Advanced</h3>
        {dl([["Minimum TLS version", f.minTls], ["Local Authentication", f.localAuth]])}
        <h3>Networking</h3>
        {dl([["Connectivity method", f.connectivity]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createNamespace(rg, f.name, body());
      notify.success(`Deployment of namespace '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("servicebus", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create namespace" closeHref="#/servicebus" glyph={<Glyph id="servicebus" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "advanced", label: "Advanced", content: advanced },
        { id: "networking", label: "Networking", content: networking },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
