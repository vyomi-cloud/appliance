/* Mesh SSH path end to end, all local: relay (local-relay.mjs) + Mesh agent (booster-dial.mjs) + `vyomi-tunnel connect` client
 * (mesh-cli.mjs) + a fake VM sshd (TCP echo).  WS_PKG=<path to ws> RELAY_PORT=8795 node wasm/relay/test-mesh-ssh.mjs
 * Proves: bytes round-trip intact (incl. 2 MB), two streams stay independent, unknown VM fails, bad/foreign/expired tokens and
 * an unlinked booster are refused, the per-session stream cap holds, session_end drops open streams, and `config` is idempotent. */
import net from "node:net";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { PassThrough } from "node:stream";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { mint } from "./booster-session.mjs";
import { dial } from "./booster-dial.mjs";

const require = createRequire(import.meta.url);
const WS = require(process.env.WS_PKG || "ws");
const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.RELAY_PORT || 8795), KEY = "mesh-ssh-test-key";
const relay = `http://127.0.0.1:${PORT}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowS = () => Math.floor(Date.now() / 1000);
const tok = (o = {}) => mint(o.key ?? KEY, { sub: "acct-1", tier: "pro", primary_cloud: "aws", session_id: "mesh-1", session_end: nowS() + 3600, ...o });

process.env.VYOMI_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "vyomi-home-"));
const cli = await import("./mesh-cli.mjs");

// fake VM sshd: echoes every byte
const vm = net.createServer((s) => s.pipe(s));
await new Promise((r) => vm.listen(0, "127.0.0.1", r));
const vmPort = vm.address().port;

const child = spawn(process.execPath, [path.join(here, "local-relay.mjs")], {
  env: { ...process.env, RELAY_PORT: String(PORT), RELAY_HOST: "127.0.0.1", VYOMI_BOOSTER_SESSION_KEY: KEY, VYOMI_RELAY_ALLOW_LOOPBACK: "1", VYOMI_MAX_STREAMS: "3", NODE_PATH: process.env.NODE_PATH || "" },
  stdio: ["ignore", "pipe", "pipe"] });
let up = false; child.stdout.on("data", (d) => { if (String(d).includes("listening") || String(d).includes(String(PORT))) up = true; });
for (let i = 0; i < 50 && !up; i++) await sleep(100);

const token = tok();
const link = dial({ relayUrl: `ws://127.0.0.1:${PORT}`, token, WS, resolveVm: async (name) => name === "my-vm" ? { host: "127.0.0.1", port: vmPort } : null });
for (let i = 0; i < 50 && !link.state.linked; i++) await sleep(100);
check("agent linked to relay", link.state.linked);

const session = (t = token, name = "my-vm", extra = {}) => {
  const stdin = new PassThrough(), stdout = new PassThrough(), stderr = new PassThrough();
  const chunks = []; stdout.on("data", (c) => chunks.push(c));
  let err = ""; stderr.on("data", (c) => { err += c; });
  const p = cli.connect(name, { relay, token: t, WS, stdin, stdout, stderr, ...extra });
  return { stdin, p, out: () => Buffer.concat(chunks), err: () => err };
};

// 1. round trip + vm name suffix handling
check("vmName strips .vyomi", cli.vmName("my-vm.vyomi") === "my-vm" && cli.vmName("x") === "x");
let s = session(); await sleep(400); s.stdin.write("hello-ssh"); await sleep(400);
check("bytes reach the VM and come back", s.out().toString() === "hello-ssh", s.out().toString());

// 2. two independent streams
let s2 = session(); await sleep(300); s2.stdin.write("second"); await sleep(300);
check("second stream is independent", s2.out().toString() === "second" && s.out().toString() === "hello-ssh");

// 3. big payload integrity
let s3 = session(); await sleep(300);
const big = crypto.randomBytes(2 * 1024 * 1024); s3.stdin.write(big);
for (let i = 0; i < 100 && s3.out().length < big.length; i++) await sleep(100);
check("2 MB round-trips byte-exact", Buffer.compare(s3.out(), big) === 0, `${s3.out().length}/${big.length}`);

// 4. cap: 3 streams open (s, s2, s3) -> 4th refused
let s4 = session(); const c4 = await Promise.race([s4.p, sleep(3000).then(() => "hung")]);
check("per-session stream cap (429)", c4 === 1 && /429|too many/.test(s4.err()), s4.err());
s3.stdin.end(); s2.stdin.end(); await sleep(400);
check("closing stdin ends the stream cleanly (exit 0)", (await s3.p) === 0);

// 5. unknown VM
let s5 = session(token, "nope"); const c5 = await Promise.race([s5.p, sleep(4000).then(() => "hung")]);
check("unknown VM -> non-zero exit, no hang", c5 === 1, String(c5));

// 6. auth failures
let a = session(tok({ key: "wrong-key" })); check("bad signature refused", (await a.p) === 1 && /401|sign-in/.test(a.err()), a.err());
a = session(tok({ sub: "someone-else" })); check("another account's token refused (403)", (await a.p) === 1 && /403/.test(a.err()), a.err());
a = session(tok({ session_id: "no-booster" })); check("no linked Mesh for that session (502)", (await a.p) === 1 && /502|not running/.test(a.err()), a.err());
a = session(tok({ session_end: nowS() - 5, iat: nowS() - 100 })); check("expired token refused before dialing", (await a.p) === 2 && /ended/.test(a.err()), a.err());
a = session(""); check("no token -> asks to log in", (await a.p) === 2 && /login/.test(a.err()), a.err());

// 7. agent leaves -> open stream closed
link.stop(); await sleep(600);
check("agent stop closes the open stream", (await Promise.race([s.p, sleep(3000).then(() => "hung")])) !== "hung");
s.stdin.end();

// 8. ssh config: idempotent Include, decline, remove
const sshDir = fs.mkdtempSync(path.join(os.tmpdir(), "ssh-"));
fs.writeFileSync(path.join(sshDir, "config"), "Host keep\n  User me\n");
let r = await cli.configureSsh({ yes: true, sshDir });
let cfg = fs.readFileSync(path.join(sshDir, "config"), "utf8");
check("config adds Include first and keeps existing entries", r.changed && cfg.startsWith("Include ") && cfg.includes("Host keep"));
r = await cli.configureSsh({ yes: true, sshDir });
check("config is idempotent", !r.changed && (fs.readFileSync(path.join(sshDir, "config"), "utf8").match(/Include /g) || []).length === 1);
const blk = fs.readFileSync(path.join(process.env.VYOMI_HOME, "ssh_config"), "utf8");
check("block uses ProxyCommand + keepalive", /Host \*\.vyomi/.test(blk) && /ProxyCommand .*connect %h/.test(blk) && /ServerAliveInterval 30/.test(blk));
cli.removeSshConfig({ sshDir });
check("remove drops the Include and the file", !fs.readFileSync(path.join(sshDir, "config"), "utf8").includes("Include ") && !fs.existsSync(path.join(process.env.VYOMI_HOME, "ssh_config")));
const sshDir2 = fs.mkdtempSync(path.join(os.tmpdir(), "ssh-"));
r = await cli.configureSsh({ sshDir: sshDir2, ask: async () => "n" });
check("declined -> nothing written to ~/.ssh/config", r.declined && !fs.existsSync(path.join(sshDir2, "config")));

child.kill(); vm.close();
console.log(bad ? `\n${bad} FAILED` : "\nall passed"); process.exit(bad ? 1 : 0);
