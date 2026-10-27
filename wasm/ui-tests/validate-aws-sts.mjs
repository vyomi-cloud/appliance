/* Nano UI: AWS STS. Same flow as the offline console test
 * (tests/conformance/ui/aws-sts.mjs) against the Nano bundle: open STS, assume a
 * role with the form defaults, every grid column filled, detail tabs render, revoke.
 *
 *   NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-aws-sts.mjs
 */
import { startServer, bootConsole, chromium } from "./lib.mjs";
import { runServiceFlow } from "../../tests/conformance/ui/service-flow.mjs";

let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] Nano ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/aws-console.html");
  await page.waitForTimeout(1500);
  await runServiceFlow(page, { service: "STS", label: "STS", listLabel: "Sessions", check });
} catch (e) {
  check(false, "STS console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
