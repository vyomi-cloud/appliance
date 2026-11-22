/* TEST ONLY: sign v2 Mesh session tokens with the PUBLIC test vector (same as tests/mesh_testkey.py).
 * v1 (HMAC) tokens are retired (V1_ACCEPTED = false, finding F2), so tests sign v2 with this published seed and trust it only
 * in processes they start themselves:
 *   spawn(process.execPath, [...TEST_HOOK, "local-relay.mjs"], ...)   // a relay process that also trusts the test key
 *   verify(tok, "", now, { trusted: TRUSTED_WITH_TEST })               // in-process
 */
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { mintV2, TRUSTED_KEYS } from "../mesh-session.mjs";

export const TEST_KID = "test-vector";
export const TEST_PUB = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg";
const PKCS8_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");      // DER header for a raw 32-byte Ed25519 seed
const seedKey = (seed) => crypto.createPrivateKey({ key: Buffer.concat([PKCS8_PREFIX, seed]), format: "der", type: "pkcs8" });
export const TEST_PRIVATE_KEY = seedKey(Buffer.from([...Array(32).keys()]));                   // 0x00..0x1f
export const WRONG_PRIVATE_KEY = seedKey(Buffer.from([...Array(32).keys()].map((i) => i + 32))); // claims TEST_KID, fails verification
export const TEST_HOOK = ["--import", fileURLToPath(new URL("./trust-test-key.mjs", import.meta.url))];
export const TRUSTED_WITH_TEST = Object.freeze({ ...TRUSTED_KEYS, [TEST_KID]: TEST_PUB });

/** A v2 token signed with the test seed; same claims as mesh-session.mjs mint(key, claims). `forged`: another key signs it. */
export function testToken(claims, { forged = false } = {}) {
  return mintV2(forged ? WRONG_PRIVATE_KEY : TEST_PRIVATE_KEY, TEST_KID, claims);
}
