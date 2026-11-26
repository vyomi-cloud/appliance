/* Hourly/nightly wrapper: AWS v4 console list -> detail -> every tab (wasm/ui-tests/validate-aws-v4-detail.mjs), per service.
 * Starts `consoles/dev_server.py` (the same router the appliance and Nano use) on a free port, runs the suite against it, forwards its
 * output + exit code, stops ONLY its own server. Retargets the legacy v3 detail/row/tab suites (see docs/architecture/v4.0/branches/suites-retarget-aws.md).
 * Env: SCRIPT (another wasm/ui-tests script to run against the same dev_server, e.g. validate-aws-v4-metrics.mjs), BASE (use an existing backend instead), PY (python with boto3), ONLY=sqs,rds,... (default: every profile), PW_CHANNEL.  */
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
const run = spawn("node", [resolve(ROOT, process.env.SCRIPT || "wasm/ui-tests/validate-aws-v4-detail.mjs")], { stdio: "inherit", env: { ...process.env, BASE } });
const code = await new Promise((res) => run.on("exit", (c) => res(c ?? 1)));
try { dev?.kill(); } catch (_) {}
process.exit(code);
