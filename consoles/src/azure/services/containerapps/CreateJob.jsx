/* Create a Container Apps Job: Basics, Container, Configuration, Tags, Review + create ->
 * one native ARM PUT (core/azure_app_core.py's jobs branch). */
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

const NAME_RE = /^[a-z]([-a-z0-9]{0,30}[a-z0-9])?$/;

export default function CreateJob() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const envs = useAsync(() => api.listEnvironments(), [sub.id]);
  const existing = useAsync(() => api.listJobs(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", environment: "",
    image: "mcr.microsoft.com/k8se/quickstart-jobs:latest", cpu: "0.5",
    triggerType: "Manual", cron: "*/5 * * * *", parallelism: "1", completions: "1", timeout: "1800", retries: "0",
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    if (!NAME_RE.test(f.name)) e.push("Job name must consist of lower case alphanumeric characters or '-', start with a letter, end with an alphanumeric character, be 2-32 characters, and not contain '--'.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`A job named "${f.name}" already exists.`);
    if (f.triggerType === "Schedule" && !f.cron) e.push("Cron expression is required for Schedule jobs.");
    return e;
  };
  const envOptions = (envs.data || []).filter((e) => e.resourceGroup === rg);

  const basics = (
    <>
      <FormSection title="Project details">
        <FormRow label="Subscription" required htmlFor="caj-sub">
          <Select id="caj-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="caj-rg">
          {newRg === null ? (
            <>
              <Select id="caj-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="caj-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Job details">
        <FormRow label="Job name" required htmlFor="caj-name"><Input id="caj-name" value={f.name} onChange={set("name")} aria-label="Job name" style={{ width: "100%" }} /></FormRow>
        <FormRow label="Region" required htmlFor="caj-location">
          <Select id="caj-location" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Container Apps Environment">
        <FormRow label="Container Apps Environment" required htmlFor="caj-env">
          <Select id="caj-env" value={f.environment} onChange={set("environment")} aria-label="Container Apps Environment">
            <option value="">Create new environment</option>
            {envOptions.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const container = (
    <FormSection title="Container details">
      <FormRow label="Image" required htmlFor="caj-image"><Input id="caj-image" value={f.image} onChange={set("image")} aria-label="Image" style={{ width: "100%" }} /></FormRow>
      <FormRow label="CPU and Memory" required htmlFor="caj-cpu">
        <Select id="caj-cpu" value={f.cpu} onChange={set("cpu")} aria-label="CPU and Memory">
          {api.CPU_CHOICES.map((c) => <option key={c} value={c}>{c} CPU cores, {api.memFor(c)} memory</option>)}
        </Select>
      </FormRow>
    </FormSection>
  );

  const configuration = (
    <FormSection title="Trigger">
      <FormRow label="Trigger type" required htmlFor="caj-trigger">
        <Select id="caj-trigger" value={f.triggerType} onChange={set("triggerType")} aria-label="Trigger type">
          <option value="Manual">Manual</option><option value="Schedule">Schedule</option><option value="Event">Event</option>
        </Select>
      </FormRow>
      {f.triggerType === "Schedule" && (
        <FormRow label="Cron expression" required htmlFor="caj-cron"><Input id="caj-cron" value={f.cron} onChange={set("cron")} aria-label="Cron expression" /></FormRow>
      )}
      <FormRow label="Parallelism" htmlFor="caj-parallelism"><Input id="caj-parallelism" type="number" value={f.parallelism} onChange={set("parallelism")} aria-label="Parallelism" /></FormRow>
      <FormRow label="Replica completion count" htmlFor="caj-completions"><Input id="caj-completions" type="number" value={f.completions} onChange={set("completions")} aria-label="Replica completion count" /></FormRow>
      <FormRow label="Replica timeout (seconds)" htmlFor="caj-timeout"><Input id="caj-timeout" type="number" value={f.timeout} onChange={set("timeout")} aria-label="Replica timeout (seconds)" /></FormRow>
      <FormRow label="Replica retry limit" htmlFor="caj-retries"><Input id="caj-retries" type="number" value={f.retries} onChange={set("retries")} aria-label="Replica retry limit" /></FormRow>
    </FormSection>
  );

  const tags = (
    <FormSection title="Tags">
      <p style={{ fontSize: 13 }}>Name/value pairs to categorize resources and view consolidated billing.</p>
      <table className="vy-grid" style={{ maxWidth: 700 }}>
        <thead><tr><th>Name</th><th>Value</th></tr></thead>
        <tbody>
          {f.tags.map((t, i) => (
            <tr key={i}>
              <td><Input size="small" value={t.name} onChange={(_, d) => setF((x) => { const xs = [...x.tags]; xs[i] = { ...xs[i], name: d.value }; if (i === xs.length - 1 && d.value) xs.push({ name: "", value: "" }); return { ...x, tags: xs }; })} aria-label={`Tag name ${i + 1}`} /></td>
              <td><Input size="small" value={t.value} onChange={(_, d) => setF((x) => { const xs = [...x.tags]; xs[i] = { ...xs[i], value: d.value }; return { ...x, tags: xs }; })} aria-label={`Tag value ${i + 1}`} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </FormSection>
  );

  const body = () => ({
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      ...(f.environment ? { environmentId: f.environment } : {}),
      configuration: {
        triggerType: f.triggerType, replicaTimeout: Number(f.timeout), replicaRetryLimit: Number(f.retries),
        ...(f.triggerType === "Manual" ? { manualTriggerConfig: { parallelism: Number(f.parallelism), replicaCompletionCount: Number(f.completions) } } : {}),
        ...(f.triggerType === "Schedule" ? { scheduleTriggerConfig: { cronExpression: f.cron, parallelism: Number(f.parallelism), replicaCompletionCount: Number(f.completions) } } : {}),
      },
      template: { containers: [{ name: f.name, image: f.image, resources: { cpu: Number(f.cpu), memory: api.memFor(Number(f.cpu)) } }] },
    },
  });

  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Job name", f.name || "--"], ["Region", locationLabel(f.location)],
          ["Container Apps Environment", f.environment ? api.envName(f.environment) : "New environment"]])}
        <h3>Container</h3>
        {dl([["Image", f.image], ["CPU and Memory", `${f.cpu} CPU cores, ${api.memFor(Number(f.cpu))} memory`]])}
        <h3>Configuration</h3>
        {dl([["Trigger type", f.triggerType], ["Replica timeout", f.timeout], ["Replica retry limit", f.retries]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createJob(rg, f.name, body());
      notify.success(`Deployment of job '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("containerapps", "jobs", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Container Apps Job" closeHref="#/containerapps/jobs" glyph={<Glyph id="containerapps" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "container", label: "Container", content: container },
        { id: "configuration", label: "Configuration", content: configuration },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
