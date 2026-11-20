/* The real tunnel and the real MCP together, against a fake Codespace (fake `gh`, a fake `ssh` that runs the Codespace's
 * docker questions and carries `-W` streams to a fake simulator, a stub portal). This is the path that broke in 1.3.0:
 * the MCP read `vyomi-tunnel list mesh` rows the tunnel no longer printed, and only canned JSON was tested.
 *   WS_PKG=<path to ws> node --test wasm/relay/test-mcp-codespace-e2e.mjs        (needs `go`; skipped without it)
 * Flow: vyomi_status suggests a forward -> run exactly that command -> vyomi_status says serving (unlocked, tier) ->
 * `list mesh` says "already forwarded". Also: Vyomi's own containers never appear, and their names are refused. */
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { startStubPortal } from "./test-fixtures/stub-portal.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const plat = `${process.platform}-${process.arch}`;
const skip = (process.platform === "win32" && "sh/node fakes") || (spawnSync("go", ["version"]).status !== 0 && "go not installed");
const cleanup = [];
after(() => { for (const f of cleanup.reverse()) { try { f(); } catch { /* */ } } });

const deadPort = async () => { const s = net.createServer(); await new Promise((r) => s.listen(0, "127.0.0.1", r)); const p = s.address().port; await new Promise((r) => s.close(r)); return p; };
const waitFor = async (fn, ms = 20000) => { const end = Date.now() + ms; for (;;) { const v = await fn().catch(() => null); if (v) return v; if (Date.now() > end) return null; await new Promise((r) => setTimeout(r, 200)); } };
/** Run a child without blocking this process (the stub portal and the fake simulator live here). */
const runAsync = (args, env, input = "", ms = 120000) => new Promise((resolve) => {
  const c = spawn(process.execPath, args, { env, stdio: ["pipe", "pipe", "pipe"] });
  let stdout = "", stderr = ""; c.stdout.on("data", (d) => { stdout += d; }); c.stderr.on("data", (d) => { stderr += d; });
  const t = setTimeout(() => c.kill("SIGKILL"), ms);
  c.on("close", (status) => { clearTimeout(t); resolve({ status, stdout, stderr }); });
  c.stdin.end(input);
});
const get = (url) => new Promise((resolve, reject) => { http.get(url, (r) => { let b = ""; r.on("data", (d) => { b += d; }); r.on("end", () => resolve({ status: r.statusCode, body: b })); }).on("error", reject); });

test("tunnel list -> MCP hint -> forward api -> MCP serving -> list 'already forwarded'", { skip, timeout: 240000 }, async () => {
  // the package, with the MCP built from this tree
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "vt-e2e-")); cleanup.push(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.cpSync(path.join(root, "packaging/tunnel/bin"), path.join(dir, "bin"), { recursive: true });
  const b = spawnSync("go", ["build", "-o", path.join(dir, "mcp", plat, "vyomi-mcp"), "."], { cwd: path.join(root, "cmd/vyomi"), env: { ...process.env, CGO_ENABLED: "0" }, encoding: "utf8", timeout: 300000 });
  assert.equal(b.status, 0, b.stderr);
  const entry = fs.realpathSync(path.join(dir, "bin/vyomi-tunnel.mjs"));

  // the fake simulator behind the Codespace (what `forward api` must reach)
  const sim = http.createServer((req, res) => {
    if (req.url.startsWith("/mesh/status")) { res.writeHead(200, { "content-type": "application/json" }); return res.end(JSON.stringify({ mesh: true, mesh_id: "m-e2e", version: "4.0.0", tier: "pro", locked: false })); }
    res.writeHead(200); res.end("ok");
  });
  await new Promise((r) => sim.listen(0, "127.0.0.1", r)); cleanup.push(() => sim.close());
  const portal = await startStubPortal({ codespace: "vyomi-mesh-e2e" }); cleanup.push(() => portal.close());

  // fake gh: an ssh config for the Codespace; fake ssh: the Codespace's answers, and -W streams to the fake simulator
  const fb = path.join(dir, "fakebin"); fs.mkdirSync(fb);
  fs.writeFileSync(path.join(fb, "gh"), "#!/bin/sh\n[ \"$1\" = --version ] && { echo 'gh version 2.99.0 (2026-01-01)'; exit 0; }\n" +
    "[ \"$1 $2\" = 'codespace ssh' ] && { printf 'Host cs.e2e\\n  User u\\n'; exit 0; }\n" +
    "[ \"$1 $2\" = 'codespace list' ] && { echo '[{\"name\":\"vyomi-mesh-e2e\",\"state\":\"Available\",\"createdAt\":\"2026-11-19T00:00:00Z\"}]'; exit 0; }\nexit 0\n", { mode: 0o755 });
  fs.writeFileSync(path.join(fb, "ssh"), `#!/usr/bin/env node
const a = process.argv.slice(2), w = a.indexOf("-W");
if (a.includes("-O")) process.exit(0);
if (w >= 0) {                                                     // a stream: whatever host:port was asked, it lands on the fake simulator
  const s = require("net").connect(${sim.address().port}, "127.0.0.1");
  process.stdin.pipe(s); s.pipe(process.stdout); s.on("close", () => process.exit(0)); s.on("error", () => process.exit(1));
} else {
  const c = a[a.length - 1];
  if (c.includes("xargs")) process.stdout.write("/vyomi-mesh-simulator-1|x|172.18.0.2 |9000/tcp \\n/vyomi-mesh-llm-1|x|172.18.0.3 |9000/tcp \\n/vyomi-i-web|u|172.18.0.5 |22/tcp \\n");
  else if (c.includes("compose.service=simulator") || c.includes("compose simulator")) process.stdout.write("vyomi-mesh-simulator-1\\n");
  else if (c.includes("docker inspect") || c.includes(" ip ")) process.stdout.write("172.18.0.2\\n");
}
`, { mode: 0o755 });

  const home = path.join(dir, "home"); fs.mkdirSync(home);
  const env = { ...process.env, HOME: home, USERPROFILE: home, VYOMI_HOME: path.join(home, ".vyomi"), VYOMI_PORTAL_URL: portal.url, VYOMI_GH: path.join(fb, "gh"),
    VYOMI_ACCESS_KEY_ID: "VYKAPRO", VYOMI_SECRET_ACCESS_KEY: "pro-secret", PATH: [fb, path.dirname(process.execPath), "/usr/bin", "/bin"].join(path.delimiter),
    RELAY_PORT: String(await deadPort()), VYOMI_MESH_URL: `http://127.0.0.1:${await deadPort()}`, VYOMI_SIMULATOR_PORT: String(await deadPort()), VYOMI_ENDPOINT: "" };
  for (const k of ["VYOMI_PROFILE", "VYOMI_CREDENTIALS_FILE", "VYOMI_TUNNEL_BIN", "VYOMI_MESH_CODESPACE", "GH_TOKEN", "GITHUB_TOKEN", "VYOMI_TARGET"]) delete env[k];

  /** One MCP session: initialize, then tool calls; returns each call's parsed text result. */
  const mcp = async (...calls) => {
    const msgs = [{ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "e2e", version: "0" } } },
      { jsonrpc: "2.0", method: "notifications/initialized" }, ...calls.map(([name, args], i) => ({ jsonrpc: "2.0", id: 10 + i, method: "tools/call", params: { name, arguments: args } }))];
    const r = await runAsync([entry, "mcp"], env, msgs.map((m) => JSON.stringify(m)).join("\n") + "\n");
    assert.equal(r.status, 0, r.stderr);
    const out = r.stdout.trim().split("\n").map((l) => JSON.parse(l));
    return calls.map((_, i) => JSON.parse(out.find((m) => m.id === 10 + i).result.content[0].text));
  };
  const csOf = (st) => st.homes.find((h) => h.id === "mesh-codespace");

  // 1. the MCP finds the Codespace through the real tunnel, and its hint is a command the tunnel accepts
  const [st1, reach] = await mcp(["vyomi_status", {}], ["vyomi_reach", { scope: "mesh" }]);
  const cs1 = csOf(st1);
  assert.equal(cs1.reachable, true, JSON.stringify(cs1)); assert.equal(cs1.serving, false);
  assert.equal(cs1.detail.api_target, "api", JSON.stringify(cs1.detail));
  const m = /^vyomi-tunnel forward (api) (\d+):9000$/.exec(cs1.detail.forward_command || ""); assert.ok(m, cs1.detail.forward_command);
  assert.doesNotMatch(JSON.stringify(reach), /simulator|llm/, "Vyomi's own containers are never listed");
  assert.match(JSON.stringify(reach), /"name":"api"/);

  // 2. the user runs exactly the suggested command
  const fwd = spawn(process.execPath, [entry, "forward", m[1], `${m[2]}:9000`], { env, stdio: ["ignore", "ignore", "pipe"] });
  let ferr = ""; fwd.stderr.on("data", (d) => { ferr += d; }); cleanup.push(() => fwd.kill("SIGTERM"));
  const up = await waitFor(async () => { const r = await get(`http://127.0.0.1:${m[2]}/mesh/status`); return r.status === 200 && r; });
  assert.ok(up, "the forward never answered: " + ferr);

  // 3. the MCP now serves from the Codespace (it asked the mesh through the forward), and the list says it is forwarded
  const [st2] = await mcp(["vyomi_status", {}]);
  const cs2 = csOf(st2);
  assert.equal(cs2.serving, true, JSON.stringify(cs2)); assert.equal(cs2.endpoint, `http://127.0.0.1:${m[2]}`);
  assert.equal(cs2.detail.locked, false); assert.equal(cs2.detail.tier, "pro"); assert.equal(cs2.detail.mesh_id, "m-e2e");
  const l = await runAsync([entry, "list", "mesh", "--json"], env);
  const api = JSON.parse(l.stdout).rows.find((x) => x.name === "api" && x.type === "service");
  assert.equal(api.connect, `already forwarded: 127.0.0.1:${m[2]}`);

  // 4. a core container name is refused with the way to the API
  const bad = await runAsync([entry, "forward", "vyomi-mesh-simulator-1", "9199:9000"], env);
  assert.equal(bad.status, 3); assert.match(bad.stderr, /Vyomi's own Mesh software.*forward api/s);
  fwd.kill("SIGTERM");
});
