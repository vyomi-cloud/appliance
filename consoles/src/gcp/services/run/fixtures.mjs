/* UI-conformance fixtures for Cloud Run — native-wire setup run by
 * consoles/tests/ui-conformance.mjs. Each returns the text the page must then show
 * (liveness: proves the page is not static). Project/region match the UI's defaults
 * (project.js DEFAULT_PROJECT, api.js DEFAULT_REGION) in a fresh browser context. */
const PROJECT = "vyomi-project";
const REGION = "us-central1";
const IMAGE = "us-docker.pkg.dev/cloudrun/container/hello";
const svcPath = (name) => `/v2/projects/${PROJECT}/locations/${REGION}/services/${name}`;
const jobPath = (name) => `/v2/projects/${PROJECT}/locations/${REGION}/jobs/${name}`;

async function ensureService(wire, name) {
  await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/services?serviceId=${name}`,
    { svc: null, body: { template: { containers: [{ image: IMAGE }] } } }).catch(() => {});
}
async function ensureJob(wire, name) {
  await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/jobs?jobId=${name}`,
    { svc: null, body: { template: { template: { containers: [{ image: IMAGE }] } } } }).catch(() => {});
}

export default {
  "run-service": async (wire) => { await ensureService(wire, "uic-run-service"); return "uic-run-service"; },
  "run-job": async (wire) => { await ensureJob(wire, "uic-run-job"); return "uic-run-job"; },
  "live-service": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/services?serviceId=${uniq}`, { svc: null, body: { template: { containers: [{ image: IMAGE }] } } });
    return uniq;
  },
  "live-service-detail": async (wire, uniq) => {
    await ensureService(wire, "uic-run-service");
    const svc = await wire("GET", svcPath("uic-run-service"), { svc: null }).catch(() => ({}));
    const labels = { ...(svc.labels || {}), uic: uniq };
    await wire("PATCH", `${svcPath("uic-run-service")}?updateMask=labels`, { svc: null, body: { labels } });
    return uniq;
  },
  "live-job": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/jobs?jobId=${uniq}`, { svc: null, body: { template: { template: { containers: [{ image: IMAGE }] } } } });
    return uniq;
  },
  "live-job-detail": async (wire, uniq) => {
    await ensureJob(wire, "uic-run-job");
    const job = await wire("GET", jobPath("uic-run-job"), { svc: null }).catch(() => ({}));
    const labels = { ...(job.labels || {}), uic: uniq };
    await wire("PATCH", `${jobPath("uic-run-job")}?updateMask=labels`, { svc: null, body: { labels } });
    return uniq;
  },
  "live-workerpool": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/locations/${REGION}/workerPools?workerPoolId=${uniq}`, { svc: null, body: { template: { containers: [{ image: IMAGE }] } } });
    return uniq;
  },
  "live-domain-mapping": async (wire, uniq) => {
    await ensureService(wire, "uic-run-service");
    const domain = `${uniq}.example.com`;
    await wire("POST", `/apis/domains.cloudrun.com/v1/namespaces/${PROJECT}/domainmappings`, { svc: null, body: { metadata: { name: domain }, spec: { routeName: "uic-run-service" } } });
    return domain;
  },
};
