import { startServer, bootConsole, chromium } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
page.on("console", (m) => { if (m.type() === "error") console.log("[console.error]", m.text().slice(0, 160)); });
try {
  await bootConsole(page, base, "/aws-console.html");
  const out = await page.evaluate(async () => {
    const r = {};
    r.mkBucket = (await (await fetch("/api/s3/buckets", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "uptest" }) })).json());
    const fd = new FormData();
    fd.append("file", new File(["hello world from UI upload"], "hello.txt", { type: "text/plain" }));
    const up = await fetch("/api/s3/buckets/uptest/objects", { method: "POST", body: fd });
    r.upStatus = up.status;
    r.upBody = (await up.text()).slice(0, 400);
    const list = await fetch("/api/s3/buckets/uptest/objects").then((x) => x.json()).catch((e) => ({ err: String(e) }));
    r.listStatus = "ok";
    r.objects = (list.objects || list.Contents || list.items || list.value || []);
    r.listRaw = JSON.stringify(list).slice(0, 300);
    return r;
  });
  console.log(JSON.stringify(out, null, 1));
  console.log("\nUPLOAD:", out.upStatus === 200 ? "OK" : "FAILED (status " + out.upStatus + ")");
} catch (e) { console.log("ERR", String(e).split("\n")[0]); }
await browser.close(); server.close();
