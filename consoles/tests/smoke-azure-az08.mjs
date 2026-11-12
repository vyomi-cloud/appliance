/* Smoke for the AZ-08 sweep: Azure Files, Storage Mover, AI Search, Marketplace, subscription extras (quota requests,
 * management certificates, partner info, ownership transfers, free services) and the cost-saved dashboard.
 *   BASE=http://127.0.0.1:9048 node consoles/tests/smoke-azure-az08.mjs */
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9048";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-az08";
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const CERT = "MH0wcqADAgECAgIBAjAKBggqhkjOPQQDAjAUMRIwEAYDVQQDDAlpc3N1ZXItY2EwHhcNMjYxMTAzMDQyODA5WhcNMzYxMDMxMDQyODA5WjAaMRgwFgYDVQQDDA92eW9taS1tZ210LWNlcnQwCTADBgEqAwIAATADBgEqAwIAAQ==";
const n = Date.now() % 100000;
const RG = `vyaz08-rg${n}`, SA = `vyaz08sa${n}`, SHARE = `docs${n}`, SVC = `vysearch${n}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2024-01-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await mkdir(OUT, { recursive: true });
await writeFile(`${OUT}/hello.txt`, "hello azure files from the smoke test");
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !/status of (400|403|404|409)/.test(m.text()) && errors.push(m.text()));
const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
const until = async (fn, ms = 15000) => { const t0 = Date.now(); for (;;) { try { const v = await fn(); if (v) return v; } catch { /* retry */ } if (Date.now() - t0 > ms) return false; await page.waitForTimeout(300); } };
const noNS = async (label, allow = []) => {
  const left = (await page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.getAttribute("data-vyomi-not-simulated") || ""))).filter((t) => !allow.some((a) => t.includes(a)));
  check(`${label}: no unexpected Not-simulated panel`, left.length === 0, left.join(" | ").slice(0, 160));
};
const blobPut = (container, name, body) => wire(`/${SA}/${container}/${name}`, { method: "PUT", body, headers: { "x-ms-blob-type": "BlockBlob", "x-ms-version": "2021-12-02", authorization: `SharedKey ${SA}:smoke` } });

try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } }, "2023-05-01");
  await wire(`/${SA}/src?restype=container`, { method: "PUT", headers: { "x-ms-version": "2021-12-02", authorization: `SharedKey ${SA}:smoke` } });
  await wire(`/${SA}/dst?restype=container`, { method: "PUT", headers: { "x-ms-version": "2021-12-02", authorization: `SharedKey ${SA}:smoke` } });
  await blobPut("src", "readme.txt", "searchable text about quasar telescopes");
  await blobPut("src", "dir/two.txt", "second document about nebula");

  // ── Azure Files: create a share, upload, snapshot ───────────────────────────────────────
  await page.goto(UI + `#/storage/${RG}/${SA}/fileshares`);
  await page.getByRole("button", { name: "File share", exact: true }).click();
  await page.getByLabel("Share name").fill(SHARE);
  await page.getByRole("button", { name: "Create" }).last().click();
  check("file share appears in the list", await until(() => page.getByRole("link", { name: SHARE }).isVisible()));
  const sh = json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}/fileServices/default/shares/${SHARE}`, null, "2023-01-01"));
  check("share exists over ARM with defaults", sh.properties?.enabledProtocols === "SMB" && sh.properties?.accessTier === "TransactionOptimized");
  await page.getByRole("link", { name: SHARE }).click();
  await page.getByLabel("Upload file").setInputFiles(`${OUT}/hello.txt`);
  check("uploaded file is listed", await until(() => page.getByText("hello.txt").first().isVisible()));
  await page.getByRole("tab", { name: "Snapshots" }).click();
  await page.getByRole("button", { name: "Add snapshot" }).click();
  check("snapshot listed", await until(async () => (await page.locator("table.vy-grid tbody tr").count()) >= 1 && !(await page.getByText("No snapshots.").isVisible())));
  await shot("files");
  const bad = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}/fileServices/default/shares/nfs${n}`, { properties: { enabledProtocols: "NFS" } }, "2023-01-01");
  check("NFS on a standard account is refused by the API", bad.status === 400);
  await page.goto(UI + `#/storage/${RG}/${SA}/cors`);
  await page.getByRole("tab", { name: "Queue service" }).click();
  await page.getByLabel("Queue service CORS allowed origins").fill("https://example.test");
  await page.getByRole("button", { name: "Add rule" }).click();
  check("queue service CORS rule saved", await until(() => page.getByText("https://example.test").first().isVisible()));
  await noNS("storage CORS tabs");

  // ── Storage Mover: copy container -> file share, really ────────────────────────────────
  await page.goto(UI + `#/storage/${RG}/${SA}/storagemover`);
  await page.getByLabel("Source container").selectOption("src");
  await page.getByLabel("Target type").selectOption("share");
  await page.getByLabel("Target", { exact: true }).selectOption(SHARE);
  await page.getByRole("button", { name: "Start copy job" }).click();
  check("copy job succeeded", await until(() => page.getByRole("cell", { name: "Succeeded" }).first().isVisible()));
  const files = json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}/fileServices/default/shares/${SHARE}/items/dir`, null, "2023-01-01"));
  check("the blob really landed in the Files share", (files.value || []).some((f) => f.name === "two.txt"));
  await shot("storagemover");

  // ── AI Search: service + import + query ─────────────────────────────────────────────────
  await page.goto(UI + `#/storage/${RG}/${SA}/azureaisearch`);
  await page.getByLabel("New search service name").fill(SVC);
  await page.getByLabel("Search service resource group").selectOption(RG);
  await page.getByRole("button", { name: "Create search service" }).click();
  check("search service created", await until(async () => (await page.getByLabel("Azure AI Search service").inputValue()) === SVC));
  await page.getByLabel("Container", { exact: true }).selectOption("src");
  await page.getByRole("button", { name: "Import data" }).click();
  check("indexer indexed the blobs", await until(() => page.getByText("Indexed 2 document(s)").isVisible()));
  await page.getByLabel("Search query").fill("quasar");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  check("search returns the matching blob", await until(() => page.getByRole("cell", { name: "readme.txt" }).isVisible()));
  await shot("aisearch");

  // ── Marketplace: subscribe to a Vyomi SaaS offer ────────────────────────────────────────
  await page.goto(UI + `#/storage/${RG}/${SA}/partnersolutions`);
  await page.getByRole("button", { name: "Create Elastic search space" }).click();
  await page.getByLabel("Resource group").selectOption(RG);
  await page.getByLabel("Resource name").fill(`elastic${n}`);
  await page.getByRole("button", { name: "Subscribe", exact: true }).click();
  await shot("marketplace");
  check("SaaS subscription created", await until(() => page.locator("td", { hasText: `elastic${n}` }).first().isVisible()));
  const saas = json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.SaaS/resources/elastic${n}`));
  check("Microsoft.SaaS resource exists over ARM", saas.properties?.status === "Subscribed");

  // ── Subscription extras ────────────────────────────────────────────────────────────────
  await page.goto(UI + `#/subscriptions/${SUB}/usagequotas`);
  await page.getByRole("button", { name: "Request increase" }).click();
  await page.getByLabel("Quota to increase").selectOption("PublicIPAddresses");
  await page.getByLabel("New limit").fill("120");
  await page.getByRole("button", { name: "Submit" }).click();
  check("quota request recorded", await until(() => page.getByRole("cell", { name: "Succeeded" }).first().isVisible()));
  const q = json(await arm("GET", `/providers/Microsoft.Network/locations/eastus/providers/Microsoft.Quota/quotas/PublicIPAddresses`));
  check("quota limit raised over ARM", q.properties?.limit?.value === 120);
  await page.goto(UI + `#/subscriptions/${SUB}/managementcertificates`);
  await page.getByRole("button", { name: "Upload" }).click();
  await page.getByLabel("Certificate data").fill(CERT);
  await page.getByRole("button", { name: "Upload" }).last().click();
  check("management certificate parsed", await until(() => page.getByText("vyomi-mgmt-cert").first().isVisible()));
  await page.goto(UI + `#/subscriptions/${SUB}/partnerinformation`);
  await page.getByLabel("MPN ID").fill("1234567");
  await page.getByRole("button", { name: "Link to a partner ID" }).click();
  check("partner associated", await until(() => page.getByText("1234567").first().isVisible()));
  await page.goto(UI + `#/subscriptions`);
  await page.getByRole("button", { name: "View Requests" }).click();
  await page.getByLabel("Recipient e-mail").fill("new.owner@example.com");
  await page.getByRole("button", { name: "Request transfer" }).click();
  check("transfer request pending", await until(() => page.getByRole("cell", { name: "Pending" }).isVisible()));
  await page.getByRole("button", { name: "Cancel", exact: true }).first().click();
  check("transfer request canceled", await until(() => page.getByRole("cell", { name: "Canceled" }).isVisible()));
  await page.keyboard.press("Escape");
  await page.goto(UI + `#/subscriptions/${SUB}`);
  await page.getByRole("tab", { name: "Top free services by usage" }).click();
  check("free services table rendered", await until(() => page.getByRole("cell", { name: "Blob storage (hot, LRS)" }).isVisible()));
  await noNS("subscription pages");

  // ── Cost saved dashboard + simulated invoices ─────────────────────────────────────────
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/vm${n}`, { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_D2s_v3" } } }, "2024-03-01");
  await page.goto(UI + `#/cost/invoices`);
  check("cost saved tiles render", await until(() => page.getByText("Saved so far").isVisible()));
  check("simulated invoice listed", await until(() => page.getByText("(simulated)").first().isVisible()));
  await shot("cost-saved");
  await noNS("cost invoices", []);

  const real = errors.filter((e) => !/favicon|ResizeObserver/.test(e));
  check("no console/page errors", real.length === 0, real.slice(0, 3).join(" | ").slice(0, 200));
} catch (e) {
  check("smoke ran to completion", false, String(e).slice(0, 300));
  await shot("failure").catch(() => {});
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
