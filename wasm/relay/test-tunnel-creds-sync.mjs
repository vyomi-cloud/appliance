/* Tunnel credentials sync: the running tunnel survives a bad/revoked key, reports it on /health, re-checks on reload, and re-pairs via /reset
 * only from Vyomi origins and only against the portal named in its own credentials file.
 * Run: NODE_PATH=<dir with ws> node wasm/relay/test-tunnel-creds-sync.mjs */
import assert from "node:assert/strict";
import http from "node:http";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, statSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const BIN = join(here, "../../packaging/tunnel/bin/vyomi-tunnel.mjs");
const ok = (n) => console.log("PASS " + n);

// fake portal: /api/tunnel/session accepts only keys in `valid`; /api/tunnel/pair/redeem hands out a fresh key for code GOODCODE...
const valid = new Set(["VYKAOLD"]); const redeemed = [];
const portal = http.createServer((req, res) => {
  let b = ""; req.on("data", (c) => (b += c)); req.on("end", () => {
    const send = (st, o) => { res.writeHead(st, { "content-type": "application/json" }); res.end(JSON.stringify(o)); };
    if (req.url === "/api/tunnel/session") {
      const k = req.headers["x-vyomi-key"];
      if (!valid.has(k)) return send(401, { error: { code: k === "VYKAGONE" ? "KeyRevoked" : "InvalidAccessKey" } });
      return send(200, { session: { tier: "pro", expires_at: Date.now() / 1000 + 600, allowed: true } });
    }
    if (req.url === "/api/tunnel/pair/redeem") {
      const j = JSON.parse(b || "{}"); redeemed.push(j.code);
      if (j.code !== "GOODCODEGOODCODEGOODCODE") return send(410, { error: "invalid_or_used_code" });
      valid.add("VYKANEW");
      return send(200, { key_id: "VYKANEW", account: "a@b.c", credentials_file: `[default]\nvyomi_access_key_id = VYKANEW\nvyomi_secret_access_key = s3cret\nportal = ${PORTAL}\n` });
    }
    send(404, {});
  });
});
await new Promise((r) => portal.listen(0, "127.0.0.1", r));
const PORTAL = `http://127.0.0.1:${portal.address().port}`;

const home = mkdtempSync(join(tmpdir(), "vyomi-cs-"));
const cred = (id) => `[default]\nvyomi_access_key_id = ${id}\nvyomi_secret_access_key = x\nportal = ${PORTAL}\n`;
writeFileSync(join(home, "credentials"), cred("VYKAGONE"), { mode: 0o600 });          // starts with a REVOKED key
const RP = 18090 + Math.floor(Math.random() * 500);
const child = spawn(process.execPath, [BIN], { env: { ...process.env, VYOMI_HOME: home, RELAY_PORT: String(RP) }, stdio: ["ignore", "pipe", "pipe"] });
let exited = false; child.on("exit", () => (exited = true));
const H = (path, opt = {}) => fetch(`http://127.0.0.1:${RP}${path}`, opt);
const health = async () => (await (await H("/health")).json());
for (let i = 0; i < 50; i++) { try { await H("/health"); break; } catch { await new Promise((r) => setTimeout(r, 100)); } }
try {
  let h = await health();
  for (let i = 0; i < 30 && h.credentials.state === "unknown"; i++) { await new Promise((r) => setTimeout(r, 100)); h = await health(); }
  assert.equal(exited, false); assert.equal(h.credentials.state, "revoked"); assert.equal(h.credentials.key_id, "VYKAGONE"); assert.ok(h.features.includes("creds-sync")); assert.equal(h.version, "1.2.2");
  assert.ok(!JSON.stringify(h).includes("x\n") && !JSON.stringify(h).includes("secret")); ok("revoked key: tunnel stays up and reports state=revoked (no crash loop, no secret on /health)");

  // file replaced -> picked up by /reload
  writeFileSync(join(home, "credentials"), cred("VYKAOLD"), { mode: 0o600 });
  let r = await H("/reload", { method: "POST", headers: { origin: "https://vyomi.cloud" } }); let j = await r.json();
  assert.equal(r.status, 200); assert.equal(j.credentials.state, "ok"); assert.equal(r.headers.get("access-control-allow-origin"), "https://vyomi.cloud"); ok("POST /reload re-reads the file and validates against the portal");

  // security: foreign origin and non-loopback Host are refused, and never reach the portal
  for (const [name, opt] of [["evil origin", { headers: { origin: "https://evil.example" } }], ["lookalike origin", { headers: { origin: "https://vyomi.cloud.evil.example" } }]]) {
    r = await H("/reset", { method: "POST", body: JSON.stringify({ code: "GOODCODEGOODCODEGOODCODE" }), ...opt }); assert.equal(r.status, 403, name); }
  assert.deepEqual(redeemed, []); ok("/reset refuses foreign and look-alike origins; the portal never saw a code");
  r = await new Promise((res) => { const q = http.request({ host: "127.0.0.1", port: RP, path: "/reset", method: "POST", headers: { host: "evil.example" } }, (x) => res(x)); q.end("{}"); });
  assert.equal(r.statusCode, 403); ok("/reset refuses a non-loopback Host header (DNS rebinding)");

  // reset: bad code, then good code swaps the file (600) and the tunnel is ok with the new key
  r = await H("/reset", { method: "POST", headers: { origin: "https://vyomi.cloud" }, body: JSON.stringify({ code: "nope" }) }); assert.equal(r.status, 400);
  r = await H("/reset", { method: "POST", headers: { origin: "https://vyomi.cloud" }, body: JSON.stringify({ code: "BADCODEBADCODEBADCODEXX" }) }); assert.equal(r.status, 410);
  valid.delete("VYKAOLD");
  r = await H("/reset", { method: "POST", headers: { origin: "https://vyomi.cloud" }, body: JSON.stringify({ code: "GOODCODEGOODCODEGOODCODE" }) }); j = await r.json();
  assert.equal(r.status, 200); assert.equal(j.credentials.state, "ok"); assert.equal(j.credentials.key_id, "VYKANEW");
  assert.match(readFileSync(join(home, "credentials"), "utf8"), /VYKANEW/); assert.equal(statSync(join(home, "credentials")).mode & 0o777, 0o600);
  assert.ok(readdirSync(home).some((f) => f.startsWith("credentials.bak."))); ok("POST /reset with a valid pairing code swaps the credentials (mode 600, backup kept) and re-validates");

  // missing file: stays up, state=none
  writeFileSync(join(home, "credentials"), ""); await H("/reload", { method: "POST" }); h = await health();
  assert.equal(h.credentials.state, "none"); assert.equal(exited, false); ok("no credentials: tunnel stays up with state=none");
} finally { child.kill(); portal.close(); }
console.log("\nall passed");
