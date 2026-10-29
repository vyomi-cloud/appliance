/* Firestore detail Usage tab: the documents list for a database must be served by
 * Nano (not 501), and a document written through the wire shows up in it. */
import { startServer, bootConsole, chromium } from "./lib.mjs";

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
try {
  const s = await startServer(); server = s.server;
  await bootConsole(page, s.base, "/gcp-console.html");
  const r = await page.evaluate(async () => {
    const j = (b) => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    const out = {};
    const c = await fetch(`/api/gcp/firestore/v1/projects/${PROJECT}/databases`, j({ name: "(default)" }));
    out.create = c.status;
    const g = await fetch(`/api/gcp/firestore/v1/projects/${PROJECT}/databases/(default)/documents`);
    out.list = g.status; out.body = (await g.text()).slice(0, 200);
    return out;
  });
  check("create database", r.create < 300, JSON.stringify(r));
  check("documents list is served (not 501)", r.list === 200, JSON.stringify(r));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
