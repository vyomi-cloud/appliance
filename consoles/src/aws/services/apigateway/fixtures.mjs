/* UI-conformance fixtures for API Gateway (native v1 REST `/restapis`, `/apikeys`,
 * `/usageplans`, `/clientcertificates` + native v2 `/v2/...`). See s3/fixtures.mjs. */
const A = { svc: "apigateway" };
const FIXED_REST_API = "uic-rest-api";
const FIXED_HTTP_API = "uic-http-api";

/** Fixed-name REST API (like s3/fixtures.mjs's "uic-bucket"): idempotent so every page
 * that needs a non-empty, real REST API can depend on it without creating duplicates. */
async function rootResourceId(wire, apiId) {
  const resources = await wire("GET", `/restapis/${apiId}/resources`, A);
  return resources.item.find((r) => r.path === "/").id;
}

async function fixedRestApi(wire) {
  const existing = (await wire("GET", "/restapis", A)).item.find((a) => a.name === FIXED_REST_API);
  if (existing) return { ...existing, rootResourceId: await rootResourceId(wire, existing.id) };
  const api = await wire("POST", "/restapis", { ...A, body: { name: FIXED_REST_API } });
  const res = await wire("POST", `/restapis/${api.id}/resources/${api.rootResourceId}`, { ...A, body: { pathPart: "ping" } });
  await wire("PUT", `/restapis/${api.id}/resources/${res.id}/methods/GET`, { ...A, body: { authorizationType: "NONE" } });
  await wire("PUT", `/restapis/${api.id}/resources/${res.id}/methods/GET/integration`, { ...A, body: { type: "MOCK", mockStatus: 200, mockBody: "pong" } });
  await wire("POST", `/restapis/${api.id}/deployments`, { ...A, body: { stageName: "prod" } });
  return api;
}

async function fixedHttpApi(wire) {
  const existing = (await wire("GET", "/v2/apis", A)).items.find((a) => a.name === FIXED_HTTP_API);
  if (existing) return existing;
  const api = await wire("POST", "/v2/apis", { ...A, body: { name: FIXED_HTTP_API, protocolType: "HTTP" } });
  await wire("POST", `/v2/apis/${api.apiId}/stages`, { ...A, body: { stageName: "$default", autoDeploy: true } });
  return api;
}

export default {
  "live-rest-api": async (wire, uniq) => {
    await wire("POST", "/restapis", { ...A, body: { name: uniq } });
    return uniq;
  },
  "apigw-rest-api": async (wire) => { await fixedRestApi(wire); },
  "live-resource-in-fixed-api": async (wire, uniq) => {
    const api = await fixedRestApi(wire);
    await wire("POST", `/restapis/${api.id}/resources/${api.rootResourceId}`, { ...A, body: { pathPart: uniq } });
    return uniq;
  },
  "live-stage-variable": async (wire, uniq) => {
    const api = await fixedRestApi(wire);
    await wire("PATCH", `/restapis/${api.id}/stages/prod`, { ...A, body: { patchOperations: [{ op: "replace", path: "/variables/live", value: uniq }] } });
    return uniq;
  },
  "apigw-http-api": async (wire) => { await fixedHttpApi(wire); },
  "live-stage-in-fixed-http-api": async (wire, uniq) => {
    const api = await fixedHttpApi(wire);
    await wire("POST", `/v2/apis/${api.apiId}/stages`, { ...A, body: { stageName: uniq, autoDeploy: false } });
    return uniq;
  },
  "live-domain-name": async (wire, uniq) => {
    const name = `${uniq}.example.com`;
    await wire("POST", "/v2/domainnames", { ...A, body: { domainName: name, domainNameConfigurations: [{ endpointType: "REGIONAL" }] } });
    return name;
  },
  "live-domain-association": async (wire, uniq) => {
    const name = `${uniq}.example.com`;
    const dom = await wire("POST", "/v2/domainnames", { ...A, body: { domainName: name } });
    const vpce = `vpce-${uniq}`;
    await wire("POST", "/v2/domainnameaccessassociations", { ...A, body: { domainNameArn: dom.domainNameArn, accessAssociationSourceType: "VPCE", accessAssociationSource: vpce } });
    return vpce;
  },
  "live-vpc-link": async (wire, uniq) => {
    await wire("POST", "/v2/vpclinks", { ...A, body: { name: uniq, subnetIds: ["subnet-0123456789abcdef0"] } });
    return uniq;
  },
  "live-usage-plan": async (wire, uniq) => {
    await wire("POST", "/usageplans", { ...A, body: { name: uniq } });
    return uniq;
  },
  "live-api-key": async (wire, uniq) => {
    await wire("POST", "/apikeys", { ...A, body: { name: uniq, value: `${uniq}0000000000000000000` } });
    return uniq;
  },
  "live-client-cert": async (wire, uniq) => {
    await wire("POST", "/clientcertificates", { ...A, body: { description: uniq } });
    return uniq;
  },
  "live-portal-product": async (wire, uniq) => {
    await wire("POST", "/v2/portalproducts", { ...A, body: { displayName: uniq } });
    return uniq;
  },
  "live-portal": async (wire, uniq) => {
    await wire("POST", "/v2/portals", { ...A, body: {
      authorization: { none: {} }, endpointConfiguration: { none: {} },
      portalContent: { displayName: uniq, theme: { customColors: { accentColor: "#0972d3" } } },
    } });
    return uniq;
  },
};
