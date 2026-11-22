// Loader hooks for trust-test-key.mjs (TEST ONLY): adds the public test-vector key to wasm/relay/mesh-session.mjs TRUSTED_KEYS.
import { TEST_KID, TEST_PUB } from "./mesh-testkey.mjs";

const OPEN = "export const TRUSTED_KEYS = Object.freeze({";

export async function load(url, context, nextLoad) {
  const res = await nextLoad(url, context);
  if (!url.endsWith("/mesh-session.mjs")) return res;     // wasm/relay/ in the repo, /opt/relay/ when mounted into a test container
  const src = String(res.source);
  if (!src.includes(OPEN)) throw new Error("trust-test-key: TRUSTED_KEYS declaration not found in mesh-session.mjs");
  return { ...res, source: src.replace(OPEN, `${OPEN}\n  ${JSON.stringify(TEST_KID)}: ${JSON.stringify(TEST_PUB)},`) };
}
