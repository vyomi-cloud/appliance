/* Container registries over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ContainerRegistry/registries/{name}
 *                  + the nested Microsoft.ContainerRegistry/registries/{name}/webhooks/{name} extension type
 *                    (generic ARM child-resource CRUD — core/azure_arm_core.py needs no extra
 *                    wiring for it, only the top-level "registries" type is in the catalog)
 *                  + POST .../listCredentials / .../regenerateCredential (admin user credentials)
 *   Data plane:    the registry's own host (`{name}.azurecr.io`) — the OCI/Docker Registry v2
 *                  read API + the ACR REST extension (`/acr/v1/...`) the portal's Repositories
 *                  blade and `az acr repository` use (core/azure_acr_core.py). */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.ContainerRegistry", "registries", "2023-07-01");
const LOCK_API_VERSION = "2020-05-01";

const shape = (r) => ({ ...r, resourceGroup: parseId(r.id).resourceGroup });

export const listRegistries = async () => (await ARM.list()).map(shape);
export const getRegistry = async (rg, name) => shape(await ARM.get(rg, name));
export const createRegistry = (rg, name, body) => ARM.put(rg, name, body);
export const updateRegistry = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteRegistry = (rg, name) => ARM.remove(rg, name);

export const loginServer = (name) => `${(name || "").toLowerCase()}.azurecr.io`;
export const skuLabel = (sku) => sku?.name || "Standard";

// ── Admin user credentials (listCredentials / regenerateCredential ARM actions) ────────
export const listCredentials = (rg, name) => ARM.action(rg, name, "listCredentials");
export const regenerateCredential = (rg, name, passwordName) => ARM.action(rg, name, "regenerateCredential", { name: passwordName });

// ── Webhooks (Microsoft.ContainerRegistry/registries/webhooks, generic nested ARM type) ─
const webhookPath = (rg, name, whName) => `${ARM.path(rg, name)}/webhooks${whName ? `/${encodeURIComponent(whName)}` : ""}`;

export const listWebhooks = async (rg, name) => (await restJson("GET", webhookPath(rg, name), { query: { "api-version": ARM.apiVersion } })).value || [];
export const putWebhook = (rg, name, whName, body) => restJson("PUT", webhookPath(rg, name, whName), { query: { "api-version": ARM.apiVersion }, body });
export const deleteWebhook = (rg, name, whName) => restJson("DELETE", webhookPath(rg, name, whName), { query: { "api-version": ARM.apiVersion } });

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this registry) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Repositories / tags data plane (OCI v2 reads + the ACR v1 REST extension) ──────────
const acr = (method, path) => restJson(method, path);

export const listRepositories = async () => (await acr("GET", "/acr/v1/_catalog")).repositories || [];
export const getRepository = (repo) => acr("GET", `/acr/v1/${repo}`);
export const deleteRepository = (repo) => acr("DELETE", `/acr/v1/${repo}`);
export const listTags = async (repo) => (await acr("GET", `/acr/v1/${repo}/_tags`)).tags || [];
export const deleteTag = (repo, tag) => acr("DELETE", `/acr/v1/${repo}/_tags/${encodeURIComponent(tag)}`);

// ── create-registry form model → ARM body ───────────────────────────────────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    sku: { name: f.pricingPlan },
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      adminUserEnabled: false,
      publicNetworkAccess: f.connectivity === "Private access" ? "Disabled" : "Enabled",
      zoneRedundancy: f.availabilityZones ? "Enabled" : "Disabled",
      encryption: { status: f.customerManagedKey ? "enabled" : "disabled" },
    },
  };
}
