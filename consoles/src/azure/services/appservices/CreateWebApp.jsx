/* Create Web App: Basics, Database, Container, Deployment, Networking, Monitor + secure,
 * Tags, Review + create → an ARM PUT on an App Service plan (new or existing) followed by
 * a PUT on the site that references it. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Input, Link, Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, InfoBar, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { vy } from "../../../common/VyomiMark.jsx";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9-]{0,58}[A-Za-z0-9]$/;
const RG_RE = /^[-\w._()]{1,90}$/;

export default function CreateWebApp() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listSites(), [sub.id]);
  const plans = useAsync(() => api.listPlans(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", location: "eastus",
    publish: "Code", runtimeStack: "PYTHON|3.12", os: "Linux",
    planChoice: "__new", newPlanName: "", planSku: "B1", zoneRedundant: "Disabled",
    createDatabase: false,
    containerImageSource: "Quickstart", containerImage: "",
    continuousDeployment: "Disable", basicAuth: "Disable",
    publicAccess: true, networkInjection: false,
    appInsights: "No", defender: false,
    tags: [{ name: "", value: "" }],
  });
  const [planNameTouched, setPlanNameTouched] = useState(false);
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));
  const rg = newRg ?? f.resourceGroup;
  const regionLabel = locationLabel(f.location);
  // The real portal auto-fills a default plan name as soon as you type the app name.
  useEffect(() => { if (!planNameTouched) setF((x) => ({ ...x, newPlanName: x.name ? `${x.name}-plan` : "" })); }, [f.name, planNameTouched]);
  const linuxPlans = (plans.data || []).filter((p) => (p.properties?.reserved || false) === (f.os === "Linux"));

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    else if (!RG_RE.test(rg)) e.push("Resource group names can only include alphanumeric, underscore, parentheses, hyphen and period characters.");
    if (!NAME_RE.test(f.name)) e.push("App name must be 2-60 characters, letters, digits or hyphens, and can't start or end with a hyphen.");
    else if ((existing.data || []).some((a) => a.name === f.name)) e.push(`The app name '${f.name}' is not available. '${f.name}.azurewebsites.net' is taken.`);
    if (f.planChoice === "__new" && !f.newPlanName) e.push("New App Service Plan name is required.");
    return e;
  };
  const nameError = f.name && !NAME_RE.test(f.name) ? "App name must be 2-60 characters, letters, digits or hyphens." :
    f.name && (existing.data || []).some((a) => a.name === f.name) ? `The app name '${f.name}' is not available.` : null;

  const basics = (
    <>
      <FormSection title="Project details">
        <FormRow label="Subscription" required htmlFor="wa-sub">
          <Select id="wa-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource Group" required htmlFor="wa-rg">
          {newRg === null ? (
            <>
              <Select id="wa-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource Group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="wa-rg" value={newRg} placeholder="Name of the new resource group" onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance Details">
        <FormRow label="Name" required htmlFor="wa-name">
          <Input id="wa-name" value={f.name} onChange={set("name")} aria-label="Name" contentAfter=".azurewebsites.net" />
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <NotSimulatedContainer title="Secure unique default hostname on." feature="Secure unique default hostname on." note={vy("Vyomi always uses the exact name you choose; there is no name-collision suffix to secure.")} />
        <FormRow label="Publish" required>
          <RadioGroup value={f.publish} onChange={set("publish")} aria-label="Publish">
            <Radio value="Code" label="Code" />
            <Radio value="Container" label="Container" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Runtime stack" required htmlFor="wa-runtime">
          <Select id="wa-runtime" value={f.runtimeStack} onChange={set("runtimeStack")} aria-label="Runtime stack" disabled={f.publish === "Container"}>
            {api.RUNTIMES.map(([label, val]) => <option key={val} value={val}>{label}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Operating System" required>
          <RadioGroup value={f.os} onChange={set("os")} aria-label="Operating System">
            <Radio value="Linux" label="Linux" />
            <Radio value="Windows" label="Windows" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Region" required htmlFor="wa-region">
          <Select id="wa-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Pricing plans">
        <FormRow label={`${f.os} Plan (${regionLabel})`} required htmlFor="wa-plan">
          <Select id="wa-plan" value={f.planChoice} onChange={set("planChoice")} aria-label={`${f.os} Plan (${regionLabel})`}>
            <option value="__new">Create new</option>
            {linuxPlans.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </Select>
          {f.planChoice === "__new" && (
            <Input style={{ marginTop: 6 }} value={f.newPlanName} placeholder="New plan name"
              onChange={(_, d) => { setPlanNameTouched(true); setF((x) => ({ ...x, newPlanName: d.value })); }} aria-label="New App Service Plan name" />
          )}
        </FormRow>
        <FormRow label="Pricing plan" required htmlFor="wa-sku">
          <Select id="wa-sku" value={f.planSku} onChange={set("planSku")} aria-label="Pricing plan">
            {api.PLAN_SKUS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Zone redundancy">
        <FormRow label="Zone redundancy" required>
          <RadioGroup value={f.zoneRedundant} onChange={set("zoneRedundant")} aria-label="Zone redundancy" disabled={f.planChoice !== "__new"}>
            <Radio value="Enabled" label="Enabled" />
            <Radio value="Disabled" label="Disabled" />
          </RadioGroup>
        </FormRow>
      </FormSection>
    </>
  );

  const database = (
    <NotSimulatedContainer title="Database" feature="Create a Database" note={vy("Provisioning a linked database from the Web App wizard is not modelled; create one directly in the SQL/Cosmos DB lens instead.")} />
  );

  const container = (
    <FormSection title="Image source">
      <FormRow label="Image Source" required htmlFor="wa-imgsrc">
        <Select id="wa-imgsrc" value={f.containerImageSource} onChange={set("containerImageSource")} aria-label="Image Source" disabled={f.publish !== "Container"}>
          <option value="Quickstart">Quickstart</option>
          <option value="Azure Container Registry">Azure Container Registry</option>
          <option value="Docker Hub or other registries">Docker Hub or other registries</option>
        </Select>
      </FormRow>
      {f.publish === "Container" && f.containerImageSource !== "Quickstart" && (
        <FormRow label="Image and tag" htmlFor="wa-img"><Input id="wa-img" value={f.containerImage} onChange={set("containerImage")} placeholder="nginx:latest" aria-label="Image and tag" /></FormRow>
      )}
    </FormSection>
  );

  const deployment = (
    <>
      <FormSection title="GitHub Actions settings">
        <FormRow label="Continuous deployment">
          <RadioGroup value={f.continuousDeployment} onChange={set("continuousDeployment")} aria-label="Continuous deployment">
            <Radio value="Disable" label="Disable" />
            <Radio value="Enable" label="Enable" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      <NotSimulatedContainer title="GitHub Actions details" feature="GitHub account, Organization, Repository, Branch"
        note={vy("Vyomi records that continuous deployment is enabled on the site; it cannot authorize a GitHub account or run a build pipeline.")} />

      <FormSection title="Authentication settings">
        <FormRow label="Basic authentication">
          <RadioGroup value={f.basicAuth} onChange={set("basicAuth")} aria-label="Basic authentication">
            <Radio value="Disable" label="Disable" />
            <Radio value="Enable" label="Enable" />
          </RadioGroup>
        </FormRow>
      </FormSection>
    </>
  );

  const networking = (
    <FormSection title="Networking">
      <FormRow label="Enable public access">
        <Checkbox checked={f.publicAccess} onChange={chk("publicAccess")} aria-label="Enable public access" />
      </FormRow>
      <NotSimulatedContainer title="Enable network injection" feature="Enable network injection" note="VNet integration for the App Service plan is not modelled." />
    </FormSection>
  );

  const monitorSecure = (
    <>
      <FormSection title="Application Insights">
        <FormRow label="Enable Application Insights">
          <RadioGroup value={f.appInsights} onChange={set("appInsights")} aria-label="Enable Application Insights">
            <Radio value="Yes" label="Yes" />
            <Radio value="No" label="No" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      <NotSimulatedContainer title="Application Insights" feature="Application Insights" note="Creating/linking an Application Insights resource (and its Region) is not modelled." />
      <FormSection title="Microsoft Defender for App Service">
        <NotSimulatedContainer feature="Enable Microsoft Defender for App Service" />
      </FormSection>
    </>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="App Service" />
    </>
  );

  const review = () => {
    const yes = (v) => (v ? "Yes" : "No");
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Details</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"]])}
        <h3>Instance Details</h3>
        {dl([["Name", f.name || "--"], ["Publish", f.publish], ["Runtime stack", api.RUNTIMES.find(([, v]) => v === f.runtimeStack)?.[0]], ["Operating System", f.os], ["Region", regionLabel]])}
        <h3>App Service Plan (New)</h3>
        {dl([["Name", f.planChoice === "__new" ? f.newPlanName || "--" : f.planChoice], ["Sku and size", f.planSku], ["Zone redundancy", f.zoneRedundant]])}
        <h3>Monitor + secure</h3>
        {dl([["Application Insights", yes(f.appInsights === "Yes")], ["Microsoft Defender for App Service", yes(f.defender)]])}
        <h3>Deployment</h3>
        {dl([["Continuous deployment", f.continuousDeployment], ["Basic authentication", f.basicAuth]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      let planId = plans.data?.find((p) => p.name === f.planChoice)?.id;
      if (f.planChoice === "__new") {
        const plan = await api.createPlan(rg, f.newPlanName, {
          location: f.location, sku: { name: f.planSku },
          properties: { reserved: f.os === "Linux", zoneRedundant: f.zoneRedundant === "Enabled" },
        });
        planId = plan.id;
      }
      const siteConfig = {
        linuxFxVersion: f.os === "Linux" ? (f.publish === "Container" ? `DOCKER|${f.containerImage || "mcr.microsoft.com/appsvc/staticsite:latest"}` : f.runtimeStack) : "",
        netFrameworkVersion: f.os === "Windows" ? "v4.0" : "v4.0",
        continuousDeploymentEnabled: f.continuousDeployment === "Enable",
        basicAuthEnabled: f.basicAuth === "Enable",
      };
      await api.createSite(rg, f.name, {
        location: f.location, kind: f.os === "Linux" ? "app,linux" : "app",
        tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
        properties: { serverFarmId: planId, siteConfig, publicNetworkAccess: f.publicAccess ? "Enabled" : "Disabled" },
      });
      notify.success(`Deployment of app service '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("appservices", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Web App" closeHref="#/appservices" glyph={<Glyph id="appservices" />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: basicsErrors },
        { id: "database", label: "Database", content: database },
        { id: "container", label: "Container", content: container },
        { id: "deployment", label: "Deployment", content: deployment },
        { id: "networking", label: "Networking", content: networking },
        { id: "monitor", label: "Monitor + secure", content: monitorSecure },
        { id: "tags", label: "Tags", content: tags },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}

/** Name / Value / Resource tag rows; a blank row is always available at the end. */
function TagRows({ tags, onChange, resource }) {
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
            <TableCell>{resource}</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
