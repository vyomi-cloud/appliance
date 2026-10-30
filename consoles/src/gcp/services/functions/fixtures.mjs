/* UI-conformance fixtures for Cloud Run functions — native-wire setup run by
 * consoles/tests/ui-conformance.mjs. Each returns the text the page must then show
 * (liveness: proves the page is not static). Project/region match the UI's defaults
 * (project.js DEFAULT_PROJECT, api.js DEFAULT_REGION) in a fresh browser context. */
const PROJECT = "vyomi-project";
const REGION = "us-central1";
const IMAGE = "us-docker.pkg.dev/cloudrun/container/hello";
const RUNTIME_ANN = "vyomi.dev/function-runtime", ENTRY_ANN = "vyomi.dev/function-entry-point", SRC_ANN = "vyomi.dev/function-source";
const svcPath = (name) => `/v2/projects/${PROJECT}/locations/${REGION}/services/${name}`;

async function ensureFunctionService(wire, name) {
  const body = {
    template: { containers: [{ image: "vyomi.dev/function-source/node-js-22:latest" }] },
    annotations: { [RUNTIME_ANN]: "Node.js 22", [ENTRY_ANN]: "handler", [SRC_ANN]: "exports.handler = (event) => event;" },
  };
  await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/services?serviceId=${name}`, { svc: null, body }).catch(() => {});
}

export default {
  "fn-service": async (wire) => { await ensureFunctionService(wire, "uic-function"); return "uic-function"; },
  "live-service": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/services?serviceId=${uniq}`, { svc: null, body: { template: { containers: [{ image: IMAGE }] } } });
    return uniq;
  },
  "live-function-detail": async (wire, uniq) => {
    await ensureFunctionService(wire, "uic-function");
    const svc = await wire("GET", svcPath("uic-function"), { svc: null }).catch(() => ({}));
    const annotations = { ...(svc.annotations || {}), [ENTRY_ANN]: uniq };
    await wire("PATCH", `${svcPath("uic-function")}?updateMask=annotations`, { svc: null, body: { annotations } });
    return uniq;
  },
  "live-function-source": async (wire, uniq) => {
    await ensureFunctionService(wire, "uic-function");
    const svc = await wire("GET", svcPath("uic-function"), { svc: null }).catch(() => ({}));
    const annotations = { ...(svc.annotations || {}), [SRC_ANN]: `// ${uniq}\nexports.handler = (event) => event;` };
    await wire("PATCH", `${svcPath("uic-function")}?updateMask=annotations`, { svc: null, body: { annotations } });
    return uniq;
  },
  "live-job": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/jobs?jobId=${uniq}`, { svc: null, body: { template: { template: { containers: [{ image: IMAGE }] } } } });
    return uniq;
  },
  "live-workerpool": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/workerPools?workerPoolId=${uniq}`, { svc: null, body: { template: { containers: [{ image: IMAGE }] } } });
    return uniq;
  },
  "live-domain-mapping": async (wire, uniq) => {
    await ensureFunctionService(wire, "uic-function");
    const domain = `${uniq}.example.com`;
    await wire("POST", `/apis/domains.cloudrun.com/v1/namespaces/${PROJECT}/domainmappings`, { svc: null, body: { metadata: { name: domain }, spec: { routeName: "uic-function" } } });
    return domain;
  },
};
