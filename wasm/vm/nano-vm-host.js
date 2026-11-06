/* Vyomi Nano — page-side host for in-browser VMs (EC2 / Compute Engine / Azure VMs).
 *
 * One backend for all three clouds: every instance record in the stores (EC2
 * instance, GCE instance, ARM virtualMachine) gets a real v86 VM, run by a
 * SharedWorker named "vm-<id>" (./vm-worker.js). Only the cloud-specific bits
 * differ: the login user (ec2-user|ubuntu / the GCE ssh-keys user / the Azure
 * adminUsername), the ids and the API paths.
 *
 *   console page (Pyodide stores) ──reconcile──▶ SharedWorker vm-<id> (v86)
 *                                                  └─WS─▶ vyomi-tunnel ◀─ssh─ laptop
 *
 * Feature flag: localStorage nano_vm_compute = "1" (or ?nano_vm=1 once). Off by
 * default: nothing here loads the engine (2 MB) or the image (21 MB) until the
 * flag is on AND an instance exists. With the flag off the Connect endpoints keep
 * answering 409 NoRuntime, exactly as before.
 *
 * API (window.NanoVM):
 *   init({listDesired, annotate})  console pages: reconcile against the stores
 *   resume()                       any Nano page: keep known running VMs alive
 *   kick()                         reconcile soon (after a compute mutation)
 *   handle(cloud, op, params)      SW tuples [cloud, "_vm", op, {ref, body}]
 */
(function () {
  if (window.NanoVM) return;
  const SCRIPT = document.currentScript && document.currentScript.src;
  const VM_BASE = SCRIPT ? new URL("./", SCRIPT).href : new URL("vm/", location.href).href;
  const REG_KEY = "nano_vm_registry", KEY_KEY = "nano_vm_account_key";

  try { if (/[?&]nano_vm=1\b/.test(location.search)) localStorage.setItem("nano_vm_compute", "1"); } catch (_) {}
  const enabled = () => { try { return localStorage.getItem("nano_vm_compute") === "1"; } catch (_) { return false; } };
  const relayBase = () => { try { return (localStorage.getItem("nano_local_ext") || "http://127.0.0.1:8090").replace(/\/$/, ""); } catch (_) { return "http://127.0.0.1:8090"; } };

  const vmId = (cloud, ref) => cloud === "aws" ? String(ref) : (cloud === "gcp" ? "gce-" : "az-") + ref;
  const readReg = () => { try { return JSON.parse(localStorage.getItem(REG_KEY) || "{}"); } catch (_) { return {}; } };
  const writeReg = (r) => { try { localStorage.setItem(REG_KEY, JSON.stringify(r)); } catch (_) {} };

  // ── the Nano account SSH key (one per browser profile, like the appliance's shared instance key) ──
  function b64u2bytes(s) { s = s.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "="; return Uint8Array.from(atob(s), (c) => c.charCodeAt(0)); }
  function sshString(bytes) { const o = new Uint8Array(4 + bytes.length); new DataView(o.buffer).setUint32(0, bytes.length); o.set(bytes, 4); return o; }
  function mpint(bytes) { let i = 0; while (i < bytes.length - 1 && bytes[i] === 0) i++; bytes = bytes.slice(i); if (bytes[0] & 0x80) { const p = new Uint8Array(bytes.length + 1); p.set(bytes, 1); bytes = p; } return sshString(bytes); }
  function concat(...a) { const n = a.reduce((s, x) => s + x.length, 0), o = new Uint8Array(n); let k = 0; for (const x of a) { o.set(x, k); k += x.length; } return o; }
  function b64(bytes) { let s = ""; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000)); return btoa(s); }
  let keyPromise = null;
  function accountKey() {
    if (keyPromise) return keyPromise;
    const make = async () => {
      try { const k = JSON.parse(localStorage.getItem(KEY_KEY) || "null"); if (k && k.pub && k.pem) return k; } catch (_) {}
      const kp = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
      const jwk = await crypto.subtle.exportKey("jwk", kp.publicKey);
      const blob = concat(sshString(new TextEncoder().encode("ssh-rsa")), mpint(b64u2bytes(jwk.e)), mpint(b64u2bytes(jwk.n)));
      const pkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", kp.privateKey));
      const pem = "-----BEGIN PRIVATE KEY-----\n" + b64(pkcs8).replace(/(.{64})/g, "$1\n").replace(/\n$/, "") + "\n-----END PRIVATE KEY-----\n";
      const k = { pub: "ssh-rsa " + b64(blob) + " vyomi-nano", pem, created: new Date().toISOString() };
      try { localStorage.setItem(KEY_KEY, JSON.stringify(k)); } catch (_) {}
      return k;
    };
    keyPromise = (navigator.locks ? navigator.locks.request("nano-vm-account-key", make) : make());
    return keyPromise;
  }

  // ── SharedWorker handles ────────────────────────────────────────────────
  const handles = new Map();   // vm id -> {port, status, waits}
  let ridSeq = 0;
  function attach(id) {
    let h = handles.get(id);
    if (h) return h;
    // extendedLifetime (Chrome 13x+): the VM worker outlives the page while you navigate
    // between consoles; elsewhere it restarts from its last checkpoint (vm-worker.js).
    const w = new SharedWorker(VM_BASE + "vm-worker.js", { name: "vm-" + id, extendedLifetime: true });
    h = { port: w.port, status: null, waits: new Map() };
    w.port.onmessage = (e) => {
      const m = e.data || {};
      if (m.rid && h.waits.has(m.rid)) { const r = h.waits.get(m.rid); h.waits.delete(m.rid); r(m); }
      if (m.type === "vm-status" || (m.rid && m.state)) { h.status = { ...m }; onStatus(id, h.status); }
      if (m.type === "serial-out") for (const f of serialSubs) { try { f(id, m.data); } catch (_) {} }
    };
    w.port.start();
    handles.set(id, h);
    addEventListener("pagehide", () => { try { w.port.postMessage({ type: "bye" }); } catch (_) {} });
    return h;
  }
  function call(id, msg, timeoutMs = 300000) {
    const h = attach(id), rid = "p" + (++ridSeq);
    return new Promise((resolve) => {
      const t = setTimeout(() => { h.waits.delete(rid); resolve({ ok: false, error: "timeout", state: h.status && h.status.state }); }, timeoutMs);
      h.waits.set(rid, (m) => { clearTimeout(t); resolve(m); });
      h.port.postMessage({ ...msg, rid });
    });
  }
  const serialSubs = new Set();

  // Runtime facts → the instance record (grid / describe show launch status + ssh port).
  let annotateFn = null;
  const lastAnn = new Map();
  const lastState = new Map();
  let powerT = null;
  function onStatus(id, st) {
    // Power transition (booting -> running ...): tell the open console to repaint its state badge in place.
    if (lastState.get(id) !== st.state) {
      lastState.set(id, st.state);
      clearTimeout(powerT);
      powerT = setTimeout(() => { try { window.dispatchEvent(new CustomEvent("nano-vm-power", { detail: { id, state: st.state } })); } catch (_) {} }, 400);
    }
    const reg = readReg(), it = reg[id];
    if (!it || !annotateFn) return;
    const ann = { launch_status: st.state === "running" ? "ready" : st.state, nano_vm: { engine: "v86", state: st.state, host_port: st.host_port || null, image: st.image } };
    if (st.state === "running" && st.host_port) ann.ssh_command = sshCommand(it, st.host_port);
    const sig = JSON.stringify(ann);
    if (lastAnn.get(id) === sig) return;
    lastAnn.set(id, sig);
    try { annotateFn(it.cloud, it.ref, ann); } catch (_) {}
  }
  const keyFile = (it) => `~/.ssh/vyomi-${it.ref}.pem`;
  const sshCommand = (it, port) => `ssh -i ${keyFile(it)} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${port} ${it.user}@127.0.0.1`;

  async function launch(it) {
    const k = await accountKey();
    const keys = [k.pub, ...(it.keys || [])].join("\n");
    return call(it.id, { type: "launch", id: it.id, cloud: it.cloud, user: it.user, pubkey: keys, hostname: it.name || it.ref,
                         mem_mb: it.mem_mb || 512, relay: relayBase() });
  }

  // ── reconcile: stores → VMs ─────────────────────────────────────────────
  let listDesired = null, recTimer = null, reconciling = null;
  const missing = new Map();
  async function reconcile() {
    if (!enabled() || !listDesired) return;
    if (reconciling) return reconciling;
    reconciling = (async () => {
      let items;
      try { items = await listDesired(); } catch (_) { return; }
      if (!Array.isArray(items)) return;
      const reg = readReg(), seen = new Set();
      for (const it of items) {
        seen.add(it.id); missing.delete(it.id);
        const prev = reg[it.id] || {};
        reg[it.id] = { ...prev, ...it };
        if (it.desired === "terminate") { await call(it.id, { type: "terminate" }, 60000); delete reg[it.id]; handles.delete(it.id); continue; }
        const st = (handles.get(it.id) || {}).status || (await call(it.id, { type: "status" }, 10000));
        const s = st && st.state;
        if (it.desired === "run" && !["running", "booting"].includes(s)) {
          if (s === "stopped" || s === "stopping") call(it.id, { type: "start" });
          else launch(reg[it.id]);
        } else if (it.desired === "stop" && ["running", "booting"].includes(s)) {
          call(it.id, { type: "stop" });
        }
      }
      // An instance whose record is gone (deleted/terminated) — after two looks, so a
      // store that has not caught up with another context yet never kills a live VM.
      for (const id of Object.keys(reg)) {
        if (seen.has(id)) continue;
        const n = (missing.get(id) || 0) + 1; missing.set(id, n);
        if (n >= 2) { await call(id, { type: "terminate" }, 60000); delete reg[id]; handles.delete(id); missing.delete(id); }
      }
      writeReg(reg);
    })().finally(() => { reconciling = null; });
    return reconciling;
  }
  let loop = null;
  function kick() {
    if (!enabled()) return;
    if (!loop && listDesired) loop = setInterval(reconcile, 5000);   // the flag may have been turned on after init (no reload)
    clearTimeout(recTimer);
    recTimer = setTimeout(async () => { await reconcile(); setTimeout(reconcile, 1500); }, 50);
  }

  // Any Nano page: re-attach to the VMs that should be running, so they survive
  // moving between consoles (and come back from saved state after a browser restart).
  function resume() {
    if (!enabled()) return;
    const reg = readReg();
    for (const it of Object.values(reg)) {
      if (it.desired !== "run") continue;
      call(it.id, { type: "status" }, 10000).then((st) => {
        if (st && st.state === "stopped") call(it.id, { type: "start" });
        else if (!st || !["running", "booting"].includes(st.state)) launch(it);
      });
    }
  }

  // ── Connect / exec / key endpoints (SW tuples [cloud, "_vm", op, {ref, body}]) ──
  const http = (status, body, headers) => ({ __http: { status, body, headers: headers || {} } });
  async function tunnelHealth() {
    try { const r = await fetch(relayBase() + "/health", { cache: "no-store" }); return await r.json(); } catch (_) { return null; }
  }
  async function handle(cloud, op, params) {
    const ref = String((params && params.ref) || "");
    if (!enabled()) {
      return http(409, { detail: { error: "NoRuntime", hint: "In-browser VM compute is off in this Nano. Turn it on with localStorage.nano_vm_compute = '1' (or open the console with ?nano_vm=1), then launch the instance again." } });
    }
    let it = readReg()[vmId(cloud, ref)];
    if (!it) { await reconcile(); it = readReg()[vmId(cloud, ref)]; }
    if (!it) return http(404, { detail: { error: "InstanceNotFound", hint: `No ${cloud} instance '${ref}' in this Nano.` } });
    if (op === "PrivateKey") {
      const k = await accountKey();
      return { __raw: { status: 200, body: k.pem, headers: { "content-type": "application/x-pem-file", "content-disposition": `attachment; filename="vyomi-${ref}.pem"` } } };
    }
    const st = await call(it.id, { type: "status" }, 10000);
    if (op === "Status") return { ok: true, instance_id: ref, ...st, rid: undefined };
    if (op === "Exec") {
      const body = (params && params.body) || {};
      const command = String(body.command || body.data || "");
      if (!st || st.state !== "running") return http(409, { detail: "InstanceNotRunning", state: st && st.state, hint: st && st.detail });
      const r = await call(it.id, { type: "exec", command, user: body.user || it.user, timeout_ms: 12000 }, 14000);
      if (!r.ok) return http(r.error === "timeout" || /timed out/.test(r.error || "") ? 504 : 409, { detail: r.error || "exec failed" });
      return { ok: true, message: "Console command executed", instance_id: ref, stdout: r.stdout, stderr: "", exit_code: r.exit_code, output: r.stdout };
    }
    if (op === "ConnectInfo") {
      if (!st || st.state !== "running") {
        return http(409, { detail: { error: st && st.state === "error" ? "VmFailed" : "InstanceNotReady",
          hint: st && st.state === "error" ? `The in-browser VM failed: ${st.detail}` :
                `The in-browser VM is ${st ? st.state : "starting"}${st && st.detail ? " (" + st.detail + ")" : ""}; retry in a few seconds.` } });
      }
      const ext = relayBase();
      if (!st.host_port) {
        const h = await tunnelHealth();
        const old = h && !(h.features || []).includes("vm-tcp");
        return http(409, { detail: { error: "TunnelRequired",
          hint: h ? (old ? `vyomi-tunnel ${h.version} at ${ext} cannot carry SSH yet; update it to 1.1.0 or newer (brew upgrade vyomi-tunnel), then retry.`
                         : `vyomi-tunnel at ${ext} is up; the VM is registering with it, retry in a few seconds.`)
                  : `SSH to an in-browser VM goes through the local tunnel. Start it on this machine: brew install vyomi-cloud/tap/vyomi-tunnel && vyomi-tunnel (expects ${ext}). The in-browser terminal works without it.` } });
      }
      const port = st.host_port, key = keyFile(it);
      const keyUrl = { aws: `/api/aws/ec2/instances/${ref}/private-key.pem`, gcp: `/api/gcp/compute/instances/${ref}/private-key.pem`,
                       azure: `/api/azure/vm/${ref}/private-key.pem` }[cloud];
      const cmd = sshCommand(it, port);
      return {
        ok: true, instance_id: ref, provisioned: true, backend: "nano-v86", auth_mode: "nano_account_key",
        ssh: {
          command: cmd, user: it.user, host: "127.0.0.1", port,
          setup_command: null, jump_host: null,
          key_download_url: keyUrl, key_local_filename: `vyomi-${ref}.pem`, host_identity_path: key,
          // The key comes from this browser (it never leaves it otherwise): download it, then move it into place.
          key_fetch_command: null,
          key_setup_command: `mkdir -p ~/.ssh && mv ~/Downloads/vyomi-${ref}.pem ${key} && chmod 600 ${key}`,
        },
        alternatives: [],
        lxc: null,
        runtime: { engine: "v86", os: "Alpine Linux 3.21 (i386, 32-bit)", arch: "i686", mem_mb: it.mem_mb, image: st.image,
                   where: "this browser tab (in-browser VM)", tunnel: ext },
        note: `This instance is a real Linux VM running inside your browser (v86, 32-bit x86, ${it.mem_mb} MB RAM). ` +
              `vyomi-tunnel forwards ${"127.0.0.1"}:${port} on this machine to its SSH port, so the command works from your terminal while this Nano tab is open. ` +
              `In-browser toolchain: git, Python 3, pip and apk. Package and git downloads go through the tunnel's allow-listed egress (pypi, Alpine, GitHub, GitLab); other hosts are blocked. Other languages run on the booster (Pro/Max).`,
      };
    }
    return http(400, { detail: "unknown op " + op });
  }

  // ── Connect tab (all three consoles) ──────────────────────────────────────
  // What it shows is exactly what works: the in-browser VM's state, the ssh command
  // through vyomi-tunnel (or why it's not available yet) and a browser terminal that
  // runs commands in the VM over the console's exec endpoint.
  const PATHS = {
    aws:   (r) => ({ ci: `/api/aws/ec2/instances/${r}/connect-info`, exec: `/api/aws/ec2/instances/${r}/exec` }),
    gcp:   (r) => ({ ci: `/api/gcp/compute/instances/${r}/connect-info`, exec: `/api/console/gce/instances/${r}/exec` }),
    azure: (r) => ({ ci: `/api/azure/vm/${r}/connect-info`, exec: `/api/console/azurevm/instances/${r}/exec` }),
  };
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "style") e.style.cssText = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
    }
    for (const c of kids.flat()) if (c != null) e.append(c.nodeType ? c : document.createTextNode(String(c)));
    return e;
  }
  const S = {
    box: "border:1px solid var(--line,#d5dbdb);border-radius:8px;padding:14px 16px;margin:0 0 14px;background:var(--card,transparent)",
    title: "font-weight:600;margin:0 0 8px",
    sub: "font-size:12px;color:var(--sub,#5f6b7a);margin:6px 0",
    pre: "font-family:ui-monospace,Menlo,monospace;font-size:12.5px;white-space:pre-wrap;word-break:break-all;background:var(--codebg,#f4f4f4);color:inherit;border-radius:6px;padding:8px 10px;margin:4px 0;flex:1",
    btn: "font:inherit;font-size:12px;padding:4px 10px;border:1px solid var(--line,#aab7b8);border-radius:6px;background:transparent;color:inherit;cursor:pointer;white-space:nowrap",
    warn: "border-left:4px solid #e07b00",
    ok: "border-left:4px solid #1d8102",
  };
  function cmdRow(cmd) {
    const b = h("button", { style: S.btn, onclick: async () => { try { await navigator.clipboard.writeText(cmd); b.textContent = "Copied"; } catch (_) { b.textContent = "Copy failed"; } setTimeout(() => (b.textContent = "Copy"), 1200); } }, "Copy");
    return h("div", { style: "display:flex;gap:8px;align-items:flex-start" }, h("pre", { style: S.pre, "data-nano-cmd": "1" }, cmd), b);
  }
  // The legacy consoles' fetch shim maps /api/* into the service-worker scope; the v4 consoles (/nano/v4/<cloud>/) have no shim.
  const apiBase = () => { const m = /^(.*)\/v4\//.exec(location.pathname); return m ? m[1] : ""; };
  function renderConnect(host, cloud, ref) {
    const wrap = h("div", { class: "nano-vm-connect", "data-cloud": cloud, "data-ref": ref });
    host.append(wrap);
    const P = PATHS[cloud](encodeURIComponent(ref));
    const userHint = { aws: "ec2-user (Amazon Linux AMIs) or ubuntu (Ubuntu AMIs)", gcp: "the user from your ssh-keys metadata (default gcpuser)", azure: "the VM's adminUsername (default azureuser)" }[cloud];
    async function paint() {
      wrap.innerHTML = "";
      wrap.append(h("div", { style: S.box },
        h("div", { style: S.title }, "In-browser VM"),
        h("div", { style: S.sub }, { aws: "Instance ID", gcp: "Instance", azure: "Virtual machine" }[cloud] + ": " + ref),
        h("div", { style: S.sub }, "In Vyomi Nano this instance is a real Linux VM running inside this browser tab (v86, 32-bit x86, Alpine Linux). " +
          "The cloud's image is not booted: the OS is Alpine, the login user follows the cloud (" + userHint + ").")));
      let r, j = null;
      try { r = await fetch(apiBase() + P.ci); j = await r.json(); } catch (e) { r = { status: 0 }; }
      if (!wrap.isConnected) return;   // a newer paint (React remount / repaint) owns the host now; never steal its shell
      const d = (j && j.detail) || {};
      if (!r.status || r.status !== 200 || !j || !j.ok) {
        const err = d.error || (j && j.reason) || "unavailable";
        const box = h("div", { style: S.box + ";" + S.warn },
          h("div", { style: S.title }, err === "NoRuntime" ? "In-browser VMs are off" : err === "TunnelRequired" ? "SSH needs vyomi-tunnel" : "VM not ready"),
          h("div", { style: S.sub }, d.hint || String(err)));
        if (err === "NoRuntime") {
          box.append(h("button", { style: S.btn, onclick: () => { try { localStorage.setItem("nano_vm_compute", "1"); } catch (_) {} kick(); try { window.dispatchEvent(new CustomEvent("nano-vm-power", { detail: { id: null, state: "enabled" } })); } catch (_) {} setTimeout(paint, 400); } }, "Turn on in-browser VMs"));  // no page reload: it dropped the user back to the console Home
        } else if (err === "TunnelRequired") {
          box.append(cmdRow("brew install vyomi-cloud/tap/vyomi-tunnel && vyomi-tunnel"));
        }
        if (err !== "NoRuntime") box.append(h("button", { style: S.btn + ";margin-top:6px", onclick: paint }, "Refresh"));
        wrap.append(box);
        if (err === "InstanceNotReady") setTimeout(() => { if (wrap.isConnected) paint(); }, 3000);
        if (err !== "TunnelRequired") return;
      } else {
        const s = j.ssh || {}, rt = j.runtime || {};
        wrap.append(h("div", { style: S.box + ";" + S.ok },
          h("div", { style: S.title }, "SSH from your terminal"),
          h("div", { style: S.sub }, `vyomi-tunnel forwards 127.0.0.1:${s.port} on this machine to the VM's SSH port, while this Nano tab is open.`),
          h("div", { style: S.sub }, "1. Download the key (one key per browser profile, valid for every Nano VM)"),
          h("div", {}, h("a", { href: s.key_download_url, download: s.key_local_filename, onclick: (e) => { e.preventDefault(); (window.vyDownloadKey || ((u, n) => fetch(apiBase() + u).then(r => r.blob()).then(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = n; a.click(); })))(s.key_download_url, s.key_local_filename); }, style: S.btn + ";display:inline-block;text-decoration:none" }, "Download " + s.key_local_filename)),
          h("div", { style: S.sub }, "2. Move it into place"), cmdRow(s.key_setup_command || ""),
          h("div", { style: S.sub }, "3. Connect"), cmdRow(s.command || ""),
          h("div", { style: S.sub }, `Logs you in as ${s.user} on ${rt.os || "the VM"}, ${rt.mem_mb || "?"} MB RAM.`)));
      }
      // Browser shell: a real terminal (xterm.js) on the VM's serial console (ttyS0 -> /bin/sh). No tunnel needed.
      wrap.append(shellBox(cloud, ref));
      wrap.append(h("div", { style: S.sub }, "Limits: 32-bit x86 only; RAM is the VM's disk (Stop saves it, Terminate discards it); " +
        "a background tab runs the VM several times slower; toolchain is git + Python (pip, apk) — package downloads need vyomi-tunnel running (allow-listed hosts only). Other languages run on the booster."));
    }
    paint();
    return wrap;
  }

  // ── in-browser shell (xterm.js on the VM serial console) ───────────────
  let xtermP = null;
  function loadXterm() {
    if (window.Terminal) return Promise.resolve(window.Terminal);
    return xtermP || (xtermP = new Promise((res) => {
      const l = document.createElement("link"); l.rel = "stylesheet"; l.href = VM_BASE + "xterm/xterm.css"; document.head.appendChild(l);
      const sc = document.createElement("script"); sc.src = VM_BASE + "xterm/xterm.js";
      sc.onload = () => res(window.Terminal); sc.onerror = () => res(null); document.head.appendChild(sc);
    }));
  }
  const terms = new Map();   // vm id -> {term, el}: survives console re-renders so the session is not lost
  function shellBox(cloud, ref) {
    const id = vmId(cloud, ref);
    const holder = h("div", { "data-nano-shell": "1", style: "background:#0c0c0c;border-radius:6px;padding:6px;min-height:120px" });
    const fsBtn = h("button", { style: S.btn + ";float:right", title: "Full screen (Esc to exit)", "data-nano-shell-fs": "1" }, "Full screen");
    const box = h("div", { style: S.box },
      h("div", { style: S.title }, "Shell", fsBtn),
      h("div", { style: S.sub }, "A real terminal on the VM's console (root, Alpine). Works without vyomi-tunnel. Click inside and type."),
      holder);
    // Full screen: the terminal box fills the display and the grid is re-fitted to it (and back on exit).
    const fit = () => {
      const t = terms.get(id); if (!t) return;
      const full = document.fullscreenElement === holder;
      try {
        if (!full) { t.term.resize(110, 22); return; }
        const d = t.term._core._renderService.dimensions.css.cell;
        const cols = Math.max(40, Math.floor((holder.clientWidth - 16) / d.width)), rows = Math.max(10, Math.floor((holder.clientHeight - 16) / d.height));
        t.term.resize(cols, rows); t.term.focus();
      } catch (_) {}
    };
    fsBtn.onclick = () => { if (document.fullscreenElement === holder) document.exitFullscreen(); else if (holder.requestFullscreen) holder.requestFullscreen(); };
    const onFs = () => { if (!holder.isConnected) { document.removeEventListener("fullscreenchange", onFs); return; } holder.style.padding = document.fullscreenElement === holder ? "10px" : "6px"; setTimeout(fit, 80); };
    document.addEventListener("fullscreenchange", onFs);
    loadXterm().then((T) => {
      if (!holder.isConnected) return;   // painted into a host that was already replaced
      if (!T) { holder.textContent = "Terminal failed to load."; return; }
      let t = terms.get(id);
      if (t) { holder.append(t.el); try { t.term.refresh(0, t.term.rows - 1); } catch (_) {} return; }
      const el = h("div", { class: "vy-term" });
      holder.append(el);
      const term = new T({ cols: 110, rows: 22, cursorBlink: true, fontSize: 13, fontFamily: "ui-monospace,Menlo,Consolas,monospace", theme: { background: "#0c0c0c" }, scrollback: 3000 });
      term.open(el);
      term.onData((d) => serialSend(cloud, ref, d));
      onSerial((sid, data) => { if (sid === id) term.write(data); });
      terms.set(id, { term, el });
      serialSend(cloud, ref, "\r");   // draw a prompt
    });
    return box;
  }

  // ── animated pending state ───────────────────────────────────────────
  (function () {
    const st = document.createElement("style");
    st.textContent = "@keyframes vyspin{to{transform:rotate(360deg)}}@keyframes vypulse{50%{opacity:.45}}@keyframes vylive{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(1.35)}}" +
      ".vy-live .pip,.vy-live .dot{animation:vylive 2s ease-in-out infinite}.vy-live:not(:has(.pip,.dot))::before{content:'';display:inline-block;width:7px;height:7px;margin-right:6px;border-radius:50%;background:currentColor;vertical-align:1px;animation:vylive 2s ease-in-out infinite}.vy-spin .pip,.vy-spin .dot{display:none}.vy-spin{animation:vypulse 1.3s ease-in-out infinite}.vy-spin::before{content:'';display:inline-block;width:9px;height:9px;margin-right:6px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;vertical-align:-1px;animation:vyspin .8s linear infinite}";
    st.textContent += "[data-vy-pending]{animation:vypulse 1.3s ease-in-out infinite}[data-vy-pending=spin]::before{content:'';display:inline-block;width:9px;height:9px;margin-right:6px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;vertical-align:-1px;animation:vyspin .8s linear infinite}";   // class-free hook the v4 status components set
    document.head.appendChild(st);
    const PEND = /^(pending|starting|provisioning|staging|vm starting|creating|stopping|shutting-down|deallocating|vm stopping|vm deallocating)$/i;
    const LIVE = /^(running|vm running)$/i;
    const own = (n) => Array.from(n.childNodes).filter((c) => c.nodeType === 3).map((c) => c.textContent).join('').trim().replace(/^PowerState\//i, '');
    let q = false;
    const scan = () => {
      q = false;
      document.querySelectorAll('.vy-spin').forEach((n) => { if (!PEND.test(own(n))) n.classList.remove('vy-spin'); });
      document.querySelectorAll('.vy-live').forEach((n) => { if (!LIVE.test(own(n))) n.classList.remove('vy-live'); });
      document.querySelectorAll("#main span, #main td, #main div, #bladeBody span, #bladeBody div, #bladeBody td").forEach((n) => {
        if (n.classList.contains("vy-spin") || n.children.length > 2) return;
        if (PEND.test(own(n))) n.classList.add("vy-spin");
        else if (LIVE.test(own(n)) && !n.classList.contains("vy-live")) n.classList.add("vy-live");
      });
    };
    new MutationObserver(() => { if (!q) { q = true; setTimeout(scan, 120); } }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  })();

  function onSerial(fn) { serialSubs.add(fn); return () => serialSubs.delete(fn); }
  function serialSend(cloud, ref, data) { const it = readReg()[vmId(cloud, ref)]; if (it) attach(it.id).port.postMessage({ type: "serial-in", data }); }


  // ── console view: show the VM's real power state ─────────────────────────
  // The cloud record says "running" the moment an instance is created, but the in-browser VM only exists when VM
  // compute is on and it has booted. Console-only: the page's fetch of the three consoles' instance records is
  // rewritten to "stopped" (VM compute off / VM not running: start it manually from Connect) or "pending" (booting).
  // The SDK/CLI/service-worker paths never go through this fetch, so their instance states are unchanged.
  const vmPower = (cloud, ref) => {
    if (!enabled()) return "stopped";
    const s = (handles.get(vmId(cloud, ref)) || {}).status;
    const st = s && s.state;
    return st === "running" ? "running" : (!st || st === "booting" || st === "launching" || st === "starting") ? "pending" : "stopped";
  };
  // what a v4 console shows for a store-"running" instance: running | pending | stopped
  const shownPower = (cloud, ref) => vmPower(cloud, ref);
  const AWS_S = { stopped: "stopped", pending: "pending" }, GCP_S = { stopped: "TERMINATED", pending: "PROVISIONING" };
  const AZ_S = { stopped: "stopped", pending: "starting" };
  function viewFix(node, depth) {
    if (!node || typeof node !== "object" || depth > 6) return;
    if (Array.isArray(node)) { node.forEach((x) => viewFix(x, depth + 1)); return; }
    try {
      if (typeof node.instance_id === "string" && /^running$/i.test(String(node.state || ""))) {            // EC2
        const v = vmPower("aws", node.instance_id); if (v !== "running") { node.state = AWS_S[v]; node.vm_note = "In-browser VM is " + (v === "pending" ? "starting" : "not running — start it from Connect"); }
      } else if (typeof node.machineType === "string" && /^RUNNING$/i.test(String(node.status || ""))) {     // Compute Engine
        const n = String(node.name || "").split("/").pop(), v = vmPower("gcp", n); if (v !== "running") node.status = GCP_S[v];
      } else if (/virtualMachines$/i.test(String(node.type || "")) && node.properties) {                    // Azure VM
        const v = vmPower("azure", node.name || ""), ps = String(node.properties.powerState || "");
        if (v !== "running" && (!ps || /running$/i.test(ps))) node.properties.powerState = "PowerState/" + AZ_S[v];
      } else if (Array.isArray(node.statuses) && node.statuses.some((s) => /^PowerState\/running$/i.test(String(s && s.code)))) { // Azure instanceView
        const ref = (/\/virtualMachines\/([^/]+)\/instanceView/i.exec(viewFix.url || "") || [])[1];
        if (ref) { const v = vmPower("azure", decodeURIComponent(ref)); if (v !== "running") node.statuses.forEach((s) => { if (/^PowerState\/running$/i.test(String(s.code))) { s.code = "PowerState/" + AZ_S[v]; s.displayStatus = "VM " + AZ_S[v]; } }); }
      }
    } catch (_) {}
    for (const k of Object.keys(node)) if (node[k] && typeof node[k] === "object") viewFix(node[k], depth + 1);
  }
  const VM_URL = /\/api\/ec2\/instances(\/|\?|$)|\/compute\/v1\/projects\/[^/]+\/zones\/[^/]+\/instances|\/Microsoft\.Compute\/virtualMachines/i;
  if (!window.__vmViewFetch) {
    window.__vmViewFetch = true;
    const of = window.fetch.bind(window);
    window.fetch = async function (input, init) {
      const res = await of(input, init);
      try {
        const u = typeof input === "string" ? input : (input && input.url) || "";
        const m = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
        if (m !== "GET" || !VM_URL.test(u) || /\/_wire\//.test(u) || /private-key|connect-info|\/exec|vm-status/.test(u) || !/json/i.test(res.headers.get("content-type") || "")) return res;
        const j = await res.clone().json(); viewFix.url = u; viewFix(j, 0);
        return new Response(JSON.stringify(j), { status: res.status, statusText: res.statusText, headers: res.headers });
      } catch (_) { return res; }
    };
  }
  window.NanoVM = {
    enabled, kick, resume, handle, onSerial, serialSend, accountKey, vmId, renderConnect, shownPower,
    registry: readReg,
    status: (cloud, ref) => call(vmId(cloud, ref), { type: "status" }, 10000),
    init(o) { listDesired = o.listDesired; annotateFn = o.annotate || null; if (enabled()) { resume(); reconcile(); setInterval(reconcile, 5000); } },
  };
})();
