/* /reset portal choice: pinned to the credentials file's portal, except a request from the real https://vyomi.cloud page re-points to vyomi.cloud.
 * Run: node wasm/relay/test-tunnel-reset-portal.mjs  (no network: fetch is stubbed) */
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createCredsSync } from "../../packaging/tunnel/bin/creds-sync.mjs";

const home = mkdtempSync(join(tmpdir(), "vyomi-rp-"));
writeFileSync(join(home, "credentials"), "[default]\nvyomi_access_key_id = VYKADEV\nvyomi_secret_access_key = x\nportal = http://localhost:8099\n");
const urls = [];
const fetchFn = async (u) => { urls.push(String(u)); return { ok: true, status: 200, json: async () => (String(u).includes("/redeem") ? { credentials_file: "[default]\nvyomi_access_key_id = VYKANEW\nvyomi_secret_access_key = y\nportal = https://vyomi.cloud\n", key_id: "VYKANEW" } : { session: { expires_at: Date.now() / 1000 + 600 } }) }; };
const mk = () => createCredsSync({ env: { VYOMI_HOME: home }, fetchFn });
const code = "G".repeat(24);
await mk().reset(code, "h", "");                                   // no origin (CLI): pinned to the file's portal
assert.ok(urls[0].startsWith("http://localhost:8099/api/tunnel/pair/redeem"), urls[0]);
writeFileSync(join(home, "credentials"), "[default]\nvyomi_access_key_id = VYKADEV\nvyomi_secret_access_key = x\nportal = http://localhost:8099\n");
urls.length = 0; await mk().reset(code, "h", "https://vyomi.cloud");  // from the real page: re-points to vyomi.cloud
assert.ok(urls[0].startsWith("https://vyomi.cloud/api/tunnel/pair/redeem"), urls[0]);
writeFileSync(join(home, "credentials"), "[default]\nvyomi_access_key_id = VYKADEV\nvyomi_secret_access_key = x\nportal = http://localhost:8099\n");
for (const o of ["http://localhost:3000", "https://vyomi.cloud.evil.example", "http://vyomi.cloud"]) { urls.length = 0; await mk().reset(code, "h", o); assert.ok(urls[0].startsWith("http://localhost:8099/"), o + " -> " + urls[0]); writeFileSync(join(home, "credentials"), "[default]\nvyomi_access_key_id = VYKADEV\nvyomi_secret_access_key = x\nportal = http://localhost:8099\n"); }
console.log("PASS reset portal: pinned to the file's portal; only the genuine https://vyomi.cloud origin re-points to vyomi.cloud\n\nall passed");
