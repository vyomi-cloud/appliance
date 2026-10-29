/* Nano UI: GCP Artifact Registry. Same flow as the offline console test
 * (tests/conformance/ui/gcp-artifactregistry.mjs) against the Nano bundle: open the
 * service, create with the wizard defaults, every grid column filled, detail tabs
 * render (Images after a sample push), delete.
 *
 *   NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-gcp-artifactregistry.mjs
 */
import { startServer, bootConsole, chromium } from "./lib.mjs";
import { runGcpServiceFlow } from "../../tests/conformance/ui/gcp-service-flow.mjs";

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
  await bootConsole(page, base, "/gcp-console.html");
  await page.waitForTimeout(1500);
  await runGcpServiceFlow(page, {
    service: "Artifact Registry", label: "Artifact Registry", check,
    pushAction: { tab: "Images", button: /Push sample image/ },
  });
} catch (e) {
  check(false, "Artifact Registry console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
