/* Reserved targets + `vyomi-tunnel forward`, all local: relay (local-relay.mjs) + Mesh agent (mesh-dial.mjs, default DNS resolver) + client (mesh-cli.mjs).
 * WS_PKG=<path to ws> RELAY_PORT=8796 node wasm/relay/test-tunnel-k3s.mjs
 * Proves: resolveReserved answers host/codespace/k3s exactly and nothing else; `connect host` reaches the host sshd address; a reserved target
 * ignores the client's requested port; a VM can not shadow a reserved name; `forward` carries bytes both ways, handles two sockets, and
 * refuses bad usage / expired tokens. */
import net from "node:net";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";
import { PassThrough } from "node:stream";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { mint } from "./mesh-session.mjs";
import { dial, resolveReserved } from "./mesh-dial.mjs";

const require = createRequire(import.meta.url);
const WS = require(process.env.WS_PKG || "ws");
const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.RELAY_PORT || 8796), KEY = "tunnel-k3s-test-key";
const relay = `http://127.0.0.1:${PORT}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowS = () => Math.floor(Date.now() / 1000);
const tok = (o = {}) => mint(KEY, { sub: "acct-1", tier: "pro", primary_cloud: "aws", session_id: "mesh-k", session_end: nowS() + 3600, ...o });

// 1. pure resolver
const env = { VYOMI_HOST_SSH_ADDR: "10.0.0.5:2222", VYOMI_K3S_ADDR: "k3s-single:6443" };
const r1 = resolveReserved("host", env), r2 = resolveReserved("Codespace", env), r3 = resolveReserved("vyomi-k3s-0123456789", env);
check("host -> VYOMI_HOST_SSH_ADDR", r1 && r1.host === "10.0.0.5" && r1.port === 2222 && r1.reserved === "host");
check("codespace is an alias of host (case-insensitive)", r2 && r2.host === "10.0.0.5");
check("default host address is host.docker.internal:22", resolveReserved("host", {}).host === "host.docker.internal" && resolveReserved("host", {}).port === 22);
check("vyomi-k3s-<10 hex> -> that server, port 6443 only", r3 && r3.host === "vyomi-k3s-0123456789" && r3.port === 6443 && r3.reserved === "k3s");
check("k3s -> VYOMI_K3S_ADDR only when set", resolveReserved("k3s", env).host === "k3s-single" && resolveReserved("k3s", {}) === null);
check("anything else is NOT reserved", ["my-vm", "vyomi-k3s-xyz", "vyomi-k3s-0123456789a", "vyomi-k3s-0123456789/../x", "minio", ""].every((n) => resolveReserved(n, env) === null));

process.env.VYOMI_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "vyomi-home-"));
const cli = await import("./mesh-cli.mjs");

// fake host sshd and fake k3s API: each echoes with a distinct prefix so we know who answered
const mk = (tag) => net.createServer((s) => s.on("data", (d) => s.write(Buffer.concat([Buffer.from(tag), d]))));
const hostSrv = mk("HOST:"), k3sSrv = mk("K3S:"), vmSrv = mk("VM:");
for (const s of [hostSrv, k3sSrv, vmSrv]) await new Promise((r) => s.listen(0, "127.0.0.1", r));
const hostPort = hostSrv.address().port, k3sPort = k3sSrv.address().port, vmPort = vmSrv.address().port;

const child = spawn(process.execPath, [path.join(here, "local-relay.mjs")], {
  env: { ...process.env, RELAY_PORT: String(PORT), RELAY_HOST: "127.0.0.1", VYOMI_MESH_SESSION_KEY: KEY, VYOMI_RELAY_ALLOW_LOOPBACK: "1", NODE_PATH: process.env.NODE_PATH || "" },
  stdio: ["ignore", "pipe", "pipe"] });
let up = false; child.stdout.on("data", (d) => { if (String(d).includes("listening") || String(d).includes(String(PORT))) up = true; });
for (let i = 0; i < 50 && !up; i++) await sleep(100);

// agent: reserved targets read from the environment; a custom resolver hands out a VM literally named "host" (must NOT win)
Object.assign(process.env, { VYOMI_HOST_SSH_ADDR: `127.0.0.1:${hostPort}`, VYOMI_K3S_ADDR: `127.0.0.1:${k3sPort}` });
const logs = [];
const token = tok();
const link = dial({ relayUrl: `ws://127.0.0.1:${PORT}`, token, WS, log: (m) => logs.push(m),
  resolveVm: async (name) => (name === "host" || name === "my-vm") ? { host: "127.0.0.1", port: vmPort } : null });
for (let i = 0; i < 50 && !link.state.linked; i++) await sleep(100);
check("agent linked to relay", link.state.linked);

const session = (name, extra = {}) => {
  const stdin = new PassThrough(), stdout = new PassThrough(), stderr = new PassThrough();
  const chunks = []; stdout.on("data", (c) => chunks.push(c));
  let err = ""; stderr.on("data", (c) => { err += c; });
  const p = cli.connect(name, { relay, token, WS, stdin, stdout, stderr, ...extra });
  return { stdin, p, out: () => Buffer.concat(chunks).toString(), err: () => err };
};

let s = session("host", { port: 9999 }); await sleep(400); s.stdin.write("a"); await sleep(400);
check("connect host reaches the host sshd; requested port 9999 is ignored", s.out() === "HOST:a", s.out());
check("a VM named 'host' can not shadow the reserved target", s.out() !== "VM:a");
check("reserved open is audit-logged", logs.some((l) => /open host target=host/.test(l)), logs.join(" | "));
s.stdin.end();
let s2 = session("codespace"); await sleep(400); s2.stdin.write("b"); await sleep(400);
check("connect codespace == host", s2.out() === "HOST:b", s2.out()); s2.stdin.end();
let s3 = session("my-vm"); await sleep(400); s3.stdin.write("c"); await sleep(400);
check("ordinary VM names still use the VM resolver", s3.out() === "VM:c", s3.out()); s3.stdin.end();
let s4 = session("k3s", { port: 1 }); await sleep(400); s4.stdin.write("d"); await sleep(400);
check("connect k3s -> VYOMI_K3S_ADDR", s4.out() === "K3S:d", s4.out()); s4.stdin.end();

// 2. forward
const f = await cli.forward("k3s", { local: 0, remote: 6443, relay, token, WS });
check("forward listens on a loopback port", f.port > 0);
const hit = (port, msg) => new Promise((res) => { const c = net.connect(port, "127.0.0.1"); let b = ""; c.on("data", (d) => { b += d; if (b.length >= msg.length + 4) { c.end(); res(b); } }); c.on("connect", () => c.write(msg)); setTimeout(() => res(b), 3000); });
const [x, y] = await Promise.all([hit(f.port, "one"), hit(f.port, "two")]);
check("forward carries bytes to the target and back (two sockets, independent)", x === "K3S:one" && y === "K3S:two", `${x} / ${y}`);
f.close(); check("forward close -> exit 0", (await f.done) === 0);

const bads = [];
for (const [label, args] of [["bad target", ["a b", { local: 0, remote: 1 }]], ["bad ports", ["k3s", { local: 0, remote: 70000 }]], ["privileged local port", ["k3s", { local: 443, remote: 1 }]]]) {
  const e = new PassThrough(); const r = await cli.forward(args[0], { ...args[1], relay, token, WS, stderr: e });
  bads.push(`${label}:${await r.done}`);
}
check("forward rejects bad target / ports / privileged port (exit 2)", bads.every((b) => b.endsWith(":2")), bads.join(" "));
const expired = tok({ session_end: nowS() - 5 });
const fe = await cli.forward("k3s", { local: 0, remote: 6443, relay, token: expired, WS, stderr: new PassThrough() });
check("forward with an ended session -> exit 2", (await fe.done) === 2);

link.stop(); child.kill(); hostSrv.close(); k3sSrv.close(); vmSrv.close();
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
