/* Create a Container App: Basics, Container, Ingress, Tags, Review + create -> one native
 * ARM PUT (core/azure_app_core.py). Naming an unknown environment ever not selected auto-
 * creates "cae-{rg}" the same way the real portal provisions one alongside the first app. */
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

const NAME_RE = /^[a-z]([-a-z0-9]{0,30}[a-z0-9])?$/;

export default function CreateContainerApp() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const envs = useAsync(() => api.listEnvironments(), [sub.id]);
  const existing = useAsync(() => api.listApps(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus", environment: "",
    image: "mcr.microsoft.com/k8se/quickstart:latest", cpu: "0.5",
    envVars: [{ name: "", value: "" }],
    ingressEnabled: true, ingressType: "external", targetPort: "80", transport: "auto",
    tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    if (!NAME_RE.test(f.name)) e.push("Container App name must consist of lower case alphanumeric characters or '-', start with a letter, end with an alphanumeric character, be 2-32 characters, and not contain '--'.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`A container app named "${f.name}" already exists.`);
    return e;
  };

  const envOptions = (envs.data || []).filter((e) => e.resourceGroup === rg);

  const basics = (
    <>
      <FormSection title="Project details">
        <FormRow label="Subscription" required htmlFor="ca-sub">
          <Select id="ca-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="ca-rg">
          {newRg === null ? (
            <>
              <Select id="ca-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="ca-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Container app details">
        <FormRow label="Container app name" required htmlFor="ca-name">
          <Input id="ca-name" value={f.name} onChange={set("name")} aria-label="Container app name" style={{ width: "100%" }} />
        </FormRow>
        <FormRow label="Region" required htmlFor="ca-location">
          <Select id="ca-location" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Container Apps Environment">
        <FormRow label="Container Apps Environment" required htmlFor="ca-env">
          <Select id="ca-env" value={f.environment} onChange={set("environment")} aria-label="Container Apps Environment">
            <option value="">Create new environment</option>
            {envOptions.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const container = (
    <>
      <FormSection title="Container details">
        <FormRow label="Name" htmlFor="ca-cname"><Input id="ca-cname" value={f.name ? `${f.name}` : ""} disabled aria-label="Container name" /></FormRow>
        <FormRow label="Image source" htmlFor="ca-image" required>
          <Input id="ca-image" value={f.image} onChange={set("image")} aria-label="Image source" style={{ width: "100%" }} />
        </FormRow>
      </FormSection>
      <FormSection title="Resource allocation">
        <FormRow label="CPU and Memory" required htmlFor="ca-cpu">
          <Select id="ca-cpu" value={f.cpu} onChange={set("cpu")} aria-label="CPU and Memory">
            {api.CPU_CHOICES.map((c) => <option key={c} value={c}>{c} CPU cores, {api.memFor(c)} memory</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Environment variables">
        <table className="vy-grid" style={{ maxWidth: 700 }}>
          <thead><tr><th>Name</th><th>Value</th></tr></thead>
          <tbody>
            {f.envVars.map((v, i) => (
              <tr key={i}>
                <td><Input size="small" value={v.name} onChange={(_, d) => setF((x) => { const xs = [...x.envVars]; xs[i] = { ...xs[i], name: d.value }; if (i === xs.length - 1 && d.value) xs.push({ name: "", value: "" }); return { ...x, envVars: xs }; })} aria-label={`Environment variable name ${i + 1}`} /></td>
                <td><Input size="small" value={v.value} onChange={(_, d) => setF((x) => { const xs = [...x.envVars]; xs[i] = { ...xs[i], value: d.value }; return { ...x, envVars: xs }; })} aria-label={`Environment variable value ${i + 1}`} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </FormSection>
    </>
  );

  const ingress = (
    <FormSection title="Ingress">
      <FormRow label="Ingress"><Checkbox checked={f.ingressEnabled} onChange={set("ingressEnabled")} label="Enabled" /></FormRow>
      {f.ingressEnabled && (
        <>
          <FormRow label="Ingress traffic">
            <RadioGroup value={f.ingressType} onChange={set("ingressType")} aria-label="Ingress traffic">
              <Radio value="external" label="Accepting traffic from anywhere" />
              <Radio value="internal" label="Limited to Container Apps Environment" />
            </RadioGroup>
          </FormRow>
          <FormRow label="Target port" required htmlFor="ca-port"><Input id="ca-port" type="number" value={f.targetPort} onChange={set("targetPort")} aria-label="Target port" /></FormRow>
          <FormRow label="Transport" htmlFor="ca-transport">
            <Select id="ca-transport" value={f.transport} onChange={set("transport")} aria-label="Transport">
              <option value="auto">Auto</option><option value="http">HTTP</option><option value="http2">HTTP/2</option><option value="tcp">TCP</option>
            </Select>
          </FormRow>
        </>
      )}
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
      ...(f.environment ? { managedEnvironmentId: f.environment } : {}),
      configuration: {
        ingress: f.ingressEnabled ? { external: f.ingressType === "external", targetPort: Number(f.targetPort) || 80, transport: f.transport } : null,
      },
      template: {
        containers: [{ name: f.name, image: f.image, resources: { cpu: Number(f.cpu), memory: api.memFor(Number(f.cpu)) },
          env: f.envVars.filter((v) => v.name).map((v) => ({ name: v.name, value: v.value })) }],
      },
    },
  });

  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Container app name", f.name || "--"], ["Region", locationLabel(f.location)],
          ["Container Apps Environment", f.environment ? api.envName(f.environment) : "New environment"]])}
        <h3>Container</h3>
        {dl([["Image", f.image], ["CPU and Memory", `${f.cpu} CPU cores, ${api.memFor(Number(f.cpu))} memory`]])}
        <h3>Ingress</h3>
        {dl(f.ingressEnabled ? [["Ingress", "Enabled"], ["Ingress traffic", f.ingressType === "external" ? "Accepting traffic from anywhere" : "Limited to Container Apps Environment"], ["Target port", f.targetPort]] : [["Ingress", "Disabled"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createApp(rg, f.name, body());
      notify.success(`Deployment of container app '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("containerapps", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Container App" closeHref="#/containerapps" glyph={<Glyph id="containerapps" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "container", label: "Container", content: container },
        { id: "ingress", label: "Ingress", content: ingress },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
