/* Nightly/hourly wrapper: Azure v4 console UI <-> ARM/az bi-directional (every service, every UI action).
 * Starts consoles/dev_server.py (the router Nano and the appliance share) on a free port, fronts it with a tiny shim
 * (/subscriptions,/providers,/api/azure -> /_wire/<path>; /healthz -> ok; /api/spaces/* -> 200) so the validator's SIM_URL
 * looks like an appliance, runs wasm/ui-tests/validate-azure-v4-bidirectional.mjs, forwards output + exit code.
 * Env: BASE (existing dev_server), PY, ONLY=vms,storage,..., MODE=offline|nano (nano = genuine in-browser engine subset). */
import { spawn } from "node:child_process";
import http from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../../..");
const freePort = () => new Promise((res) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
let dev = null, BASE = process.env.BASE || "";
if (!BASE) {
  const port = await freePort();
  dev = spawn(process.env.PY || "python3", [resolve(ROOT, "consoles/dev_server.py"), "--port", String(port), "-q"], { stdio: "ignore", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  BASE = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/v4/azure/")).ok) break; } catch (_) {} await new Promise((r) => setTimeout(r, 500)); }
}
const shim = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/healthz") { res.writeHead(200, { "content-type": "application/json" }); return res.end('{"status":"ok"}'); }
  if (/^\/api\/spaces\//.test(u.pathname)) { res.writeHead(200, { "content-type": "application/json" }); return res.end("{}"); }
  const chunks = []; for await (const c of req) chunks.push(c);
  const path = /^\/(_wire)\b/.test(u.pathname) ? req.url : "/_wire" + req.url;
  try {
    const r = await fetch(BASE + path, { method: req.method, headers: Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length"].includes(k))), body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks) });
    res.writeHead(r.status, Object.fromEntries([...r.headers].filter(([k]) => !["content-encoding", "transfer-encoding", "content-length"].includes(k))));
    res.end(Buffer.from(await r.arrayBuffer()));
  } catch (e) { res.writeHead(502); res.end(String(e)); }
});
await new Promise((r) => shim.listen(0, "127.0.0.1", r));
const SIM_URL = `http://127.0.0.1:${shim.address().port}`;
const run = spawn("node", [resolve(ROOT, "wasm/ui-tests/validate-azure-v4-bidirectional.mjs")], { stdio: "inherit", env: { ...process.env, SIM_URL, NANO_DIR: process.env.NANO_DIR || resolve(ROOT, "wasm") } });
const code = await new Promise((res) => run.on("exit", (c) => res(c ?? 1)));
try { dev?.kill(); } catch (_) {}
shim.close();
process.exit(code);
