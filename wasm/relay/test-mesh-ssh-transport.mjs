/* Laptop-side ssh transport (mesh-ssh.mjs) with a fake `ssh`: no network, no Codespace.
 * WS_PKG=<path to ws> node wasm/relay/test-mesh-ssh-transport.mjs */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import http from "node:http";
import net from "node:net";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createRequire } from "node:module";
import { createSshTransport, createSshHub, connectSsh, forwardSsh, findCodespace } from "./mesh-ssh.mjs";

const WS = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
const { WebSocketServer } = WS;
const cmds = [];
const IPS = { simulator_c: "10.0.0.2", "vyomi-i-web": "10.0.0.5", "vyomi-k3s-0123456789": "10.0.0.9" };
// fake child: exec -> canned text; -W host:port -> an HTTP-ish echo server behind the pipe
function fakeSpawn(bin, args) {
  const c = new EventEmitter(); c.stdout = new PassThrough(); c.stderr = new PassThrough(); c.stdin = new PassThrough(); c.kill = () => c.emit("close", 0);
  const w = args.indexOf("-W");
  if (w >= 0) {
    cmds.push("W " + args[w + 1]);
    c.stdin.on("data", (d) => {
      const s = String(d);
      if (s.startsWith("GET ")) c.stdout.write("HTTP/1.1 200 OK\r\ncontent-type: text/plain\r\ncontent-length: 2\r\nconnection: close\r\n\r\nok");
      else c.stdout.write(d);
    });
    c.stdin.on("end", () => setImmediate(() => { c.stdout.end(); c.emit("close", 0); }));   // ssh exits when its stdin closes
    return c;
  }
  const cmd = args[args.length - 1]; cmds.push(cmd);
  let out = "";
  const m = /docker inspect .* (\S+) 2>/.exec(cmd);
  if (m && IPS[m[1]]) out = IPS[m[1]] + " ";
  if (cmd.includes("xargs -r docker inspect")) out = "/simulator|vyomi/appliance:x|172.18.0.2 |9000/tcp \n/llm-chat|llama|172.18.0.7 |8080/tcp \n/vyomi-i-web|ubuntu|172.18.0.5 |22/tcp \n/vyomi-k3s-0123456789|rancher/k3s|172.18.0.9 |6443/tcp \n/bad name|x||\n";
  if (cmd.includes("compose.service=simulator")) out = "simulator_c\n";
  if (cmd.includes("name=vyomi-k3s-")) out = "vyomi-k3s-0123456789\n";
  setImmediate(() => { c.stdout.end(out); c.emit("close", 0); });
  return c;
}
const t = createSshTransport({ codespace: "cs-test", spawn: fakeSpawn, config: { file: "/dev/null", host: "cs.test.main" }, keepaliveMs: 0 });

// resolve
assert.deepEqual(await t.resolve("host"), { host: "127.0.0.1", port: 2222, reserved: "host" });
assert.deepEqual(await t.resolve("codespace"), { host: "127.0.0.1", port: 2222, reserved: "host" });
assert.deepEqual(await t.resolve("vyomi-k3s-0123456789", 1234), { host: "10.0.0.9", port: 6443, reserved: "k3s" });
assert.equal((await t.resolve("k3s")).port, 6443);
assert.deepEqual(await t.resolve("web", 22), { host: "10.0.0.5", port: 22 });
assert.equal(await t.resolve("ghost"), null);
const before = cmds.length;
assert.equal(await t.resolve("bad;rm -rf /"), null);          // never reaches a shell
assert.equal(cmds.length, before);
assert.equal(await t.resolve("vyomi-k3s-ZZ"), null);
assert.deepEqual(await t.simulatorTarget(), { host: "10.0.0.2", port: 9000 });
assert.ok(cmds.some((c) => /^W /.test(c)) === false);
await assert.rejects(() => t.open("1.2.3.4; id", 22));         // open() only takes dotted quads

// list: everything reachable, classified, with the name the user types
const lt = await t.list();
assert.deepEqual(lt.map((r) => [r.name, r.kind]), [["host", "host"], ["simulator", "service"], ["llm-chat", "llm"], ["web", "instance"], ["vyomi-k3s-0123456789", "k3s"]]);
assert.equal(lt.find((r) => r.name === "web").ip, "172.18.0.5"); assert.deepEqual(lt.find((r) => r.name === "simulator").ports, [9000]);
// list in the packaged CLI: JSON shape, no crash with nothing reachable
assert.equal(spawnSync(process.execPath, [new URL("../../packaging/tunnel/bin/vyomi-tunnel.mjs", import.meta.url).pathname, "list", "bogus"], { encoding: "utf8" }).status, 2);
const jl = spawnSync(process.execPath, [new URL("../../packaging/tunnel/bin/vyomi-tunnel.mjs", import.meta.url).pathname, "list", "--json"], { encoding: "utf8", timeout: 40000, env: { ...process.env, RELAY_PORT: "8999" } });
assert.ok(Array.isArray(JSON.parse(jl.stdout).targets));

// the user's Mesh Codespace is found automatically (newest running vyomi-mesh-*; never someone else's or an unrelated one)
const lst = (rows) => (b, a) => { const c = new EventEmitter(); c.stdout = new PassThrough(); c.stderr = new PassThrough(); setImmediate(() => { c.stdout.end(JSON.stringify(rows)); c.emit("close", 0); }); return c; };
assert.equal(await findCodespace("gh", lst([{ name: "other-app", state: "Available" }, { name: "vyomi-mesh-old", state: "Available", createdAt: "2026-11-01" },
  { name: "vyomi-mesh-new", state: "Available", createdAt: "2026-11-09" }, { name: "vyomi-mesh-off", state: "Shutdown", createdAt: "2026-11-10" }])), "vyomi-mesh-new");
await assert.rejects(() => findCodespace("gh", lst([{ name: "vyomi-mesh-off", state: "Shutdown" }])), /stopped/);
await assert.rejects(() => findCodespace("gh", lst([{ name: "other", state: "Available" }])), /no Mesh Codespace/);

// keepalive: starts by itself on first use, sends real ssh traffic on a schedule, stops on close
const kaCmds = []; const kt = createSshTransport({ codespace: "cs-ka", config: { file: "/dev/null", host: "h" }, keepaliveMs: 40,
  spawn: (b, a) => { kaCmds.push(a[a.length - 1]); return fakeSpawn(b, a); } });
assert.equal(kaCmds.length, 0);                                   // nothing before the transport is used
await kt.exec("true"); await new Promise((r) => setTimeout(r, 150));
const beats = kaCmds.filter((c) => c.includes("vyomi-keepalive")).length;
assert.ok(beats >= 3, "keepalive beats: " + beats); assert.ok(kt.keepalive().writes >= 3);
kt.close(); const after = kaCmds.length; await new Promise((r) => setTimeout(r, 120)); assert.equal(kaCmds.length, after);   // stops on close

// connectSsh: bytes round trip
const stdin = new PassThrough(), stdout = new PassThrough(); const got = []; stdout.on("data", (d) => got.push(d));
const p = connectSsh("host", { transport: t, stdin, stdout, stderr: new PassThrough() });
stdin.write("hello"); await new Promise((r) => setTimeout(r, 30)); stdin.end();
assert.equal(await p, 0); assert.equal(Buffer.concat(got).toString(), "hello");
assert.equal(await connectSsh("ghost", { transport: t, stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough() }), 3);

// forwardSsh
const f = await forwardSsh("host", { local: 0, remote: 22, transport: t, net });
const echo = await new Promise((res) => { const c = net.connect(f.port, "127.0.0.1", () => c.write("ping")); c.on("data", (d) => { res(String(d)); c.destroy(); }); });
assert.equal(echo, "ping"); f.close(); assert.equal(await f.done, 0);

// hub over a real http server + ws
const hub = createSshHub({ WebSocketServer, transport: t, origins: ["https://vyomi.cloud"] });
const srv = http.createServer((req, res) => { const b = []; req.on("data", (d) => b.push(d)); req.on("end", () => { if (!hub.http(req, res, Buffer.concat(b))) { res.writeHead(404); res.end(); } }); });
srv.on("upgrade", (req, s, h) => { const p = new URL(req.url, "http://x").pathname; if (p === "/connect") hub.connectUpgrade(req, s, h); else if (p === "/shell") hub.shellUpgrade(req, s, h); else hub.upgrade(req, s, h); });
await new Promise((r) => srv.listen(0, "127.0.0.1", r)); const port = srv.address().port;
const get = (headers) => new Promise((res) => http.get({ port, path: "/x", headers }, (r) => { let b = ""; r.on("data", (d) => { b += d; }); r.on("end", () => res({ s: r.statusCode, b, h: r.headers })); }));
const ok = await get({ "x-vyomi-session-token": "x", origin: "https://vyomi.cloud" });
assert.equal(ok.s, 200); assert.equal(ok.b, "ok"); assert.equal(ok.h["access-control-allow-origin"], "https://vyomi.cloud");
assert.equal((await get({ "x-vyomi-session-token": "x", origin: "https://evil.example" })).s, 403);
assert.equal((await get({})).s, 404);                            // not the Mesh plane -> falls through
const wsOk = await new Promise((res) => { const w = new WS(`ws://127.0.0.1:${port}/connect?vm=host&port=22`); w.on("open", () => w.send(Buffer.from("abc"), { binary: true })); w.on("message", (d) => { res(String(d)); w.close(); }); w.on("error", () => res("err")); });
assert.equal(wsOk, "abc");
const refused = await new Promise((res) => { const w = new WS(`ws://127.0.0.1:${port}/connect?vm=host`, { headers: { origin: "https://evil.example" } }); w.on("unexpected-response", (_q, r) => res(r.statusCode)); w.on("error", () => {}); });
assert.equal(refused, 403);
// /shell: tab <-> simulator's /booster/shell WS over a stream (stub transport -> real local ws server standing in for the simulator)
const sim = http.createServer(); const simWss = new WebSocketServer({ server: sim }); const seen = [];
simWss.on("connection", (ws, rq) => { seen.push(rq.url); ws.send(JSON.stringify({ t: "opened", container: "vyomi-i-x" })); ws.on("message", (d, b) => ws.send(b ? Buffer.concat([Buffer.from("echo:"), d]) : JSON.stringify({ t: "resize-ack" }))); });
await new Promise((r) => sim.listen(0, "127.0.0.1", r));
const stub = { codespace: "x", simulatorTarget: async () => ({ host: "127.0.0.1", port: sim.address().port }), open: async (h, p) => net.connect(p, h), close() {}, resolve: t.resolve, httpToSimulator: t.httpToSimulator };
const hub2 = createSshHub({ WebSocketServer, WebSocket: WS, transport: stub, origins: ["https://vyomi.cloud"] });
const srv2 = http.createServer(); srv2.on("upgrade", (rq, s, h) => hub2.shellUpgrade(rq, s, h));
await new Promise((r) => srv2.listen(0, "127.0.0.1", r));
const msgs = await new Promise((res) => { const out = []; const w = new WS(`ws://127.0.0.1:${srv2.address().port}/shell`, { headers: { origin: "https://vyomi.cloud" } });
  w.on("open", () => w.send(JSON.stringify({ type: "auth", cloud: "aws", ref: "i-1", cols: 80, rows: 24 })));
  w.on("message", (d, b) => { out.push(b ? "B:" + d : "T:" + d); if (out.length === 1) { w.send(Buffer.from("ls"), { binary: true }); w.send(JSON.stringify({ t: "resize", cols: 1, rows: 1 })); } if (out.length === 3) { w.close(); res(out); } }); });
assert.equal(msgs[0], 'T:{"t":"opened","container":"vyomi-i-x"}'); assert.ok(msgs.includes("B:echo:ls")); assert.ok(msgs.includes('T:{"t":"resize-ack"}'));
assert.match(seen[0], /cloud=aws&ref=i-1&cols=80&rows=24/);
const bad = await new Promise((res) => { const w = new WS(`ws://127.0.0.1:${srv2.address().port}/shell`); w.on("open", () => w.send(JSON.stringify({ type: "auth", cloud: "nope", ref: "x" }))); w.on("message", (d) => res(String(d))); });
assert.match(bad, /BadRequest/);
sim.close(); srv2.close();
srv.close(); t.close();
// help: every spelling prints the same usage; unknown commands fail with rc 2 and never start a relay
const bin = new URL("../../packaging/tunnel/bin/vyomi-tunnel.mjs", import.meta.url).pathname;
for (const a of [["help"], ["-help"], ["--help"], ["-h"], ["forward", "--help"], ["login", "-h"], ["help", "forward"]]) {
  const r = spawnSync(process.execPath, [bin, ...a], { encoding: "utf8", env: { ...process.env, VYOMI_HOME: "/nonexistent" }, timeout: 15000 });
  assert.equal(r.status, 0, a.join(" ")); assert.match(r.stdout, a.length === 2 ? new RegExp("vyomi-tunnel " + (a[0] === "help" ? a[1] : a[0])) : /login[\s\S]*ssh <name>\.vyomi[\s\S]*forward/);
}
const badCmd = spawnSync(process.execPath, [bin, "bogus"], { encoding: "utf8", timeout: 15000 });
assert.equal(badCmd.status, 2); assert.match(badCmd.stderr, /unknown command "bogus"/);
console.log("mesh-ssh transport: all checks passed");
process.exit(0);
