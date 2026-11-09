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
export function connect(vm, { port = 22, role = "codespace", relay, token, WS, stdin = process.stdin, stdout = process.stdout, stderr = process.stderr } = {}) {
  return new Promise((resolve) => {
    if (!token) { stderr.write("vyomi-tunnel: not signed in. Run `vyomi-tunnel login` (and start Mesh in the Vyomi console).\n"); return resolve(2); }
    const end = tokenEnd(token);
    if (Number.isFinite(end) && Date.now() >= end * 1000) { stderr.write("vyomi-tunnel: your Mesh session has ended. Start Mesh again, then run `vyomi-tunnel login`.\n"); return resolve(2); }
    const ws = new WS(`${wsUrl(relay)}/connect?vm=${encodeURIComponent(vm)}&port=${port}${role !== "codespace" ? "&role=" + encodeURIComponent(role) : ""}`, { headers: { authorization: `Bearer ${token}` } });
    let done = false, refused = false;
    const finish = (code) => { if (done) return; done = true; try { stdin.pause(); } catch { /* */ } try { ws.close(); } catch { /* */ } resolve(code); };
    ws.on("unexpected-response", (_rq, res) => {
      const why = { 401: "sign-in expired - run `vyomi-tunnel login`", 403: "not allowed for this session", 410: "Mesh session ended",
                    502: "Mesh is not running (start it in the Vyomi console)", 429: "too many open connections" }[res.statusCode] || "refused";
      refused = true; stderr.write(`vyomi-tunnel: ${vm}: ${why} (HTTP ${res.statusCode})\n`); finish(1);
    });
    ws.on("open", () => {
      stdin.on("data", (d) => { if (ws.readyState === 1) { ws.send(d, { binary: true }); if (ws.bufferedAmount > 1 << 20) { stdin.pause(); const t = setInterval(() => { if (ws.bufferedAmount < 1 << 16) { clearInterval(t); stdin.resume(); } }, 20); } } });
      stdin.on("end", () => finish(0));
    });
    ws.on("message", (d, isBinary) => { if (isBinary) stdout.write(d); });
    ws.on("close", (code) => finish(code === 1000 || code === 1005 ? 0 : 1));
    ws.on("error", (e) => { if (!refused) stderr.write(`vyomi-tunnel: ${e.message}\n`); finish(1); });
  });
}

const ROLE_RE = /^[a-z0-9][a-z0-9-]{0,40}$/;
/** `forward` target syntax: <target>[.<role>] (or an explicit role). A name with a dot is read as target.role when the suffix is a valid
 *  role label; pass `--role` to force the whole string to be the target. */
export function parseTarget(arg, explicitRole) {
  const a = vmName(arg);
  if (explicitRole !== undefined) return { target: a, role: explicitRole };
  const i = a.lastIndexOf(".");
  if (i > 0 && ROLE_RE.test(a.slice(i + 1))) return { target: a.slice(0, i), role: a.slice(i + 1) };
  return { target: a, role: "codespace" };
}

/** `forward`: listen on 127.0.0.1:<local>; every accepted socket becomes one /connect stream to <target>:<remote> (in <role>).
 *  Resolves {close(), done: Promise<exitCode>, port} once listening. Exit codes: 0 session_end / closed, 1 refused (401/403/410) or
 *  listener error, 2 usage / not signed in / session already ended. A refusal of a single stream (502 not running, 429 cap) only
 *  drops that connection; the listener keeps running. */
export function forward(target, { local, remote, role = "codespace", relay, token, WS, allowPrivileged = false, stderr = process.stderr } = {}) {
  return new Promise((resolveStart) => {
    const fail = (code, msg) => { if (msg) stderr.write(msg + "\n"); resolveStart({ close() {}, done: Promise.resolve(code), port: 0 }); };
    if (!token) return fail(2, "vyomi-tunnel: not signed in. Run `vyomi-tunnel login` (and start Mesh in the Vyomi console).");
    if (!/^[A-Za-z0-9._-]{1,80}$/.test(target || "")) return fail(2, "vyomi-tunnel: bad target");
    if (!ROLE_RE.test(role)) return fail(2, "vyomi-tunnel: bad role");
    if (!(Number.isInteger(local) && local >= 0 && local < 65536) || !(Number.isInteger(remote) && remote > 0 && remote < 65536)) return fail(2, "vyomi-tunnel: ports must be 1-65535");
    if (local > 0 && local < 1024 && !allowPrivileged) return fail(2, "vyomi-tunnel: local ports below 1024 need --allow-privileged");
    const end = tokenEnd(token);
    if (Number.isFinite(end) && Date.now() >= end * 1000) return fail(2, "vyomi-tunnel: your Mesh session has ended. Start Mesh again, then run `vyomi-tunnel login`.");
    const socks = new Set();
    let resolveDone, finished = false, endTimer = null;
    const done = new Promise((r) => { resolveDone = r; });
    const srv = net.createServer();
    const finish = (code, msg) => {
      if (finished) return; finished = true; clearTimeout(endTimer);
      if (msg) stderr.write(msg + "\n");
      try { srv.close(); } catch { /* */ }
      for (const x of socks) { try { x.destroy(); } catch { /* */ } }
      resolveDone(code);
    };
    let started = false;
    srv.on("error", (e) => { finish(1, `vyomi-tunnel: cannot listen on 127.0.0.1:${local}: ${e.message}`); if (!started) { started = true; resolveStart({ close() {}, done, port: 0 }); } });
    srv.on("connection", (sock) => {
      socks.add(sock); sock.setNoDelay(true);
      const ws = new WS(`${wsUrl(relay)}/connect?vm=${encodeURIComponent(target)}&port=${remote}&role=${encodeURIComponent(role)}`, { headers: { authorization: `Bearer ${token}` } });
      let open = false; const queue = [];
      const drop = () => { socks.delete(sock); try { sock.destroy(); } catch { /* */ } try { ws.close(); } catch { /* */ } };
      ws.on("unexpected-response", (_rq, res) => {
        const why = { 401: "sign-in expired - run `vyomi-tunnel login`", 403: "not allowed for this session", 410: "Mesh session ended",
                      502: "that agent is not running", 429: "too many open connections" }[res.statusCode] || "refused";
        stderr.write(`vyomi-tunnel: ${target}.${role}: ${why} (HTTP ${res.statusCode})\n`);
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

export async function main(argv) {
  const [cmd, ...rest] = argv;
  const WS = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
  if (cmd === "connect") {
    const vm = vmName(rest[0]); if (!vm) { console.error("usage: vyomi-tunnel connect <vm>[.vyomi] [port]"); return 2; }
    const { relay, token } = load();
    return connect(vm, { port: Number(rest[1] || 22), relay, token, WS });
  }
  if (cmd === "forward") {
    const ri = rest.indexOf("--role"), role = ri >= 0 ? rest[ri + 1] : undefined;
    const pos = rest.filter((x, i) => !x.startsWith("--") && (ri < 0 || i !== ri + 1));
    const m = /^(\d{1,5}):(\d{1,5})$/.exec(pos[1] || "");
    if (!pos[0] || !m) { console.error("usage: vyomi-tunnel forward <target>[.<role>] <local>:<remote> [--role r] [--allow-privileged]"); return 2; }
    const { target, role: r } = parseTarget(pos[0], role);
    const { relay, token } = load();
    const f = await forward(target, { local: Number(m[1]), remote: Number(m[2]), role: r, relay, token, WS, allowPrivileged: rest.includes("--allow-privileged") });
    if (f.port) console.error(`forwarding 127.0.0.1:${f.port} -> ${target}.${r}:${m[2]} (Ctrl-C to stop)`);
    for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => f.close());
    return f.done;
  }
  if (cmd === "login") {
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
  console.error("usage: vyomi-tunnel login | config [--yes|--remove] | connect <vm>[.vyomi] | forward <target>[.<role>] <local>:<remote> | keep [--user u] [--key f] [--interval s] | status"); return 2;
}
