/* RAG Studio end to end in a browser (Nano preview; demo-corpus backend unless a live facilities-kb answers).
 *   node consoles/nano_preview.mjs --port 8745 --tier pro &   BASE=http://127.0.0.1:8745 SHOTS=/tmp/shots node consoles/tests/smoke-aws-ragstudio.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8745", SHOTS = process.env.SHOTS || "/tmp/ragstudio-shots";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
const tab = (name) => page.getByRole("tab", { name }).click();
await page.goto(`${BASE}/nano/v4/aws/#/bedrock/knowledge-bases/studio`);
await page.getByRole("heading", { name: "RAG Studio" }).first().waitFor({ timeout: 60000 });
await page.getByTestId("studio-reason").waitFor({ timeout: 60000 }).catch(() => {});
const live = !(await page.getByTestId("studio-reason").count());
console.log("backend:", await page.getByTestId("backend-label").innerText());

// 1 DESIGN
await page.getByTestId("flow").waitFor();
check("design: 9 pipeline nodes rendered", (await page.locator('[data-testid^="node-"]').count()) >= 9);
await page.getByTestId("node-retrieve").click();
check("design: retrieve node parameters open", (await page.getByTestId("node-params").getByText("Hybrid weight").count()) > 0);
await page.getByRole("button", { name: /Load preset/ }).click(); await page.getByText("Policy manuals").first().click();
check("design: preset changes chunk strategy in API payload", /SEMANTIC/.test(await page.getByTestId("api-payload").innerText().catch(async () => { await page.getByText("Real API payload").click(); return page.getByTestId("api-payload").innerText(); })));
await page.getByRole("button", { name: "Apply and ingest" }).click();
await page.getByTestId("job-msg").getByText(/COMPLETE/).waitFor({ timeout: 60000 });
check("design: apply + ingest job COMPLETE", true, await page.getByTestId("job-msg").innerText());
await shot("1-design");

// 2 VALIDATE
await tab("Validate");
await page.getByTestId("lint-table").waitFor();
await page.getByTestId("node-params").count();
check("validate: lint table renders", (await page.getByTestId("lint-table").count()) === 1);
await page.getByRole("button", { name: "Run evaluation" }).click();
await page.getByTestId("eval-latest").waitFor({ timeout: 90000 });
check("validate: 7 metrics with pass/fail", (await page.getByTestId("eval-latest").getByText(/^(Pass|Fail)$/).count()) === 7);
await page.getByRole("button", { name: /Current design/ }).click(); await page.getByText("Preset: Semantic only").click();
await page.getByRole("button", { name: "Run evaluation" }).click();
await page.waitForFunction(() => document.querySelectorAll('[data-testid="run-history"] tbody tr').length >= 2, null, { timeout: 90000 });
check("validate: run history has 2 runs", true);
await page.getByRole("button", { name: /Choose run A/ }).click(); await page.getByRole("option").first().click();
await page.getByRole("button", { name: /Choose run B/ }).click(); await page.getByRole("option").nth(1).click();
await page.getByTestId("ab-compare").waitFor();
check("validate: A/B comparison renders", true);
await shot("2-validate");

// back to the default fine-grained chunking for the test + corpus views
await tab("Design"); await page.getByRole("button", { name: "Reset", exact: true }).click(); await page.getByRole("button", { name: "Apply and ingest" }).click();
await page.getByTestId("job-msg").getByText(/chunks/).waitFor({ timeout: 60000 }); await page.waitForTimeout(500);

// 3 TEST
await tab("Test");
await page.getByRole("button", { name: "Run query" }).click();
await page.getByTestId("rag-answer").waitFor({ timeout: 30000 });
check("test: cited answer", /90 days/.test(await page.getByTestId("rag-answer").innerText()), await page.getByTestId("rag-answer").innerText());
check("test: per-stage scores table + latency", (await page.getByTestId("trace-table").locator("tbody tr").count()) >= 3 && (await page.getByTestId("latency").innerText()).includes("vector"));
check("test: guardrail status shown", /NONE/.test(await page.getByTestId("guardrail-status").innerText()));
await shot("3-test");

// 4 PRE-RAG
await tab("Corpus (pre-RAG)");
await page.getByTestId("stat-chunks").waitFor();
check("corpus: chunk count shown", Number(await page.getByTestId("stat-chunks").innerText()) > 20);
check("corpus: duplicate clusters detected (v1/v2 policy)", Number(await page.getByTestId("stat-dups").innerText()) >= 1);
check("corpus: PII chunks flagged", Number(await page.getByTestId("stat-pii").innerText()) >= 1);
check("corpus: embedding map with points", (await page.getByTestId("embedding-map").first().locator("circle").count()) > 20);
await shot("4-corpus");

// 5 POST-RAG
await tab("Query analysis (post-RAG)");
await page.getByTestId("map-query").waitFor();
check("post: query plotted + retrieved highlighted/linked", (await page.getByTestId("map-hit").count()) >= 1 && (await page.getByTestId("map-link").count()) >= 1);
check("post: waterfall rows", (await page.getByTestId("wf-row").count()) >= 3);
check("post: provenance sentences linked", (await page.getByTestId("sent-grounded").count()) >= 1);
check("post: evaluation dashboard", (await page.getByTestId("eval-dashboard").count()) === 1);
await shot("5-post");

// ungrounded flag: out-of-scope + PII guardrail
await tab("Test");
await page.getByLabel("Question").fill("My SSN is 123-45-6789 what is the HVAC policy?"); await page.getByRole("button", { name: "Run query" }).click();
await page.getByTestId("guardrail").waitFor({ timeout: 20000 });
check("test: guardrail intervention shown", true);
check("no page errors", errs.length === 0, errs[0]);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
