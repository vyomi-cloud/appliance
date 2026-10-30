/* Preview the Nano bundle exactly as the portal serves it — under /nano/ — straight from
 * this checkout's wasm/ (no portal, no login gate, no sync into portal/app/nano).
 *
 *   node consoles/nano_preview.mjs [--port 8743]   →  http://127.0.0.1:8743/nano/  (launcher → v4 consoles)
 */
import http from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../wasm/", import.meta.url));
const PORT = Number(process.argv[process.argv.indexOf("--port") + 1]) || 8743;
const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json", ".py": "text/plain; charset=utf-8", ".wasm": "application/wasm",
  ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".woff": "font/woff", ".whl": "application/octet-stream",
  ".data": "application/octet-stream", ".zip": "application/zip", ".map": "application/json",
};

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  if (url.pathname === "/" || url.pathname === "/nano") { res.writeHead(302, { location: "/nano/" }); return res.end(); }
  if (!url.pathname.startsWith("/nano/")) { res.writeHead(404); return res.end(); }
  let f = normalize(join(ROOT, decodeURIComponent(url.pathname.slice("/nano/".length))));
  if (!f.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  try {
    if ((await stat(f)).isDirectory()) f = join(f, "index.html");
    const body = await readFile(f);
    // The service worker must be allowed to control the whole /nano/ scope.
    res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream", "service-worker-allowed": "/nano/", "cache-control": "no-cache" });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
}).listen(PORT, "127.0.0.1", () => console.log(`Nano preview: http://127.0.0.1:${PORT}/nano/v4/aws/`));
