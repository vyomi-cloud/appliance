// Laptop-side Mesh transport over the user's own ssh session (docs/architecture/v4.0/VYOMI-TUNNEL-ARCHITECTURE.md §1b/§1c).
//
// The Codespace dials nothing. This process runs on the laptop and opens ONE ssh session to the Codespace host
// (`gh codespace ssh`, authenticated by the user's own gh login), then multiplexes everything over it with ControlMaster:
//   tunnel 1  host / codespace      -> the Codespace's own sshd (127.0.0.1:2222)
//   tunnel 2  (browser VMs)         -> unchanged, local relay /vm
//   tunnel 3  vyomi-i-<id>, k3s     -> a Docker container inside the Codespace (its IP found with `docker inspect` over ssh)
//   plus      simulator HTTP API    -> container `simulator` :9000, for the Nano console's compute calls
// Each stream is `ssh -W host:port` on the master connection (no extra handshake: ~0 ms once the master is up).
import { spawn as nodeSpawn } from "node:child_process";
import { Duplex } from "node:stream";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import http from "node:http";
import crypto from "node:crypto";
import { ensureGh, ghAuthOk } from "./gh-manager.mjs";

const NAME = /^[A-Za-z0-9._-]{1,80}$/;
const CODESPACE = /^[A-Za-z0-9._-]{1,120}$/;
const K3S = /^vyomi-k3s-[0-9a-f]{10}$/;
const HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-connection", "content-length", "x-vyomi-session-token"]);

// What a user may reach: their own VMs and k3s clusters. Vyomi's own containers (simulator, llm*, ...) are never a target.
// Docs: docs/architecture/v4.0/MESH-SOFTWARE-PROTECTION.md. The same allow-list is enforced on the Codespace by `vyomi-gate`.
export const USER_CONTAINER = /^(vyomi-i-[A-Za-z0-9][A-Za-z0-9._-]{0,60}|vyomi-k3s-[0-9a-f]{10})$/;
const GATE = "/usr/local/sbin/vyomi-gate";
/** Run `verb` through the Codespace's root-owned gate when it is installed; older Codespaces fall back to the plain docker command. */
const viaGate = (verb, legacy) => `if [ -x ${GATE} ]; then sudo -n ${GATE} ${verb}; else ${legacy}; fi`;
const dockerIp = (rawName) => viaGate(`ip ${rawName}`, `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' ${rawName} 2>/dev/null`);

/** Turn `docker inspect` rows (name|image|ips|exposed ports) into the targets a user can reach, with the name to type for each. */
export function classifyTargets(text) {
  const out = [{ name: "host", kind: "host", what: "the Codespace's own sshd", ssh: true, ports: [22] }];
  for (const line of String(text || "").split("\n")) {
    const [raw, , ips = "", ports = ""] = line.split("|"); const n = (raw || "").replace(/^\//, "").trim();
    if (!NAME.test(n)) continue;
    const ps = ports.split(/\s+/).map((x) => Number(x.split("/")[0])).filter(Boolean);
    const ip = ips.trim().split(/\s+/)[0] || "";
    if (!USER_CONTAINER.test(n)) continue;                       // Vyomi's own containers are never listed (and no image names are shown)
    if (n.startsWith("vyomi-k3s-")) out.push({ name: n, kind: "k3s", what: "Kubernetes API (port 6443)", ip, ports: [6443] });
    else out.push({ name: n.slice(8), kind: "instance", what: "Docker instance", ssh: true, ip, ports: ps.length ? ps : [22] });
  }
  return out;
}

/** Find the user's Mesh Codespace on their own account: the newest running (or starting) one named vyomi-mesh-* / vyomi-mesh-*. */
export async function findCodespace(ghBin, spawn = nodeSpawn) {
  const text = await new Promise((resolve, reject) => {
    let out = "", err = "";
    const c = spawn(ghBin, ["codespace", "list", "--json", "name,state,createdAt"], { stdio: ["ignore", "pipe", "pipe"] });
    c.stdout.on("data", (d) => { out += d; }); c.stderr?.on("data", (d) => { err += d; });
    c.on("error", reject); c.on("close", (code) => (code === 0 ? resolve(out) : reject(new Error((err || "gh codespace list failed").trim().slice(0, 200)))));
  });
  let list; try { list = JSON.parse(text); } catch { list = []; }
  const mine = list.filter((c) => /^vyomi-mesh-/.test(c.name || ""));
  const rank = { Available: 0, Starting: 1, Queued: 1, Provisioning: 1 };
  const live = mine.filter((c) => c.state in rank).sort((a, b) => rank[a.state] - rank[b.state] || String(b.createdAt).localeCompare(String(a.createdAt)));
  if (!live.length) throw new Error(mine.length ? "your Mesh Codespace is stopped. Start Mesh in the Vyomi console, then retry." : "no Mesh Codespace found on your GitHub account. Start Mesh in the Vyomi console first.");
  return live[0].name;
}

/** @returns transport {resolve(name,port), open(host,port), exec(cmd), http(req,res,body), close(), simulatorTarget()} */
export function createSshTransport({ codespace, spawn = nodeSpawn, ghBin = null, log = () => {}, ipTtlMs = 30000,
                                     simulatorPort = 9000, hostSshPort = 2222, config = null, keepaliveMs = 240000, env = {} } = {}) {
  if (codespace && !CODESPACE.test(String(codespace))) throw new Error("bad Codespace name");   // none given: found on the user's account at first use
  let cfg = config;                         // {file, host} - tests inject it; otherwise `gh codespace ssh --config` provides it
  let dir = null;
  const sp = (bin, args, o = {}) => spawn(bin, args, { ...o, env: { ...process.env, ...env } });   // env carries GH_TOKEN from the Vyomi session
  const stopHandlers = []; let stopTimer = null;
  const ips = new Map();                    // container name -> {ip, at}
  const live = new Set();
  let closed = false;
  // Beat the Codespaces idle timeout automatically: GitHub resets its idle timer on ssh traffic THE CLIENT sends (not on keepalives
  // inside an idle connection), so while this transport is in use it runs a trivial command on the host every ~4 min. Users do nothing.
  const ka = { writes: 0, failures: 0, lastAt: 0, timer: null };
  function startKeepalive() {
    if (ka.timer || !keepaliveMs) return;
    const beat = async () => {
      if (closed) return;
      try { await exec("echo vyomi-keepalive > /dev/null"); ka.writes++; ka.failures = 0; ka.lastAt = Date.now(); }
      catch (e) { if (++ka.failures === 1) log("keepalive failed: " + String(e.message).slice(0, 120)); }
    };
    ka.timer = setInterval(beat, keepaliveMs); ka.timer.unref?.();
    beat();
  }

  const collect = (child) => new Promise((resolve, reject) => {
    let out = "", err = "";
    child.stdout.on("data", (d) => { out += d; });
    child.stderr?.on("data", (d) => { err += d; });
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve(out) : reject(Object.assign(new Error((err || out || `exit ${code}`).trim().slice(0, 300)), { code }))));
  });

  async function ensureConfig() {
    if (cfg) { startKeepalive(); return cfg; }
    if (!ghBin) {                                                    // find gh, or install a private pinned copy (gh-manager.mjs)
      ghBin = (await ensureGh({ spawn: sp, log })).path;
      const a = await ghAuthOk(ghBin, { spawn: sp, env: { ...process.env, ...env } });
      if (!a.ok) throw new Error(a.reason);
    }
    if (!codespace) { codespace = await findCodespace(ghBin, sp); log("using Codespace " + codespace); }
    dir = mkdtempSync(join(process.platform === "win32" ? tmpdir() : "/tmp", "vm-"));   // short: a unix ControlPath is limited to ~100 chars
    const text = await collect(sp(ghBin, ["codespace", "ssh", "-c", codespace, "--config"], { stdio: ["ignore", "pipe", "pipe"] }));
    const m = /^Host\s+(\S+)/m.exec(text);
    if (!m) throw new Error("gh did not return an ssh config for this Codespace");
    const file = join(dir, "ssh_config");
    writeFileSync(file, text, { mode: 0o600 });
    cfg = { file, host: m[1] };
    startKeepalive();
    return cfg;
  }
  const sshArgs = (c) => ["-F", c.file, "-o", `ControlPath=${join(dir || tmpdir(), "cm-%C")}`, "-o", "ControlMaster=auto", "-o", "ControlPersist=600",
    "-o", "ServerAliveInterval=30", "-o", "BatchMode=yes"];

  /** Run a command on the Codespace host (names are validated by the callers; nothing user-controlled is interpolated raw). */
  async function exec(cmd) {
    const c = await ensureConfig();
    return collect(sp("ssh", [...sshArgs(c), c.host, cmd], { stdio: ["ignore", "pipe", "pipe"] }));
  }

  async function containerIp(rawName, internal = false) {
    if (!internal && !USER_CONTAINER.test(rawName)) return null;     // user-facing lookups reach only allow-listed containers
    const hit = ips.get(rawName);
    if (hit && Date.now() - hit.at < ipTtlMs) return hit.ip;
    const out = (await exec(dockerIp(rawName)).catch(() => "")).trim().split(/\s+/)[0];
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(out || "")) return null;
    ips.set(rawName, { ip: out, at: Date.now() });
    return out;
  }
  async function composeContainer(service) {
    const out = (await exec(viaGate(`compose ${service}`, `docker ps --filter label=com.docker.compose.service=${service} --format '{{.Names}}' | head -1`)).catch(() => "")).trim();
    return NAME.test(out) ? out : null;
  }

  /** Where does <name> listen, from the Codespace host's point of view? Same names and fixed ports as mesh-dial's resolver. */
  async function resolve(name, port = 22) {
    const n = String(name || "").toLowerCase();
    if (n === "host" || n === "codespace") return { host: "127.0.0.1", port: hostSshPort, reserved: "host" };
    if (K3S.test(n)) { const ip = await containerIp(n); return ip ? { host: ip, port: 6443, reserved: "k3s" } : null; }
    if (n === "k3s") {
      const out = (await exec(viaGate("k3s", `docker ps --filter name=vyomi-k3s- --format '{{.Names}}' | head -1`)).catch(() => "")).trim();
      const ip = K3S.test(out) ? await containerIp(out) : null;
      return ip ? { host: ip, port: 6443, reserved: "k3s" } : null;
    }
    if (!NAME.test(String(name || ""))) return null;
    for (const c of [`vyomi-i-${name}`, name]) {                     // the bare name only works when it is itself a user container (vyomi-i-...)
      const ip = await containerIp(c);
      if (ip) return { host: ip, port: Number(port) || 22 };
    }
    return null;
  }

  async function simulatorTarget() {
    const c = await composeContainer("simulator");
    const ip = c ? await containerIp(c, true) : null;            // internal: the console's own API calls, never a user-typed target
    return ip ? { host: ip, port: simulatorPort } : null;
  }

  /** A raw byte stream to host:port on the Codespace side, as a Duplex (also usable as an http socket). */
  async function open(host, port) {
    if (closed) throw new Error("transport closed");
    if (!/^[0-9.]{7,15}$/.test(host) || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error("bad target");
    const c = await ensureConfig();
    const child = sp("ssh", [...sshArgs(c), "-W", `${host}:${port}`, c.host], { stdio: ["pipe", "pipe", "pipe"] });
    live.add(child);
    let errText = "";
    child.stderr?.on("data", (d) => { errText += d; });
    const d = new Duplex({
      read() { child.stdout.resume(); },
      write(chunk, _e, cb) { child.stdin.write(chunk, cb); },
      final(cb) { try { child.stdin.end(); } catch { /* gone */ } cb(); },
      destroy(err, cb) { try { child.kill(); } catch { /* gone */ } cb(err); },
    });
    child.stdout.on("data", (b) => { if (!d.push(b)) child.stdout.pause(); });
    child.stdout.on("end", () => d.push(null));
    child.stdin.on("error", () => {});
    child.on("error", (e) => d.destroy(e));
    child.on("close", (code) => { live.delete(child); if (code && !d.destroyed) d.destroy(new Error(errText.trim().slice(0, 200) || `ssh exit ${code}`)); });
    // http.request wants a socket-shaped object
    for (const f of ["setTimeout", "setNoDelay", "setKeepAlive", "ref", "unref"]) d[f] = () => d;
    return d;
  }

  /** Forward one HTTP request to the simulator container and relay the answer (Nano's compute calls). */
  async function httpToSimulator(req, res, body, extraHeaders = {}) {
    const t = await simulatorTarget();
    if (!t) { res.writeHead(502, { "content-type": "application/json", ...extraHeaders }); return res.end(JSON.stringify({ error: { ok: false, code: "MeshSimulatorDown", reason: "the simulator is not running in the Codespace" } })); }
    const sock = await open(t.host, t.port);
    const headers = {};
    for (const [k, v] of Object.entries(req.headers)) if (!HOP.has(k)) headers[k] = v;
    headers.host = `simulator:${simulatorPort}`;                // the simulator's DNS-rebinding guard allows its own service name (VYOMI_MESH_HOSTS)
    // ...but that name only exists inside the Codespace's Docker network. Tell the simulator the address the USER reaches it at (the laptop side
    // of `vyomi-tunnel forward <simulator> 9000:9000`), so the endpoints it advertises (Keys and Endpoints, selfLinks) work from the laptop.
    headers["x-forwarded-host"] = process.env.VYOMI_MESH_ENDPOINT_HOST || "127.0.0.1:9000";
    headers["x-forwarded-proto"] = "http";
    headers["content-length"] = String(body.length);
    const out = http.request({ method: req.method, path: req.url, headers, createConnection: () => sock }, (r) => {
      const h = {};
      for (const [k, v] of Object.entries(r.headers)) if (!HOP.has(k)) h[k] = v;
      Object.assign(h, extraHeaders);
      res.writeHead(r.statusCode || 502, h);
      r.pipe(res);
    });
    out.setTimeout?.(0);
    out.on("error", (e) => { if (!res.headersSent) { res.writeHead(502, { "content-type": "application/json", ...extraHeaders }); res.end(JSON.stringify({ error: { ok: false, code: "MeshStreamFailed", reason: String(e.message).slice(0, 200) } })); } else res.destroy(); });
    out.end(body);
  }

  /** Everything reachable in the Mesh Codespace right now. */
  async function list() {
    const text = await exec(viaGate("list", `docker ps -q | xargs -r docker inspect -f '{{.Name}}|{{.Config.Image}}|{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}|{{range $p, $_ := .Config.ExposedPorts}}{{$p}} {{end}}'`));
    return classifyTargets(text);
  }

  /** Close everything at an epoch-seconds deadline (the Mesh session end); handlers added with onStop run first. */
  function stopAt(epochS) { clearTimeout(stopTimer); const ms = epochS * 1000 - Date.now(); stopTimer = setTimeout(() => { for (const h of stopHandlers) { try { h(); } catch { /* */ } } close(); }, Math.max(0, ms)); stopTimer.unref?.(); }

  function close() { closed = true; clearTimeout(stopTimer); clearInterval(ka.timer); for (const c of live) { try { c.kill(); } catch { /* */ } } live.clear(); if (cfg && dir) sp("ssh", [...sshArgs(cfg), "-O", "exit", cfg.host], { stdio: "ignore" }).on("error", () => {}); }

  return { resolve, open, exec, list, stopAt, onStop: (h) => stopHandlers.push(h), simulatorTarget, httpToSimulator, close, get codespace() { return codespace; }, get closed() { return closed; }, keepalive: () => ({ ...ka, timer: undefined }) };
}

/** A drop-in for mesh-hub's createHub() when the link runs over ssh: same surface local-relay.mjs already calls.
 *  The laptop is the trust boundary here (the ssh session is the user's own), so there is no session token; browser callers
 *  are still limited to the allow-listed origins. */
export function createSshHub({ WebSocketServer, WebSocket: WSClient = null, transport, log = () => {},
                               origins = (process.env.VYOMI_RELAY_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean),
                               allowLoopback = process.env.VYOMI_RELAY_ALLOW_LOOPBACK === "1", maxTcp = Number(process.env.VYOMI_MAX_STREAMS || 20) } = {}) {
  const allow = new Set(origins.length ? origins : ["https://vyomi.cloud", "https://www.vyomi.cloud"]);
  const LOOP = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/;
  const originOk = (o) => !o || allow.has(o) || (allowLoopback && LOOP.test(o));
  const cors = (o) => (o && originOk(o) ? { "access-control-allow-origin": o, vary: "Origin", "access-control-allow-methods": "GET,PUT,POST,DELETE,HEAD,OPTIONS",
    "access-control-allow-headers": "*", "access-control-allow-private-network": "true" } : {});
  const connWss = new WebSocketServer({ noServer: true, maxPayload: 70 * 1024 });
  const streams = new Set();
  const shellWss = new WebSocketServer({ noServer: true, maxPayload: 70 * 1024 });
  const maxShells = Number(process.env.VYOMI_SHELL_MAX_PER_SESSION || 4), idleMs = Number(process.env.VYOMI_SHELL_IDLE_MS || 900000);
  let shells = 0;
  const reject = (socket, status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };

  function connectUpgrade(req, socket, head) {
    if (!originOk(req.headers.origin)) { reject(socket, 403, "OriginNotAllowed"); return true; }
    const u = new URL(req.url, "http://x");
    const vm = u.searchParams.get("vm") || "", port = Number(u.searchParams.get("port") || 22);
    if (!NAME.test(vm) || !Number.isInteger(port) || port < 1 || port > 65535) { reject(socket, 400, "BadVm"); return true; }
    if (streams.size >= maxTcp) { reject(socket, 429, "TooManyStreams"); return true; }
    connWss.handleUpgrade(req, socket, head, async (ws) => {
      const id = crypto.randomUUID(); streams.add(id);
      const done = () => streams.delete(id);
      ws.on("close", done); ws.on("error", done);
      const early = []; let up = null;
      ws.on("message", (d, isBin) => { if (!isBin) return; if (up) up.write(d); else if (early.length < 64) early.push(Buffer.from(d)); });
      try {
        const t = await transport.resolve(vm, port);
        if (!t) { ws.close(4404, "VmNotFound"); return; }
        up = await transport.open(t.host, t.port);
        log(`tcp stream ${id} -> ${vm}:${t.port}`);
        for (const b of early) up.write(b);
        up.on("data", (b) => { try { ws.send(b); } catch { /* */ } });
        up.on("close", () => { try { ws.close(1000); } catch { /* */ } });
        up.on("error", () => { try { ws.close(4502, "MeshStreamFailed"); } catch { /* */ } });
        ws.on("close", () => up.destroy());
      } catch (e) { try { ws.close(4502, "MeshStreamFailed"); } catch { /* */ } }
    });
    return true;
  }


  /** /shell (the Nano tab's terminal): first message is the JSON auth {cloud, ref, cols, rows}; bytes then flow tab <-> the simulator's own
   *  /mesh/shell WebSocket, reached over an ssh stream (the simulator resolves the container itself and uses its own session token). */
  function shellUpgrade(req, socket, head) {
    if (!originOk(req.headers.origin)) { reject(socket, 403, "OriginNotAllowed"); return true; }
    if (!WSClient) { reject(socket, 501, "MeshShellUnavailable"); return true; }
    shellWss.handleUpgrade(req, socket, head, (tab) => {
      const fail = (code, message, wsCode = 4401) => { try { tab.send(JSON.stringify({ t: "error", code, message })); tab.close(wsCode, code.slice(0, 100)); } catch { /* */ } };
      const authTimer = setTimeout(() => fail("AuthTimeout", "no auth message"), 10000);
      tab.on("close", () => clearTimeout(authTimer));
      tab.once("message", async (data, isBin) => {
        clearTimeout(authTimer);
        let a; try { if (isBin) throw 0; a = JSON.parse(data.toString()); } catch { return fail("BadRequest", "first message must be JSON auth"); }
        const cloud = String(a?.cloud || ""), ref = String(a?.ref || "");
        if (!a || a.type !== "auth" || !/^(aws|gcp|azure)$/.test(cloud) || !ref || ref.length > 200) return fail("BadRequest", "cloud/ref", 4400);
        if (shells >= maxShells) return fail("TooManyShells", `at most ${maxShells} shells`, 4429);
        shells++; let freed = false; const free = () => { if (!freed) { freed = true; shells--; } };
        let sock, sim, last = Date.now(); const queue = [];
        const idle = setInterval(() => { if (Date.now() - last > idleMs) { fail("IdleTimeout", "shell closed after being idle", 4408); end(); } }, Math.min(1000, Math.max(20, idleMs / 4)));
        const end = () => { clearInterval(idle); free(); try { sim && sim.close(); } catch { /* */ } try { sock && sock.destroy(); } catch { /* */ } try { tab.close(1000); } catch { /* */ } };
        tab.on("close", end); tab.on("error", end);
        tab.on("message", (d, bin) => {
          last = Date.now();
          if (bin && d.length > 64 * 1024) return fail("FrameTooLarge", "input frame too large", 1009);
          if (sim && sim.readyState === 1) sim.send(d, { binary: bin }); else if (queue.length < 64) queue.push([d, bin]);
        });
        try {
          const t = await transport.simulatorTarget(); if (!t) return fail("MeshSimulatorDown", "the simulator is not running in the Codespace", 4502);
          sock = await transport.open(t.host, t.port);
          const q = new URLSearchParams({ cloud, ref, cols: String(a.cols ?? ""), rows: String(a.rows ?? "") });
          sim = new WSClient(`ws://simulator:9000/mesh/shell?${q}`, { createConnection: () => sock, maxPayload: 1024 * 1024 });
          sim.on("open", () => { for (const [d, b] of queue) sim.send(d, { binary: b }); queue.length = 0; });
          sim.on("message", (d, b) => { last = Date.now(); try { tab.send(d, { binary: b }); } catch { /* */ } });
          sim.on("close", () => end()); sim.on("error", () => end());
          sim.on("unexpected-response", (_q, r) => { fail("LocalRefused", "simulator refused the shell: HTTP " + r.statusCode, 4403); end(); });
        } catch (e) { fail("MeshStreamFailed", String(e.message).slice(0, 200), 4502); end(); }
      });
    });
    return true;
  }

  /** HTTP carrying X-Vyomi-Session-Token marks the Mesh plane (the Nano console's compute calls) -> the simulator in the Codespace. */
  function http_(req, res, body) {
    if (req.headers["x-vyomi-session-token"] === undefined) return false;
    const origin = req.headers.origin;
    if (!originOk(origin)) { res.writeHead(403, { "content-type": "application/json" }); res.end(JSON.stringify({ error: { ok: false, code: "OriginNotAllowed", reason: "origin not allowed" } })); return true; }
    transport.httpToSimulator(req, res, body, cors(origin)).catch((e) => {
      if (!res.headersSent) { res.writeHead(502, { "content-type": "application/json", ...cors(origin) }); res.end(JSON.stringify({ error: { ok: false, code: "MeshStreamFailed", reason: String(e.message).slice(0, 200) } })); }
    });
    return true;
  }

  return {
    upgrade: (_q, socket) => { reject(socket, 410, "MeshLinkNotUsed"); return true; },          // no outbound link exists any more
    shellUpgrade, connectUpgrade, http: http_, enabled: () => true,
    linked: () => [transport.codespace], streams: () => streams.size, close: () => transport.close(),
  };
}

// ── CLI side: `vyomi-tunnel connect|forward` straight over the ssh transport (no relay, no token) ─────────────────────────────
/** `connect`: pipe stdin/stdout to <name>:<port> in the Codespace. Resolves with the exit code (0 clean, 1 failed, 3 not found). */
export async function connectSsh(name, { port = 22, transport, stdin = process.stdin, stdout = process.stdout, stderr = process.stderr } = {}) {
  let t; try { t = await transport.resolve(name, port); } catch (e) { stderr.write(`vyomi-tunnel: ${e.message}\n`); return 1; }
  if (!t) { stderr.write(`vyomi-tunnel: ${name}: not found in the Codespace\n`); return 3; }
  let up; try { up = await transport.open(t.host, t.port); } catch (e) { stderr.write(`vyomi-tunnel: ${e.message}\n`); return 1; }
  return new Promise((resolve) => {
    let done = false; const fin = (c) => { if (done) return; done = true; try { up.destroy(); } catch { /* */ } try { stdin.pause(); } catch { /* */ } resolve(c); };
    stdin.on("data", (d) => up.write(d)); stdin.on("end", () => up.end());
    up.on("data", (b) => stdout.write(b));
    up.on("close", () => fin(0)); up.on("error", (e) => { stderr.write(`vyomi-tunnel: ${e.message}\n`); fin(1); });
  });
}

/** `forward`: listen on 127.0.0.1:<local>; each accepted socket is one ssh stream to <target>:<remote> inside the Codespace. */
export async function forwardSsh(target, { local, remote, transport, net, stderr = process.stderr } = {}) {
  const t = await transport.resolve(target, remote);
  if (!t) { stderr.write(`vyomi-tunnel: ${target}: not found in the Codespace\n`); return { close() {}, done: Promise.resolve(3), port: 0 }; }
  const socks = new Set(); let finish; const done = new Promise((r) => { finish = r; });
  const srv = net.createServer(async (sock) => {
    socks.add(sock); sock.setNoDelay(true);
    const drop = () => { socks.delete(sock); try { sock.destroy(); } catch { /* */ } };
    sock.on("close", drop); sock.on("error", drop);
    try {
      const up = await transport.open(t.host, t.port);
      sock.pipe(up); up.pipe(sock); up.on("close", drop); up.on("error", drop); sock.on("close", () => up.destroy());
    } catch (e) { stderr.write(`vyomi-tunnel: ${target}: ${e.message}\n`); drop(); }
  });
  return new Promise((resolve) => {
    srv.on("error", (e) => { stderr.write(`vyomi-tunnel: cannot listen on 127.0.0.1:${local}: ${e.message}\n`); finish(1); resolve({ close() {}, done, port: 0 }); });
    srv.listen(local, "127.0.0.1", () => resolve({ port: srv.address().port, done,
      close: () => { try { srv.close(); } catch { /* */ } for (const s of socks) s.destroy(); finish(0); } }));
  });
}
