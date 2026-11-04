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
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { listAllSubnets } from "../../kit/PrivateEndpoints.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { setPricing } from "../defender/api.js";
import * as sqlApi from "../sql/api.js";
import * as cosmosApi from "../cosmos/api.js";
import { Components } from "../../kit/AppInsights.jsx";

const SCOPES = [["TenantReuse", "Tenant Reuse"], ["SubscriptionReuse", "Subscription Reuse"], ["ResourceGroupReuse", "Resource Group Reuse"], ["NoReuse", "No Reuse"]];
const hostFor = (name, scope, region) => (scope ? `${name || "<name>"}-<hash>.${region.toLowerCase().replace(/[^a-z0-9]/g, "")}-01.azurewebsites.net` : `${name || "<name>"}.azurewebsites.net`);

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
    createDatabase: false, dbEngine: "sql", dbServer: "", dbName: "", dbLogin: "sqladmin", dbPassword: "",
    secureHost: false, hostScope: "TenantReuse",
    containerImageSource: "Quickstart", containerImage: "",
    continuousDeployment: "Disable", basicAuth: "Disable", ghRepo: "", ghBranch: "main", ghToken: "",
    publicAccess: true, networkInjection: false,
    appInsights: "No", aiName: "", defender: false,
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
    else if (!f.secureHost && (existing.data || []).some((a) => a.name === f.name)) e.push(`The app name '${f.name}' is not available. '${f.name}.azurewebsites.net' is taken.`);
    else if (f.secureHost && f.name.length > 40) e.push("With a secure unique default hostname the app name must be 40 characters or fewer.");
    if (f.createDatabase) {
      if (!f.dbServer || !f.dbName) e.push("Database server and database names are required.");
      if (f.dbEngine === "sql" && (!f.dbLogin || f.dbPassword.length < 8)) e.push("SQL admin login is required and the password must be at least 8 characters.");
    }
    if (f.planChoice === "__new" && !f.newPlanName) e.push("New App Service Plan name is required.");
    return e;
  };
  const nameError = f.name && !NAME_RE.test(f.name) ? "App name must be 2-60 characters, letters, digits or hyphens." :
    f.name && !f.secureHost && (existing.data || []).some((a) => a.name === f.name) ? `The app name '${f.name}' is not available.` : null;

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
        <CapabilityContainer id="azure.appservices.webapp.securehostname" title="Secure unique default hostname on.">
          <FormRow label="Secure unique default hostname on.">
            <Checkbox checked={f.secureHost} onChange={chk("secureHost")} aria-label="Secure unique default hostname on." label="Enabled" />
          </FormRow>
          {f.secureHost && (
            <FormRow label="Domain name label scope" htmlFor="wa-scope">
              <Select id="wa-scope" value={f.hostScope} onChange={set("hostScope")} aria-label="Domain name label scope">
                {SCOPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
            </FormRow>
          )}
          <div data-testid="default-hostname" style={{ fontSize: 12, marginBottom: 8 }}>Default hostname: <code>{hostFor(f.name, f.secureHost && f.hostScope, regionLabel)}</code></div>
        </CapabilityContainer>
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
    <CapabilityContainer id="azure.appservices.webapp.createdatabase" title="Database">
      <FormSection title="Database">
        <FormRow label="Create a database">
          <Checkbox checked={f.createDatabase} onChange={chk("createDatabase")} aria-label="Create a database" label="Enabled" />
        </FormRow>
        {f.createDatabase && (
          <>
            <FormRow label="Engine" required>
              <Select value={f.dbEngine} onChange={set("dbEngine")} aria-label="Database engine">
                <option value="sql">SQL Server (Azure SQL Database)</option>
                <option value="cosmos">Azure Cosmos DB for NoSQL</option>
              </Select>
            </FormRow>
            <FormRow label={f.dbEngine === "sql" ? "Server name" : "Account name"} required><Input value={f.dbServer} onChange={set("dbServer")} aria-label="Database server name" /></FormRow>
            <FormRow label="Database name" required><Input value={f.dbName} onChange={set("dbName")} aria-label="Database name" /></FormRow>
            {f.dbEngine === "sql" && (
              <>
                <FormRow label="Admin username" required><Input value={f.dbLogin} onChange={set("dbLogin")} aria-label="Database admin username" /></FormRow>
                <FormRow label="Admin password" required><Input type="password" value={f.dbPassword} onChange={set("dbPassword")} aria-label="Database admin password" /></FormRow>
              </>
            )}
            <InfoBar title="Connection string">The wizard creates the database resource, then adds its connection string to the app (Connection strings, and the AZURE_SQL_CONNECTIONSTRING / AZURE_COSMOS_CONNECTIONSTRING app setting).</InfoBar>
          </>
        )}
      </FormSection>
    </CapabilityContainer>
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
      {f.continuousDeployment === "Enable" && (
        <FormSection title="GitHub Actions details" description="Vyomi generates the workflow for the chosen runtime stack and, when you supply a GitHub personal access token (repo + workflow scope), commits it to the repository. The pipeline itself runs on GitHub.">
          <FormRow label="Repository URL" required htmlFor="wa-gh-repo"><Input id="wa-gh-repo" value={f.ghRepo} onChange={set("ghRepo")} placeholder="https://github.com/org/repo" aria-label="GitHub repository URL" /></FormRow>
          <FormRow label="Branch" required htmlFor="wa-gh-branch"><Input id="wa-gh-branch" value={f.ghBranch} onChange={set("ghBranch")} aria-label="GitHub branch" /></FormRow>
          <FormRow label="Personal access token" htmlFor="wa-gh-token"><Input id="wa-gh-token" type="password" value={f.ghToken} onChange={set("ghToken")} placeholder="optional: needed to commit the workflow file" aria-label="GitHub personal access token" /></FormRow>
        </FormSection>
      )}

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

  const subnets = useAsync(listAllSubnets, []);
  const networking = (
    <FormSection title="Networking">
      <FormRow label="Enable public access">
        <Checkbox checked={f.publicAccess} onChange={chk("publicAccess")} aria-label="Enable public access" />
      </FormRow>
      <CapabilityContainer id="azure.appservices.webapp.networking" title="Network injection">
        <FormRow label="Enable network injection">
          <Checkbox checked={!!f.inject} onChange={chk("inject")} aria-label="Enable network injection" />
        </FormRow>
        {f.inject && (
          <FormRow label="Virtual network integration subnet" htmlFor="app-inject-subnet">
            <Select id="app-inject-subnet" value={f.injectSubnet || subnets.data?.[0]?.id || ""} onChange={(_, d) => setF((x) => ({ ...x, injectSubnet: d.value }))} aria-label="Integration subnet">
              {(subnets.data || []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </Select>
            <div style={{ fontSize: 12 }}>The subnet must be delegated to Microsoft.Web/serverFarms, at least a /28, in the app's region, and the plan must be Basic or higher.</div>
          </FormRow>
        )}
      </CapabilityContainer>
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
      {f.appInsights === "Yes" && (
        <CapabilityContainer id="azure.appservices.applicationinsights" title="Application Insights resource">
          <FormRow label="Name" htmlFor="wa-ai"><Input id="wa-ai" value={f.aiName} placeholder={f.name ? `${f.name}-ai` : "Application Insights name"} onChange={set("aiName")} aria-label="Application Insights name" /></FormRow>
          <FormRow label="Region"><Input value={regionLabel} readOnly aria-label="Application Insights region" /></FormRow>
          <InfoBar title="Linked at creation">A real Microsoft.Insights/components resource is created in this region and the app's APPLICATIONINSIGHTS_CONNECTION_STRING setting is set to it.</InfoBar>
        </CapabilityContainer>
      )}
      <FormSection title="Microsoft Defender for App Service">
        <CapabilityContainer id="azure.defender.plans" title="Defender for App Service">
          <FormRow label="Enable Microsoft Defender for App Service">
            <RadioGroup layout="horizontal" value={f.defender ? "Yes" : "No"} onChange={(_, d) => setF((x) => ({ ...x, defender: d.value === "Yes" }))} aria-label="Enable Microsoft Defender for App Service">
              <Radio value="Yes" label="Enable" />
              <Radio value="No" label="Not now" />
            </RadioGroup>
          </FormRow>
          <InfoBar title="Subscription-wide plan">Like Azure, this turns the Defender for App Service plan on for the whole subscription when the app is created (Defender for Cloud > Environment settings).</InfoBar>
        </CapabilityContainer>
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
        {dl([["Name", f.name || "--"], ["Default hostname", hostFor(f.name, f.secureHost && f.hostScope, regionLabel)], ["Publish", f.publish], ["Runtime stack", api.RUNTIMES.find(([, v]) => v === f.runtimeStack)?.[0]], ["Operating System", f.os], ["Region", regionLabel]])}
        <h3>App Service Plan (New)</h3>
        {dl([["Name", f.planChoice === "__new" ? f.newPlanName || "--" : f.planChoice], ["Sku and size", f.planSku], ["Zone redundancy", f.zoneRedundant]])}
        <h3>Database</h3>
        {dl([["Create a database", f.createDatabase ? `${f.dbEngine === "sql" ? "SQL" : "Cosmos DB"} ${f.dbServer}/${f.dbName}` : "No"]])}
        <h3>Monitor + secure</h3>
        {dl([["Application Insights", f.appInsights === "Yes" ? `Yes (${f.aiName || f.name + "-ai"})` : "No"], ["Microsoft Defender for App Service", yes(f.defender)]])}
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
        properties: { serverFarmId: planId, siteConfig, ...(f.secureHost ? { autoGeneratedDomainNameLabelScope: f.hostScope } : {}), publicNetworkAccess: f.publicAccess ? "Enabled" : "Disabled",
          ...(f.inject ? { virtualNetworkSubnetId: f.injectSubnet || subnets.data?.[0]?.id } : {}) },
      });
      if (f.continuousDeployment === "Enable" && f.ghRepo) {
        await api.putSourceControl(rg, f.name, { repoUrl: f.ghRepo, branch: f.ghBranch || "main", isGitHubAction: true, ...(f.ghToken ? { vyomiAccessToken: f.ghToken } : {}), gitHubActionConfiguration: {
          codeConfiguration: { runtimeStack: (f.runtimeStack || "").split("|")[0].toLowerCase() || "python", runtimeVersion: (f.runtimeStack || "").split("|")[1] }, isLinux: f.os === "Linux" } });
      }
      const settings = {};
      const conns = {};
      if (f.createDatabase) {
        if (f.dbEngine === "sql") {
          await sqlApi.createServer(rg, f.dbServer, { location: f.location, properties: { administratorLogin: f.dbLogin, administratorLoginPassword: f.dbPassword, version: "12.0" } });
          await sqlApi.createDatabase(rg, f.dbServer, f.dbName, { location: f.location, sku: { name: "Basic" } });
          await sqlApi.putFirewallRule(rg, f.dbServer, "AllowAllWindowsAzureIps", { properties: { startIpAddress: "0.0.0.0", endIpAddress: "0.0.0.0" } });
          const cs = `Server=tcp:${f.dbServer}.database.windows.net,1433;Initial Catalog=${f.dbName};User ID=${f.dbLogin};Password=${f.dbPassword};Encrypt=True;`;
          conns[f.dbName] = { value: cs, type: "SQLAzure" }; settings.AZURE_SQL_CONNECTIONSTRING = cs;
        } else {
          await cosmosApi.createAccount(rg, f.dbServer, { location: f.location, kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: f.location, failoverPriority: 0 }] } });
          const cstr = (await cosmosApi.listConnectionStrings(rg, f.dbServer))?.connectionStrings?.[0]?.connectionString || `AccountEndpoint=${cosmosApi.accountEndpoint(f.dbServer)};`;
          conns[f.dbName] = { value: cstr, type: "DocDb" }; settings.AZURE_COSMOS_CONNECTIONSTRING = cstr;
        }
      }
      if (f.appInsights === "Yes") {
        const c = await Components.put(rg, f.aiName || `${f.name}-ai`, { location: f.location, kind: "web", properties: { Application_Type: "web", Flow_Type: "Bluefield", Request_Source: "rest" } });
        settings.APPLICATIONINSIGHTS_CONNECTION_STRING = c.properties.ConnectionString;
        settings.APPINSIGHTS_INSTRUMENTATIONKEY = c.properties.InstrumentationKey;
        settings.ApplicationInsightsAgent_EXTENSION_VERSION = "~3";
      }
      if (Object.keys(settings).length) await api.updateAppSettings(rg, f.name, { ...(await api.getAppSettings(rg, f.name)), ...settings });
      if (Object.keys(conns).length) await api.updateConnectionStrings(rg, f.name, conns);
      if (f.defender) await setPricing("AppServices", "Standard");
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
