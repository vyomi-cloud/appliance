/* Azure console Overview: a resource whose properties.vyomiRuntime.backend is "none" shows an honest
 * "Runtime: Control plane only" row; a runtime error shows "Container failed to start".
 * Nano: default. Offline: VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/azure. */
import { startServer, bootConsole, chromium } from "./lib.mjs";
const offline = process.env.VYOMI_CONSOLE_URL;
let server, base;
if (!offline) ({ server, base } = await startServer());
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const check = (n, ok, note = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " " + note}`); };
try {
  if (offline) await page.goto(offline, { waitUntil: "domcontentloaded" });
  else await bootConsole(page, base, "/azure-console.html");
  await page.waitForFunction(() => typeof SUB === "string" && SUB && typeof SUB_RENDERERS === "object" && SUB_RENDERERS.overview, null, { timeout: 120000 });
  const out = await page.evaluate(() => {
    const render = (props) => { const host = document.createElement("div"); document.body.appendChild(host);
      try { SUB_RENDERERS.overview({ id: "x", name: "x", type: "Microsoft.App/containerApps" }, { id: "/s/x", name: "x", type: "Microsoft.App/containerApps", location: "eastus", properties: props }, host); } catch (e) { return "ERR " + e; }
      return host.innerText; };
    return { none: render({ provisioningState: "Succeeded", vyomiRuntime: { backend: "none", note: "no container runtime in the browser" } }),
             err: render({ provisioningState: "Succeeded", vyomiRuntime: { error: "image pull failed" } }),
             ok: render({ provisioningState: "Succeeded" }) };
  });
  check("backend none → Control plane only row", /Runtime[\s\S]*Control plane only — no container runtime in the browser/.test(out.none), out.none.slice(0, 200));
  check("error → failed to start row", /Container failed to start: image pull failed/.test(out.err), out.err.slice(0, 200));
  check("normal resource → no Runtime row", !/Runtime\s/.test(out.ok) || !/Control plane|failed to start/.test(out.ok));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server?.close();
process.exit(results.length && results.every(Boolean) ? 0 : 1);
