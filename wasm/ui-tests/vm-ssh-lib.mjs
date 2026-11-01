/* Nano post-create probe core for VMs (EC2 / Compute Engine / Azure VM): the instance
 * must be USABLE the way the console says, from the user's own terminal.
 *
 * Contract (PLAN: tests/conformance/post_create/PLAN.md; offline twin: probes/vm_ssh.py):
 *   GET  <connect-info>     -> 200 {ok:true, ssh:{command, host, port, key_download_url}}
 *   GET  <private-key.pem>  -> the key the shown `ssh -i` needs
 *   real `ssh` from THIS machine with the shown command (through vyomi-tunnel)
 *     -> whoami, uname, file write + read back, a python http.server answering in the VM
 *   POST <exec> {command}   -> {stdout, exit_code}   (the console terminal's path)
 *   stop -> ssh refused; start -> the file written before the stop is still there
 *   delete -> the tunnel's port for it is closed (no leak)
 * The browser page is a real Nano console (flag nano_vm_compute=1) and the tunnel is
 * a real vyomi-tunnel at RELAY_HTTP (wasm/relay/local-relay.mjs >= 1.1.0).
 */
import { spawnSync, spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, chmodSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import net from "node:net";
import { startServer, bootConsole, chromium, sleep, RELAY, relayHealth } from "./lib.mjs";

export async function openNano(consolePath) {
  const { server, base } = await startServer(process.env.NANO_DIR, Number(process.env.NANO_PORT || 0));
  const userDataDir = process.env.NANO_PROFILE || "";
  const browser = userDataDir ? null : await chromium.launch();
  const ctx = userDataDir ? await chromium.launchPersistentContext(userDataDir, {}) : await browser.newContext();
  const ext = RELAY.replace(/\/$/, "");
  await ctx.addInitScript((ext) => {
    try {
      localStorage.setItem("nano_vm_compute", "1");
      localStorage.setItem("nano_local_ext", ext);
      localStorage.setItem("nano_local_health", ext + "/health");
      localStorage.setItem("nano_local_ws", ext.replace(/^http/, "ws") + "/register");
    } catch (_) {}
  }, ext);
  const page = ctx.pages()[0] || await ctx.newPage();
  page.on("console", (m) => { if (process.env.VM_DEBUG) console.log("[page]", m.text().slice(0, 300)); });
  await bootConsole(page, base, consolePath);
  const call = (method, path, body, raw) => page.evaluate(async ([m, p, b, raw]) => {
    const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
    const t = await r.text();
    let j = null; if (!raw) { try { j = JSON.parse(t); } catch (_) {} }
    return { status: r.status, body: raw ? t : j };
  }, [method, path, body, !!raw]);
  const close = async () => { try { await ctx.close(); } catch (_) {} if (browser) await browser.close(); server.close(); };
  return { page, call, close, base };
}

function ssh(argv, remote, timeoutMs = 60000) {
  const r = spawnSync(argv[0], [...argv.slice(1), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "LogLevel=ERROR", remote],
                      { encoding: "utf8", timeout: timeoutMs });
  return { rc: r.status, out: r.stdout || "", err: (r.stderr || "") + (r.error ? String(r.error) : "") };
}
const portOpen = (port) => new Promise((res) => {
  const s = net.connect({ host: "127.0.0.1", port }, () => { s.destroy(); res(true); });
  s.on("error", () => res(false)); s.setTimeout(3000, () => { s.destroy(); res(false); });
});
function shellSplit(cmd) { return (cmd.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g) || []).map((x) => x.replace(/^["']|["']$/g, "")); }

/* cfg: {cloud, label, ciPath, keyPath?, execPath, stop(), start(), del(), waitState?} */
export async function probeVm(nano, cfg, check) {
  const { call } = nano;
  const tmp = mkdtempSync(join(tmpdir(), "nano-vm-"));
  try {
    const h = await relayHealth();
    check("vyomi-tunnel reachable and VM-capable (vm-tcp)", !!(h && (h.features || []).includes("vm-tcp")), JSON.stringify(h).slice(0, 160));

    // connect-info: 409 InstanceNotReady while the VM boots (first launch in a browser
    // cold-boots the image once, ~20-60 s), then 200 with the ssh command.
    let ci = null; const t0 = Date.now();
    for (let i = 0; i < 120; i++) {
      ci = await call("GET", cfg.ciPath);
      if (ci.status === 200 && ci.body && ci.body.ok) break;
      await sleep(2000);
    }
    const ok = ci.status === 200 && ci.body && ci.body.ok;
    check("connect info available (CONNECT_INFO_MISSING)", ok, `status ${ci.status} ${JSON.stringify(ci.body).slice(0, 220)} after ${Math.round((Date.now() - t0) / 1000)}s`);
    if (!ok) return;
    const sshi = ci.body.ssh || {};
    const cmd = sshi.command || "";
    check("console shows an ssh command (CONNECT_INFO_MISSING)", /^ssh /.test(cmd) && !!sshi.host && !!sshi.port, cmd);
    check("shown host is this machine, not an in-browser address (CONNECT_INFO_UNREACHABLE)", sshi.host === "127.0.0.1", sshi.host);
    check("shown host:port reachable from the user's machine (CONNECT_INFO_UNREACHABLE)", await portOpen(Number(sshi.port)), `${sshi.host}:${sshi.port}`);

    const kr = await call("GET", sshi.key_download_url, null, true);
    const keyfile = join(tmp, "key.pem");
    writeFileSync(keyfile, kr.body || ""); chmodSync(keyfile, 0o600);
    check("key obtainable from what the console shows (CONNECT_INFO_MISSING)", kr.status === 200 && /PRIVATE KEY/.test(kr.body || ""), `status ${kr.status}`);
    check("shown -i path is a path on the user's machine", /^~\/\.ssh\/vyomi-/.test(sshi.host_identity_path || ""), sshi.host_identity_path);

    const argv = shellSplit(cmd);
    const ki = argv.indexOf("-i"); if (ki >= 0) argv[ki + 1] = keyfile;
    let r = ssh(argv, "echo POSTCREATE-OK; whoami; uname -m; echo vyomi > ~/pc.txt; cat ~/pc.txt");
    check("ssh with the shown command runs a command (POST_CREATE_UNUSABLE)", r.rc === 0 && r.out.includes("POSTCREATE-OK"), `rc=${r.rc} ${r.err.trim().slice(-200)}`);
    const lines = r.out.split("\n").map((s) => s.trim());
    check(`logged in as the ${cfg.cloud} default user (${cfg.user})`, lines[1] === cfg.user, lines.slice(0, 3).join(" | "));
    check("file write + read back on the instance", (lines[3] || "") === "vyomi", r.out.slice(-80));

    r = ssh(argv, "mkdir -p www && echo nano-http-ok > www/index.html && cd www && (setsid python3 -m http.server 8080 >/dev/null 2>&1 &) ; " +
                  "for i in $(seq 1 40); do wget -qO- http://127.0.0.1:8080/index.html 2>/dev/null && exit 0; sleep 1; done; exit 1", 90000);
    check("a python http.server runs and answers inside the VM", r.rc === 0 && r.out.includes("nano-http-ok"), `rc=${r.rc} ${r.out.slice(-80)} ${r.err.slice(-120)}`);

    const ex = await call("POST", cfg.execPath, { command: "whoami; cat ~/pc.txt" });
    check("console exec runs in the instance VM", ex.status === 200 && (ex.body.stdout || "").includes("vyomi") && (ex.body.stdout || "").includes(cfg.user),
          `status ${ex.status} ${JSON.stringify(ex.body).slice(0, 160)}`);

    // Stop → no ssh; Start → same disk (the file survives).
    const port = Number(sshi.port);
    await cfg.stop();
    let closed = false;
    for (let i = 0; i < 60 && !closed; i++) { await sleep(2000); closed = !(await portOpen(port)); }
    check("stop: the VM stops and its ssh port closes", closed);
    await cfg.start();
    let ci2 = null;
    for (let i = 0; i < 90; i++) { ci2 = await call("GET", cfg.ciPath); if (ci2.status === 200 && ci2.body && ci2.body.ok) break; await sleep(2000); }
    const argv2 = ci2 && ci2.body && ci2.body.ok ? shellSplit(ci2.body.ssh.command) : argv;
    const k2 = argv2.indexOf("-i"); if (k2 >= 0) argv2[k2 + 1] = keyfile;
    r = ssh(argv2, "cat ~/pc.txt");
    check("start: the VM comes back with its files (state saved on stop)", r.rc === 0 && r.out.trim() === "vyomi", `rc=${r.rc} ${r.out.slice(-60)} ${r.err.slice(-160)}`);

    const p2 = Number(ci2 && ci2.body && ci2.body.ssh ? ci2.body.ssh.port : port);
    await cfg.del();
    let gone = false;
    for (let i = 0; i < 40 && !gone; i++) { await sleep(1500); gone = !(await portOpen(p2)); }
    check("delete removes the VM (tunnel port closed, no leak)", gone, `port ${p2}`);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

export function reporter() {
  const results = [];
  const check = (name, ok, note = "") => { results.push({ name, ok: !!ok, note }); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + note}`); return ok; };
  const finish = () => process.exit(results.length && results.every((r) => r.ok) ? 0 : 1);
  return { check, finish, results };
}
