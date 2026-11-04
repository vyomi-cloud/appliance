/* Create a Container Apps Environment: Basics, Monitoring, Networking, Tags, Review + create
 * -> one native ARM PUT (core/azure_app_core.py's managedEnvironments branch). */
import { useState } from "react";
import { Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const NAME_RE = /^[A-Za-z][-A-Za-z0-9_]{0,59}$/;

export default function CreateEnvironment() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listEnvironments(), [sub.id]);
  const workspaces = useAsync(() => api.listWorkspaces(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({ resourceGroup: DEFAULT_RG, name: "", location: "eastus", workspace: "", zoneRedundant: false, tags: [{ name: "", value: "" }] });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    if (!NAME_RE.test(f.name)) e.push("Environment name must start with a letter and contain only letters, numbers, underscores and hyphens, up to 60 characters.");
    else if ((existing.data || []).some((v) => v.name.toLowerCase() === f.name.toLowerCase())) e.push(`An environment named "${f.name}" already exists.`);
    return e;
  };

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription to manage deployed resources and costs. Use resource groups like folders to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="cae-sub">
          <Select id="cae-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource group" required htmlFor="cae-rg">
          {newRg === null ? (
            <>
              <Select id="cae-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="cae-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Environment details">
        <FormRow label="Environment name" required htmlFor="cae-name">
          <Input id="cae-name" value={f.name} onChange={set("name")} aria-label="Environment name" style={{ width: "100%" }} />
        </FormRow>
        <FormRow label="Region" required htmlFor="cae-location">
          <Select id="cae-location" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
    </>
  );

  const monitoring = (
    <FormSection title="Log Analytics workspace" description="Container Apps environments use Log Analytics to collect application and system logs.">
      <FormRow label="Log Analytics workspace">
        {(workspaces.data || []).length ? (
          <Select value={f.workspace} onChange={set("workspace")} aria-label="Log Analytics workspace">
            <option value="">Create a new workspace</option>
            {workspaces.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </Select>
        ) : <p style={{ fontSize: 13 }}>A new Log Analytics workspace will be created for this environment.</p>}
      </FormRow>
    </FormSection>
  );

  const networking = (
    <FormSection title="Virtual network">
      <NotSimulatedContainer title="Custom virtual network" feature="Custom virtual network integration"
        note="Vyomi always provisions the environment's own virtual network; bringing an existing VNet/subnet is not simulated." />
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
    properties: { zoneRedundant: f.zoneRedundant, ...(f.workspace ? { appLogsConfiguration: { destination: "log-analytics", logAnalyticsConfiguration: { customerId: f.workspace } } } : {}) },
  });

  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basics</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"], ["Environment name", f.name || "--"], ["Region", locationLabel(f.location)]])}
        <h3>Monitoring</h3>
        {dl([["Log Analytics workspace", f.workspace || "New workspace"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createEnvironment(rg, f.name, body());
      notify.success(`Deployment of environment '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("containerapps", "environments", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Container Apps Environment" closeHref="#/containerapps/environments" glyph={<Glyph id="containerapps" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "monitoring", label: "Monitoring", content: monitoring },
        { id: "networking", label: "Networking", content: networking },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
