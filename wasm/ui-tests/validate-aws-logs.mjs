/* Nano console: CloudWatch Logs — the same flow as the offline console test
 * (tests/conformance/ui/_aws_logs_flow.mjs): open the service, create with the
 * defaults, every column filled, detail tabs render, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-aws-logs.mjs
 */
import { startServer, bootConsole, chromium } from "./lib.mjs";
import { runLogsFlow } from "../../tests/conformance/ui/_aws_logs_flow.mjs";

let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};

const { server, base } = await startServer();
const browser = await chromium.launch();
try {
  const page = await (await browser.newContext()).newPage();
  await bootConsole(page, base, "/aws-console.html");
  await runLogsFlow(page, check);
} catch (e) {
  check(false, "CloudWatch Logs Nano console flow ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
process.exit(fails ? 1 : 0);
