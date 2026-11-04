/* Create a subscription: Basics, Advanced, Tags, Review + create. Vyomi simulates exactly one
 * subscription (every other Azure service's fixtures depend on it existing), so "Create" does
 * something real and visible — it renames that one subscription to the chosen name and opens
 * its Overview — rather than pretending to mint an independent, listable second subscription. */
import { useState } from "react";
import { Button, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, InfoBar, NotSimulated } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const PLANS = ["Microsoft Azure Plan", "Microsoft Azure Plan for DevTest"];

function TagRows({ tags, onChange }) {
  const upd = (i, k, v) => {
    const xs = tags.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "" });
    onChange(xs);
  };
  return (
    <Table size="small" aria-label="Tags" style={{ maxWidth: 760 }}>
      <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
      <TableBody>
        {tags.map((t, i) => (
          <TableRow key={i}>
            <TableCell><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></TableCell>
            <TableCell><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></TableCell>
            <TableCell>Subscription</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function CreateSubscription() {
  const notify = useNotify();
  const sub = useSubscription();
  const [f, setF] = useState({ name: "", plan: PLANS[0], tags: [{ name: "", value: "" }] });
  const [addOwner, setAddOwner] = useState(false);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));

  const basicsErrors = () => (f.name.trim() ? [] : ["Subscription name is required."]);

  const basics = (
    <FormSection title="Project details" description="Select a billing account and billing profile and enter a descriptive name for your subscription.">
      <FormRow label="Subscription name" required htmlFor="cs-name">
        <Input id="cs-name" value={f.name} onChange={set("name")} aria-label="Subscription name" style={{ width: "100%" }} />
      </FormRow>
      <FormRow label="Billing account" required htmlFor="cs-account">
        <Select id="cs-account" aria-label="Billing account" defaultValue="cloudlearn"><option value="cloudlearn">CloudLearn Billing Account</option></Select>
      </FormRow>
      <FormRow label="Billing profile" required htmlFor="cs-profile">
        <Select id="cs-profile" aria-label="Billing profile" defaultValue="cloudlearn"><option value="cloudlearn">CloudLearn Billing Profile</option></Select>
      </FormRow>
      <FormRow label="Invoice section" required htmlFor="cs-invoice">
        <Select id="cs-invoice" aria-label="Invoice section" defaultValue="cloudlearn"><option value="cloudlearn">CloudLearn Invoice Section</option></Select>
      </FormRow>
      <FormRow label="Plan" htmlFor="cs-plan">
        <Select id="cs-plan" value={f.plan} onChange={set("plan")} aria-label="Plan">{PLANS.map((p) => <option key={p}>{p}</option>)}</Select>
      </FormRow>
    </FormSection>
  );

  const advanced = (
    <FormSection title="Advanced">
      <FormRow label="Subscription directory" htmlFor="cs-dir">
        <Select id="cs-dir" aria-label="Subscription directory" defaultValue="default"><option value="default">Vyomi simulator (default directory)</option></Select>
      </FormRow>
      <FormRow label="Management group" htmlFor="cs-mg">
        <Select id="cs-mg" aria-label="Management group" defaultValue="none"><option value="none">None</option></Select>
      </FormRow>
      <FormRow label="Subscription owner">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>vyomi@simulator.local (you)</span>
          <Button size="small" onClick={() => setAddOwner(true)}>Add owner</Button>
        </div>
        {addOwner && <div style={{ marginTop: 8 }}><NotSimulated feature="Adding another subscription owner (multi-identity IAM)" /></div>}
      </FormRow>
    </FormSection>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Name/value pairs to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} />
    </>
  );

  const review = () => {
    const tagList = f.tags.filter((t) => t.name);
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription name", f.name || "--"], ["Billing account", "CloudLearn Billing Account"], ["Billing profile", "CloudLearn Billing Profile"], ["Invoice section", "CloudLearn Invoice Section"], ["Plan", f.plan]])}
        <h3>Advanced</h3>
        {dl([["Subscription directory", "Vyomi simulator (default directory)"], ["Management group", "None"]])}
        <h3>Tags</h3>
        {dl(tagList.length ? tagList.map((t) => [t.name, t.value || "(empty)"]) : [["Tags", "None"]])}
        <InfoBar intent="warning" title="Vyomi simulates exactly one subscription">
          Creating a subscription renames Vyomi's one simulated subscription to the name above — it does not mint an independent, separately billable subscription.
        </InfoBar>
      </>
    );
  };

  const onCreate = async () => {
    try {
      const r = await api.renameSubscription(sub.id, f.name.trim());
      if (f.tags.some((t) => t.name)) await api.putTags(sub.id, Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])));
      notify.success(`Successfully created subscription '${f.name.trim()}'.`, "Deployment succeeded");
      navigate("subscriptions", r.subscriptionId);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create a subscription" closeHref="#/subscriptions" glyph={<Glyph id="subscriptions" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "advanced", label: "Advanced", content: advanced },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
