/* UI-conformance fixtures for Cloud Scheduler (native REST v1, no SigV4 — svc: null). */
const PROJECT = "vyomi-project";   // consoles/src/gcp/project.js DEFAULT_PROJECT
const REGION = "us-central1";
const job = (id) => ({
  name: `projects/${PROJECT}/locations/${REGION}/jobs/${id}`,
  schedule: "0 * * * *",
  timeZone: "Etc/UTC",
  httpTarget: { uri: "https://example.com/handler", httpMethod: "POST" },
});
const jobsPath = `/v1/projects/${PROJECT}/locations/${REGION}/jobs`;

export default {
  "sched-job": async (wire) => { await wire("POST", jobsPath, { svc: null, body: job("uic-job") }).catch(() => {}); return "uic-job"; },
  "live-job": async (wire, uniq) => { await wire("POST", jobsPath, { svc: null, body: job(uniq) }); return uniq; },
};
