/* Managed-Kubernetes tier gate, end to end through the dev server (consoles/dev_server.py).
 * Free  -> AKS (Azure) and GKE (GCP) are LOCKED: visible, read-only, upgrade call-to-action, no create / kubectl / backup,
 *          and the same calls over the native wire are refused with the cloud's native 403.
 * Max   -> both open (real pages), native wire calls succeed.
 * Pro (primary azure) -> AKS open, GKE locked.
 *
 *   python3 consoles/dev_server.py --port 8741 -q &
 *   BASE=http://127.0.0.1:8741 node consoles/tests/smoke-k8s-tier.mjs      (screenshots -> $OUT, default smoke-out-k8s-tier)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:8741";
const OUT = process.env.OUT || "smoke-out-k8s-tier";
const SUB = "00000000-0000-0000-0000-cloudlearn01";
let fails = 0;
const ok = (name, cond, extra = "") => { console.log(`${cond ? "PASS" : "FAIL"}  ${name}${cond ? "" : "  " + extra}`); if (!cond) fails++; };
const setTier = (tier, primary = "") => fetch(`${BASE}/_dev/tier?tier=${tier}&primary=${primary}`).then((r) => r.json());
const wire = (m, p, body) => fetch(`${BASE}/_wire${p}`, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const open = async (cloud, hash) => { await page.goto(`${BASE}/v4/${cloud}/#${hash}`); await page.reload(); await page.waitForTimeout(1200); };

// ── Free: locked ────────────────────────────────────────────────────────────────────────────
await setTier("free");
await open("azure", "/aks");
await page.waitForSelector('[data-testid="k8s-locked"]', { timeout: 8000 }).catch(() => {});
ok("Free/Azure: AKS shows the locked pane", await page.locator('[data-testid="k8s-locked"]').count() === 1);
ok("Free/Azure: upgrade CTA names Pro/Max", /Upgrade to Pro or Max/.test(await page.locator('[data-testid="k8s-upgrade-cta"]').innerText().catch(() => "")));
ok("Free/Azure: no Create / Run command / Backup controls", await page.getByRole("button", { name: /^(\+ )?Create|Run command|Backup/ }).count() === 0);
await page.screenshot({ path: `${OUT}/free-azure-aks-locked.png` });
await open("azure", "/allservices");
ok("Free/Azure: AKS stays listed (visible) with a lock badge", await page.locator('[data-testid="k8s-lock-badge"]').count() >= 1 && /Kubernetes services/.test(await page.content()));
await page.screenshot({ path: `${OUT}/free-azure-allservices-badge.png` });

await open("gcp", "/kubernetes");
await page.waitForSelector('[data-testid="k8s-locked"]', { timeout: 8000 }).catch(() => {});
ok("Free/GCP: GKE shows the locked pane", await page.locator('[data-testid="k8s-locked"]').count() === 1);
ok("Free/GCP: no Create cluster button", await page.getByRole("button", { name: /Create/ }).count() === 0);
await page.screenshot({ path: `${OUT}/free-gcp-gke-locked.png` });

let r = await wire("PUT", `/subscriptions/${SUB}/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/c1?api-version=2024-09-02-preview`, { location: "eastus" });
let b = await r.json().catch(() => ({}));
ok("Free: ARM create AKS over the wire -> 403 FeatureNotAvailableForTier", r.status === 403 && b?.error?.code === "FeatureNotAvailableForTier", JSON.stringify(b));
r = await wire("POST", `/subscriptions/${SUB}/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/c1/runCommand?api-version=2024-09-02-preview`, { command: "kubectl get ns" });
ok("Free: AKS runCommand (kubectl) -> 403", r.status === 403);
r = await wire("POST", `/v1/projects/p/locations/us-central1/clusters`, { cluster: { name: "g1" } });
b = await r.json().catch(() => ({}));
ok("Free: GKE create over the wire -> 403 PERMISSION_DENIED", r.status === 403 && b?.error?.status === "PERMISSION_DENIED", JSON.stringify(b));

// ── Pro (primary azure): AKS open, GKE locked ───────────────────────────────────────────────
await setTier("pro", "azure");
await open("gcp", "/kubernetes");
await page.waitForSelector('[data-testid="k8s-locked"]', { timeout: 8000 }).catch(() => {});
ok("Pro(azure)/GCP: GKE locked, CTA says Max", /Upgrade to Max/.test(await page.locator('[data-testid="k8s-upgrade-cta"]').innerText().catch(() => "")));
await open("azure", "/aks");
await page.waitForTimeout(800);
ok("Pro(azure)/Azure: AKS open", await page.locator('[data-testid="k8s-locked"]').count() === 0);

// ── Max: both open ──────────────────────────────────────────────────────────────────────────
await setTier("max");
await open("azure", "/aks");
await page.waitForTimeout(1500);
ok("Max/Azure: AKS page is the real service (not locked)", await page.locator('[data-testid="k8s-locked"]').count() === 0 && /Kubernetes services/.test(await page.content()));
ok("Max/Azure: a Create control is present", await page.getByText(/Create/).count() > 0);
await page.screenshot({ path: `${OUT}/max-azure-aks-open.png` });
await open("gcp", "/kubernetes");
await page.waitForTimeout(1500);
ok("Max/GCP: GKE page is the real service (not locked)", await page.locator('[data-testid="k8s-locked"]').count() === 0);
ok("Max/GCP: a Create control is present", await page.getByText(/Create/).count() > 0);
await page.screenshot({ path: `${OUT}/max-gcp-gke-open.png` });
await open("azure", "/allservices");
ok("Max: no lock badge on AKS", await page.locator('[data-testid="k8s-lock-badge"]').count() === 0);

r = await wire("PUT", `/subscriptions/${SUB}/resourceGroups/rg?api-version=2021-04-01`, { location: "eastus" });
r = await wire("PUT", `/subscriptions/${SUB}/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/c1?api-version=2024-09-02-preview`, { location: "eastus" });
ok("Max: ARM create AKS over the wire succeeds", r.status < 300, String(r.status));
r = await wire("POST", `/v1/projects/p/locations/us-central1/clusters`, { cluster: { name: "g1", initialNodeCount: 1 } });
ok("Max: GKE create over the wire succeeds", r.status < 300, String(r.status));

ok("no page errors", errs.length === 0, errs.join(" | ").slice(0, 300));
await browser.close();
console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
