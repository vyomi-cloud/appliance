/* API Gateway over the native wire — v1 REST control plane (`/restapis`, `/apikeys`,
 * `/usageplans`, `/clientcertificates`, `/account`) and v2 HTTP/WebSocket control plane
 * (`/v2/...`). Both are plain REST+JSON; SigV4 credential scope ("apigateway") is what
 * routes the account-level v1 paths that don't carry a distinguishing path segment. */
import { awsRest } from "../../../common/wire.js";

const v1 = (method, path, opts) => awsRest("apigateway", method, path, opts);
const v2 = (method, path, opts) => awsRest("apigateway", method, `/v2${path}`, opts);
const patch = (ops) => ({ patchOperations: ops });
const PP = (op, path, value) => ({ op, path, value });

// ── v1: RestApi ──────────────────────────────────────────────────────────────
export const createRestApi = (input) => v1("POST", "/restapis", { body: input });
export const listRestApis = () => v1("GET", "/restapis").then((r) => r.item || []);
export const getRestApi = (id) => v1("GET", `/restapis/${id}`);
export const updateRestApi = (id, ops) => v1("PATCH", `/restapis/${id}`, { body: patch(ops) });
export const deleteRestApi = (id) => v1("DELETE", `/restapis/${id}`);

/** Resolve a route param that may be either a REST API id or its (non-unique) name —
 * detail routes are id-keyed, but a fixed display name is handy for deep links. */
export async function resolveRestApi(idOrName) {
  try { return await getRestApi(idOrName); }
  catch {
    const byName = (await listRestApis()).find((a) => a.name === idOrName);
    if (!byName) throw new Error(`No REST API "${idOrName}"`);
    return byName;
  }
}

// ── v1: Resource ─────────────────────────────────────────────────────────────
export const listResources = (apiId) => v1("GET", `/restapis/${apiId}/resources`).then((r) => r.item || []);
export const getResource = (apiId, resId) => v1("GET", `/restapis/${apiId}/resources/${resId}`);
export const createResource = (apiId, parentId, pathPart) =>
  v1("POST", `/restapis/${apiId}/resources/${parentId}`, { body: { pathPart } });
export const deleteResource = (apiId, resId) => v1("DELETE", `/restapis/${apiId}/resources/${resId}`);

// ── v1: Method / Integration ──────────────────────────────────────────────────
export const putMethod = (apiId, resId, httpMethod, input) =>
  v1("PUT", `/restapis/${apiId}/resources/${resId}/methods/${httpMethod}`, { body: input });
export const getMethod = (apiId, resId, httpMethod) =>
  v1("GET", `/restapis/${apiId}/resources/${resId}/methods/${httpMethod}`);
export const deleteMethod = (apiId, resId, httpMethod) =>
  v1("DELETE", `/restapis/${apiId}/resources/${resId}/methods/${httpMethod}`);
export const putIntegration = (apiId, resId, httpMethod, input) =>
  v1("PUT", `/restapis/${apiId}/resources/${resId}/methods/${httpMethod}/integration`, { body: input });
export const deleteIntegration = (apiId, resId, httpMethod) =>
  v1("DELETE", `/restapis/${apiId}/resources/${resId}/methods/${httpMethod}/integration`);
export const testInvokeMethod = (apiId, resId, httpMethod, input) =>
  v1("POST", `/restapis/${apiId}/resources/${resId}/methods/${httpMethod}`, { body: input });

/** Enable CORS — the console's convenience action: an OPTIONS mock method on this
 * resource plus the Access-Control-* response headers, exactly like the real console. */
export async function enableCors(apiId, resId) {
  await putMethod(apiId, resId, "OPTIONS", { authorizationType: "NONE" });
  await putIntegration(apiId, resId, "OPTIONS", { type: "MOCK", mockStatus: 200, mockBody: "" });
}

// ── v1: Deployment / Stage ────────────────────────────────────────────────────
export const createDeployment = (apiId, input) => v1("POST", `/restapis/${apiId}/deployments`, { body: input });
export const listDeployments = (apiId) => v1("GET", `/restapis/${apiId}/deployments`).then((r) => r.item || []);
export const listStages = (apiId) => v1("GET", `/restapis/${apiId}/stages`).then((r) => r.item || []);
export const getStage = (apiId, name) => v1("GET", `/restapis/${apiId}/stages/${encodeURIComponent(name)}`);
export const createStage = (apiId, input) => v1("POST", `/restapis/${apiId}/stages`, { body: input });
export const updateStage = (apiId, name, ops) => v1("PATCH", `/restapis/${apiId}/stages/${encodeURIComponent(name)}`, { body: patch(ops) });
export const deleteStage = (apiId, name) => v1("DELETE", `/restapis/${apiId}/stages/${encodeURIComponent(name)}`);
export { PP as patchOp };

// ── v1: Account ───────────────────────────────────────────────────────────────
export const getAccount = () => v1("GET", "/account");
export const updateAccount = (ops) => v1("PATCH", "/account", { body: patch(ops) });

// ── v1: ApiKey ────────────────────────────────────────────────────────────────
export const createApiKey = (input) => v1("POST", "/apikeys", { body: input });
export const listApiKeys = () => v1("GET", "/apikeys", { query: { includeValues: "true" } }).then((r) => r.item || []);
export const getApiKey = (id) => v1("GET", `/apikeys/${id}`, { query: { includeValue: "true" } });
export const updateApiKey = (id, ops) => v1("PATCH", `/apikeys/${id}`, { body: patch(ops) });
export const deleteApiKey = (id) => v1("DELETE", `/apikeys/${id}`);

// ── v1: UsagePlan / UsagePlanKey ──────────────────────────────────────────────
export const createUsagePlan = (input) => v1("POST", "/usageplans", { body: input });
export const listUsagePlans = () => v1("GET", "/usageplans").then((r) => r.item || []);
export const getUsagePlan = (id) => v1("GET", `/usageplans/${id}`);
export const updateUsagePlan = (id, ops) => v1("PATCH", `/usageplans/${id}`, { body: patch(ops) });
export const deleteUsagePlan = (id) => v1("DELETE", `/usageplans/${id}`);
export const listUsagePlanKeys = (id) => v1("GET", `/usageplans/${id}/keys`).then((r) => r.item || []);
export const createUsagePlanKey = (id, keyId) => v1("POST", `/usageplans/${id}/keys`, { body: { keyId, keyType: "API_KEY" } });
export const deleteUsagePlanKey = (id, keyId) => v1("DELETE", `/usageplans/${id}/keys/${keyId}`);

// ── v1: ClientCertificate ─────────────────────────────────────────────────────
export const generateClientCertificate = (input) => v1("POST", "/clientcertificates", { body: input });
export const listClientCertificates = () => v1("GET", "/clientcertificates").then((r) => r.item || []);
export const getClientCertificate = (id) => v1("GET", `/clientcertificates/${id}`);
export const updateClientCertificate = (id, ops) => v1("PATCH", `/clientcertificates/${id}`, { body: patch(ops) });
export const deleteClientCertificate = (id) => v1("DELETE", `/clientcertificates/${id}`);

// ── v2: Api ───────────────────────────────────────────────────────────────────
export const createApiV2 = (input) => v2("POST", "/apis", { body: input });
export const listApisV2 = () => v2("GET", "/apis").then((r) => r.items || []);
export const getApiV2 = (id) => v2("GET", `/apis/${id}`);
export const updateApiV2 = (id, input) => v2("PATCH", `/apis/${id}`, { body: input });
export const deleteApiV2 = (id) => v2("DELETE", `/apis/${id}`);

/** Resolve a route param that may be either an Api id or its (non-unique) name. */
export async function resolveApiV2(idOrName) {
  try { return await getApiV2(idOrName); }
  catch {
    const byName = (await listApisV2()).find((a) => a.name === idOrName);
    if (!byName) throw new Error(`No API "${idOrName}"`);
    return byName;
  }
}

// ── v2: Route / Integration / Authorizer / Model / Deployment ───────────────────
const child = (plural) => ({
  create: (apiId, input) => v2("POST", `/apis/${apiId}/${plural}`, { body: input }),
  list: (apiId) => v2("GET", `/apis/${apiId}/${plural}`).then((r) => r.items || []),
  get: (apiId, id) => v2("GET", `/apis/${apiId}/${plural}/${id}`),
  update: (apiId, id, input) => v2("PATCH", `/apis/${apiId}/${plural}/${id}`, { body: input }),
  remove: (apiId, id) => v2("DELETE", `/apis/${apiId}/${plural}/${id}`),
});
export const routesV2 = child("routes");
export const integrationsV2 = child("integrations");
export const authorizersV2 = child("authorizers");
export const modelsV2 = child("models");
export const deploymentsV2 = child("deployments");

// ── v2: Stage ─────────────────────────────────────────────────────────────────
export const listStagesV2 = (apiId) => v2("GET", `/apis/${apiId}/stages`).then((r) => r.items || []);
export const getStageV2 = (apiId, name) => v2("GET", `/apis/${apiId}/stages/${encodeURIComponent(name)}`);
export const createStageV2 = (apiId, input) => v2("POST", `/apis/${apiId}/stages`, { body: input });
export const updateStageV2 = (apiId, name, input) => v2("PATCH", `/apis/${apiId}/stages/${encodeURIComponent(name)}`, { body: input });
export const deleteStageV2 = (apiId, name) => v2("DELETE", `/apis/${apiId}/stages/${encodeURIComponent(name)}`);

// ── v2: Tags ──────────────────────────────────────────────────────────────────
export const getTagsV2 = (arn) => v2("GET", `/tags/${encodeURIComponent(arn)}`).then((r) => r.tags || {});
export const tagResourceV2 = (arn, tags) => v2("POST", `/tags/${encodeURIComponent(arn)}`, { body: { tags } });

// ── v2: DomainName / ApiMapping ───────────────────────────────────────────────
export const createDomainNameV2 = (input) => v2("POST", "/domainnames", { body: input });
export const listDomainNamesV2 = () => v2("GET", "/domainnames").then((r) => r.items || []);
export const getDomainNameV2 = (name) => v2("GET", `/domainnames/${encodeURIComponent(name)}`);
export const deleteDomainNameV2 = (name) => v2("DELETE", `/domainnames/${encodeURIComponent(name)}`);
export const createApiMappingV2 = (domain, input) => v2("POST", `/domainnames/${encodeURIComponent(domain)}/apimappings`, { body: input });
export const listApiMappingsV2 = (domain) => v2("GET", `/domainnames/${encodeURIComponent(domain)}/apimappings`).then((r) => r.items || []);

// ── v2: VpcLink ───────────────────────────────────────────────────────────────
export const createVpcLinkV2 = (input) => v2("POST", "/vpclinks", { body: input });
export const listVpcLinksV2 = () => v2("GET", "/vpclinks").then((r) => r.items || []);
export const deleteVpcLinkV2 = (id) => v2("DELETE", `/vpclinks/${id}`);

// ── v2: DomainNameAccessAssociation ───────────────────────────────────────────
export const createDomainAccessAssociationV2 = (input) => v2("POST", "/domainnameaccessassociations", { body: input });
export const listDomainAccessAssociationsV2 = (domainNameArn) =>
  v2("GET", "/domainnameaccessassociations", { query: domainNameArn ? { domainNameArn } : {} }).then((r) => r.items || []);
export const deleteDomainAccessAssociationV2 = (arn) => v2("DELETE", `/domainnameaccessassociations/${encodeURIComponent(arn)}`);

// ── v2: Portal / PortalProduct (developer portal control plane) ─────────────
export const createPortal = (input) => v2("POST", "/portals", { body: input });
export const listPortals = () => v2("GET", "/portals").then((r) => r.items || []);
export const getPortal = (id) => v2("GET", `/portals/${id}`);
export const updatePortal = (id, input) => v2("PATCH", `/portals/${id}`, { body: input });
export const deletePortal = (id) => v2("DELETE", `/portals/${id}`);
export const publishPortal = (id, description) => v2("POST", `/portals/${id}/publish`, { body: { description } });
export const disablePortal = (id) => v2("DELETE", `/portals/${id}/publish`);
export const previewPortal = (id) => v2("POST", `/portals/${id}/preview`);

export const createPortalProduct = (input) => v2("POST", "/portalproducts", { body: input });
export const listPortalProducts = () => v2("GET", "/portalproducts").then((r) => r.items || []);
export const getPortalProduct = (id) => v2("GET", `/portalproducts/${id}`);
export const updatePortalProduct = (id, input) => v2("PATCH", `/portalproducts/${id}`, { body: input });
export const deletePortalProduct = (id) => v2("DELETE", `/portalproducts/${id}`);

// ── cross-service: Lambda functions (for the method-integration picker) ──────
export async function listLambdaFunctions() {
  const r = await awsRest("lambda", "GET", "/2015-03-31/functions");
  return r.Functions || [];
}

// ── combined "APIs" list: v1 REST + v2 HTTP/WebSocket in one shape ────────────
export async function listAllApis() {
  const [rest, v2s] = await Promise.all([listRestApis(), listApisV2()]);
  return [
    ...rest.map((a) => ({
      id: a.id, name: a.name, description: a.description || "", protocol: "REST",
      endpointType: (a.endpointConfiguration?.types || ["EDGE"])[0],
      securityPolicy: "TLS 1.2", created: a.createdDate, kind: "rest",
    })),
    ...v2s.map((a) => ({
      id: a.apiId, name: a.name, description: a.description || "",
      protocol: a.protocolType === "WEBSOCKET" ? "WebSocket" : "HTTP",
      endpointType: "Regional", securityPolicy: "TLS 1.2", created: a.createdDate,
      kind: a.protocolType === "WEBSOCKET" ? "websocket" : "http",
    })),
  ];
}
