/* Azure All services blade: categories, filter, favorites persistence, hamburger flyout, navigation to a service.
 *   python3 consoles/dev_server.py --port 8773 &   BASE=http://127.0.0.1:8773 node consoles/tests/smoke-azure-all-services.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8773";
const UI = `${BASE}/v4/azure/`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 828 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/allservices");
await page.locator(".vy-as-cats").waitFor({ timeout: 20000 });

const cats = await page.locator(".vy-as-cat").allInnerTexts();
check("left list: All, Favorites, Recents then Categories", JSON.stringify(cats.slice(0, 3)) === JSON.stringify(["All", "Favorites", "Recents"]), cats.slice(0, 3));
check("18 real portal categories in order", JSON.stringify(cats.slice(3)) === JSON.stringify(["AI + machine learning", "Analytics", "Compute", "Containers", "Databases", "DevOps", "General", "Hybrid + multicloud", "Identity", "Integration", "Internet of Things", "Management and governance", "Migration", "Monitor", "Networking", "Security", "Storage", "Web & Mobile"]), cats.length);
check("Categories heading", (await page.locator(".vy-as-cats-title").innerText()) === "Categories");
const heads = await page.locator(".vy-as-sec-title").allInnerTexts();
check("All view headings with counts", heads[0] === "AI + machine learning" && (await page.locator(".vy-as-sec-count").first().innerText()) === "(20)" && (await page.locator(".vy-as-sec-count").nth(2).innerText()) === "(33)", heads.slice(0, 3));
check("featured row (Entra ID, VMs, App Services, Storage, Cost)", (await page.locator(".vy-as-featured li").count()) === 5);
check("detail view cards have Create/View + star", (await page.locator(".vy-as-card").first().locator(".vy-as-star").count()) === 1 && (await page.locator(".vy-as-card").first().locator(".vy-as-view").count()) === 1);

// category + deep link
await page.locator('[data-category="Compute"]').click();
await page.waitForFunction(() => location.hash.includes("cat=Compute"));
check("Compute shows real subcategories", (await page.locator(".vy-as-sec-title").allInnerTexts()).join("|").includes("Infrastructure as a Service (IaaS)|Platform as a Service (PaaS)"));
check("title shows | Compute", (await page.locator(".vy-as-title h2").innerText()) === "Compute");

// filter
await page.goto(UI + "#/allservices");
const f = page.locator('input[placeholder="Filter services"]');
await f.fill("storage");
check("filter 'storage' lists Storage accounts first", (await page.locator(".vy-as-results .vy-as-row").first().innerText()).startsWith("Storage accounts"));
check("filter hides featured row + detail toggle", (await page.locator(".vy-as-featured").count()) === 0 && (await page.locator(".vy-as-detail").count()) === 0);
await f.fill("zzzqq");
check("no-result state text", (await page.locator(".vy-as-empty").innerText()).includes("There are no results matching your filter query"));
await f.fill("");

// favorites persistence
await page.evaluate(() => localStorage.removeItem("vyomi.v4.azure.favorites"));
await page.reload(); await page.locator(".vy-as-cats").waitFor();
await page.locator('[data-category="Security"]').click();
const kv = page.locator('.vy-as-card[data-service="Key vaults"]').first();
await kv.locator(".vy-as-star").click();
check("star toggles favorite on", (await kv.locator(".vy-as-star").getAttribute("aria-pressed")) === "true");
await page.reload(); await page.locator(".vy-as-cats").waitFor();
await page.locator(".vy-as-cat", { hasText: "Favorites" }).click();
check("favorite persists across reload and shows in Favorites", (await page.locator('.vy-as-card[data-service="Key vaults"]').count()) === 1);
await page.click('[aria-label="Show portal menu"]');
check("hamburger flyout: Create a resource, Home, Dashboard, All services", (await page.locator(".vy-pm > a").allInnerTexts()).map((t) => t.trim()).join("|") === "Create a resource|Home|Dashboard|All services");
check("flyout Favorites list includes the new favorite", (await page.locator(".vy-pm-list a").allInnerTexts()).some((t) => t.trim() === "Key vaults"));
await page.keyboard.press("Escape");
await page.locator('.vy-as-card[data-service="Key vaults"] .vy-as-star').click();
check("star toggles favorite off", (await page.locator('.vy-as-card[data-service="Key vaults"]').count()) === 0);

// navigation
await page.goto(UI + "#/allservices"); await page.locator(".vy-as-cats").waitFor();
await page.locator('.vy-as-featured a', { hasText: "Storage accounts" }).click();
await page.waitForFunction(() => location.hash === "#/storage");
check("featured tile navigates to the simulated Storage accounts blade", (await page.evaluate(() => location.hash)) === "#/storage");
await page.goto(UI + "#/allservices?cat=Compute"); await page.locator(".vy-as-cats").waitFor();
await page.locator('.vy-as-card[data-service="Virtual machines"] .vy-as-view').click();
await page.waitForFunction(() => location.hash === "#/vms");
check("View on Virtual machines opens the VMs blade", true);
await page.goto(UI + "#/allservices?cat=Compute"); await page.locator(".vy-as-cats").waitFor();
await page.locator('.vy-as-card[data-service="Batch accounts"] .vy-as-view').click();
await page.locator("text=does not simulate").waitFor({ timeout: 8000 });
check("unsimulated service opens an honest not-simulated page", true);
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
console.log(bad ? `\n${bad} FAILED` : "\nALL PASS");
process.exit(bad ? 1 : 0);
