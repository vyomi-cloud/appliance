/* vyomi-tunnel Mesh/SSH client:  vyomi-tunnel login | config | connect <vm> | status
 *
 *   ssh my-vm.vyomi  ->  ProxyCommand "vyomi-tunnel connect %h"  ->  wss://<relay>/connect?vm=my-vm  (raw TCP bytes as binary WS)
 *   -> the Mesh agent in the Codespace -> the VM's sshd:22.  `ssh` still does the handshake/auth/encryption end to end; this only
 *   carries bytes, so it never sees the key.
 *
 * State lives in ~/.vyomi/ (override with VYOMI_HOME): session.json {relay, token}, ssh_config, known_hosts.
 * Env overrides: VYOMI_RELAY_URL, VYOMI_SESSION_TOKEN.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import net from "node:net";
import crypto from "node:crypto";
import readline from "node:readline";
import { spawn } from "node:child_process";
import { requireSession } from "./credentials.mjs";
import { createRequire } from "node:module";
import { keep } from "./keeper.mjs";

const HOME = process.env.VYOMI_HOME || path.join(os.homedir(), ".vyomi");
const SESSION = path.join(HOME, "session.json");
const SSH_CONF = path.join(HOME, "ssh_config");
const DEFAULT_RELAY = "https://relay.vyomi.cloud";
const DEFAULT_PORTAL = "https://vyomi.cloud";
export const SUFFIX = ".vyomi";

export const vmName = (host) => String(host || "").replace(/\.vyomi\.?$/i, "");
const wsUrl = (relay) => relay.replace(/\/$/, "").replace(/^http/, "ws");

function load() {
  let s = {}; try { s = JSON.parse(fs.readFileSync(SESSION, "utf8")); } catch { /* none yet */ }
  return { relay: process.env.VYOMI_RELAY_URL || s.relay || DEFAULT_RELAY, token: process.env.VYOMI_SESSION_TOKEN || s.token || "" };
}
function save(o) {
  fs.mkdirSync(HOME, { recursive: true, mode: 0o700 });
  fs.writeFileSync(SESSION, JSON.stringify(o, null, 2), { mode: 0o600 });
}
const tokenEnd = (t) => { try { return Number(JSON.parse(Buffer.from(String(t).split(".")[1], "base64url").toString()).session_end); } catch { return NaN; } };

/** `connect`: pipe stdin/stdout through the relay to the VM. Resolves with the process exit code. */
export function connect(vm, { port = 22, relay, token, WS, stdin = process.stdin, stdout = process.stdout, stderr = process.stderr } = {}) {
  return new Promise((resolve) => {
    if (!token) { stderr.write("vyomi-tunnel: not signed in. Run `vyomi-tunnel login` (and start Mesh in the Vyomi console).\n"); return resolve(2); }
    const end = tokenEnd(token);
    if (Number.isFinite(end) && Date.now() >= end * 1000) { stderr.write("vyomi-tunnel: your Mesh session has ended. Start Mesh again, then run `vyomi-tunnel login`.\n"); return resolve(2); }
    const ws = new WS(`${wsUrl(relay)}/connect?vm=${encodeURIComponent(vm)}&port=${port}`, { headers: { authorization: `Bearer ${token}` } });
    let done = false, refused = false;
    const finish = (code) => { if (done) return; done = true; try { stdin.pause(); } catch { /* */ } try { ws.close(); } catch { /* */ } resolve(code); };
    ws.on("unexpected-response", (_rq, res) => {
      const why = { 401: "sign-in expired - run `vyomi-tunnel login`", 403: "not allowed for this session", 410: "Mesh session ended",
                    502: "Mesh is not running (start it in the Vyomi console)", 429: "too many open connections" }[res.statusCode] || "refused";
      refused = true; stderr.write(`vyomi-tunnel: ${vm}: ${why} (HTTP ${res.statusCode})\n`); finish(1);
    });
    ws.on("open", () => {
      stdin.on("data", (d) => { if (ws.readyState === 1) { for (let i = 0; i < d.length; i += 32768) ws.send(d.subarray(i, i + 32768), { binary: true });   // relay caps frames at 64 KiB
        if (ws.bufferedAmount > 1 << 20) { stdin.pause(); const t = setInterval(() => { if (ws.bufferedAmount < 1 << 16) { clearInterval(t); stdin.resume(); } }, 20); } } });
      stdin.on("end", () => finish(0));
    });
    ws.on("message", (d, isBinary) => { if (isBinary) stdout.write(d); });
    ws.on("close", (code) => finish(code === 1000 || code === 1005 ? 0 : 1));
    ws.on("error", (e) => { if (!refused) stderr.write(`vyomi-tunnel: ${e.message}\n`); finish(1); });
  });
}

/** `forward`: listen on 127.0.0.1:<local>; each accepted socket becomes one /connect stream to <target>:<remote>.
 *  Resolves {close(), done: Promise<exitCode>, port} once listening. Exit codes: 0 session_end / closed, 1 refused (401/403/410) or listener
 *  error, 2 usage / not signed in / session ended. Refusal of a single stream (502, 429) only drops that connection. */
export function forward(target, { local, remote, relay, token, WS, allowPrivileged = false, stderr = process.stderr } = {}) {
  return new Promise((resolveStart) => {
    const fail = (code, msg) => { if (msg) stderr.write(msg + "\n"); resolveStart({ close() {}, done: Promise.resolve(code), port: 0 }); };
    if (!token) return fail(2, "vyomi-tunnel: not signed in. Run `vyomi-tunnel login` (and start Mesh in the Vyomi console).");
    if (!/^[A-Za-z0-9._-]{1,80}$/.test(target || "")) return fail(2, "vyomi-tunnel: bad target");
    if (!(Number.isInteger(local) && local >= 0 && local < 65536) || !(Number.isInteger(remote) && remote > 0 && remote < 65536)) return fail(2, "vyomi-tunnel: ports must be 1-65535");
    if (local > 0 && local < 1024 && !allowPrivileged) return fail(2, "vyomi-tunnel: local ports below 1024 need --allow-privileged");
    const end = tokenEnd(token);
    if (Number.isFinite(end) && Date.now() >= end * 1000) return fail(2, "vyomi-tunnel: your Mesh session has ended. Start Mesh again, then run `vyomi-tunnel login`.");
    const socks = new Set();
    let resolveDone, finished = false, endTimer = null, started = false;
    const done = new Promise((r) => { resolveDone = r; });
    const srv = net.createServer();
    const finish = (code, msg) => {
      if (finished) return; finished = true; clearTimeout(endTimer);
      if (msg) stderr.write(msg + "\n");
      try { srv.close(); } catch { /* */ }
      for (const x of socks) { try { x.destroy(); } catch { /* */ } }
      resolveDone(code);
    };
    srv.on("error", (e) => { finish(1, `vyomi-tunnel: cannot listen on 127.0.0.1:${local}: ${e.message}`); if (!started) { started = true; resolveStart({ close() {}, done, port: 0 }); } });
    srv.on("connection", (sock) => {
      socks.add(sock); sock.setNoDelay(true);
      const ws = new WS(`${wsUrl(relay)}/connect?vm=${encodeURIComponent(target)}&port=${remote}`, { headers: { authorization: `Bearer ${token}` } });
      let open = false; const queue = [];
      const drop = () => { socks.delete(sock); try { sock.destroy(); } catch { /* */ } try { ws.close(); } catch { /* */ } };
      ws.on("unexpected-response", (_rq, res) => {
        const why = { 401: "sign-in expired - run `vyomi-tunnel login`", 403: "not allowed for this session", 410: "Mesh session ended",
                      502: "the Mesh agent is not running", 429: "too many open connections" }[res.statusCode] || "refused";
        stderr.write(`vyomi-tunnel: ${target}: ${why} (HTTP ${res.statusCode})\n`);
        drop(); if ([401, 403, 410].includes(res.statusCode)) finish(1);
      });
      ws.on("open", () => { open = true; for (const q of queue) ws.send(q, { binary: true }); queue.length = 0; });
      ws.on("message", (d, isBinary) => { if (isBinary && !sock.destroyed) sock.write(d); });
      ws.on("close", drop); ws.on("error", drop);
      sock.on("data", (d) => { if (open) ws.send(d, { binary: true }); else queue.push(d); });
      sock.on("close", drop); sock.on("error", drop);
    });
    srv.listen(local, "127.0.0.1", () => {
      started = true;
      if (Number.isFinite(end)) endTimer = setTimeout(() => finish(0, "vyomi-tunnel: Mesh session ended; forward stopped."), Math.max(0, end * 1000 - Date.now()));
      resolveStart({ close: () => finish(0), done, port: srv.address().port });
    });
  });
}

/** `config`: write ~/.vyomi/ssh_config and add ONE Include line to ~/.ssh/config (asks first unless yes). */
export async function configureSsh({ yes = false, cmd = "vyomi-tunnel", sshDir = path.join(os.homedir(), ".ssh"), ask } = {}) {
  fs.mkdirSync(HOME, { recursive: true, mode: 0o700 });
  const block = [
    "# Written by `vyomi-tunnel config`. Remove with `vyomi-tunnel config --remove`.",
    // The Mesh Codespace's sshd trusts the key `gh codespace ssh` generates, for the `vscode` user. Without these two lines plain
    // `ssh host.vyomi` offers the local user + default keys and gets "Permission denied (publickey)". Specific stanza first: ssh keeps
    // the first value it finds for each option.
    `Host host${SUFFIX}`,
    "  User vscode",
    `  IdentityFile ${path.join(os.homedir(), ".ssh", "codespaces.auto")}`,
    "  IdentitiesOnly yes",
    "",
    `Host *${SUFFIX}`,
    `  ProxyCommand ${cmd} connect %h`,
    "  ServerAliveInterval 30",
    "  ServerAliveCountMax 4",
    "  StrictHostKeyChecking accept-new",
    `  UserKnownHostsFile ${path.join(HOME, "known_hosts")}`,
    "",
  ].join("\n");
  fs.writeFileSync(SSH_CONF, block, { mode: 0o600 });
  const main = path.join(sshDir, "config"), inc = `Include ${SSH_CONF}`;
  let cur = ""; try { cur = fs.readFileSync(main, "utf8"); } catch { /* none */ }
  if (cur.split("\n").some((l) => l.trim() === inc)) return { changed: false, file: main };
  if (!yes) { const a = ask ? await ask(`Add "${inc}" to ${main}? [y/N] `) : "n"; if (!/^y/i.test(a)) return { changed: false, declined: true, file: main, include: inc }; }
  fs.mkdirSync(sshDir, { recursive: true, mode: 0o700 });
  fs.writeFileSync(main, inc + "\n\n" + cur, { mode: 0o600 });          // Include must come first to apply to all hosts
  return { changed: true, file: main };
}
export function removeSshConfig({ sshDir = path.join(os.homedir(), ".ssh") } = {}) {
  const main = path.join(sshDir, "config"), inc = `Include ${SSH_CONF}`;
  try { const cur = fs.readFileSync(main, "utf8"); fs.writeFileSync(main, cur.split("\n").filter((l) => l.trim() !== inc).join("\n").replace(/^\n+/, "")); } catch { /* none */ }
  try { fs.rmSync(SSH_CONF); } catch { /* none */ }
}

/** `login`: browser sign-in. The portal redirects to http://127.0.0.1:<port>/cb?state=..&token=..&relay=..; we store the token. */
export function login({ portal = DEFAULT_PORTAL, open = openBrowser, log = console.log, timeoutMs = 300000 } = {}) {
  return new Promise((resolve, reject) => {
    const state = crypto.randomBytes(16).toString("hex");
    const srv = http.createServer((req, res) => {
      const u = new URL(req.url, "http://x");
      if (u.pathname !== "/cb") { res.writeHead(404).end(); return; }
      const token = u.searchParams.get("token") || "", relay = u.searchParams.get("relay") || "";
      if (u.searchParams.get("state") !== state || !token) { res.writeHead(400).end("bad state"); return; }
      save({ relay: relay || DEFAULT_RELAY, token });
      res.writeHead(200, { "content-type": "text/html" }).end("<!doctype html><meta charset=utf-8><title>Vyomi</title><body style='font:16px system-ui;padding:3rem'>Signed in. You can close this tab and return to your terminal.</body>");
      clearTimeout(t); srv.close(); resolve({ relay, token });
    });
    const t = setTimeout(() => { srv.close(); reject(new Error("login timed out")); }, timeoutMs);
    srv.listen(0, "127.0.0.1", () => {
      const url = `${portal.replace(/\/$/, "")}/mesh/cli-login?port=${srv.address().port}&state=${state}`;
      log(`Opening ${url}\nIf the browser does not open, paste that address into it.`);
      open(url);
    });
  });
}
function openBrowser(url) {
  const [c, ...a] = process.platform === "darwin" ? ["open", url] : process.platform === "win32" ? ["cmd", "/c", "start", "", url] : ["xdg-open", url];
  try { spawn(c, a, { stdio: "ignore", detached: true }).unref(); } catch { /* user pastes it */ }
}


const HELP = `vyomi-tunnel - connect your machine to Vyomi

  vyomi-tunnel list [nano|mesh|all] [type]
                          show what you can reach, and how
  ssh <name>.vyomi        connect to the Codespace, a Docker instance or k3s
  vyomi-tunnel forward <name> <local>:<remote>
                          forward a port, e.g. forward k3s 6443:6443
  vyomi-tunnel            start the local relay for the Nano console

Everything needs a key (Free works for Nano; Mesh needs Pro or Max).
Get one: 'vyomi-tunnel help credentials'.
`;
const DETAILS = {
  credentials: `Mesh credentials (like ~/.aws/credentials)

Where to get it: https://vyomi.cloud/account/tunnel-credentials
(in the console: avatar menu > Access Key)

1. Create an access key. The secret is shown once, so download it.
2. Save the downloaded file as ~/.vyomi/credentials (it looks like this):

   [default]
   vyomi_access_key_id     = VYKA...
   vyomi_secret_access_key = ...

Or set VYOMI_ACCESS_KEY_ID and VYOMI_SECRET_ACCESS_KEY.
Use another profile with VYOMI_PROFILE. A Free key covers Nano; Mesh needs Pro or Max.
The first Mesh command also sets up 'ssh <name>.vyomi' for you.`,
  list: `vyomi-tunnel list [nano|mesh|all] [type] [--json]

Shows what you can reach right now, and the command for each.
  nano    the Nano endpoint, browser VMs and databases
  mesh    your Mesh Codespace: host, Docker instances, k3s, LLMs, services, and your forwards
  all     everything (the default)
Add a type to narrow it:
  vyomi-tunnel list nano vm        (also: api, db)
  vyomi-tunnel list mesh k3s       (also: host, instance, llm, service, forward)
A type alone works too: vyomi-tunnel list vm`,
  forward: `vyomi-tunnel forward <name> <local>:<remote>

Listen on 127.0.0.1:<local> and forward to <name>:<remote> in your Mesh Codespace.
  vyomi-tunnel forward k3s 6443:6443
  vyomi-tunnel forward host 2222:22`,
};
export const helpText = (topic) => (topic && DETAILS[topic]) || HELP;

/** Credentials -> Vyomi session -> an ssh transport to the user's Mesh Codespace. Returns {transport, sess} or {error, code}. */
async function openMesh({ cs, log = () => {} } = {}) {
  const { createSessionManager } = await import("./credentials.mjs");
  const ssh = await import("./mesh-ssh.mjs");
  let sess; try { sess = await createSessionManager({ log }).get(); } catch (e) { return { error: e.message, code: e.code }; }
  if (!sess.meshAllowed) return { error: "Mesh needs a Pro or Max plan.", code: "PlanNotAllowed" };
  try { await configureSsh({ yes: true }); } catch { /* ssh setup is best effort */ }
  const transport = ssh.createSshTransport({ codespace: cs || sess.codespace || null, env: sess.githubToken ? { GH_TOKEN: sess.githubToken } : {}, log });
  if (sess.sessionEnd) transport.stopAt(sess.sessionEnd);
  return { transport, sess };
}

export async function main(argv) {
  const [cmd, ...rest] = argv;
  if (!cmd || ["help", "-h", "--help", "-help", "-?"].includes(cmd) || rest.some((a) => ["-h", "--help", "-help"].includes(a))) { const topic = cmd === "help" ? rest[0] : (["-h", "--help", "-help", "-?"].includes(cmd) ? undefined : cmd); const t = topic && DETAILS[topic];
    if (topic && !t) { console.error(`vyomi-tunnel: no help for "${topic}".`); process.stdout.write(HELP); return 2; }
    process.stdout.write((t || HELP) + (t ? "\n" : "")); return cmd ? 0 : 2; }
  if (cmd === "--version" || cmd === "-v" || cmd === "version") { console.log(process.env.VYOMI_TUNNEL_VERSION || "vyomi-tunnel 1.2.0"); return 0; }
  const WS = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
  // Mesh over the user's own ssh session (`--codespace <name>` or VYOMI_MESH_CODESPACE): no relay, no token (mesh-ssh.mjs).
  const ci = rest.indexOf("--codespace");
  const cs = ci >= 0 ? rest[ci + 1] : process.env.VYOMI_MESH_CODESPACE;      // optional: normally found automatically on the user's account
  if (ci >= 0) rest.splice(ci, 2);
  const ri = rest.indexOf("--relay-mode"); if (ri >= 0) rest.splice(ri, 1);   // legacy portal-token relay path
  if (ri < 0 && (cmd === "connect" || cmd === "forward")) {
    const ssh = await import("./mesh-ssh.mjs");
    const o = await openMesh({ cs, log: (m) => console.error("vyomi-tunnel: " + m) });
    if (o.error) { console.error("vyomi-tunnel: " + o.error); return o.code === "NoCredentials" ? 2 : 1; }
    const transport = o.transport;
    transport.onStop(() => console.error("vyomi-tunnel: your Mesh session has ended."));
    try {
      if (cmd === "connect") { const vm = vmName(rest[0]); if (!vm) { console.error("usage: vyomi-tunnel connect <vm>[.vyomi] [port]"); return 2; } return await ssh.connectSsh(vm, { port: Number(rest[1] || 22), transport }); }
      const pos = rest.filter((x) => !x.startsWith("--")); const m = /^(\d{1,5}):(\d{1,5})$/.exec(pos[1] || "");
      if (!pos[0] || !m) { console.error("usage: vyomi-tunnel forward <target> <local>:<remote> --codespace <name>"); return 2; }
      const f = await ssh.forwardSsh(vmName(pos[0]), { local: Number(m[1]), remote: Number(m[2]), transport, net });
      if (f.port) console.error(`forwarding 127.0.0.1:${f.port} -> ${vmName(pos[0])}:${m[2]} via ${transport.codespace} (Ctrl-C to stop)`);
      let reg = null; if (f.port) { try { fs.mkdirSync(path.join(HOME, "forwards"), { recursive: true }); reg = path.join(HOME, "forwards", `${process.pid}.json`);
        fs.writeFileSync(reg, JSON.stringify({ pid: process.pid, target: vmName(pos[0]), local: f.port, remote: Number(m[2]), codespace: transport.codespace, started: new Date().toISOString() })); } catch { /* list just won't show it */ } }
      for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => f.close());
      transport.onStop(() => f.close());
      f.done.then(() => { try { reg && fs.rmSync(reg); } catch { /* */ } });
      return await f.done;
    } catch (e) { console.error("vyomi-tunnel: " + e.message); return 1; }
    finally { transport.close(); }
  }
  if (cmd === "login" || cmd === "gh-login") {                         // there is no login: credentials live in a file, like ~/.aws/credentials
    console.error("vyomi-tunnel has no login. Save your access key as ~/.vyomi/credentials (console: avatar menu > Access Key). Run `vyomi-tunnel help credentials`.");
    return 2;
  }
  if (cmd === "list" || cmd === "ls") {                                // every transport line, with the command to use it
    const json = rest.includes("--json"); const pos = rest.filter((x) => !x.startsWith("-"));
    const auth = await requireSession();                                                                // nothing is listed without a valid key, Nano included
    if (auth.error) { console.error("vyomi-tunnel: " + auth.error); return auth.code === "NoCredentials" ? 2 : 1; }
    const KINDS = ["api", "vm", "db", "host", "instance", "k3s", "llm", "service", "forward"];
    const SCOPES = { nano: ["api", "vm", "db"], mesh: ["host", "instance", "k3s", "llm", "service", "forward"], all: KINDS };      // forwards go to a Mesh target
    const norm = (w) => { w = String(w || "").toLowerCase(); return w === "k3s" || KINDS.includes(w) || SCOPES[w] ? w : w.replace(/(s|es)$/, "") && KINDS.includes(w.replace(/s$/, "")) ? w.replace(/s$/, "") : w; };   // vms -> vm, dbs -> db
    let want = norm(pos[0]), kinds = SCOPES[want] || (want ? [want] : KINDS);
    if (pos[1]) {                                                                                                               // list <scope> <type>
      const t = norm(pos[1]);
      if (!SCOPES[want] || want === "all") { console.error(`vyomi-tunnel: "${pos[0]}" cannot take a type. Use: list nano|mesh <type>`); return 2; }
      if (!SCOPES[want].includes(t)) { console.error(`vyomi-tunnel: "${pos[1]}" is not a ${want} type. ${want} types: ${SCOPES[want].join(", ")}`); return 2; }
      kinds = [t]; want = t;
    } else if (want && !KINDS.includes(want) && !SCOPES[want]) { console.error(`vyomi-tunnel: unknown "${pos[0]}". Use: nano, mesh, all, or a type (${KINDS.join(", ")})`); return 2; }
    const rows = []; const notes = [];
    let transport = null, meshP = Promise.resolve(null);
    if (kinds.some((k) => ["host", "instance", "k3s", "llm", "service"].includes(k))) {                    // Mesh also needs a plan that allows it
      const o = await openMesh({ cs });
      if (o.error) meshP = Promise.resolve({ err: o.error });
      else { transport = o.transport; meshP = transport.list().then((ts) => ({ ts, cs: transport.codespace })).catch((e) => ({ err: e.message })); }
    }
    const port = process.env.RELAY_PORT || 8090;
    if (kinds.some((k) => ["api", "vm", "db"].includes(k))) try {
      const h = await (await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(1500) })).json();
      rows.push({ where: "local", name: "nano-api", type: "api", address: `http://127.0.0.1:${port}`, connect: `aws --endpoint-url http://127.0.0.1:${port} ...   (tab ${h.tab ? "connected" : "NOT connected"})` });
      for (const v of h.vms || []) rows.push({ where: "browser", name: v.vm, type: "vm", address: `127.0.0.1:${v.host_port}`, connect: `ssh -p ${v.host_port} user@127.0.0.1` });
      for (const d of h.dbs || []) rows.push({ where: "browser", name: d.db, type: "db", address: `127.0.0.1:${d.host_port}`, connect: `${d.engine || "db"} client -> 127.0.0.1:${d.host_port}` });
    } catch { notes.push(`local relay not running on :${port} (run: vyomi-tunnel)`); }
    const m = await meshP;
    if (m && m.err) notes.push("mesh: " + m.err);
    else if (m) for (const t of m.ts) {
      const how = t.kind === "k3s" ? `vyomi-tunnel forward ${t.name} 6443:6443` : t.ssh ? `ssh ${t.name}${SUFFIX}` : t.ports.length ? `vyomi-tunnel forward ${t.name} ${t.ports[0]}:${t.ports[0]}` : "";
      rows.push({ where: "mesh", name: t.name, type: t.kind, address: t.ip ? t.ip + (t.ports[0] ? ":" + t.ports[0] : "") : "", connect: how });
    }
    transport?.close();
    try { for (const f of fs.readdirSync(path.join(HOME, "forwards"))) {                       // active forwards (one file per running `forward`)
      const fp = path.join(HOME, "forwards", f); let d; try { d = JSON.parse(fs.readFileSync(fp, "utf8")); } catch { continue; }
      let alive = true; try { process.kill(d.pid, 0); } catch { alive = false; }
      if (!alive) { try { fs.rmSync(fp); } catch { /* */ } continue; }
      rows.push({ where: "local", name: `${d.target}`, type: "forward", address: `127.0.0.1:${d.local}`, connect: `-> ${d.target}:${d.remote} (pid ${d.pid})` });
    } } catch { /* none */ }
    const out = rows.filter((r) => kinds.includes(r.type));
    if (json) { console.log(JSON.stringify({ targets: out, notes }, null, 2)); return out.length ? 0 : 1; }
    const w = [9, 22, 10, 22]; const line = (r) => [r.where, r.name, r.type, r.address].map((c, i) => String(c).padEnd(w[i])).join(" ") + " " + r.connect;
    if (out.length) { console.log(line({ where: "WHERE", name: "NAME", type: "TYPE", address: "ADDRESS", connect: "CONNECT" })); for (const r of out) console.log(line(r)); }
    else console.log(want && want !== "all" ? `No ${want} targets right now.` : "Nothing reachable right now.");
    for (const n of notes) console.log(`\n! ${n}`);
    return out.length ? 0 : 1;
  }
  if (cmd === "connect") {
    const vm = vmName(rest[0]); if (!vm) { console.error("usage: vyomi-tunnel connect <vm>[.vyomi] [port]"); return 2; }
    const { relay, token } = load();
    return connect(vm, { port: Number(rest[1] || 22), relay, token, WS });
  }
  if (cmd === "forward") {
    const pos = rest.filter((x) => !x.startsWith("--"));
    const m = /^(\d{1,5}):(\d{1,5})$/.exec(pos[1] || "");
    if (!pos[0] || !m) { console.error("usage: vyomi-tunnel forward <target> <local>:<remote> [--allow-privileged]\n  e.g. vyomi-tunnel forward vyomi-k3s-<id> 6443:6443   (then kubectl --server https://127.0.0.1:6443)"); return 2; }
    const { relay, token } = load();
    const f = await forward(vmName(pos[0]), { local: Number(m[1]), remote: Number(m[2]), relay, token, WS, allowPrivileged: rest.includes("--allow-privileged") });
    if (f.port) console.error(`forwarding 127.0.0.1:${f.port} -> ${vmName(pos[0])}:${m[2]} (Ctrl-C to stop)`);
    for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => f.close());
    return f.done;
  }
  if (cmd === "relay-login") {                                        // legacy: Vyomi portal token for the old relay path
    const i = rest.indexOf("--token");
    if (i >= 0) { const { relay } = load(); save({ relay: rest[rest.indexOf("--relay") + 1] || relay, token: rest[i + 1] }); console.log("Saved."); return 0; }
    try { await login({ portal: process.env.VYOMI_PORTAL_URL || DEFAULT_PORTAL }); console.log("Signed in."); } catch (e) { console.error("vyomi-tunnel login: " + e.message); return 1; }
    const r = await configureSsh({ ask: (q) => new Promise((ok) => { const rl = readline.createInterface({ input: process.stdin, output: process.stdout }); rl.question(q, (a) => { rl.close(); ok(a); }); }) });
    console.log(r.changed ? `Added to ${r.file}. Try: ssh <vm>${SUFFIX}` : r.declined ? `Skipped. Add this line to ${r.file} yourself: ${r.include}` : "SSH config already set up.");
    return 0;
  }
  if (cmd === "config") {
    if (rest.includes("--remove")) { removeSshConfig(); console.log("Removed."); return 0; }
    const r = await configureSsh({ yes: rest.includes("--yes") || rest.includes("-y"), ask: (q) => new Promise((ok) => { const rl = readline.createInterface({ input: process.stdin, output: process.stdout }); rl.question(q, (a) => { rl.close(); ok(a); }); }) });
    console.log(r.changed ? `Added to ${r.file}.` : r.declined ? `Skipped. Add this line to ${r.file}: ${r.include}` : "Already set up.");
    return 0;
  }
  if (cmd === "status") {
    const { relay, token } = load(); const end = tokenEnd(token);
    console.log(token ? `signed in; relay ${relay}; session ${Number.isFinite(end) ? (Date.now() < end * 1000 ? "ends " + new Date(end * 1000).toISOString() : "ENDED") : "unknown"}` : "not signed in");
    return 0;
  }
  if (cmd === "keep") {                       // hold an ssh session to the Codespace host and write to it, to renew GitHub's idle timer
    const opt = (n, d) => { const i = rest.indexOf(n); return i >= 0 ? rest[i + 1] : d; };
    const { token } = load(); if (!token) { console.error("vyomi-tunnel: not signed in. Run `vyomi-tunnel login`."); return 2; }
    const end = tokenEnd(token);
    const k = keep({ user: opt("--user", "vscode"), key: opt("--key"), proxy: opt("--proxy", "vyomi-tunnel connect codespace"),
                     intervalMs: Number(opt("--interval", 240)) * 1000, sessionEndMs: Number.isFinite(end) ? end * 1000 : Infinity,
                     onStatus: (s) => { if (s.state === "stopped") console.log(`keeper stopped: ${s.reason}`); }, log: (m) => console.error(m) });
    for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => k.stop());
    const s = await k.done; return s.reason === "too many failed connects" ? 1 : 0;
  }
  console.error(`vyomi-tunnel: unknown command "${cmd}". Run \`vyomi-tunnel help\`.`); return 2;
}
