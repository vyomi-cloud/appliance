/* Azure AI Search (Microsoft.Search/searchServices): thin ARM adapter over core/azure_search_core.py. The management
 * plane and the index / indexer / data source operations ride the same native ARM wire (api-version 2023-11-01). */
import { arm, armList, rgPath, subPath } from "../../kit/az08.js";
import { parseId } from "../../kit/arm.js";

export const V = "2023-11-01";
export const SKUS = ["free", "basic", "standard", "standard2", "standard3", "storage_optimized_l1", "storage_optimized_l2"];
const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });
const base = (rg, name) => `${rgPath(rg)}/providers/Microsoft.Search/searchServices/${encodeURIComponent(name)}`;
const e = encodeURIComponent;

export const listServices = async () => (await armList(`${subPath()}/providers/Microsoft.Search/searchServices`, { "api-version": V })).map(shape);
export const getService = async (rg, name) => shape(await arm("GET", base(rg, name), undefined, {}, V));
export const putService = (rg, name, body) => arm("PUT", base(rg, name), body, {}, V);
export const deleteService = (rg, name) => arm("DELETE", base(rg, name), undefined, {}, V);
export const adminKeys = (rg, name) => arm("POST", `${base(rg, name)}/listAdminKeys`, {}, {}, V);
export const regenKey = (rg, name, which) => arm("POST", `${base(rg, name)}/regenerateAdminKey/${which}`, {}, {}, V);
export const queryKeys = async (rg, name) => (await arm("POST", `${base(rg, name)}/listQueryKeys`, {}, {}, V)).value || [];
export const createQueryKey = (rg, name, keyName) => arm("POST", `${base(rg, name)}/createQueryKey/${e(keyName)}`, {}, {}, V);
export const deleteQueryKey = (rg, name, key) => arm("DELETE", `${base(rg, name)}/deleteQueryKey/${e(key)}`, undefined, {}, V);
export const stats = (rg, name) => arm("GET", `${base(rg, name)}/stats`, undefined, {}, V);

const coll = (kind) => ({
  list: async (rg, name) => (await arm("GET", `${base(rg, name)}/${kind}`, undefined, {}, V)).value || [],
  put: (rg, name, item, body) => arm("PUT", `${base(rg, name)}/${kind}/${e(item)}`, body, {}, V),
  remove: (rg, name, item) => arm("DELETE", `${base(rg, name)}/${kind}/${e(item)}`, undefined, {}, V),
});
export const indexes = coll("indexes");
export const datasources = coll("datasources");
export const indexers = coll("indexers");
export const skillsets = coll("skillsets");
export const indexCount = (rg, name, ix) => arm("GET", `${base(rg, name)}/indexes/${e(ix)}/docs/count`, undefined, {}, V);
export const searchDocs = (rg, name, ix, body) => arm("POST", `${base(rg, name)}/indexes/${e(ix)}/docs/search`, body, {}, V);
export const indexDocs = (rg, name, ix, value) => arm("POST", `${base(rg, name)}/indexes/${e(ix)}/docs/index`, { value }, {}, V);
export const runIndexer = (rg, name, ixr) => arm("POST", `${base(rg, name)}/indexers/${e(ixr)}/run`, {}, {}, V);
export const indexerStatus = (rg, name, ixr) => arm("GET", `${base(rg, name)}/indexers/${e(ixr)}/status`, undefined, {}, V);

/* RAG Studio: Vyomi inspect extension on the same ARM wire (core/azure_search_core.inspect_index): chunk list + per-stage retrieve trace. */
export const inspectChunks = (rg, name, ix, vectors = false) => arm("GET", `${base(rg, name)}/indexes/${e(ix)}/chunks`, undefined, vectors ? { vectors: "true" } : {}, V);
export const inspectTrace = (rg, name, ix, body) => arm("POST", `${base(rg, name)}/indexes/${e(ix)}/retrieve-trace`, body, {}, V);
export const resetIndexer = (rg, name, ixr) => arm("POST", `${base(rg, name)}/indexers/${e(ixr)}/reset`, {}, {}, V);
/* Azure OpenAI through the ARM proxy (account/openai/deployments/{d}/chat/completions) - chat "on your data" included. */
export const OPENAI_V = "2024-10-21";
export const openaiChat = (accountId, deployment, body) => arm("POST", `${accountId}/openai/deployments/${e(deployment)}/chat/completions`, body, {}, OPENAI_V);
export const listStorageAccounts = async () => (await armList(`${subPath()}/providers/Microsoft.Storage/storageAccounts`, { "api-version": "2023-01-01" }));
export const listOpenAiAccounts = async () => (await armList(`${subPath()}/providers/Microsoft.CognitiveServices/accounts`, { "api-version": "2023-05-01" })).filter((a) => a.kind === "OpenAI");
export const listDeployments = async (accountId) => (await armList(`${accountId}/deployments`, { "api-version": "2023-05-01" }));
