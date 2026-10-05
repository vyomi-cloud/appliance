/* Nano UI AUDIT — crawl every console, click every service, classify its panel.
 * Produces the gap inventory for Goal 2 (which UIs are empty/stub) and the target
 * list for Goal 1 (which UIs to functionally validate against the CLI/relay).
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const PAGES = [
  { path: "/aws-console.html", cloud: "AWS" },
  { path: "/gcp-console.html", cloud: "GCP" },
  { path: "/azure-console.html", cloud: "Azure" },
];

function classify(m) {
  const t = (m.text || "").toLowerCase();
  const hasCreate = m.buttons.some((b) => /add|create|launch|new|upload|generate|put|write/i.test(b));
  const hasActions = m.buttons.some((b) => /action|delete|edit|more_horiz|settings/i.test(b));
  const hasTableish = m.rows > 1 || /items|no .* in |empty/i.test(t);
  const hasInputs = m.inputs.length > 0;
  const brokenish = /not implemented|coming soon|todo|undefined|error|failed|cannot/i.test(t);
  if (brokenish) return "BROKEN/STUB";
  if (!m.exists || (m.textLen < 15 && m.buttons.length === 0)) return "EMPTY";
  if (hasCreate && (hasInputs || hasTableish)) return "FUNCTIONAL";
  if (hasActions || hasTableish || m.buttons.length >= 1) return "VIEW-ONLY";
  return "EMPTY";
}

const { server, base } = await startServer();
const browser = await chromium.launch();
const results = [];

for (const pg of PAGES) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  try {
    await bootConsole(page, base, pg.path);
    const services = await page.evaluate((sel) => {
      return [...document.querySelectorAll(sel)]
        .map((e, i) => ({ i, label: (e.innerText || e.title || e.getAttribute("data-key") || "").trim().split("\n").pop() }))
        .filter((x) => x.label && x.label !== "home");
    }, RAIL_SEL);
    for (const svc of services) {
      try {
        await page.evaluate(([i, sel]) => {
          const el = document.querySelectorAll(sel)[i];
          if (el) el.click();
        }, [svc.i, RAIL_SEL]);
        await sleep(1500);
        const m = await page.evaluate(() => {
          const el = document.querySelector("#main");
          if (!el) return { exists: false };
          const txt = (el.innerText || "").trim();
          return {
            exists: true, textLen: txt.length, text: txt.slice(0, 200),
            title: (txt.split("\n")[0] || "").trim(),
            buttons: [...el.querySelectorAll("button,[role=button]")].map((b) => (b.innerText || b.title || "").trim().split("\n").pop()).filter(Boolean),
            inputs: [...el.querySelectorAll("input,select,textarea")].map((i) => i.name || i.id || i.placeholder || i.type).filter(Boolean),
            rows: el.querySelectorAll("tr,[role=row]").length,
          };
        });
        results.push({ cloud: pg.cloud, svc: m.title || svc.label, klass: classify(m),
          buttons: m.buttons.length, inputs: m.inputs.length, rows: m.rows, sample: m.text.replace(/\n/g, " ⏎ ").slice(0, 90) });
      } catch (e) {
        results.push({ cloud: pg.cloud, svc: svc.label, klass: "ERROR", sample: String(e).split("\n")[0].slice(0, 80) });
      }
    }
  } catch (e) {
    results.push({ cloud: pg.cloud, svc: "(boot)", klass: "BOOT-FAIL", sample: String(e).split("\n")[0] });
  }
  await ctx.close();
}
await browser.close();
server.close();

// Report
console.log("\n==================== NANO UI AUDIT ====================");
const by = {};
for (const r of results) { (by[r.cloud] ||= []).push(r); }
for (const cloud of Object.keys(by)) {
  console.log(`\n### ${cloud}`);
  for (const r of by[cloud])
    console.log(`  [${(r.klass).padEnd(11)}] ${String(r.svc).padEnd(22)} btn:${r.buttons ?? "-"} in:${r.inputs ?? "-"} rows:${r.rows ?? "-"}  | ${r.sample || ""}`);
}
const tally = {};
for (const r of results) tally[r.klass] = (tally[r.klass] || 0) + 1;
console.log("\n==================== TALLY ====================");
console.log(JSON.stringify(tally, null, 1));
console.log(`total services audited: ${results.length}`);
