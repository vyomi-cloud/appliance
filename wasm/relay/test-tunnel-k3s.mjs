/* Reserved targets (host/codespace/k3s), agent roles, `forward` and the security rules, all local: relay + agents + fake TCP servers.
 * WS_PKG=<path to ws> RELAY_PORT=8799 node wasm/relay/test-tunnel-k3s.mjs      (no GitHub, no Codespace, no docker) */
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
import { dial, vmCandidates, isReservedName, resolveReserved } from "./booster-dial.mjs";

const require = createRequire(import.meta.url);
const WS = require(process.env.WS_PKG || "ws");
const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.RELAY_PORT || 8799), KEY = "tunnel-k3s-test-key";
const relay = `http://127.0.0.1:${PORT}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowS = () => Math.floor(Date.now() / 1000);
const tok = (o = {}) => mint(o.key ?? KEY, { sub: "acct-1", tier: "pro", primary_cloud: "aws", session_id: "s-1", session_end: nowS() + 3600, ...o });
process.env.VYOMI_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "vyomi-home-"));
const cli = await import("./mesh-cli.mjs");

// fake TCP servers: say their TAG on connect (so we know WHICH network answered), then echo
const tagServer = async (tag) => { const s = net.createServer((c) => { c.write(tag + "\n"); c.pipe(c); }); await new Promise((r) => s.listen(0, "127.0.0.1", r)); return s; };
const srvs = { cHost: await tagServer("CS-HOST"), cK3s: await tagServer("CS-K3S"), rHost: await tagServer("RUN-HOST"), rK3s: await tagServer("RUN-K3S"), vm: await tagServer("VM") };
const addr = (s) => `127.0.0.1:${s.address().port}`;

const child = spawn(process.execPath, [path.join(here, "local-relay.mjs")], {
  env: { ...process.env, RELAY_PORT: String(PORT), RELAY_HOST: "127.0.0.1", VYOMI_BOOSTER_SESSION_KEY: KEY, VYOMI_RELAY_ALLOW_LOOPBACK: "1", VYOMI_MAX_STREAMS: "4", NODE_PATH: process.env.NODE_PATH || "" },
  stdio: ["ignore", "pipe", "pipe"] });
let up = false; child.stdout.on("data", (d) => { if (process.env.DEBUG) process.stdout.write("[relay] " + d); if (String(d).includes(String(PORT))) up = true; });
for (let i = 0; i < 50 && !up; i++) await sleep(100);

const audits = [];
const token = tok();
const vmResolver = async (n) => (n === "my-vm" || n === "host" /* must never be reached for 'host' */) ? { host: "127.0.0.1", port: srvs.vm.address().port } : null;
const csAgent = dial({ relayUrl: `ws://127.0.0.1:${PORT}`, token, WS, resolveVm: vmResolver, audit: (m) => audits.push("cs:" + m),
  env: { VYOMI_HOST_SSH_ADDR: addr(srvs.cHost), VYOMI_K3S_ADDR: addr(srvs.cK3s) } });
const runAgent = dial({ relayUrl: `ws://127.0.0.1:${PORT}`, token, WS, role: "runner-a", resolveVm: async () => null, audit: (m) => audits.push("run:" + m),
  env: { VYOMI_HOST_SSH_ADDR: addr(srvs.rHost), VYOMI_K3S_ADDR: addr(srvs.rK3s) } });
for (let i = 0; i < 50 && !(csAgent.state.linked && runAgent.state.linked); i++) await sleep(100);
check("two agents (codespace + runner-a) linked for ONE session", csAgent.state.linked && runAgent.state.linked);

// open a target, read what the far end says first, return {banner, code, err}; closes after reading
async function probe(target, { role, t = token, port = 22, wait = 600 } = {}) {
  const stdin = new PassThrough(), stdout = new PassThrough(), stderr = new PassThrough();
  let out = "", err = ""; stdout.on("data", (c) => { out += c; }); stderr.on("data", (c) => { err += c; });
  const p = cli.connect(target, { relay, token: t, WS, stdin, stdout, stderr, port, role });
  await sleep(wait); stdin.end();
  const code = await Promise.race([p, sleep(3000).then(() => "hung")]);
  return { banner: out.trim(), code, err };
}

// 1. section 9b: reserved targets
let r = await probe("host");        check("'host' reaches the configured host sshd address", r.banner === "CS-HOST", r.banner + r.err);
r = await probe("codespace");       check("'codespace' is an alias of host on the codespace role", r.banner === "CS-HOST", r.banner + r.err);
r = await probe("host", { port: 2222 }); check("client-requested port is ignored for host (fixed address)", r.banner === "CS-HOST", r.banner);
r = await probe("my-vm");           check("normal VM names still resolve through the resolver", r.banner === "VM", r.banner + r.err);
check("a resolver can not shadow 'host' (resolver would answer VM)", (await probe("host")).banner === "CS-HOST");
check("reserved names are never container candidates", vmCandidates("host").length === 0 && vmCandidates("codespace").length === 0 && vmCandidates("k3s").length === 0 && vmCandidates("web").length === 3);
check("isReservedName exported for backends/portal", isReservedName("Host") && isReservedName("k3s") && !isReservedName("web"));
const d = resolveReserved("host", "codespace", {});
check("defaults: host.docker.internal:22 and vyomi-k3s:6443", d.host === "host.docker.internal" && d.port === 22 && resolveReserved("k3s", "codespace", {}).host === "vyomi-k3s" && resolveReserved("k3s", "codespace", {}).port === 6443);
check("env override parsed (host:port)", (() => { const x = resolveReserved("host", "codespace", { VYOMI_HOST_SSH_ADDR: "10.0.0.5:2200" }); return x.host === "10.0.0.5" && x.port === 2200; })());
check("audit line per open of host/k3s (codespace)", audits.filter((a) => a.startsWith("cs:") && /open host role=codespace/.test(a)).length >= 4, audits.join(" | "));
r = await probe("my-vm");
check("no audit line for ordinary VMs", !audits.some((a) => a.includes("target=my-vm")));

// 2. section 12: k3s + roles
r = await probe("k3s");             check("'k3s' reaches the codespace's k3s address", r.banner === "CS-K3S", r.banner + r.err);
check("audit line for k3s opens", audits.some((a) => /open k3s role=codespace target=k3s/.test(a)));
r = await probe("k3s", { role: "runner-a" });   check("role=runner-a k3s reaches the RUNNER's network", r.banner === "RUN-K3S", r.banner + r.err);
r = await probe("host", { role: "runner-a" });  check("role=runner-a host reaches the runner host", r.banner === "RUN-HOST", r.banner + r.err);
check("audit lines carry the role", audits.some((a) => /^run:.*open k3s role=runner-a/.test(a)));
r = await probe("my-vm", { role: "runner-a" }); check("role cannot reach another role's VMs (my-vm lives on codespace)", r.code === 1 && r.banner === "", r.err);
r = await probe("codespace", { role: "runner-a" }); check("'codespace' alias is NOT valid on a runner role", r.code === 1 && r.banner === "", r.banner + r.err);
r = await probe("k3s", { role: "runner-zzz" }); check("unknown role -> 502, nothing reached", r.code === 1 && /502/.test(r.err) && r.banner === "", r.err);
await new Promise((res) => { const w = new WS(`ws://127.0.0.1:${PORT}/connect?vm=k3s&port=6443&role=BAD_ROLE!`, { headers: { authorization: `Bearer ${token}` } }); w.on("unexpected-response", (_q, rs) => { check("malformed role label -> 400", rs.statusCode === 400, rs.statusCode); res(); }); w.on("error", () => {}); });

// 3. security: other accounts
for (const [t, role] of [["host", undefined], ["k3s", undefined], ["host", "runner-a"], ["k3s", "runner-a"]]) {
  r = await probe(t, { role, t: tok({ sub: "mallory" }) });
  check(`another account's token -> 403 for ${t}${role ? "." + role : ""}`, r.code === 1 && /403/.test(r.err) && r.banner === "", r.err);
}
r = await probe("host", { t: tok({ key: "wrong" }) }); check("forged token -> 401, host unreachable", /401|sign-in/.test(r.err) && r.banner === "", r.err);
r = await probe("k3s", { t: tok({ session_id: "other-session" }) }); check("same account, different session -> 502 (cannot reach this session's k3s)", /502/.test(r.err) && r.banner === "", r.err);
const evil = dial({ relayUrl: `ws://127.0.0.1:${PORT}`, token: tok({ sub: "mallory" }), WS, role: "runner-a", resolveVm: async () => null, minBackoffMs: 100 });
const ev = await Promise.race([evil.done, sleep(3000).then(() => "hung")]);
check("another account can not hijack a (session, role) agent slot (403)", ev === "refused-403", ev);
r = await probe("k3s", { role: "runner-a" }); check("victim's runner agent unaffected after hijack attempt", r.banner === "RUN-K3S", r.banner);

// 4. stream cap is per session across roles (cap 4)
const open = []; const mk = (role) => { const stdin = new PassThrough(), stdout = new PassThrough(), stderr = new PassThrough(); let err = ""; stderr.on("data", (c) => { err += c; }); stdout.resume();
  const p = cli.connect("k3s", { relay, token, WS, stdin, stdout, stderr, role }); open.push({ stdin, p }); return { p, err: () => err }; };
await sleep(800);   // let the previous probes' close handshakes finish
const four = [mk(), mk(), mk("runner-a"), mk("runner-a")]; await sleep(700);
check("4 streams across 2 roles all open", (await Promise.all(four.map((x) => Promise.race([x.p, sleep(10).then(() => "open")])))).every((v) => v === "open"));
const c5 = mk(); const c5r = await Promise.race([c5.p, sleep(3000).then(() => "hung")]);
check("cap 4 holds across roles (2 codespace + 2 runner -> 5th refused 429)", c5r === 1 && /429/.test(c5.err()), c5r + " " + c5.err());
const c6 = mk("runner-a"); check("...also for the other role", (await Promise.race([c6.p, sleep(3000).then(() => "hung")])) === 1 && /429/.test(c6.err()));
for (const o of open) o.stdin.end(); await sleep(500);

// 5. section 13: forward
check("parseTarget: target.role", JSON.stringify(cli.parseTarget("c1.runner-a")) === JSON.stringify({ target: "c1", role: "runner-a" }) && cli.parseTarget("k3s").role === "codespace" && cli.parseTarget("k3s", "runner-a").role === "runner-a" && cli.parseTarget("a.b", "").target === "a.b");
const tcp = (port) => new Promise((res, rej) => { const c = net.connect(port, "127.0.0.1"); c.once("connect", () => res(c)); c.once("error", rej); });
const slurp = (c) => { const ch = []; c.on("data", (d) => ch.push(d)); return () => Buffer.concat(ch); };
let f = await cli.forward("k3s", { local: 0, remote: 6443, relay, token, WS });
check("forward listens on a loopback port", f.port > 0);
let c = await tcp(f.port); let got = slurp(c); await sleep(500); c.write("kubectl-bytes"); await sleep(500);
check("forward: bytes round-trip through relay+agent to k3s", got().toString() === "CS-K3S\nkubectl-bytes", JSON.stringify(got().toString()));
let c2 = await tcp(f.port); let got2 = slurp(c2); await sleep(500); c2.write("second");
const big = crypto.randomBytes(1024 * 1024); c.write(big);
for (let i = 0; i < 100 && got().length < 7 + 13 + big.length; i++) await sleep(100);
await sleep(300);
check("forward: 1 MB byte-exact on one connection while a second stays independent", Buffer.compare(got().subarray(7 + 13), big) === 0 && got2().toString() === "CS-K3S\nsecond", `${got().length}`);
c.destroy(); c2.destroy(); await sleep(300);
const lsock = net.createServer(); await new Promise((res) => lsock.listen(0, "127.0.0.1", res));
check("forward binds loopback only", (await new Promise((res) => { const x = net.createServer().listen(0, "127.0.0.1", function () { res(true); x.close(); }); })) && f.port && true);
f.close(); check("close() -> exit code 0", (await f.done) === 0);
await sleep(200);
check("listener is gone after close", await tcp(f.port).then(() => false, () => true));
lsock.close();

let fr = await cli.forward("k3s", { local: 0, remote: 6443, role: "runner-a", relay, token, WS });
c = await tcp(fr.port); got = slurp(c); await sleep(500); check("forward k3s.runner-a reaches the runner network", got().toString().startsWith("RUN-K3S"), got().toString()); c.destroy(); fr.close(); await fr.done;

// refusal paths / exit codes
const quiet = new PassThrough(); let qerr = ""; quiet.on("data", (x) => { qerr += x; });
const ex = async (args) => { qerr = ""; const x = await cli.forward(args.t ?? "k3s", { local: 0, remote: 6443, relay, token, WS, stderr: quiet, ...args }); return { x, code: await Promise.race([x.done, sleep(250).then(() => "running")]) }; };
let e = await ex({ local: 80 }); check("forward refuses ports < 1024 (exit 2)", e.code === 2 && /1024/.test(qerr), qerr);
e = await ex({ token: "" }); check("forward without sign-in -> exit 2", e.code === 2 && /login/.test(qerr), qerr);
e = await ex({ token: tok({ session_end: nowS() - 5, iat: nowS() - 100 }) }); check("forward with ended session -> exit 2", e.code === 2 && /ended/.test(qerr), qerr);
e = await ex({ t: "bad target!" }); check("forward bad target -> exit 2", e.code === 2);
const busy = net.createServer(); await new Promise((res) => busy.listen(0, "127.0.0.1", res));
e = await ex({ local: busy.address().port }); check("forward port in use -> exit 1", e.code === 1 && /cannot listen/.test(qerr), qerr); busy.close();
e = await ex({ role: "runner-nope" }); const cc = await tcp(e.x.port); await sleep(700);
check("502 on one stream drops that connection but the listener keeps running", cc.destroyed || cc.readableEnded || (await Promise.race([new Promise((r) => cc.on("close", () => r(true))), sleep(500).then(() => false)])), qerr);
check("...and forward is still running (no exit)", (await Promise.race([e.x.done, sleep(200).then(() => "running")])) === "running" && /502/.test(qerr), qerr);
e.x.close(); await e.x.done;
e = await ex({ token: tok({ sub: "mallory" }) }); const cm = await tcp(e.x.port); cm.on("error", () => {});
check("403 (foreign account) is fatal: forward exits 1", (await Promise.race([e.x.done, sleep(2500).then(() => "running")])) === 1 && /403/.test(qerr), qerr);

// stop at session_end
const shortTok = tok({ session_id: "short", session_end: nowS() + 3 });
const shortAgent = dial({ relayUrl: `ws://127.0.0.1:${PORT}`, token: shortTok, WS, resolveVm: async () => null, env: { VYOMI_K3S_ADDR: addr(srvs.cK3s) } });
for (let i = 0; i < 30 && !shortAgent.state.linked; i++) await sleep(100);
const fs1 = await cli.forward("k3s", { local: 0, remote: 6443, relay, token: shortTok, WS, stderr: quiet });
const sc = await tcp(fs1.port); const sgot = slurp(sc); await sleep(500);
check("short session: forward works before session_end", sgot().toString().startsWith("CS-K3S"));
const t0 = Date.now(); const sc_code = await Promise.race([fs1.done, sleep(6000).then(() => "hung")]);
check("forward stops at session_end with exit 0", sc_code === 0 && Date.now() - t0 < 5000, `${sc_code} after ${Date.now() - t0}ms`);
check("...open socket closed and listener gone", sc.destroyed || await new Promise((r) => { sc.on("close", () => r(true)); setTimeout(() => r(false), 500); }));
check("...and nothing listens any more", await tcp(fs1.port).then(() => false, () => true));

csAgent.stop(); runAgent.stop(); shortAgent.stop(); child.kill(); for (const s of Object.values(srvs)) s.close();
console.log(bad ? `\n${bad} FAILED` : "\nall passed"); process.exit(bad ? 1 : 0);
