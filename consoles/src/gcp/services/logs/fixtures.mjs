/* UI-conformance fixtures for Cloud Logging (native REST v2, svc: null — no AWS
 * signature). See aws/s3/fixtures.mjs for the contract. */
const PROJECT = "vyomi-project";

async function writeEntries(wire, entries, logName = `projects/${PROJECT}/logs/app`) {
  await wire("POST", "/v2/entries:write", { svc: null, body: { logName, resource: { type: "global" }, entries } });
}

async function ensureBucket(wire, id) {
  try {
    await wire("POST", `/v2/projects/${PROJECT}/locations/global/buckets?bucketId=${id}`, { svc: null, body: { retentionDays: 30 } });
  } catch (e) { if (!/ALREADY_EXISTS/.test(e.message)) throw e; }
}

export default {
  "logs-seed": async (wire) => {
    await writeEntries(wire, [
      { severity: "INFO", textPayload: "Request completed in 42ms" },
      { severity: "WARNING", textPayload: "Disk usage above 80%" },
      { severity: "ERROR", textPayload: "Connection to database timed out" },
    ]);
  },
  "logs-live-entry": async (wire, uniq) => {
    const text = `live entry ${uniq}`;
    await writeEntries(wire, [{ severity: "INFO", textPayload: text }]);
    return text;
  },
  "metric-live": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/metrics`, { svc: null, body: { name: uniq, filter: 'severity>="ERROR"' } });
    return uniq;
  },
  "sink-live": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/sinks`, { svc: null, body: { name: uniq, destination: "storage.googleapis.com/uic-log-sink-bucket", filter: "" } });
    return uniq;
  },
  "bucket-live": async (wire, uniq) => {
    await wire("POST", `/v2/projects/${PROJECT}/locations/global/buckets?bucketId=${uniq}`, { svc: null, body: { retentionDays: 30 } });
    return uniq;
  },
  "view-live": async (wire, uniq) => {
    await ensureBucket(wire, "uic-log-bucket");
    await wire("POST", `/v2/projects/${PROJECT}/locations/global/buckets/uic-log-bucket/views?viewId=${uniq}`, { svc: null, body: { filter: "" } });
    return uniq;
  },
};
