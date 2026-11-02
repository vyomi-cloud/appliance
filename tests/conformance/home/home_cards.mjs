/* Console Home page (the landing page of each cloud console): the Cost savings card and the
 * Connect-your-SDK/CLI card, checked against the API. The crawler never opens Home, which is
 * where the cost card broke before (stuck $0.00, deleted resources lingering, mismatched heights).
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/home/home_cards.mjs aws|gcp|azure
 * Run home_setup.py <cloud> first so the active space has savings. One [PASS]/[FAIL] per check.
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
const CLOUD = process.argv[2];
const LABEL = { aws: "AWS", gcp: "GCP", azure: "Azure" }[CLOUD];
if (!LABEL) { console.error("usage: home_cards.mjs aws|gcp|azure"); process.exit(2); }
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${CLOUD} home: ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
// Service keys whose card label is not a prefix of the key (azure.vm -> "Virtual Machines").
const ALIAS = { vm: ["virtualmachines"], sql: ["sqldatabase", "sqlserver"], kv: ["keyvault"], fn: ["functions"] };
const money = (s) => { const m = /\$\s*([\d,]+(?:\.\d+)?)/.exec(s || ""); return m ? Number(m[1].replace(/,/g, "")) : null; };

const api = await (await fetch(`${BASE}/api/spaces`)).json();
const cs = (api.active_space || {}).cost_savings || {};
const wantUsd = Number((cs.by_provider || {})[CLOUD] || 0);
const wantSvcs = Object.entries(cs.by_service || {}).filter(([k, v]) => k.startsWith(CLOUD + ".") && Number(v) > 0);
check(wantUsd > 0, "setup left savings for this cloud in the API", `by_provider.${CLOUD}=${wantUsd}`);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errs = [], bad = [];
page.on("pageerror", (e) => errs.push(String(e.message).slice(0, 120)));
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
try {
  await page.goto(`${BASE}/console/${CLOUD}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => /Cost savings/i.test((document.querySelector("#main") || {}).innerText || ""), null, { timeout: 60000 });
  // The card fills from /api/spaces after it renders; on a busy appliance that answer can take
  // several seconds, so wait for the headline to turn into a number rather than a fixed sleep.
  await page.waitForFunction(() => {
    const t = (document.querySelector("#main") || {}).innerText || "";
    const i = t.search(/Cost savings/i);
    return i >= 0 && !/Loading savings/i.test(t.slice(i, i + 600)) && /\$\s*[\d,]+\.\d{2}/.test(t.slice(i, i + 600));
  }, null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(500);

  const card = await page.evaluate(() => {
    const main = document.querySelector("#main");
    // heading element -> climb to the card that holds its content
    const find = (re, holds) => {
      const h = [...main.querySelectorAll("div, h2, h3, span")].find((e) => e.children.length <= 3 && re.test((e.innerText || "").trim()) && (e.innerText || "").trim().length < 60);
      let c = h;
      for (let i = 0; c && i < 8; i++, c = c.parentElement) if (holds.test(c.innerText || "") && c !== main) break;
      return c && c !== main ? c : null;
    };
    const cost = find(/^(savings\s*)?Cost savings/i, /\/\s*mo|Spin up/i);
    const conn = find(/Connect your SDK or CLI/i, /export |az |gcloud |aws |boto|python/i);
    return { text: cost ? cost.innerText : "", h: cost ? cost.getBoundingClientRect().height : 0,
             connect: conn ? conn.innerText : "", connectH: conn ? conn.getBoundingClientRect().height : 0 };
  });
  check(card.text.length > 0, "Cost savings card is on the page");
  const shown = money(card.text);
  check(shown !== null, "card shows a dollar headline", card.text.slice(0, 80).replace(/\n+/g, " | "));
  check(shown !== null && Math.abs(shown - wantUsd) < 0.02 + wantUsd * 0.005,
    `card headline equals the API's ${LABEL} savings`, `card=$${shown} api=$${wantUsd.toFixed(2)}`);
  check(!/spin up .* services/i.test(card.text) || wantUsd === 0, "card is not stuck on its empty-state text while the API has savings");
  // The card ranks paid services and shows the top 4 by name; any further ones fold into one
  // "Other (n)" row (vySavingsBody). So: every service ranked above the 5th appears by name, and
  // when there are more than 4 the Other row counts exactly the rest. (Services tied with the
  // 5th may land either side of the cut, so only strictly-higher ones are required by name.)
  const ranked = [...wantSvcs].sort((a, b) => Number(b[1]) - Number(a[1]));
  const cut = ranked.length > 4 ? Number(ranked[4][1]) : -Infinity;
  const named = ranked.filter(([, v]) => Number(v) > cut);
  const flat = card.text.toLowerCase().replace(/[^a-z0-9]+/g, "");   // "Pub/Sub" -> "pubsub"
  const svcMissing = named.filter(([k]) => !(flat.includes(k.split(".")[1].replace(/[^a-z0-9]+/gi, "").slice(0, 4).toLowerCase()) || (ALIAS[k.split(".")[1]] || []).some((a) => flat.includes(a)))).map(([k]) => k);
  if (svcMissing.length) console.log("card text:", card.text.replace(/\n/g, " | ").slice(0, 400));
  check(svcMissing.length === 0, "every top-ranked service the API credits appears as a row", `missing: ${svcMissing.join(", ")}`);
  if (ranked.length > 4)
    check(card.text.includes(`Other (${ranked.length - 4})`), "the remaining credited services fold into one Other row",
      `want "Other (${ranked.length - 4})"; card: ${card.text.slice(0, 200).replace(/\n+/g, " | ")}`);
  check(/\/\s*mo|per month|\/mo/i.test(card.text), "card states the period (per month)");
  check(card.connect.length > 0 && /export|az |gcloud|aws /i.test(card.connect), "Connect your SDK or CLI card shows its snippet", card.connect.slice(0, 60));
  check(card.h > 0 && Math.abs(card.h - card.connectH) <= 3, "cost and connect cards share the row height", `${Math.round(card.h)}px vs ${Math.round(card.connectH)}px`);
  check(errs.length === 0, "no uncaught page errors on Home", errs.join(" ; "));
  check(bad.length === 0, "no 5xx from the API on Home", bad.join(" ; "));
} catch (e) {
  check(false, "Home page check ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
