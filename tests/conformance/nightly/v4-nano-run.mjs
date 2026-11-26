/* Hourly/nightly wrapper: run a GENUINE-Nano v4 UI script (service worker + Pyodide cores) against `consoles/nano_preview.mjs`, the bundle exactly
 * as the portal serves it under /nano/. Starts the preview on a free port, runs SCRIPT (a wasm/ui-tests/validate-*.mjs that reads BASE), forwards
 * its output + exit code, stops ONLY its own preview. Env: SCRIPT (required), BASE (use an existing preview instead), PW_CHANNEL. */
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../../..");
if (!process.env.SCRIPT) { console.log("[FAIL] SCRIPT not set"); process.exit(1); }
const freePort = () => new Promise((res) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
let prev = null, BASE = process.env.BASE || "";
if (!BASE) {
  const port = await freePort();
  prev = spawn("node", [resolve(ROOT, "consoles/nano_preview.mjs"), "--port", String(port)], { stdio: "ignore" });
  BASE = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/nano/v4/aws/")).ok) break; } catch (_) {} await new Promise((r) => setTimeout(r, 500)); }
}
const run = spawn("node", [resolve(ROOT, process.env.SCRIPT)], { stdio: "inherit", env: { ...process.env, BASE } });
const code = await new Promise((res) => run.on("exit", (c) => res(c ?? 1)));
try { prev?.kill(); } catch (_) {}
process.exit(code);
