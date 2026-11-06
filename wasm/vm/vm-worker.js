/* Vyomi Nano — one in-browser VM instance (EC2 / Compute Engine / Azure VM).
 *
 * Runs as a SharedWorker named "vm-<instance id>": its own thread, shared by
 * every Nano view (dashboard + the three consoles), so the VM keeps running
 * while the user moves between consoles. The engine is v86 (BSD-2, 32-bit x86)
 * booting the Alpine i386 image in ./image (rootfs in RAM).
 *
 *   page  ──MessagePort──▶  this worker  ──v86──▶ guest (dropbear :22, agent on ttyS1)
 *                                 │
 *                                 └─WebSocket──▶ vyomi-tunnel /vm  ◀──TCP── ssh on the laptop
 *
 * Launch: restore the cached golden snapshot (built once per browser by a cold
 * boot, ~20 s, then IndexedDB) and provision the instance over the agent:
 * hostname, clock, entropy reseed, the cloud's default user + the instance key.
 * Stop = save_state into IndexedDB + halt; Start = restore that state;
 * Terminate = halt + delete the saved state.
 *
 * Page → worker messages (each may carry rid; the reply echoes it):
 *   {type:"launch", id, cloud, user, pubkey, hostname, mem_mb, relay, prefer_port}
 *   {type:"start"} {type:"stop"} {type:"terminate"} {type:"status"}
 *   {type:"exec", command, user, timeout_ms}
 *   {type:"serial-in", data}           → interactive serial console (ttyS0)
 * Worker → page: {rid, ok, ...} replies, and broadcasts {type:"vm-status"|"serial-out"}.
 */
importScripts("engine/libv86.js");

const HERE = new URL("./", self.location.href).href;
const IMAGE_VERSION = "alpine3.21-i386-v5";
const DB_NAME = "nano-vm", DB_STORE = "blobs";
const CMDLINE = "console=ttyS0 rdinit=/init quiet tsc=reliable mitigations=off random.trust_cpu=on";

const clients = new Set();
let emu = null;
let inst = null;            // {id, cloud, user, pubkey, hostname, mem_mb, relay, prefer_port}
let state = "pending";      // pending | booting | running | stopping | stopped | terminated | error
let detail = "";
let hostPort = null;        // the TCP port vyomi-tunnel opened for this VM's :22
let relay = null;           // WebSocket to vyomi-tunnel
let relayWanted = false;
const timings = {};

function broadcast(msg) { for (const p of clients) { try { p.postMessage(msg); } catch (_) {} } }
function setState(s, d) {
  state = s; if (d !== undefined) detail = d;
  broadcast({ type: "vm-status", ...statusObj() });
}
function statusObj() {
  return { id: inst && inst.id, state, detail, host_port: hostPort, relay: !!(relay && relay.readyState === 1),
           user: inst && inst.user, cloud: inst && inst.cloud, mem_mb: inst && inst.mem_mb, timings,
           image: IMAGE_VERSION };
}

// ── IndexedDB blob store (golden snapshot + per-instance saved state) ──────
function db() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(DB_STORE);
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
}
async function idb(op, key, val) {
  const d = await db();
  return new Promise((res, rej) => {
    const tx = d.transaction(DB_STORE, op === "get" ? "readonly" : "readwrite");
    const st = tx.objectStore(DB_STORE);
    const r = op === "get" ? st.get(key) : op === "put" ? st.put(val, key) : st.delete(key);
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
}
async function gzip(buf) {
  return new Response(new Blob([buf]).stream().pipeThrough(new CompressionStream("gzip"))).arrayBuffer();
}
async function gunzip(buf) {
  return new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
}

// ── v86 ──────────────────────────────────────────────────────────────────
function makeEmulator(opts) {
  return new V86({
    wasm_path: HERE + "engine/v86.wasm",
    memory_size: (inst.mem_mb || 512) * 1024 * 1024,
    vga_memory_size: 2 * 1024 * 1024,
    bios: { url: HERE + "bios/seabios.bin" },
    vga_bios: { url: HERE + "bios/vgabios.bin" },
    autostart: true,
    disable_keyboard: true, disable_mouse: true, disable_speaker: true,
    uart1: true,
    // Guest HTTP goes out via the browser fetch; the CORS-less package mirrors are reached through the relay's allow-listed /egress.
    net_device: { type: "virtio", relay_url: "fetch", ...(inst && inst.relay ? { cors_proxy: inst.relay.replace(/\/$/, "") + "/egress?u=" } : {}) },
    preserve_mac_from_state_image: true,
    ...opts,
  });
}

// Agent protocol on ttyS1: "<rid> <b64 cmd> [user]\n" → "@@VYOMI <rid> <rc> <b64 out>\n"
let agentLine = "";
const agentWait = new Map();     // rid -> {resolve, timer}
let agentReady = null, agentReadyResolve = null;
function resetAgent() {
  agentLine = "";
  agentReady = new Promise((r) => (agentReadyResolve = r));
}
function onAgentByte(b) {
  if (b === 10) {
    const line = agentLine.replace(/\r$/, ""); agentLine = "";
    const m = line.match(/@@VYOMI (\S+) (-?\d+) ?(\S*)/);
    if (!m) return;
    if (m[1] === "ready") { agentReadyResolve && agentReadyResolve(); return; }
    const w = agentWait.get(m[1]);
    if (w) {
      agentWait.delete(m[1]); clearTimeout(w.timer);
      let out = "";
      try { out = (!m[3] || m[3] === "-") ? "" : new TextDecoder().decode(Uint8Array.from(atob(m[3]), (c) => c.charCodeAt(0))); } catch (_) {}
      w.resolve({ exit_code: Number(m[2]), stdout: out });
    }
    return;
  }
  agentLine += String.fromCharCode(b);
  if (agentLine.length > 8 * 1024 * 1024) agentLine = "";
}
let ridSeq = 0;
function b64(s) { return btoa(String.fromCharCode(...new TextEncoder().encode(s))); }
function agentExec(command, user, timeoutMs = 60000) {
  const rid = "r" + (++ridSeq) + "x" + Math.random().toString(36).slice(2, 7);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { agentWait.delete(rid); reject(new Error("exec timed out")); }, timeoutMs);
    agentWait.set(rid, { resolve, timer });
    const line = `${rid} ${b64(command)} ${user || "root"}\n`;
    emu.serial_send_bytes(1, new TextEncoder().encode(line));
  });
}
async function agentPing(timeoutMs) {
  const t0 = Date.now();
  for (;;) {
    try { await agentExec("true", "root", 3000); return; }
    catch (e) { if (Date.now() - t0 > timeoutMs) throw new Error("guest agent not answering"); }
  }
}

function wire(e) {
  e.add_listener("serial1-output-byte", onAgentByte);
  let buf = "", flushT = null;
  e.add_listener("serial0-output-byte", (b) => {
    buf += String.fromCharCode(b);
    if (!flushT) flushT = setTimeout(() => { broadcast({ type: "serial-out", id: inst && inst.id, data: buf }); buf = ""; flushT = null; }, 30);
  });
}
function waitReady(e) { return new Promise((r) => e.add_listener("emulator-ready", r)); }

async function destroyEmu() {
  if (!emu) return;
  try { await emu.destroy(); } catch (_) { try { emu.stop(); } catch (_) {} }
  emu = null;
}

// The golden snapshot: one cold boot per browser per (image, memory size).
async function golden() {
  const key = `golden:${IMAGE_VERSION}:${inst.mem_mb}`;
  const run = async () => {
    const hit = await idb("get", key).catch(() => null);
    if (hit) return hit;
    const t0 = performance.now();
    resetAgent();
    const e = makeEmulator({ bzimage: { url: HERE + "image/vmlinuz" }, initrd: { url: HERE + "image/rootfs.cpio.gz" }, cmdline: CMDLINE });
    emu = e; wire(e);
    setState("booting", "first launch in this browser: cold-booting the VM image (once)");
    await Promise.race([agentReady, new Promise((_, rj) => setTimeout(() => rj(new Error("cold boot timed out")), 240000))]);
    await agentPing(60000);                              // the agent answers commands before we snapshot it
    await new Promise((r) => setTimeout(r, 1000));    // let dropbear finish starting
    timings.cold_boot_ms = Math.round(performance.now() - t0);
    const raw = await e.save_state();
    const gz = await gzip(raw);
    timings.golden_bytes = gz.byteLength;
    await idb("put", key, gz).catch(() => {});
    await destroyEmu();
    return gz;
  };
  return navigator.locks ? navigator.locks.request("nano-vm-golden:" + key, run) : run();
}

async function bootFrom(gzState) {
  const t0 = performance.now();
  const raw = await gunzip(gzState);
  resetAgent();
  emu = makeEmulator({ initial_state: { buffer: raw } });
  wire(emu);
  await waitReady(emu);
  await agentPing(30000);
  timings.restore_ms = Math.round(performance.now() - t0);
}

function sq(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }
async function provision() {
  const u = inst.user, rnd = new Uint8Array(64); crypto.getRandomValues(rnd);
  const seed = btoa(String.fromCharCode(...rnd));
  const host = (inst.hostname || inst.id).replace(/[^a-zA-Z0-9-]/g, "-").slice(0, 63);
  const script = [
    `date -s @${Math.floor(Date.now() / 1000)} >/dev/null 2>&1`,
    `echo ${sq(seed)} | base64 -d > /dev/urandom`,
    `hostname ${sq(host)}; echo ${sq(host)} > /etc/hostname`,
    `grep -q ${sq(host)} /etc/hosts || echo "127.0.1.1 ${host}" >> /etc/hosts`,
    `id -u ${u} >/dev/null 2>&1 || adduser -D -s /bin/sh ${u}`,
    `sed -i "s#^${u}:!:#${u}:*:#" /etc/shadow`,
    `addgroup ${u} wheel 2>/dev/null; true`,
    `mkdir -p /home/${u}/.ssh && printf '%s\\n' ${sq(inst.pubkey || "")} > /home/${u}/.ssh/authorized_keys`,
    `chown -R ${u}:${u} /home/${u}/.ssh && chmod 700 /home/${u}/.ssh && chmod 600 /home/${u}/.ssh/authorized_keys`,
    `mkdir -p /etc/vyomi && printf '%s\\n' ${sq(JSON.stringify({ instance_id: inst.id, cloud: inst.cloud, user: u }))} > /etc/vyomi/instance.json`,
    `rm -f /etc/dropbear/dropbear_*_host_key; killall dropbear 2>/dev/null; sleep 0.3; /usr/sbin/dropbear -R -p 22`,
  ].join("\n");
  const r = await agentExec(script, "root", 60000);
  if (r.exit_code !== 0) throw new Error("provisioning failed: " + r.stdout.slice(-300));
}

// ── vyomi-tunnel TCP bridge ───────────────────────────────────────────────
// Text frames: JSON control. Binary frames: [u32 stream id][payload].
const streams = new Map();   // sid -> {conn, open, queue}
function relayConnect() {
  if (!inst || !inst.relay || !relayWanted) return;
  const u = inst.relay.replace(/^http/, "ws").replace(/\/$/, "") +
    `/vm?vm=${encodeURIComponent(inst.id)}&port=22&prefer=${inst.prefer_port || 0}`;
  let ws;
  try { ws = new WebSocket(u); } catch (_) { return setTimeout(relayConnect, 5000); }
  ws.binaryType = "arraybuffer";
  relay = ws;
  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") {
      const dv = new DataView(ev.data); const sid = dv.getUint32(0);
      const s = streams.get(sid); if (!s) return;
      const payload = new Uint8Array(ev.data, 4);
      if (s.open) s.conn.write(payload); else s.queue.push(payload.slice());
      return;
    }
    let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === "ping") { ws.send(JSON.stringify({ type: "pong" })); return; }
    if (m.type === "vm-listening") { hostPort = m.host_port; broadcast({ type: "vm-status", ...statusObj() }); return; }
    if (m.type === "tcp-open") openStream(ws, m.sid, m.port || 22);
    if (m.type === "tcp-close") { const s = streams.get(m.sid); if (s) { streams.delete(m.sid); try { s.conn.close(); } catch (_) {} } }
  };
  ws.onclose = () => {
    if (relay === ws) relay = null;
    for (const [sid, s] of streams) { try { s.conn.close(); } catch (_) {} streams.delete(sid); }
    broadcast({ type: "vm-status", ...statusObj() });
    if (relayWanted) setTimeout(relayConnect, 4000);
  };
  ws.onopen = () => broadcast({ type: "vm-status", ...statusObj() });
}
function openStream(ws, sid, port) {
  if (!emu || state !== "running" || !emu.network_adapter || !emu.network_adapter.connect) {
    ws.send(JSON.stringify({ type: "tcp-close", sid, reason: "vm not running" })); return;
  }
  const conn = emu.network_adapter.connect(port);
  const s = { conn, open: false, queue: [] };
  streams.set(sid, s);
  const frame = (data) => {
    const out = new Uint8Array(4 + data.length);
    new DataView(out.buffer).setUint32(0, sid); out.set(data, 4);
    try { ws.send(out); } catch (_) {}
  };
  conn.on("connect", () => {
    s.open = true;
    for (const q of s.queue) conn.write(q);
    s.queue = [];
    ws.send(JSON.stringify({ type: "tcp-opened", sid }));
  });
  conn.on("data", (d) => frame(d instanceof Uint8Array ? d : new Uint8Array(d)));
  const closed = () => {
    if (!streams.has(sid)) return;
    streams.delete(sid);
    try { ws.send(JSON.stringify({ type: "tcp-close", sid })); } catch (_) {}
  };
  conn.on("shutdown", () => { closed(); try { conn.close(); } catch (_) {} });
  conn.on("close", closed);
}

// ── checkpoints ───────────────────────────────────────────────────────────
// A running VM saves its state every CHECKPOINT_MS, so if every Nano page goes away
// (browser closed, or a browser without SharedWorker extendedLifetime navigating
// between consoles) the next page resumes it from there instead of a fresh image.
const CHECKPOINT_MS = 5 * 60 * 1000;
setInterval(() => {
  if (state !== "running" || !emu || !inst) return;
  serial(async () => {
    if (state !== "running" || !emu) return;
    const t0 = performance.now();
    try {
      emu.stop();
      const raw = await emu.save_state();
      emu.run();
      await idb("put", "state:" + inst.id, await gzip(raw));
      timings.checkpoint_ms = Math.round(performance.now() - t0); timings.checkpoint_at = Date.now();
    } catch (_) { try { emu.run(); } catch (_) {} }
  });
}, CHECKPOINT_MS);

// ── lifecycle ─────────────────────────────────────────────────────────────
let busy = Promise.resolve(), launching = false;
function serial(fn) { const p = busy.then(fn, fn); busy = p.catch(() => {}); return p; }

async function doLaunch(m) {
  inst = { id: m.id, cloud: m.cloud || "aws", user: m.user || "ec2-user", pubkey: m.pubkey || "",
           hostname: m.hostname || m.id, mem_mb: m.mem_mb || 256, relay: m.relay || "", prefer_port: m.prefer_port || 0 };
  const saved = await idb("get", "state:" + inst.id).catch(() => null);
  try {
    setState("booting", saved ? "resuming saved state" : "restoring VM image");
    if (saved) {
      await bootFrom(saved);
      await agentExec(`date -s @${Math.floor(Date.now() / 1000)} >/dev/null 2>&1`, "root", 20000).catch(() => {});
    }
    else { const g = await golden(); setState("booting", "provisioning"); await bootFrom(g); await provision(); }
    setState("running", "");
    relayWanted = true; if (!relay) relayConnect();
  } catch (e) {
    if (!m.debug) await destroyEmu();
    setState("error", String(e && e.message || e));
    throw e;
  }
}
async function doStop() {
  if (!emu) { setState("stopped", ""); return; }
  setState("stopping", "saving VM state");
  const t0 = performance.now();
  try { emu.stop(); } catch (_) {}
  const raw = await emu.save_state();
  const gz = await gzip(raw);
  await idb("put", "state:" + inst.id, gz);
  timings.save_ms = Math.round(performance.now() - t0); timings.saved_bytes = gz.byteLength;
  relayWanted = false; if (relay) try { relay.close(); } catch (_) {}
  await destroyEmu();
  setState("stopped", "");
}
async function doStart() {
  if (state === "running") return;
  const saved = await idb("get", "state:" + inst.id).catch(() => null);
  if (!saved) return doLaunch(inst);
  setState("booting", "resuming saved state");
  await bootFrom(saved);
  // the clock stood still while stopped
  await agentExec(`date -s @${Math.floor(Date.now() / 1000)} >/dev/null 2>&1`, "root", 20000).catch(() => {});
  setState("running", "");
  relayWanted = true; if (!relay) relayConnect();
}
async function doTerminate() {
  relayWanted = false; if (relay) try { relay.close(); } catch (_) {}
  await destroyEmu();
  if (inst) await idb("delete", "state:" + inst.id).catch(() => {});
  setState("terminated", "");
  setTimeout(() => self.close(), 500);
}

self.onconnect = (ev) => {
  const port = ev.ports[0];
  clients.add(port);
  port.onmessage = async (e) => {
    const m = e.data || {}; const rid = m.rid;
    const reply = (o) => { try { port.postMessage({ rid, ...o }); } catch (_) {} };
    try {
      if (m.type === "status") return reply({ ok: true, ...statusObj() });
      if (m.type === "bye") { clients.delete(port); return; }
      if (m.type === "serial-in") { if (emu) emu.serial0_send(m.data || ""); return reply({ ok: true }); }
      if (m.type === "exec") {
        if (state !== "running" || !emu) return reply({ ok: false, error: "InstanceNotRunning", state });
        const r = await agentExec(m.command || "", m.user || (inst && inst.user), m.timeout_ms || 60000);
        return reply({ ok: true, ...r });
      }
      if (m.type === "launch") {
        if (launching || (inst && (state === "running" || state === "booting"))) return reply({ ok: true, ...statusObj() });
        launching = true;
        try { await serial(() => doLaunch(m)); } finally { launching = false; }
        return reply({ ok: true, ...statusObj() });
      }
      if (m.type === "relay") { if (inst) { inst.relay = m.relay; relayWanted = state === "running"; if (relay) relay.close(); else relayConnect(); } return reply({ ok: true }); }
      if (m.type === "stop") { await serial(doStop); return reply({ ok: true, ...statusObj() }); }
      if (m.type === "start") { await serial(doStart); return reply({ ok: true, ...statusObj() }); }
      if (m.type === "terminate") { await serial(doTerminate); return reply({ ok: true, ...statusObj() }); }
      reply({ ok: false, error: "unknown message " + m.type });
    } catch (err) { reply({ ok: false, error: String(err && err.message || err), ...statusObj() }); }
  };
  port.start && port.start();
};
