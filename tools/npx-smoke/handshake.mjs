#!/usr/bin/env node
/* npx smoke for the vyomi-tunnel MCP: start a packed tarball through npx the way agents do, then MCP initialize + tools/list
 * (and, when asked, tools/call vyomi_status). Used by .github/workflows/tunnel-npx-smoke.yml on Linux, macOS and Windows.
 *
 *   node tools/npx-smoke/handshake.mjs --tarball dist/vyomi-tunnel-1.4.0.tgz                   # plain: npx -y ./<tgz> mcp
 *   node tools/npx-smoke/handshake.mjs --tarball <tgz> --mode sync --expect-handover 1.3.3     # sync: npx -y --package=./<tgz> vyomi-tunnel mcp
 *
 * Flags:
 *   --tarball <path>          the packed tunnel (a single `*` glob in the file name is expanded; required)
 *   --mode plain|sync         plain (default): `npx -y ./<tgz> mcp`. sync: `npx -y --package=./<tgz> vyomi-tunnel mcp` (both run in the
 *                             tarball's directory). Plain fails if the npx copy hands over; sync runs with an
 *                             installed vyomi-tunnel on PATH, which the npx copy must hand over to (wasm/relay/mcp-launch.mjs).
 *   --min-tools <n>           at least n tools (default 8)
 *   --expect-tool <name>      a tool that must be listed (repeatable; default vyomi_status)
 *   --expect-handover <ver>   the launcher's stderr line "running the MCP from your installed vyomi-tunnel <ver> (npm has ...)" must
 *                             appear: proof that the installed copy serves (printed when the npx copy is newer than the installed one)
 *   --expect-installed <ver>  vyomi_status must return tunnel.installed = <ver> (implies --call-status)
 *   --expect-upgrade          vyomi_status must return tunnel.upgrade (implies --call-status)
 *   --call-status             call vyomi_status and print its tunnel field
 *   --allow-stderr <regex>    another stderr line to accept (repeatable). Accepted by default: the server's "vyomi mcp: serving on
 *                             stdio" banner and, in sync mode, the launcher's handover line. Any other stderr line fails the run.
 *   --cache <dir>             npm cache for this run (npm_config_cache); a fresh dir makes the timing a true cold start
 *   --timeout <s>             overall limit (default 60)
 *   --label <text>            name for the step summary row
 *
 * npm's own update notifier and warnings are turned off (npm_config_update_notifier=false, npm_config_loglevel=error) so the stderr
 * check is about the launcher and the server. Exit 0 on pass, 1 on a failed check, 2 on a usage error. Writes the cold-start time
 * (spawn to initialize reply) to $GITHUB_STEP_SUMMARY when set.
 */
import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

function usage(msg) { process.stderr.write(`handshake: ${msg}\n`); process.exit(2); }

const opt = { mode: "plain", minTools: 8, tools: [], allow: [], timeout: 60, callStatus: false, expectUpgrade: false };
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i], eq = a.indexOf("="), key = eq > 0 ? a.slice(0, eq) : a;
  const val = () => (eq > 0 ? a.slice(eq + 1) : (i + 1 < argv.length ? argv[++i] : usage(`${key} needs a value`)));
  switch (key) {
    case "--tarball": opt.tarball = val(); break;
    case "--mode": opt.mode = val(); break;
    case "--min-tools": opt.minTools = Number(val()); break;
    case "--expect-tool": opt.tools.push(val()); break;
    case "--expect-handover": opt.handover = val(); break;
    case "--expect-installed": opt.installed = val(); opt.callStatus = true; break;
    case "--expect-upgrade": opt.expectUpgrade = true; opt.callStatus = true; break;
    case "--call-status": opt.callStatus = true; break;
    case "--allow-stderr": opt.allow.push(new RegExp(val())); break;
    case "--cache": opt.cache = val(); break;
    case "--timeout": opt.timeout = Number(val()); break;
    case "--label": opt.label = val(); break;
    case "-h": case "--help": process.stdout.write(fs.readFileSync(new URL(import.meta.url), "utf8").split("*/")[0] + "*/\n"); process.exit(0);
    default: usage(`unknown flag ${a}`);
  }
}
if (!opt.tarball) usage("--tarball is required");
if (!["plain", "sync"].includes(opt.mode)) usage("--mode is plain or sync");
if (!(opt.minTools >= 0) || !(opt.timeout > 0)) usage("--min-tools and --timeout take numbers");
if (!opt.tools.length) opt.tools.push("vyomi_status");

/** Resolve the tarball to an absolute path (npm reads "dist/x.tgz" as a GitHub user/repo, so it must look like a path). */
function resolveTarball(p) {
  const abs = path.resolve(p), dir = path.dirname(abs), base = path.basename(abs);
  if (!base.includes("*")) { if (!fs.existsSync(abs)) usage(`no tarball ${abs}`); return abs; }
  const re = new RegExp("^" + base.split("*").map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$");
  const hits = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => re.test(f)) : [];
  if (hits.length !== 1) usage(`${p} matches ${hits.length} files (${hits.join(", ") || "none"}); want exactly one`);
  return path.join(dir, hits[0]);
}
const tgz = resolveTarball(opt.tarball);
// npx runs in the tarball's directory with a `./<file>` spec: an absolute path is taken for a command to execute (exit 126), and
// `file:` with a Windows drive path is fragile. `./x.tgz` works the same on every OS.
const cwd = path.dirname(tgz), spec = "./" + path.basename(tgz);
const npxArgs = opt.mode === "plain" ? ["-y", spec, "mcp"] : ["-y", `--package=${spec}`, "vyomi-tunnel", "mcp"];

const env = { ...process.env, npm_config_update_notifier: "false", npm_config_loglevel: "error", npm_config_fund: "false", npm_config_audit: "false" };
if (opt.cache) { fs.mkdirSync(opt.cache, { recursive: true }); env.npm_config_cache = path.resolve(opt.cache); }

// Windows: npx is npx.cmd, which Node only spawns through a shell (as `cmd /c npx ...` in an agent's config). Quote for cmd.exe.
const win = process.platform === "win32";
const q = (s) => (/[\s"&|<>^()]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
const shown = `npx ${npxArgs.map(q).join(" ")}`;
console.log(`handshake: ${opt.mode} mode on ${process.platform}-${process.arch}, node ${process.version}: ${shown} (in ${cwd})${opt.cache ? ` (npm cache ${env.npm_config_cache})` : ""}`);

const t0 = performance.now();
const child = win
  ? spawn(["npx", ...npxArgs.map(q)].join(" "), { cwd, shell: true, env, stdio: ["pipe", "pipe", "pipe"], windowsHide: true })
  : spawn("npx", npxArgs, { cwd, env, stdio: ["pipe", "pipe", "pipe"], detached: true });

let stderr = "", outBuf = "", exited = null;
const pending = new Map();
child.stderr.setEncoding("utf8").on("data", (d) => { stderr += d; });
child.stdout.setEncoding("utf8").on("data", (d) => {
  outBuf += d;
  let nl;
  while ((nl = outBuf.indexOf("\n")) >= 0) {
    const line = outBuf.slice(0, nl).trim(); outBuf = outBuf.slice(nl + 1);
    if (!line) continue;
    let msg; try { msg = JSON.parse(line); } catch { fail(`stdout is not JSON-RPC: ${line.slice(0, 200)}`); return; }
    const p = msg.id != null && pending.get(msg.id);
    if (p) { pending.delete(msg.id); p(msg); }
  }
});
child.on("error", (e) => fail(`cannot start npx: ${e.message}`));
child.on("exit", (code, signal) => {
  exited = { code, signal };
  for (const [, p] of pending) p({ error: { message: `server exited (${signal || code}) before replying` } });
  pending.clear();
});

let nextId = 1;
function send(obj) { child.stdin.write(JSON.stringify({ jsonrpc: "2.0", ...obj }) + "\n"); }
function request(method, params) {
  const id = nextId++;
  return new Promise((resolve) => { pending.set(id, resolve); send({ id, method, params }); });
}

function killTree() {
  if (exited) return;
  try {
    if (win) spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else process.kill(-child.pid, "SIGTERM");
  } catch { /* gone */ }
}
let finished = false;
function fail(msg) {
  if (finished) return; finished = true;
  console.error(`handshake: FAIL: ${msg}`);
  if (stderr.trim()) console.error(`--- server stderr ---\n${stderr.trimEnd()}\n---`);
  summary(false, msg);
  killTree();
  process.exitCode = 1;
  setTimeout(() => process.exit(1), 2000).unref();
}
const timer = setTimeout(() => fail(`no complete handshake within ${opt.timeout} s`), opt.timeout * 1000);
timer.unref();

const fmt = (ms) => `${(ms / 1000).toFixed(2)} s`;
function summary(ok, detail) {
  const f = process.env.GITHUB_STEP_SUMMARY;
  if (!f) return;
  const label = opt.label || `${opt.mode} (${process.platform}-${process.arch})`;
  try {
    let empty = true; try { empty = fs.statSync(f).size === 0; } catch { /* new file */ }
    if (empty) fs.appendFileSync(f, "| npx smoke | result | cold start: initialize | tools/list | detail |\n|---|---|---|---|---|\n");
    fs.appendFileSync(f, `| ${label} | ${ok ? "pass" : "FAIL"} | ${timing.init != null ? fmt(timing.init) : "-"} | ${timing.tools != null ? fmt(timing.tools) : "-"} | ${String(detail).replace(/\|/g, "\\|").replace(/\n/g, " ")} |\n`);
  } catch { /* summary is best effort */ }
}
const timing = {};

function statusPayload(res) {
  const r = res && res.result;
  if (!r) return null;
  if (r.structuredContent) return r.structuredContent;
  const text = r.content && r.content[0] && r.content[0].text;
  try { return JSON.parse(text); } catch { return null; }
}

async function main() {
  const init = await request("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "npx-smoke", version: "0" } });
  timing.init = performance.now() - t0;
  if (finished) return;
  if (init.error) return fail(`initialize: ${init.error.message}`);
  const si = init.result && init.result.serverInfo;
  if (!si || si.name !== "vyomi") return fail(`initialize: serverInfo is ${JSON.stringify(si)}, want name "vyomi"`);
  send({ method: "notifications/initialized" });

  const list = await request("tools/list", {});
  timing.tools = performance.now() - t0;
  if (finished) return;
  if (list.error) return fail(`tools/list: ${list.error.message}`);
  const names = ((list.result && list.result.tools) || []).map((t) => t.name);
  console.log(`handshake: serverInfo ${si.name} ${si.version}; ${names.length} tools: ${names.join(", ")}`);
  console.log(`handshake: cold start ${fmt(timing.init)} to initialize, ${fmt(timing.tools)} to tools/list`);
  if (names.length < opt.minTools) return fail(`${names.length} tools, want at least ${opt.minTools}`);
  const missing = opt.tools.filter((t) => !names.includes(t));
  if (missing.length) return fail(`missing tools: ${missing.join(", ")}`);

  let tunnel;
  if (opt.callStatus) {
    const st = await request("tools/call", { name: "vyomi_status", arguments: {} });
    if (finished) return;
    if (st.error || (st.result && st.result.isError)) return fail(`vyomi_status: ${st.error ? st.error.message : JSON.stringify(st.result.content)}`);
    const payload = statusPayload(st);
    if (!payload) return fail(`vyomi_status: reply is not a JSON object: ${JSON.stringify(st.result).slice(0, 300)}`);
    tunnel = payload.tunnel;
    console.log(`handshake: vyomi_status tunnel = ${JSON.stringify(tunnel)}`);
    if (opt.installed && !(tunnel && tunnel.installed === opt.installed)) return fail(`vyomi_status tunnel.installed is ${JSON.stringify(tunnel && tunnel.installed)}, want "${opt.installed}"`);
    if (opt.expectUpgrade && !(tunnel && tunnel.upgrade)) return fail(`vyomi_status has no tunnel.upgrade (tunnel: ${JSON.stringify(tunnel)})`);
  }

  // Close stdin: the server exits on EOF; then judge stderr (everything the chain wrote is in by then).
  child.stdin.end();
  await new Promise((resolve) => { if (exited) resolve(); else { child.once("exit", resolve); setTimeout(resolve, 5000).unref(); } });
  if (finished) return;

  const allowed = [/^vyomi mcp: serving on stdio\b/, ...opt.allow];
  const handoverRe = /^vyomi-tunnel: running the MCP from your installed vyomi-tunnel (\S+) \(npm has (\S+)\)/;
  if (opt.mode === "sync") allowed.push(handoverRe);
  const lines = stderr.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const extra = lines.filter((l) => !allowed.some((re) => re.test(l)));
  if (extra.length) return fail(`unexpected stderr:\n  ${extra.join("\n  ")}`);
  let detail = `${si.version}, ${names.length} tools`;
  if (opt.handover) {
    const m = lines.map((l) => handoverRe.exec(l)).find(Boolean);
    if (!m) return fail(`no handover line naming the installed vyomi-tunnel ${opt.handover} on stderr`);
    if (m[1] !== opt.handover) return fail(`handed over to installed ${m[1]}, want ${opt.handover}`);
    console.log(`handshake: handed over to the installed vyomi-tunnel ${m[1]} (npx copy ${m[2]})`);
    detail += `, served by installed ${m[1]} (npx ${m[2]})`;
  }
  if (tunnel) detail += `, tunnel.installed ${tunnel.installed}${tunnel.upgrade ? ", upgrade hint" : ""}`;
  finished = true;
  clearTimeout(timer);
  console.log(`handshake: PASS (${detail})`);
  summary(true, detail);
  killTree();
}
main().catch((e) => fail(e.stack || String(e)));
