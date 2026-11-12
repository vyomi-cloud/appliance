// The Mesh plane must tell the simulator the address the USER reaches it at (not the in-Codespace service name), so the endpoints the
// simulator advertises work from the laptop. Run: node wasm/relay/test-mesh-forwarded-host.mjs
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createSshTransport } from "./mesh-ssh.mjs";

let seen = "";
function fakeSpawn(bin, args) {
  const c = new EventEmitter(); c.stdout = new PassThrough(); c.stderr = new PassThrough(); c.stdin = new PassThrough(); c.kill = () => c.emit("close", 0);
  if (args.indexOf("-W") >= 0) {
    c.stdin.on("data", (d) => { seen += String(d); c.stdout.write("HTTP/1.1 200 OK\r\ncontent-type: text/plain\r\ncontent-length: 2\r\nconnection: close\r\n\r\nok"); });
    c.stdin.on("end", () => setImmediate(() => { c.stdout.end(); c.emit("close", 0); }));
    return c;
  }
  const cmd = args[args.length - 1];
  const out = cmd.includes("compose.service=simulator") ? "sim_c\n" : (/docker inspect/.test(cmd) ? "10.0.0.2 " : "");
  setImmediate(() => { c.stdout.end(out); c.emit("close", 0); });
  return c;
}

async function call(headers) {
  seen = "";
  const t = createSshTransport({ codespace: "cs-test", spawn: fakeSpawn, config: { file: "/dev/null", host: "cs.test.main" }, keepaliveMs: 0 });
  const res = { headersSent: false, writeHead() { this.headersSent = true; }, write() {}, end() { this.ended = true; }, on() {}, once() {}, emit() {} };
  await new Promise((resolve) => { res.end = resolve; res.write = () => {}; t.httpToSimulator({ method: "POST", url: "/subscriptions/s/providers/Microsoft.CognitiveServices/accounts/a", headers }, res, Buffer.from("{}")); setTimeout(resolve, 1500); });
  t.close();
  return seen.toLowerCase();
}

delete process.env.VYOMI_MESH_ENDPOINT_HOST;
let req = await call({ "content-type": "application/json" });
assert.match(req, /\r\nhost: simulator:9000\r\n/);                       // the simulator's own guard still sees its service name
assert.match(req, /\r\nx-forwarded-host: 127\.0\.0\.1:9000\r\n/);         // ...and is told the laptop-side address
assert.match(req, /\r\nx-forwarded-proto: http\r\n/);
req = await call({ "x-forwarded-host": "evil.example" });                // a caller cannot choose what the simulator advertises
assert.ok(!/evil\.example/.test(req), req);
process.env.VYOMI_MESH_ENDPOINT_HOST = "127.0.0.1:19000";                // the user forwards to a different local port
req = await call({});
assert.match(req, /\r\nx-forwarded-host: 127\.0\.0\.1:19000\r\n/);
console.log("test-mesh-forwarded-host: ok");
