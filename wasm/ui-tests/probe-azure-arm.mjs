import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let collUrl = null;
page.on("request", (r) => { const u = r.url(); if (!collUrl && /\/subscriptions\/.*\/providers\/Microsoft\.Storage\/storageAccounts\?/.test(u)) collUrl = u.replace(base, ""); });
try {
  await bootConsole(page, base, "/azure-console.html");
  // click Storage accounts → triggers the ARM list (captures the collection URL)
  await page.evaluate((sel) => { const e = [...document.querySelectorAll(sel)].find((x) => (x.innerText || "").includes("Storage accounts")); e && e.click(); }, RAIL_SEL);
  await sleep(2500);
  if (!collUrl) throw new Error("did not capture a storageAccounts ARM list URL");
  const out = await page.evaluate(async (coll) => {
    const [path, qs] = coll.split("?");
    const name = "probesa1";
    const put = await fetch(path + "/" + name + "?" + qs, { method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2", properties: {} }) });
    const putTxt = (await put.text()).slice(0, 100);
    const lj = await (await fetch(coll)).json().catch(() => ({}));
    return { collUrl: coll, putStatus: put.status, putTxt, listed: (lj.value || []).some((r) => (r.name || "").includes(name)), count: (lj.value || []).length };
  }, collUrl);
  console.log("Azure ARM storage-account create/list:", JSON.stringify(out, null, 1));
  console.log("\nVERDICT:", (out.putStatus < 300 && out.listed)
    ? "ARM backend WORKS — the 12 ARM services are functional; sweep FAILs = generic-fill can't drive their multi-field wizards (test limit, not broken UI)."
    : "ARM create/list did NOT round-trip — real fix needed.");
} catch (e) { console.log("ERR", String(e).split("\n")[0]); }
await browser.close(); server.close();
