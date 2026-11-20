/* Nano AWS console: the Vyomi Mesh drawer is as wide as the section below it. Home: the centred content column. Service pages
 * (side navigation open): the whole nav + content frame, i.e. its right edge equals the content's right edge. */
import { startServer, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
try {
  await page.goto(base + "/v4/aws/index.html", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#vy-md .md-body", { timeout: 90000 }); await sleep(3000);
  const measure = () => page.evaluate(() => {
    const b = document.querySelector("#vy-md .md-body"), cs = getComputedStyle(b), bb = b.getBoundingClientRect();
    const md = document.querySelector("#vy-md").getBoundingClientRect();
    const crumbs = [...document.querySelectorAll('[class*="awsui_breadcrumbs"]')].map((e) => e.getBoundingClientRect()).find((r) => r.top >= md.bottom - 2 && r.width > 200);
    const content = [...document.querySelectorAll('[class*="awsui_container_"]')].map((e) => e.getBoundingClientRect()).filter((r) => r.top >= md.bottom - 400 && r.width > 500).sort((a, c) => c.width - a.width)[0];
    return { l: Math.round(bb.left + parseFloat(cs.paddingLeft)), r: Math.round(bb.right - parseFloat(cs.paddingRight)), cl: Math.round((content || crumbs).left), cr: Math.round((content || crumbs).right), nav: !!document.querySelector('#vy-md.nav') };
  });
  await page.evaluate(() => { location.hash = "#/"; }); await sleep(2500);
  let m = await measure();
  check("Home: drawer spans the content column", Math.abs(m.l - m.cl) <= 2 && Math.abs(m.r - m.cr) <= 2, JSON.stringify(m));
  for (const h of ["#/s3", "#/dynamodb", "#/sqs"]) {
    await page.evaluate((h) => { location.hash = h; }, h); await sleep(2500);
    m = await measure();
    check(`${h}: drawer right edge equals the content's right edge`, m.nav && Math.abs(m.r - m.cr) <= 2, JSON.stringify(m));
  }
  await page.evaluate(() => { location.hash = "#/"; }); await sleep(2500);
  m = await measure();
  check("back on Home the drawer returns to the content column", !m.nav && Math.abs(m.l - m.cl) <= 2, JSON.stringify(m));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
