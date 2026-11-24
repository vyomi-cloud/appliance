/* `vyomi-tunnel mcp`: run the Vyomi MCP server (the Go vyomi-mcp, cmd/vyomi) on this process's stdin/stdout.
 *
 * The npm package bundles one binary per platform at ../mcp/<platform>-<arch>/vyomi-mcp[.exe], relative to this file (Node's names:
 * darwin-arm64, darwin-x64, linux-arm64, linux-x64, win32-x64; built by scripts/build_tunnel_mcp.sh, never committed). Without it
 * (unsupported platform, trimmed install, the in-repo copy) the launcher falls back to `vyomi-mcp`, then `vyomi mcp`, on PATH.
 *
 * Rules: stdout is the MCP protocol channel, so this file never writes to it; a failure is ONE stderr line and exit 127.
 * It needs no Vyomi key (the entry script dispatches `mcp` before the credentials gate). The child gets VYOMI_TUNNEL_BIN = this
 * install's entry script, so the MCP calls back the same vyomi-tunnel (`list mesh --json`) instead of whatever is on PATH.
 * An npx copy first hands over to an installed vyomi-tunnel (see installedTunnel), so `npx -y vyomi-tunnel mcp` and
 * `vyomi-tunnel mcp` run the same server.
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const exe = (platform) => (platform === "win32" ? ".exe" : "");

/** First executable `name` on PATH (PATHEXT on Windows), or null. */
export function onPath(name, { env = process.env, platform = process.platform } = {}) {
  const exts = platform === "win32" ? (env.PATHEXT || ".EXE;.CMD;.BAT").split(";").filter(Boolean) : [""];
  for (const dir of String(env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const f = path.join(dir, name + ext);
      try { if (fs.statSync(f).isFile()) { if (platform !== "win32") fs.accessSync(f, fs.constants.X_OK); return f; } } catch { /* next */ }
    }
  }
  return null;
}

/** Which binary to run: {cmd, args, via} or {error}. The bundled binary first (its exec bit restored once if an unpack dropped it). */
export function resolveMcp(args = [], { dir = here, platform = process.platform, arch = process.arch, env = process.env } = {}) {
  const bundled = path.join(dir, "..", "mcp", `${platform}-${arch}`, "vyomi-mcp" + exe(platform));
  let bundledNote = "";
  if (fs.existsSync(bundled)) {
    if (platform === "win32") return { cmd: bundled, args, via: "bundled" };
    try { fs.accessSync(bundled, fs.constants.X_OK); return { cmd: bundled, args, via: "bundled" }; } catch { /* not executable */ }
    try { fs.chmodSync(bundled, 0o755); fs.accessSync(bundled, fs.constants.X_OK); return { cmd: bundled, args, via: "bundled (exec bit restored)" }; }
    catch { bundledNote = ` (${bundled} is not executable: chmod 755 it)`; }
  }
  const mcp = onPath("vyomi-mcp", { env, platform }); if (mcp) return { cmd: mcp, args, via: "PATH vyomi-mcp" };
  const vyomi = onPath("vyomi", { env, platform }); if (vyomi) return { cmd: vyomi, args: ["mcp", ...args], via: "PATH vyomi mcp" };
  return { error: `vyomi-tunnel: no Vyomi MCP server for ${platform}-${arch}${bundledNote}. Reinstall: npm i -g vyomi-tunnel@latest (or brew reinstall vyomi-tunnel), or put vyomi-mcp on your PATH.` };
}

/* Keeping `npx -y vyomi-tunnel mcp` and `vyomi-tunnel mcp` in sync.
 * Plugins start the MCP with `npx -y vyomi-tunnel mcp`, which runs a copy from npm's npx cache. When the user also has vyomi-tunnel
 * installed (npm -g, Homebrew, ...), that installed tunnel is the one they run for Nano and meshes, and the MCP calls a tunnel back
 * (VYOMI_TUNNEL_BIN). So an npx copy hands over to the installed tunnel (1.3.0+, the first with `mcp`): both commands then run the
 * same server against the same tunnel. Only nothing installed (or one too old) leaves the npx copy running. When the npx copy is
 * newer, it passes its version on (VYOMI_TUNNEL_LATEST, beside VYOMI_TUNNEL_VERSION) so vyomi_status can suggest the upgrade.
 * VYOMI_MCP_DELEGATE=0 turns the handover off; the child always gets VYOMI_MCP_DELEGATE=0, so it can never loop. */
export const MIN_MCP_TUNNEL = [1, 3, 0];

export function parseVersion(s) {
  const m = /(\d+)\.(\d+)\.(\d+)/.exec(String(s || ""));
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}
export function cmpVersion(a, b) {
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return 0;
}
/** True when this file runs from npm's npx cache (~/.npm/_npx/<hash>/node_modules/vyomi-tunnel/...). */
export function fromNpx(file) {
  return /[\\/]_npx[\\/]/.test(String(file || ""));
}
/** Every executable `name` on PATH, in order (PATHEXT on Windows). */
export function allOnPath(name, { env = process.env, platform = process.platform } = {}) {
  const exts = platform === "win32" ? (env.PATHEXT || ".EXE;.CMD;.BAT").split(";").filter(Boolean) : [""];
  const out = [];
  for (const dir of String(env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const f = path.join(dir, name + ext);
      try { if (fs.statSync(f).isFile()) { if (platform !== "win32") fs.accessSync(f, fs.constants.X_OK); out.push(f); } } catch { /* next */ }
    }
  }
  return out;
}
const needsShell = (cmd, platform) => platform === "win32" && /\.(cmd|bat)$/i.test(cmd);
function ownVersion(entry) {
  try { return JSON.parse(fs.readFileSync(path.join(path.dirname(entry), "..", "package.json"), "utf8")).version || null; } catch { return null; }
}

/** The installed vyomi-tunnel an npx copy should hand over to: {cmd, version, self, note?}, or {note} / null when it should not. */
export function installedTunnel({ entry, env = process.env, platform = process.platform, probe } = {}) {
  if (!entry || env.VYOMI_MCP_DELEGATE === "0" || !(env.VYOMI_MCP_DELEGATE === "1" || fromNpx(entry))) return null;
  let selfReal = entry;
  try { selfReal = fs.realpathSync(entry); } catch { /* keep */ }
  const selfPkg = path.dirname(path.dirname(selfReal));            // .../node_modules/vyomi-tunnel
  const selfBin = path.join(path.dirname(selfPkg), ".bin");        // .../node_modules/.bin (npx puts it first on PATH)
  const self = ownVersion(selfReal);
  const versionOf = probe || ((cmd) => {
    const r = spawnSync(cmd, ["--version"], { encoding: "utf8", timeout: 5000, windowsHide: true, shell: needsShell(cmd, platform), env: { ...env, VYOMI_MCP_DELEGATE: "0" } });
    return r.status === 0 ? r.stdout : null;
  });
  for (const cand of allOnPath("vyomi-tunnel", { env, platform })) {
    let real = cand;
    try { real = fs.realpathSync(cand); } catch { /* keep */ }
    if (real === selfReal || path.dirname(cand) === selfBin || real.startsWith(selfPkg + path.sep) || fromNpx(real)) continue;
    const v = parseVersion(versionOf(cand));
    if (!v) continue;
    if (cmpVersion(v, MIN_MCP_TUNNEL) < 0) {
      return { note: `vyomi-tunnel: your installed vyomi-tunnel ${v.join(".")} (${cand}) is older than 1.3.0 and cannot run the MCP; using the npm copy${self ? " " + self : ""}. Upgrade it so both stay in sync: npm i -g vyomi-tunnel@latest (or brew upgrade vyomi-tunnel).` };
    }
    return { cmd: cand, version: v.join("."), self };
  }
  return null;
}

/** Spawn `cmd args` with stdio inherited; resolves with its exit code (128 + signal number when it was killed). */
function runInherited(cmd, args, childEnv, stderr, shell = false) {
  return new Promise((resolve) => {
    let child;
    try { child = spawn(cmd, args, { stdio: "inherit", env: childEnv, windowsHide: true, shell }); }
    catch (e) { stderr.write(`vyomi-tunnel: cannot start ${cmd}: ${e.message}\n`); resolve(127); return; }
    const fwd = (sig) => () => { try { child.kill(sig); } catch { /* gone */ } };
    const handlers = ["SIGINT", "SIGTERM", "SIGHUP"].filter((s) => !(process.platform === "win32" && s === "SIGHUP")).map((s) => [s, fwd(s)]);
    for (const [s, h] of handlers) process.on(s, h);
    const done = (code) => { for (const [s, h] of handlers) process.off(s, h); resolve(code); };
    child.on("error", (e) => { stderr.write(`vyomi-tunnel: cannot start ${cmd}: ${e.code || e.message}\n`); done(127); });
    child.on("exit", (code, signal) => done(code ?? 128 + (os.constants.signals[signal] || 0)));
  });
}

/** Run the MCP with stdio inherited; resolves with its exit code (128 + signal number when it was killed). */
export function launchMcp(args = [], { entryUrl, dir = here, env = process.env, stderr = process.stderr, platform = process.platform, probe } = {}) {
  const entry = entryUrl ? fileURLToPath(entryUrl) : null;
  const inst = installedTunnel({ entry, env, platform, probe });
  if (inst && inst.note) stderr.write(inst.note + "\n");
  if (inst && inst.cmd) {
    const childEnv = { ...env, VYOMI_MCP_DELEGATE: "0", VYOMI_TUNNEL_VERSION: inst.version };
    const selfV = parseVersion(inst.self);
    if (selfV && cmpVersion(selfV, parseVersion(inst.version)) > 0) {
      childEnv.VYOMI_TUNNEL_LATEST = inst.self;
      stderr.write(`vyomi-tunnel: running the MCP from your installed vyomi-tunnel ${inst.version} (npm has ${inst.self}). Upgrade: npm i -g vyomi-tunnel@latest (or brew upgrade vyomi-tunnel).\n`);
    }
    return runInherited(inst.cmd, ["mcp", ...args], childEnv, stderr, needsShell(inst.cmd, platform));
  }
  const r = resolveMcp(args, { dir, env });
  if (r.error) { stderr.write(r.error + "\n"); return Promise.resolve(127); }
  const childEnv = { ...env, VYOMI_MCP_DELEGATE: "0" };
  // An explicit VYOMI_TUNNEL_BIN (a test harness, a pinned install) wins, like every other VYOMI_* override.
  if (entry && !env.VYOMI_TUNNEL_BIN) childEnv.VYOMI_TUNNEL_BIN = entry;
  // The MCP runs `node <VYOMI_TUNNEL_BIN> list ...`: make sure the node running us is findable even if PATH lacks it (appended, so it never shadows).
  const nodeDir = path.dirname(process.execPath);
  if (!String(childEnv.PATH || "").split(path.delimiter).includes(nodeDir)) childEnv.PATH = [childEnv.PATH, nodeDir].filter(Boolean).join(path.delimiter);
  return runInherited(r.cmd, r.args, childEnv, stderr);
}
