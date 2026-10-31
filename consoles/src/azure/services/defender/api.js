/* Microsoft Defender for Cloud over the native wire — the Microsoft.Security ARM namespace,
 * served by the shared ARM engine on every substrate (core/azure_security_core.py):
 *   pricings                       GET / PUT  /subscriptions/{sub}/providers/Microsoft.Security/pricings[/{plan}]
 *   assessments                    GET        {scope}/providers/Microsoft.Security/assessments[/{name}]
 *   subAssessments                 GET        {assessment id}/subAssessments
 *   secureScores / …Controls       GET        /subscriptions/{sub}/providers/Microsoft.Security/secureScores[/ascScore/secureScoreControls]
 * Everything is computed live from the ARM state; the Kubernetes recommendations come from the
 * cluster's Kubescape scan (Vyomi adds `vyomiKubernetesScanners` to the assessments list so the
 * console can say whether/when/how each cluster was scanned). */
import { restJson } from "../../../common/wire.js";
import { getSubscription, parseId } from "../../kit/arm.js";

const SEC = () => `/subscriptions/${getSubscription()}/providers/Microsoft.Security`;
export const API = { pricings: "2024-01-01", assessments: "2021-06-01", sub: "2019-01-01-preview", scores: "2020-01-01" };

export const listPricings = async () =>
  (await restJson("GET", `${SEC()}/pricings`, { query: { "api-version": API.pricings } })).value || [];
export const setPricing = (plan, pricingTier) =>
  restJson("PUT", `${SEC()}/pricings/${plan}`, { query: { "api-version": API.pricings }, body: { properties: { pricingTier } } });

/** {value: [assessment…], vyomiKubernetesScanners: […]} at subscription scope, or scoped to one resource. */
export const listAssessments = async (resourceId) => {
  const base = resourceId ? `${resourceId}/providers/Microsoft.Security` : SEC();
  const r = await restJson("GET", `${base}/assessments`, { query: { "api-version": API.assessments } });
  return { value: r.value || [], scanners: r.vyomiKubernetesScanners || [] };
};
export const listSubAssessments = async (assessmentId) =>
  (await restJson("GET", `${assessmentId}/subAssessments`, { query: { "api-version": API.sub } })).value || [];
export const getSecureScore = async () =>
  (await restJson("GET", `${SEC()}/secureScores/ascScore`, { query: { "api-version": API.scores } }));
export const listSecureScoreControls = async () =>
  (await restJson("GET", `${SEC()}/secureScores/ascScore/secureScoreControls`, { query: { "api-version": API.scores, "$expand": "definition" } })).value || [];
export const listResources = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/resources`, { query: { "api-version": "2021-04-01" } })).value || [];

const SEV = { High: 3, Medium: 2, Low: 1 };
export const sevRank = (s) => SEV[s] || 0;

/** Group per-resource assessments into recommendation rows (the portal's Recommendations list). */
export function groupRecommendations(assessments) {
  const by = new Map();
  for (const a of assessments) {
    const p = a.properties;
    const k = a.name;
    if (!by.has(k)) by.set(k, { name: k, displayName: p.displayName, severity: p.metadata?.severity, metadata: p.metadata,
      control: p.metadata?.securityControl, kubescape: p.metadata?.kubescapeControlId, items: [] });
    by.get(k).items.push(a);
  }
  return [...by.values()].map((r) => {
    const count = (c) => r.items.filter((a) => a.properties.status.code === c).length;
    const unhealthy = count("Unhealthy"), healthy = count("Healthy"), na = count("NotApplicable");
    const types = [...new Set(r.items.map((a) => resourceType(a.properties.resourceDetails.Id)))];
    return { ...r, unhealthy, healthy, na, status: unhealthy ? "Unhealthy" : healthy ? "Healthy" : "Not applicable", resourceTypes: types };
  }).sort((a, b) => (b.unhealthy > 0) - (a.unhealthy > 0) || sevRank(b.severity) - sevRank(a.severity) || a.displayName.localeCompare(b.displayName));
}

const TYPE_LABEL = {
  "microsoft.storage/storageaccounts": "Storage account", "microsoft.network/networksecuritygroups": "Network security group",
  "microsoft.sql/servers": "SQL server", "microsoft.sql/servers/databases": "SQL database", "microsoft.keyvault/vaults": "Key vault",
  "microsoft.compute/virtualmachines": "Virtual machine", "microsoft.web/sites": "App Service", "microsoft.containerregistry/registries": "Container registry",
  "microsoft.apimanagement/service": "API Management service", "microsoft.containerservice/managedclusters": "Kubernetes service",
};
export function resourceType(id = "") {
  const p = id.split("/").filter(Boolean);
  const i = p.findIndex((x) => x.toLowerCase() === "providers");
  if (i < 0) return "";
  const ns = p[i + 1], parts = [ns];
  for (let j = i + 2; j < p.length; j += 2) parts.push(p[j]);
  return parts.join("/");
}
export const typeLabel = (t) => TYPE_LABEL[String(t).toLowerCase()] || t;
export const resourceName = (id) => parseId(id).name;
export const resourceGroup = (id) => parseId(id).resourceGroup;

/** Portal deep link to a resource's own blade (where Vyomi has one). */
export function resourceHref(id = "") {
  const t = resourceType(id).toLowerCase(), rg = encodeURIComponent(resourceGroup(id) || ""), n = encodeURIComponent(resourceName(id) || "");
  const map = {
    "microsoft.storage/storageaccounts": `#/storage/${rg}/${n}`, "microsoft.network/networksecuritygroups": `#/nsgs/${rg}/${n}`,
    "microsoft.keyvault/vaults": `#/keyvaults/${rg}/${n}`, "microsoft.compute/virtualmachines": `#/vms/${rg}/${n}`,
    "microsoft.containerregistry/registries": `#/acr/${rg}/${n}`, "microsoft.apimanagement/service": `#/apim/${rg}/${n}`,
    "microsoft.containerservice/managedclusters": `#/aks/${rg}/${n}`,
  };
  return map[t] || null;
}

export const PLAN_LABEL = {
  VirtualMachines: "Servers", SqlServers: "Azure SQL Databases", AppServices: "App Service", StorageAccounts: "Storage",
  SqlServerVirtualMachines: "SQL servers on machines", KeyVaults: "Key Vault", Arm: "Resource Manager",
  OpenSourceRelationalDatabases: "Open-source relational databases", CosmosDbs: "Azure Cosmos DB", Containers: "Containers",
  CloudPosture: "Defender CSPM", Api: "APIs", AI: "AI services",
};
