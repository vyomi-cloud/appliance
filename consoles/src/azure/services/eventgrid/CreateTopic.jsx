/* Create an Event Grid topic: Basics, Networking, Security, Advanced, Tags, Review + create
 * → one native ARM PUT. */
import { useState } from "react";
import { Checkbox, Input, Link, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./TagRows.jsx";
import * as api from "./api.js";

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9-]{1,48}[a-zA-Z0-9]$/;
const RG_RE = /^[-\w._()]{1,90}$/;
const SCHEMA_MAP = { "Event Grid Schema": "EventGridSchema", "Cloud Event Schema v1.0": "CloudEventSchemaV1_0", "Custom Input Schema": "CustomEventSchema" };

export default function CreateTopic() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listTopics(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus",
    connectivity: "Public access",
    identityType: "None", accessKeys: true, minimumTls: "1.2",
    eventSchema: "Cloud Event Schema v1.0",
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("Topic name must be 3-50 characters, alphanumeric and hyphens, starting and ending with a letter or number.");
    else if ((existing.data || []).some((t) => t.name === f.name)) e.push(`A topic named ${f.name} already exists.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Topic name") || m.startsWith("A topic"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription to manage deployed resources and costs. Use resource groups to organize and manage your resources.">
        <FormRow label="Subscription" required htmlFor="eg-sub">
          <Select id="eg-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="eg-rg">
          {newRg === null ? (
            <>
              <Select id="eg-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="eg-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Topic Details">
        <FormRow label="Name" required htmlFor="eg-name">
          <Input id="eg-name" value={f.name} onChange={set("name")} aria-label="Name" style={{ width: "100%" }} />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Region" required htmlFor="eg-region">
          <Select id="eg-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>(US) {l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <FormSection title="Network connectivity" description="You can connect to your topic either publicly, via public IP addresses, or privately, using a private endpoint.">
      <FormRow label="Connectivity method" required>
        <RadioGroup value={f.connectivity} onChange={set("connectivity")} aria-label="Connectivity method">
          <Radio value="Public access" label="Public access" />
          <Radio value="Private access" label="Private access" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const security = (
    <>
      <FormSection title="Managed identity">
        <FormRow label="Managed identity type" htmlFor="eg-identity">
          <Select id="eg-identity" value={f.identityType} onChange={set("identityType")} aria-label="Managed identity type">
            <option value="None">None</option>
            <option value="SystemAssigned">System assigned</option>
            <option value="UserAssigned">User assigned</option>
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Access keys">
        <FormRow label="Enable access keys and Shared Access Signatures (SAS)">
          <Checkbox checked={f.accessKeys} onChange={chk("accessKeys")} aria-label="Enable access keys and Shared Access Signatures (SAS)" />
        </FormRow>
      </FormSection>
      <FormSection title="Minimum TLS version">
        <FormRow label="Minimum TLS version" htmlFor="eg-tls">
          <Select id="eg-tls" value={f.minimumTls} onChange={set("minimumTls")} aria-label="Minimum TLS version">
            <option value="1.0">1.0</option><option value="1.1">1.1</option><option value="1.2">1.2</option>
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const advanced = (
    <FormSection title="Event Schema">
      <FormRow label="Event Schema" htmlFor="eg-schema">
        <Select id="eg-schema" value={f.eventSchema} onChange={set("eventSchema")} aria-label="Event Schema">
          {Object.keys(SCHEMA_MAP).map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </FormRow>
    </FormSection>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Topic" />
    </>
  );

  const body = () => ({
    location: f.location,
    identity: f.identityType === "None" ? undefined : { type: f.identityType },
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      inputSchema: SCHEMA_MAP[f.eventSchema],
      publicNetworkAccess: f.connectivity === "Public access" ? "Enabled" : "Disabled",
      minimumTlsVersionAllowed: f.minimumTls,
      disableLocalAuth: !f.accessKeys,
    },
  });

  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource group", rg || "--"], ["Name", f.name || "--"], ["Region", locationLabel(f.location)]])}
        <h3>Networking</h3>
        {dl([["Connectivity method", f.connectivity]])}
        <h3>Security</h3>
        {dl([["Managed identity type", f.identityType === "SystemAssigned" ? "System assigned" : f.identityType === "UserAssigned" ? "User assigned" : "None"],
          ["Access keys and SAS", f.accessKeys ? "Enabled" : "Disabled"], ["Minimum TLS version", f.minimumTls]])}
        <h3>Advanced</h3>
        {dl([["Event Schema", f.eventSchema]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createTopic(rg, f.name, body());
      notify.success(`Deployment of topic '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("eventgrid", "topics", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Topic" closeHref="#/eventgrid/topics" glyph={<Glyph id="eventgrid" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "networking", label: "Networking", content: networking },
        { id: "security", label: "Security", content: security },
        { id: "advanced", label: "Advanced", content: advanced },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
