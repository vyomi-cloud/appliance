/* Laptop-side ssh transport (mesh-ssh.mjs) with a fake `ssh`: no network, no Codespace.
 * WS_PKG=<path to ws> node wasm/relay/test-mesh-ssh-transport.mjs */
import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createRequire } from "node:module";
import { createSshTransport, createSshHub, connectSsh, forwardSsh } from "./mesh-ssh.mjs";

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
  if (cmd.includes("compose.service=simulator")) out = "simulator_c\n";
  if (cmd.includes("name=vyomi-k3s-")) out = "vyomi-k3s-0123456789\n";
  setImmediate(() => { c.stdout.end(out); c.emit("close", 0); });
  return c;
}
const t = createSshTransport({ codespace: "cs-test", spawn: fakeSpawn, config: { file: "/dev/null", host: "cs.test.main" } });

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
assert.equal(await new Promise((res) => { const w = new WS(`ws://127.0.0.1:${port}/shell`); w.on("unexpected-response", (_q, r) => res(r.statusCode)); w.on("error", () => {}); }), 501);
srv.close(); t.close();
console.log("mesh-ssh transport: all checks passed");
process.exit(0);
