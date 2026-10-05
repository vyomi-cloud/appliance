/* Goal-1 sweep (GCP): for every service, drive the real UI CREATE and assert the
 * UI list reflects it — proving the create path works, not just that a button exists.
 * Generic form-fill: open CREATE → fill the first text input with a unique name →
 * click the confirm button → assert the name appears in #main. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const PATH = process.env.UI_PATH || "/gcp-console.html";
const CLOUD = PATH.includes("azure") ? "Azure" : PATH.includes("aws") ? "AWS" : "GCP";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const uniq = (s) => (s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 10) || "svc") + "t1";

try {
  await bootConsole(page, base, PATH);
  const services = await page.evaluate((sel) => [...document.querySelectorAll(sel)]
    .map((e, i) => ({ i, label: (e.innerText || "").trim().split("\n").pop() })).filter((x) => x.label), RAIL_SEL);

  for (const svc of services) {
    const name = uniq(svc.label);
    let r = { svc: svc.label, name };
    try {
      await page.evaluate(([i, sel]) => document.querySelectorAll(sel)[i]?.click(), [svc.i, RAIL_SEL]);
      await sleep(1200);
      // open CREATE
      const opened = await page.evaluate(() => {
        const b = [...document.querySelectorAll("#main button")].find((x) => /create|add/i.test(x.innerText));
        if (b) { b.click(); return true; } return false;
      });
      r.createBtn = opened;
      await sleep(900);
      // fill the first text input in whatever create surface appeared + confirm
      const submitted = await page.evaluate((nm) => {
        const scopes = ["dialog", "[role=dialog]", ".modal", ".drawer", "#bladeBody", "form", "#main"];
        let d = null;
        for (const s of scopes) { const c = document.querySelector(s); if (c && [...c.querySelectorAll("input[type=text],input:not([type]),input[type=search]")].some((i) => i.offsetParent !== null)) { d = c; break; } }
        if (!d) return false;
        const inp = [...d.querySelectorAll("input")].find((i) => i.type !== "checkbox" && i.type !== "radio" && i.offsetParent !== null && !/filter|search/i.test(i.placeholder || ""));
        if (inp) { inp.value = nm; inp.dispatchEvent(new Event("input", { bubbles: true })); inp.dispatchEvent(new Event("change", { bubbles: true })); }
        const vis = [...d.querySelectorAll("button")].filter((b) => b.offsetParent !== null);
        // clean button text: drop leading material-icon ligature + non-letters
        const clean = (b) => b.innerText.replace(/^\s*[a-z_]+\s*\n/i, " ").replace(/[^a-zA-Z ]/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
        // Wizard submit priority: AWS "Create resource" → exact Create/Save → a
        // "Create <noun>" confirm (GCP/Azure), excluding step tabs ("6 Review and create").
        const btn = vis.find((b) => /create resource/i.test(b.innerText))
          || vis.find((b) => { const t = clean(b); return t === "create" || t === "save" || t === "ok" || t === "submit"; })
          || vis.find((b) => { const t = clean(b); return /^create (bucket|table|queue|key|secret|user|instance|function|database|topic|vpc|network|service account|rule|api|template|volume|snapshot|group|role|vault|account|server|namespace|gateway)/.test(t) && !/review/.test(t); });
        if (btn) { btn.click(); return true; } return false;
      }, name);
      r.filledSubmit = submitted;
      await sleep(2000);
      r.appeared = await page.evaluate((nm) => (document.querySelector("#main")?.innerText || "").includes(nm), name);
    } catch (e) { r.err = String(e).split("\n")[0]; }
    r.pass = !!(r.createBtn && r.filledSubmit && r.appeared);
    results.push(r);
  }
} catch (e) { results.push({ svc: "(boot)", pass: false, err: String(e).split("\n")[0] }); }
await browser.close(); server.close();

console.log(`===== ${CLOUD} Goal-1 sweep: UI CREATE actually works? =====`);
for (const r of results) console.log(`  [${r.pass ? "PASS" : "FAIL"}] ${String(r.svc).padEnd(18)} createBtn:${r.createBtn ?? "-"} submit:${r.filledSubmit ?? "-"} appeared:${r.appeared ?? "-"} ${r.err || ""}`);
const n = results.filter((r) => r.pass).length;
console.log(`\n${n}/${results.length} GCP services: UI create works end-to-end`);
