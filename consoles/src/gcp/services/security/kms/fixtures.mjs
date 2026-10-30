/* UI-conformance fixtures for Cloud KMS (native Cloud KMS REST v1, no SigV4 — svc: null).
 * See s3/fixtures.mjs and networking/fixtures.mjs for the pattern. */
const PROJECT = "vyomi-project";   // consoles/src/gcp/project.js DEFAULT_PROJECT
const LOC = "us-central1";
const RING = "uic-keyring";
const KEY = "uic-key";
const base = `/v1/projects/${PROJECT}`;
const ringPath = (id) => `${base}/locations/${LOC}/keyRings?keyRingId=${id}`;
const keyPath = (ring, id) => `${base}/locations/${LOC}/keyRings/${ring}/cryptoKeys?cryptoKeyId=${id}`;
const KEY_BODY = { purpose: "ENCRYPT_DECRYPT", versionTemplate: { algorithm: "GOOGLE_SYMMETRIC_ENCRYPTION" } };

async function ensureRing(wire) { await wire("POST", ringPath(RING), { svc: null, body: {} }).catch(() => {}); }
async function ensureKey(wire) { await ensureRing(wire); await wire("POST", keyPath(RING, KEY), { svc: null, body: KEY_BODY }).catch(() => {}); }

export default {
  "kms-keyring": async (wire) => { await ensureRing(wire); return RING; },
  "kms-key": async (wire) => { await ensureKey(wire); return KEY; },

  "live-key-ring": async (wire, uniq) => { await wire("POST", ringPath(uniq), { svc: null, body: {} }); return uniq; },

  "live-key": async (wire, uniq) => { await ensureRing(wire); await wire("POST", keyPath(RING, uniq), { svc: null, body: KEY_BODY }); return uniq; },

  // Key detail page proof: a unique label value shows up on the Overview tab (which the
  // conformance checker reaches by clicking through every tab on the page).
  "live-key-label": async (wire, uniq) => {
    await ensureKey(wire);
    await wire("PATCH", `${base}/locations/${LOC}/keyRings/${RING}/cryptoKeys/${KEY}?updateMask=labels`, {
      svc: null, headers: { "content-type": "application/json" }, body: { labels: { live: uniq } },
    });
    return uniq;
  },
};
