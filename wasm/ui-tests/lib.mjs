/* Nano UI validation harness — shared library.
 *
 * Goal: drive the REAL Nano console (the exact bundle the portal serves) in a
 * headless browser, component by component, and cross-check what the UI shows
 * against what the relay (CLI/SDK surface) returns — so a green test means the
 * UI actually works, not just the API.
 *
 * Self-contained: serves portal/app/nano statically (bypasses the login gate),
 * boots the console tolerating nano-boot's self-reload churn, and exposes helpers
 * to query the relay (the "cmd line" side) for the same resources.
 */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright");
export const chromium = pw.chromium;

export const NANO_DIR = "/Users/sudhirganti/Applications/simulator/portal/app/nano";
export const RELAY = process.env.RELAY_HTTP || "http://127.0.0.1:8090";

// Rail-item selector that works across all three consoles: AWS/GCP use
// a/button/li/[data-service]/.svc/.service; Azure uses .navitem[data-key].
export const RAIL_SEL = "#rail a, #rail button, #rail li, #rail [data-service], #rail .svc, #rail .service, #rail .navitem, #rail [data-key]";

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".py": "text/plain; charset=utf-8", ".wasm": "application/wasm",
  ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".map": "application/json",
  ".data": "application/octet-stream", ".whl": "application/octet-stream",
};

// Static server for the nano bundle. no-cache (match the portal's _RevalidatingStatic)
// so re-runs always see current files.
export function startServer(root = NANO_DIR, port = 0) {
  return new Promise((resolve) => {
    const server = http.createServer(async (req, res) => {
      try {
        const url = new URL(req.url, "http://x");
        let p = normalize(decodeURIComponent(url.pathname));
        if (p === "/" || p === "") p = "/index.html";
        const file = join(root, p);
        if (!file.startsWith(root) || !existsSync(file)) { res.writeHead(404); return res.end("404"); }
        const body = await readFile(file);
        res.writeHead(200, {
          "content-type": MIME[extname(file)] || "application/octet-stream",
          "cache-control": "no-cache",
          "service-worker-allowed": "/",
        });
        res.end(body);
      } catch (e) { res.writeHead(500); res.end(String(e)); }
    });
    server.listen(port, "127.0.0.1", () => resolve({ server, port: server.address().port,
      base: `http://127.0.0.1:${server.address().port}` }));
  });
}

// Boot a console page, tolerating nano-boot's self-reloads. Resolves when the SW
// controls the page AND the SPA shell is populated (service rail has items).
export async function bootConsole(page, base, path) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message)));
  await page.goto(base + path, { waitUntil: "domcontentloaded" });
  // waitForFunction survives navigations (Playwright re-injects after each reload).
  await page.waitForFunction((sel) => {
    const swOk = navigator.serviceWorker && navigator.serviceWorker.controller;
    const railReady = document.querySelectorAll(sel).length > 0;
    return swOk && railReady;
  }, RAIL_SEL, { timeout: 180000, polling: 500 });
  return { errors };
}

// The "cmd line" side: query the relay the way aws/gcloud/az/curl would.
export async function relayS3List() {
  const r = await fetch(RELAY + "/");
  const xml = await r.text();
  return (xml.match(/<Name>([^<]*)<\/Name>/g) || []).map((s) => s.replace(/<\/?Name>/g, ""));
}
export async function relayHealth() { try { return await (await fetch(RELAY + "/health")).json(); } catch { return { ok: false }; } }
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Dump a compact description of a DOM subtree for audit/inspection.
export async function describe(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return { exists: false, selector: sel };
    const txt = (el.innerText || "").trim().slice(0, 400);
    const buttons = [...el.querySelectorAll("button,[role=button]")].map((b) => (b.innerText || b.title || "").trim()).filter(Boolean);
    const inputs = [...el.querySelectorAll("input,select,textarea")].map((i) => i.name || i.id || i.placeholder || i.type).filter(Boolean);
    const rows = el.querySelectorAll("tr,[role=row],li,.row").length;
    return { exists: true, selector: sel, textLen: txt.length, text: txt, buttons, inputs, rows };
  }, selector);
}
