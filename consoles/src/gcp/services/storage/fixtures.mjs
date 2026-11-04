/* UI-conformance fixtures for Cloud Storage — native GCS JSON API v1 (svc: null → no
 * AWS signature). Each returns the text the page must then show (liveness: proves the
 * page is not static). See consoles/src/aws/services/s3/fixtures.mjs for the pattern. */
const PROJECT = "vyomi-project";
const B = "uic-bucket";
const O = "uic-object.txt";

async function ensureBucket(wire) {
  await wire("POST", `/storage/v1/b?project=${PROJECT}`, { svc: null, body: { name: B } }).catch(() => {});
}
async function ensureObject(wire) {
  await ensureBucket(wire);
  await wire("POST", `/upload/storage/v1/b/${B}/o?uploadType=media&name=${encodeURIComponent(O)}`,
    { svc: null, headers: { "content-type": "text/plain" }, body: "hello gcs" }).catch(() => {});
}

export default {
  "gcs-bucket": async (wire) => { await ensureObject(wire); return B; },

  "live-bucket": async (wire, uniq) => { await wire("POST", `/storage/v1/b?project=${PROJECT}`, { svc: null, body: { name: uniq } }); return uniq; },

  // Bucket-details page proof: patch a fresh label onto the fixed bucket right before
  // load — Configuration tab's Labels chips must show it.
  "live-bucket-detail": async (wire, uniq) => {
    await ensureBucket(wire);
    await wire("PATCH", `/storage/v1/b/${B}`, { svc: null, headers: { "content-type": "application/json" }, body: { labels: { live: uniq } } });
    return uniq;
  },

  // Object-details page proof: patch a fresh custom-metadata key onto the fixed object —
  // the Live object tab's Metadata section must show it.
  "live-object-detail": async (wire, uniq) => {
    await ensureObject(wire);
    await wire("PATCH", `/storage/v1/b/${B}/o/${encodeURIComponent(O)}`, { svc: null, headers: { "content-type": "application/json" }, body: { metadata: { live: uniq } } });
    return uniq;
  },

  // Batch Operations page proof: create a real job (harmless no-op Delete against a
  // prefix nothing matches) whose Prefix column shows the fresh unique string.
  "live-batch-job": async (wire, uniq) => {
    await ensureBucket(wire);
    await wire("POST", "/storage/v1/batchOperations", { svc: null, body: { bucket: B, prefix: uniq, action: { type: "Delete" } } });
    return uniq;
  },

  // Insights datasets page proof: create a dataset config whose display name is fresh.
  "live-dataset": async (wire, uniq) => {
    await wire("POST", "/storage/v1/insightsDatasets", { svc: null, body: { displayName: uniq } });
    return uniq;
  },
};
