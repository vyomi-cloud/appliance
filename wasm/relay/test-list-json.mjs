/* `vyomi-tunnel list --json` contract (read by the Vyomi MCP): {schema: 1, rows: [{where, name, type, address, connect}], notes: [string]}.
 *   WS_PKG=<path to ws> node --test wasm/relay/test-list-json.mjs
 * Runs the packaged CLI (packaging/tunnel/bin) with a temp HOME/VYOMI_HOME, dummy env keys and stub portals on 127.0.0.1 (never vyomi.cloud).
 * Exit codes: 0 with rows, 1 with none, 2 with no credentials or a usage error. JSON on every path but a usage error, including
 * NoMeshSession / SessionEnded (the key is valid, so Nano is still listed). Listing never writes ssh config. L1-29 is the first test. */
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { startStubPortal } from "./test-fixtures/stub-portal.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const bin = path.resolve(here, "../../packaging/tunnel/bin/vyomi-tunnel.mjs");
const ROW_KEYS = ["address", "connect", "name", "type", "where"];
const servers = [];
after(() => { for (const s of servers) s.close(); });

const listen = (handler) => new Promise((r) => { const s = http.createServer(handler); servers.push(s); s.listen(0, "127.0.0.1", () => r(s.address().port)); });
/** A portal that refuses every session with one error code (what the real portal says when the Mesh is not running). */
const refusingPortal = async (code, status = 409) => `http://127.0.0.1:${await listen((req, res) => { req.resume(); req.on("end", () => {
  res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify({ error: { code, message: code } })); }); })}`;
/** A local relay /health with a connected tab and one browser VM. */
const relay = async () => listen((req, res) => { res.writeHead(200, { "content-type": "application/json" });
  res.end(JSON.stringify({ tab: true, tabs: 1, features: ["http", "vm-tcp"], vms: [{ vm: "i-abc", host_port: 22000 }], dbs: [] })); });
const deadPort = async () => { const s = http.createServer(); await new Promise((r) => s.listen(0, "127.0.0.1", r)); const p = s.address().port; await new Promise((r) => s.close(r)); return p; };

const portal = await startStubPortal({ codespace: "vyomi-mesh-stub" });
const endedPortal = await startStubPortal({ sessionEnd: Math.floor(Date.now() / 1000) - 5 });
servers.push({ close: portal.close }, { close: endedPortal.close });
const FREE = { VYOMI_ACCESS_KEY_ID: "VYKAFREE", VYOMI_SECRET_ACCESS_KEY: "free-secret" };
const PRO = { VYOMI_ACCESS_KEY_ID: "VYKAPRO", VYOMI_SECRET_ACCESS_KEY: "pro-secret" };

function sandbox() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "vt-list-"));
  const gh = path.join(home, "fake-gh");                     // a GitHub CLI that is installed but cannot reach any Codespace
  fs.writeFileSync(gh, "#!/bin/sh\n[ \"$1\" = --version ] && { echo 'gh version 2.99.0 (2026-01-01)'; exit 0; }\necho 'fake gh: no codespace' >&2; exit 1\n", { mode: 0o755 });
  return { home, gh };
}
const run = (sb, args, extra = {}) => new Promise((resolve) => {
  const env = { ...process.env, HOME: sb.home, USERPROFILE: sb.home, VYOMI_HOME: path.join(sb.home, ".vyomi"), VYOMI_PORTAL_URL: portal.url, VYOMI_GH: sb.gh, ...extra };
  for (const k of ["VYOMI_PROFILE", "VYOMI_CREDENTIALS_FILE", "GH_TOKEN", "GITHUB_TOKEN", "VYOMI_MESH_CODESPACE"]) delete env[k];
  for (const k of ["VYOMI_ACCESS_KEY_ID", "VYOMI_SECRET_ACCESS_KEY"]) if (!(k in extra)) delete env[k];
  const c = spawn(process.execPath, [bin, "list", ...args], { env, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "", stderr = ""; c.stdout.on("data", (d) => { stdout += d; }); c.stderr.on("data", (d) => { stderr += d; });
  const t = setTimeout(() => c.kill("SIGKILL"), 40000);
  c.on("close", (status) => { clearTimeout(t); let json = null; try { json = JSON.parse(stdout); } catch { /* not JSON */ } resolve({ status, stdout, stderr, json }); });
});
const shape = (j) => {
  assert.ok(j, "stdout is JSON");
  assert.deepEqual(Object.keys(j).sort(), ["notes", "rows", "schema"]); assert.equal(j.schema, 1);
  assert.ok(Array.isArray(j.rows)); assert.ok(Array.isArray(j.notes)); for (const n of j.notes) assert.equal(typeof n, "string");
  for (const r of j.rows) { assert.deepEqual(Object.keys(r).sort(), ROW_KEYS); for (const k of ROW_KEYS) assert.equal(typeof r[k], "string"); }
  return j;
};
const noSshEdits = (sb) => { assert.ok(!fs.existsSync(path.join(sb.home, ".ssh", "config")), "~/.ssh/config written"); assert.ok(!fs.existsSync(path.join(sb.home, ".vyomi", "ssh_config")), "~/.vyomi/ssh_config written"); };

test("L1-29: list all --json, no credentials, no mesh -> {schema:1, rows:[], notes:[...]}, exit 2 as before", async () => {
  const sb = sandbox(); const r = await run(sb, ["all", "--json"], { RELAY_PORT: String(await deadPort()) });
  assert.equal(r.status, 2, r.stderr); const j = shape(r.json);
  assert.deepEqual(j.rows, []); assert.match(j.notes.join(" "), /No Vyomi credentials/);
  noSshEdits(sb);
});

test("free key, relay down: exit 1, notes for the relay and the plan", async () => {
  const sb = sandbox(); const port = await deadPort(); const r = await run(sb, ["all", "--json"], { ...FREE, RELAY_PORT: String(port) });
  assert.equal(r.status, 1, r.stderr); const j = shape(r.json); assert.deepEqual(j.rows, []);
  assert.ok(j.notes.some((n) => n.includes(`local relay not running on :${port}`)), j.notes); assert.ok(j.notes.some((n) => /^mesh: .*Pro or Max/.test(n)), j.notes);
});

test("free key, tab connected: exit 0, rows for the Nano API and the browser VM", async () => {
  const sb = sandbox(); const port = await relay(); const r = await run(sb, ["nano", "--json"], { ...FREE, RELAY_PORT: String(port) });
  assert.equal(r.status, 0, r.stderr); const j = shape(r.json);
  assert.deepEqual(j.rows.map((x) => [x.where, x.name, x.type, x.address]), [["local", "nano-api", "api", `http://127.0.0.1:${port}`], ["browser", "i-abc", "vm", "127.0.0.1:22000"]]);
  assert.match(j.rows[0].connect, /tab connected/);
});

test("NoMeshSession: still JSON; Nano is listed and the Mesh gets a note", async () => {
  const sb = sandbox(); const port = await relay(); const p = await refusingPortal("NoMeshSession");
  const all = await run(sb, ["all", "--json"], { ...PRO, RELAY_PORT: String(port), VYOMI_PORTAL_URL: p });
  assert.equal(all.status, 0, all.stderr); const j = shape(all.json);
  assert.ok(j.rows.some((x) => x.name === "nano-api")); assert.ok(j.notes.some((n) => /^mesh: Mesh is not running/.test(n)), j.notes);
  const mesh = await run(sb, ["mesh", "--json"], { ...PRO, RELAY_PORT: String(port), VYOMI_PORTAL_URL: p });
  assert.equal(mesh.status, 1); assert.deepEqual(shape(mesh.json).rows, []); assert.match(mesh.json.notes.join(" "), /Mesh is not running/);
  const text = await run(sb, ["nano"], { ...PRO, RELAY_PORT: String(port), VYOMI_PORTAL_URL: p });           // text mode: Nano listed too
  assert.equal(text.status, 0, text.stderr); assert.match(text.stdout, /nano-api/);
  noSshEdits(sb);
});

test("SessionEnded: still JSON with the session-ended note", async () => {
  const sb = sandbox(); const r = await run(sb, ["all", "--json"], { ...PRO, RELAY_PORT: String(await deadPort()), VYOMI_PORTAL_URL: endedPortal.url });
  assert.equal(r.status, 1, r.stderr); const j = shape(r.json); assert.ok(j.notes.some((n) => /session has ended/.test(n)), j.notes);
});

test("other auth errors (bad key): JSON with the error, exit 1", async () => {
  const sb = sandbox(); const r = await run(sb, ["all", "--json"], { VYOMI_ACCESS_KEY_ID: "VYKAPRO", VYOMI_SECRET_ACCESS_KEY: "wrong", RELAY_PORT: String(await deadPort()) });
  assert.equal(r.status, 1); const j = shape(r.json); assert.match(j.notes.join(" "), /secret key does not match/);
});

test("pro key, live session: listing the Mesh never writes ~/.ssh/config or ~/.vyomi/ssh_config", { skip: process.platform === "win32" && "sh fake gh" }, async () => {
  const sb = sandbox(); const r = await run(sb, ["mesh", "--json"], { ...PRO, RELAY_PORT: String(await deadPort()) });
  assert.equal(r.status, 1, r.stderr); const j = shape(r.json); assert.ok(j.notes.some((n) => n.startsWith("mesh: ")), j.notes);
  noSshEdits(sb);
});

test("usage errors: exit 2, nothing on stdout", async () => {
  const sb = sandbox();
  for (const a of [["bogus", "--json"], ["nano", "k3s", "--json"]]) { const r = await run(sb, a, FREE); assert.equal(r.status, 2, a.join(" ")); assert.equal(r.stdout, ""); }
});
