/* `vyomi-tunnel mcp`: run the Vyomi MCP server (the Go vyomi-mcp, cmd/vyomi) on this process's stdin/stdout.
 *
 * The npm package bundles one binary per platform at ../mcp/<platform>-<arch>/vyomi-mcp[.exe], relative to this file (Node's names:
 * darwin-arm64, darwin-x64, linux-arm64, linux-x64, win32-x64; built by scripts/build_tunnel_mcp.sh, never committed). Without it
 * (unsupported platform, trimmed install, the in-repo copy) the launcher falls back to `vyomi-mcp`, then `vyomi mcp`, on PATH.
 *
 * Rules: stdout is the MCP protocol channel, so this file never writes to it; a failure is ONE stderr line and exit 127.
 * It needs no Vyomi key (the entry script dispatches `mcp` before the credentials gate). The child gets VYOMI_TUNNEL_BIN = this
 * install's entry script, so the MCP calls back the same vyomi-tunnel (`list mesh --json`) instead of whatever is on PATH.
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawn } from "node:child_process";
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

/** Run the MCP with stdio inherited; resolves with its exit code (128 + signal number when it was killed). */
export function launchMcp(args = [], { entryUrl, dir = here, env = process.env, stderr = process.stderr } = {}) {
  const r = resolveMcp(args, { dir, env });
  if (r.error) { stderr.write(r.error + "\n"); return Promise.resolve(127); }
  const childEnv = { ...env };
  if (entryUrl) childEnv.VYOMI_TUNNEL_BIN = fileURLToPath(entryUrl);
  // The MCP runs `node <VYOMI_TUNNEL_BIN> list ...`: make sure the node running us is findable even if PATH lacks it (appended, so it never shadows).
  const nodeDir = path.dirname(process.execPath);
  if (!String(childEnv.PATH || "").split(path.delimiter).includes(nodeDir)) childEnv.PATH = [childEnv.PATH, nodeDir].filter(Boolean).join(path.delimiter);
  return new Promise((resolve) => {
    let child;
    try { child = spawn(r.cmd, r.args, { stdio: "inherit", env: childEnv, windowsHide: true }); }
    catch (e) { stderr.write(`vyomi-tunnel: cannot start ${r.cmd}: ${e.message}\n`); resolve(127); return; }
    const fwd = (sig) => () => { try { child.kill(sig); } catch { /* gone */ } };
    const handlers = ["SIGINT", "SIGTERM", "SIGHUP"].filter((s) => !(process.platform === "win32" && s === "SIGHUP")).map((s) => [s, fwd(s)]);
    for (const [s, h] of handlers) process.on(s, h);
    const done = (code) => { for (const [s, h] of handlers) process.off(s, h); resolve(code); };
    child.on("error", (e) => { stderr.write(`vyomi-tunnel: cannot start ${r.cmd}: ${e.code || e.message}\n`); done(127); });
    child.on("exit", (code, signal) => done(code ?? 128 + (os.constants.signals[signal] || 0)));
  });
}
