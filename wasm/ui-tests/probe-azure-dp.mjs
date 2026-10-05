import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const net = [];
page.on("response", (r) => { const u = r.url(); if (u.includes("/api/azure/")) net.push(`${r.status()} ${r.request().method()} ${u.replace(base, "")}`); });
try {
  await bootConsole(page, base, "/azure-console.html");
  // Go to Blob containers (rail data-plane item)
  await page.evaluate((sel) => { const el = [...document.querySelectorAll(sel)].find((e) => (e.innerText || "").includes("Blob containers")); el && el.click(); }, RAIL_SEL);
  await sleep(2000);
  const listState = await page.evaluate(() => {
    const m = document.querySelector("#main");
    return { text: m.innerText.replace(/\n/g, " ⏎ ").slice(0, 200), emptyMsg: (m.querySelector(".empty") || {}).innerText || "" };
  });
  console.log("LIST state:", JSON.stringify(listState, null, 1));
  // Open the Create dialog + dump its shape
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /create/i.test(x.innerText)); b && b.click(); });
  await sleep(1200);
  const dlg = await page.evaluate(() => {
    const d = document.querySelector("dialog,[role=dialog],.modal,.dialog,.drawer") || document.body;
    return {
      found: !!document.querySelector("dialog,[role=dialog],.modal,.dialog,.drawer"),
      inputs: [...d.querySelectorAll("input,select,textarea")].map((i) => ({ name: i.name || i.id || i.placeholder || i.type, tag: i.tagName })),
      buttons: [...d.querySelectorAll("button")].map((b) => b.innerText.trim()).filter(Boolean).slice(0, 8),
      text: (d.innerText || "").slice(0, 160).replace(/\n/g, " ⏎ "),
    };
  });
  console.log("CREATE dialog:", JSON.stringify(dlg, null, 1));
} catch (e) { console.log("PROBE ERR:", String(e).split("\n")[0]); }
console.log("\n/api/azure network:", net.slice(0, 15));
await browser.close(); server.close();
