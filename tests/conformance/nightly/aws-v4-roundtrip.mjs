/* Nightly/hourly wrapper: AWS v4 console UI <-> SDK bi-directional round-trip (check 5).
 * Starts `consoles/dev_server.py` (the same router the appliance and Nano use) on a free port, runs
 * wasm/ui-tests/validate-aws-v4-roundtrip.mjs against it, forwards its output + exit code, stops ONLY its own server.
 * Env: BASE (use an existing backend instead), PY (python with boto3), ONLY=s3,sqs,... (EKS runs only where a k3s backend exists). */
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../../..");
const freePort = () => new Promise((res) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
let dev = null, BASE = process.env.BASE || "";
if (!BASE) {
  const port = await freePort();
  dev = spawn(process.env.PY || "python3", [resolve(ROOT, "consoles/dev_server.py"), "--port", String(port)], { stdio: "ignore", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  BASE = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/v4/aws/")).ok) break; } catch (_) {} await new Promise((r) => setTimeout(r, 500)); }
}
const run = spawn("node", [resolve(ROOT, "wasm/ui-tests/validate-aws-v4-roundtrip.mjs")], { stdio: "inherit", env: { ...process.env, BASE } });
const code = await new Promise((res) => run.on("exit", (c) => res(c ?? 1)));
try { dev?.kill(); } catch (_) {}
process.exit(code);
