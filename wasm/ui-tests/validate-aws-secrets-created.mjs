/* Secrets Manager grid: a created secret has a Created timestamp (no rotation
 * columns that stay "-" — the real list shows name/description/last retrieved).
 * Nano: boots the console; offline: set VYOMI_CONSOLE_URL. */
import { startServer, bootConsole, chromium } from "./lib.mjs";
const results = [];
const check = (name, ok) => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}`); };
const offline = process.env.VYOMI_CONSOLE_URL;
let server, base;
if (!offline) ({ server, base } = await startServer());
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  if (offline) { base = new URL(offline).origin; await page.goto(offline); } else await bootConsole(page, base, "/aws-console.html");
  const r = await page.evaluate(async () => {
    await fetch("/api/aws/secrets", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "val/created", value: "s" }) });
    const j = await (await fetch("/api/aws/secrets")).json();
    const cat = await (await fetch("/api/aws/catalog").catch(() => ({ json: async () => ({}) }))).json().catch(() => ({}));
    return { row: (j.value || j.items || j.secrets || []).find((x) => x.name === "val/created"), cat: JSON.stringify(cat) };
  });
  check("created secret is listed", !!r.row);
  check("row has a created timestamp", /^\d{4}-\d\d-\d\dT/.test(r.row?.created || ""));
  check("grid no longer has rotation placeholder columns", !/Last rotated|Next rotation/.test(r.cat));
} catch (e) { check("boot: " + String(e).split("\n")[0], false); }
await browser.close(); server?.close();
process.exit(results.every(Boolean) ? 0 : 1);
