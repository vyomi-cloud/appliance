/* Create Function App (Flex Consumption): Basics, Storage, Azure OpenAI, Networking,
 * Monitoring, Deployment, Authentication, Tags, Review + create → one native ARM PUT. */
import { useState } from "react";
import { Button, Checkbox, Input, Link, Radio, RadioGroup, Select, Switch, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, InfoBar, NotSimulatedContainer } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$/;

export default function CreateFunctionApp() {
  const notify = useNotify();
  const sub = useSubscription();
  const rgs = useAsync(() => listResourceGroups(), [sub.id]);
  const existing = useAsync(() => api.listFunctionApps(), [sub.id]);
  const [newRg, setNewRg] = useState(null);
  const [f, setF] = useState({
    resourceGroup: DEFAULT_RG, name: "", secureHostname: true, runtime: "Python", version: "3.12", location: "eastus",
    zoneRedundant: false, storageAccount: "vyomistorage", diagnostics: "none", openai: false,
    publicAccess: true, vnetIntegration: false, appInsights: "yes", appInsightsName: "", cicd: false, basicAuth: false,
    authType: "secrets", tags: [{ name: "", value: "" }],
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const rg = newRg ?? f.resourceGroup;

  const basicsErrors = () => {
    const e = [];
    if (!rg) e.push("Resource group is required.");
    if (!NAME_RE.test(f.name)) e.push("Function App name must be 2-60 characters, lower-case letters, numbers and hyphens, and cannot start or end with a hyphen.");
    else if ((existing.data || []).some((a) => a.name === f.name)) e.push(`Site name '${f.name}' is already in use.`);
    return e;
  };
  const nameError = f.name && basicsErrors().find((m) => m.startsWith("Function App") || m.startsWith("Site name"));

  const basics = (
    <>
      <FormSection title="Project details" description="Select the subscription to manage deployed resources and costs. Use resource groups like folders to organize and manage all your resources.">
        <FormRow label="Subscription" required htmlFor="fa-sub">
          <Select id="fa-sub" value={sub.id} aria-label="Subscription"><option value={sub.id}>{sub.displayName || sub.id}</option></Select>
        </FormRow>
        <FormRow label="Resource Group" required htmlFor="fa-rg">
          {newRg === null ? (
            <>
              <Select id="fa-rg" value={f.resourceGroup} onChange={set("resourceGroup")} aria-label="Resource Group">
                {[...new Set([DEFAULT_RG, ...(rgs.data || []).map((r) => r.name)])].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg("")}>Create new</Link>
            </>
          ) : (
            <>
              <Input id="fa-rg" value={newRg} onChange={(_, d) => setNewRg(d.value)} aria-label="New resource group name" />
              <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => setNewRg(null)}>Use existing</Link>
            </>
          )}
        </FormRow>
      </FormSection>
      <FormSection title="Instance Details">
        <FormRow label="Function App name" required htmlFor="fa-name" info=".azurewebsites.net">
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Input id="fa-name" value={f.name} onChange={set("name")} aria-label="Function App name" style={{ width: "100%" }} />
            <span className="vy-muted">.azurewebsites.net</span>
          </div>
          {nameError && <div style={{ color: "var(--colorPaletteRedForeground1)", fontSize: 12, marginTop: 4 }}>{nameError}</div>}
        </FormRow>
        <FormRow label="Secure unique default hostname on.">
          <Switch checked={f.secureHostname} onChange={(_, d) => setF((x) => ({ ...x, secureHostname: d.checked }))} label={f.secureHostname ? "On" : "Off"} />
        </FormRow>
        <FormRow label="Runtime stack" required htmlFor="fa-runtime">
          <Select id="fa-runtime" value={f.runtime} onChange={(_, d) => setF((x) => ({ ...x, runtime: d.value, version: api.RUNTIMES[d.value][0] }))} aria-label="Runtime stack">
            {Object.keys(api.RUNTIMES).map((r) => <option key={r} value={r}>{r}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Version" required htmlFor="fa-version">
          <Select id="fa-version" value={f.version} onChange={set("version")} aria-label="Version">
            {api.RUNTIMES[f.runtime].map((v) => <option key={v} value={v}>{v}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Region" required htmlFor="fa-region">
          <Select id="fa-region" value={f.location} onChange={set("location")} aria-label="Region">
            {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Zone redundancy">
        <FormRow label="Zone redundancy">
          <RadioGroup value={f.zoneRedundant ? "Enabled" : "Disabled"} onChange={(_, d) => setF((x) => ({ ...x, zoneRedundant: d.value === "Enabled" }))} aria-label="Zone redundancy">
            <Radio value="Enabled" label="Enabled" /><Radio value="Disabled" label="Disabled" />
          </RadioGroup>
        </FormRow>
      </FormSection>
    </>
  );

  const storage = (
    <FormSection title="Storage">
      <FormRow label="Storage account" required htmlFor="fa-storage">
        <Input id="fa-storage" value={f.storageAccount} onChange={set("storageAccount")} aria-label="Storage account" />
        <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => notify.info("Vyomi reuses one simulated storage account name; no separate account is provisioned.")}>Create new</Link>
      </FormRow>
      <FormRow label="Diagnostic Settings">
        <RadioGroup value={f.diagnostics} onChange={set("diagnostics")} aria-label="Diagnostic Settings">
          <Radio value="none" label="Don't configure diagnostic settings now" />
          <Radio value="configure" label="Configure diagnostic settings now" />
        </RadioGroup>
      </FormRow>
    </FormSection>
  );

  const openaiTab = (
    <FormSection title="Azure OpenAI">
      <FormRow label="Enable Azure OpenAI"><Checkbox checked={f.openai} onChange={(_, d) => setF((x) => ({ ...x, openai: !!d.checked }))} aria-label="Enable Azure OpenAI" /></FormRow>
      {f.openai && <NotSimulatedContainer title="Azure OpenAI resource" feature="Provisioning an Azure OpenAI resource and wiring its connection string" />}
    </FormSection>
  );

  const networking = (
    <FormSection title="Networking">
      <FormRow label="Enable public access"><Switch checked={f.publicAccess} onChange={(_, d) => setF((x) => ({ ...x, publicAccess: d.checked }))} label={f.publicAccess ? "On" : "Off"} /></FormRow>
      <FormRow label="Enable virtual network integration">
        <Switch checked={f.vnetIntegration} onChange={(_, d) => setF((x) => ({ ...x, vnetIntegration: d.checked }))} label={f.vnetIntegration ? "On" : "Off"} />
      </FormRow>
      {f.vnetIntegration && <NotSimulatedContainer title="Virtual network integration" feature="Regional VNet integration for Function Apps" />}
    </FormSection>
  );

  const monitoring = (
    <FormSection title="Application Insights">
      <FormRow label="Enable Application Insights">
        <RadioGroup value={f.appInsights} onChange={set("appInsights")} aria-label="Enable Application Insights">
          <Radio value="yes" label="Yes" /><Radio value="no" label="No" />
        </RadioGroup>
      </FormRow>
      {f.appInsights === "yes" && (
        <FormRow label="Application Insights" htmlFor="fa-ai">
          <Input id="fa-ai" value={f.appInsightsName || `${f.name || "func"}-insights`} onChange={set("appInsightsName")} aria-label="Application Insights" />
          <Link as="button" style={{ marginTop: 4, display: "block" }} onClick={() => notify.info("Vyomi records the instrumentation key on the site; no Application Insights resource is provisioned.")}>Create new</Link>
        </FormRow>
      )}
    </FormSection>
  );

  const deployment = (
    <>
      <FormSection title="GitHub Actions settings">
        <FormRow label="Continuous deployment">
          <RadioGroup value={f.cicd ? "Enable" : "Disable"} onChange={(_, d) => setF((x) => ({ ...x, cicd: d.value === "Enable" }))} aria-label="Continuous deployment">
            <Radio value="Disable" label="Disable" /><Radio value="Enable" label="Enable" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      <FormSection title="Authentication settings">
        <FormRow label="Basic authentication">
          <RadioGroup value={f.basicAuth ? "Enable" : "Disable"} onChange={(_, d) => setF((x) => ({ ...x, basicAuth: d.value === "Enable" }))} aria-label="Basic authentication">
            <Radio value="Disable" label="Disable" /><Radio value="Enable" label="Enable" />
          </RadioGroup>
        </FormRow>
      </FormSection>
      {f.cicd && <NotSimulatedContainer title="GitHub Actions" feature="Continuous deployment via GitHub Actions" />}
    </>
  );

  const authentication = (
    <FormSection title="Authentication settings">
      <FormRow label="Authentication type">
        <RadioGroup value={f.authType} onChange={set("authType")} aria-label="Authentication type">
          <Radio value="secrets" label="Secrets" /><Radio value="managed-identity" label="Managed identity" />
        </RadioGroup>
      </FormRow>
      <NotSimulatedContainer title="Microsoft Entra authentication" feature="Easy Auth (App Service Authentication) sign-in providers" />
    </FormSection>
  );

  const tags = (
    <>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={f.tags} onChange={(t) => setF((x) => ({ ...x, tags: t }))} resource="Function App" />
    </>
  );

  const body = () => api.toArmBody(f);
  const review = () => {
    const b = body();
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Details</h3>
        {dl([["Subscription", sub.displayName || sub.id], ["Resource Group", rg || "--"]])}
        <h3>Instance Details</h3>
        {dl([["Function App name", f.name || "--"], ["Runtime stack", f.runtime], ["Version", f.version], ["Region", locationLabel(f.location)], ["Zone redundancy", f.zoneRedundant ? "Enabled" : "Disabled"]])}
        <h3>Storage</h3>
        {dl([["Storage account", f.storageAccount], ["Diagnostic Settings", f.diagnostics === "configure" ? "Configure diagnostic settings now" : "Don't configure diagnostic settings now"]])}
        <h3>Monitoring</h3>
        {dl([["Application Insights", f.appInsights === "yes" ? "Yes" : "No"]])}
        <h3>Deployment</h3>
        {dl([["Continuous deployment", f.cicd ? "Enable" : "Disable"], ["Basic authentication", f.basicAuth ? "Enable" : "Disable"], ["Authentication type", f.authType === "secrets" ? "Secrets" : "Managed identity"]])}
        <h3>Tags</h3>
        {dl(Object.keys(b.tags).length ? Object.entries(b.tags).map(([k, v]) => [k, v || "(empty)"]) : [["Tags", "None"]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createFunctionApp(rg, f.name, body());
      notify.success(`Deployment of Function App '${f.name}' to resource group '${rg}' was successful.`, "Deployment succeeded");
      navigate("functionapp", rg, f.name);
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Function App (Flex Consumption)" closeHref="#/functionapp" glyph={<Glyph id="functionapp" />}
      tabs={[
        { id: "basics", label: "Basics", content: <><InfoBar>"Vyomi models one Function App resource shape regardless of hosting plan — the create succeeds the same way for every plan on the previous step."</InfoBar>{basics}</>, validate: basicsErrors },
        { id: "storage", label: "Storage", content: storage },
        { id: "openai", label: "Azure OpenAI", content: openaiTab },
        { id: "networking", label: "Networking", content: networking },
        { id: "monitoring", label: "Monitoring", content: monitoring },
        { id: "deployment", label: "Deployment", content: deployment },
        { id: "authentication", label: "Authentication", content: authentication },
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
