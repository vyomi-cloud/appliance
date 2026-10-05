import { startServer, bootConsole, chromium } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/gcp-console.html");
  const out = await page.evaluate(async () => {
    const r = {};
    // create a GCS bucket (collection_path POST)
    const mk = await fetch("/api/gcp/storage/v1/b", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "gcsuptest" }) });
    r.mkStatus = mk.status; r.mkBody = (await mk.text()).slice(0, 120);
    // upload a file (multipart → the GCS upload path)
    const fd = new FormData();
    fd.append("file", new File(["hello gcs"], "g.txt", { type: "text/plain" }));
    const up = await fetch("/api/gcp/storage/v1/b/gcsuptest/upload", { method: "POST", body: fd });
    r.upStatus = up.status; r.upBody = (await up.text()).slice(0, 300);
    const lj = await (await fetch("/api/gcp/storage/v1/b/gcsuptest/o")).json().catch(() => ({}));
    r.listed = (lj.objects || lj.items || []).some((o) => (o.name || o.key) === "g.txt");
    r.listCount = (lj.objects || lj.items || []).length;
    return r;
  });
  console.log(JSON.stringify(out, null, 1));
  console.log("\nGCS UPLOAD:", out.upStatus === 200 ? "OK" : "FAILED (status " + out.upStatus + ")");
} catch (e) { console.log("ERR", String(e).split("\n")[0]); }
await browser.close(); server.close();
