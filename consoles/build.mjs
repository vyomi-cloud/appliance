/* Build the v4 consoles once and emit them to every substrate:
 *   static/v4/<cloud>/  — offline appliance + Codespaces sandbox (served at /v4/<cloud>/)
 *   wasm/v4/<cloud>/    — Nano canonical (served by the portal at /nano/v4/<cloud>/)
 * Everything is bundled locally (no CDN) so Nano and air-gapped appliances work offline.
 *
 *   node build.mjs [--watch] [--cloud aws]
 */
import * as esbuild from "esbuild";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const TARGETS = [join(ROOT, "static", "v4"), join(ROOT, "wasm", "v4")];
const argv = process.argv.slice(2);
const only = argv.includes("--cloud") ? argv[argv.indexOf("--cloud") + 1] : null;
const TITLES = { aws: "Vyomi · AWS", gcp: "Vyomi · Google Cloud", azure: "Vyomi · Azure" };
const CLOUDS = ["aws", "gcp", "azure"].filter((c) => (!only || c === only) && existsSync(join(HERE, "src", c, "main.jsx")));

// Nano: the page must boot the in-browser backend — nano-boot.js registers the service
// worker (which answers /_wire) and runs Pyodide in this page; nano-kernel.js shows the
// once-per-launch loader. Offline/sandbox pages talk to the appliance and need neither.
// Content-hash the boot scripts so a fixed nano-boot.js / nano-kernel.js always reaches an open
// browser (a fixed ?v= let a broken boot script linger in caches).
const _bootHash = (f) => { try { return createHash("sha256").update(readFileSync(new URL(`../wasm/${f}`, import.meta.url))).digest("hex").slice(0, 12); } catch { return "0"; } };
const NANO_HEAD = `<script src="../../booster-link.js?v=${_bootHash("booster-link.js")}"></script>\n<script type="module" src="../../nano-boot.js?v=${_bootHash("nano-boot.js")}"></script>\n`;
const NANO_BODY = `<script src="../../nano-kernel.js?v=${_bootHash("nano-kernel.js")}"></script>\n<script>window.__nk = window.NanoKernel && NanoKernel.start("Vyomi console");</script>\n`;
// Nano chrome the legacy consoles carried and users see today: the bottom app bar (Spaces / Health / Knowledge /
// SDK & CLI / API, back to clouds.html) and the "How Nano <cloud> works" video banner (mounted on each Home by
// consoles/src/common/NanoVideoBanner.jsx). Plain scripts, shared with clouds.html; v4 pages sit two levels down.
const nanoChrome = (cloud) => `<script>window.__VY_ASSET_BASE = "../../";</script>\n<script src="../../nano-video.js?v=${_bootHash("nano-video.js")}"></script>\n<script src="../../vyomi-appbar.js?v=${_bootHash("vyomi-appbar.js")}" data-cloud="${cloud}" data-clouds="../../clouds.html" defer></script>\n`;

// Cache-busting: asset URLs carry a hash of the bundle, so browsers (and Nano's service
// worker) fetch the new build after every rebuild/upgrade instead of a stale main.js.
let assetVersion = "dev";
// Nano: the relay-tunnel footer (Start tunnel / Logs / Local tunnel + Cloudflare tabs) is the shared
// widget the Nano pages carry. It is lifted verbatim from wasm/aws-console.html at build time (single
// source) and mounted on every v4 Nano console; __NANO_BASE points it at the bundle root (../..).
function nanoFoot() {
  try {
    const src = readFileSync(join(ROOT, "wasm", "aws-console.html"), "utf8");
    const i = src.indexOf(" #nano-star{");
    const a = i < 0 ? -1 : src.lastIndexOf("<style>", i);
    const b = src.indexOf('<script src="./vyomi-appbar.js"', a);
    if (a < 0 || b < 0) throw new Error("tunnel footer block not found in wasm/aws-console.html");
    return '<script>window.__NANO_BASE = "../..";</script>\n' + src.slice(a, b) + "\n";
  } catch (e) { console.warn("[v4] tunnel footer not embedded:", e.message); return ""; }
}
const NANO_FOOT = nanoFoot();

const html = (cloud, title, nano = false) => `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<meta name="vyomi-substrate" content="${nano ? "nano" : "offline"}">
${existsSync(join(HERE, "..", "static", "v4", cloud, "main.css")) ? `<link rel="stylesheet" href="./main.css?v=${assetVersion}">\n` : ""}${nano ? NANO_HEAD : ""}</head>
<body>
${nano ? NANO_BODY : ""}<div id="root"></div>
${nano ? nanoChrome(cloud) : ""}<script type="module" src="./main.js?v=${assetVersion}"></script>
${nano ? NANO_FOOT : ""}
</body>
</html>
`;

async function buildCloud(cloud, watch) {
  const out = join(HERE, "dist", cloud);
  await rm(out, { recursive: true, force: true });
  await mkdir(out, { recursive: true });
  const opts = {
    entryPoints: { main: join(HERE, "src", cloud, "main.jsx") },
    outdir: out,
    bundle: true,
    splitting: false,           // esbuild does not load CSS of lazy chunks; per-service splitting is P3 (bundle budget)
    format: "esm",
    minify: !watch,
    sourcemap: watch ? "inline" : false,
    target: ["es2020"],
    jsx: "automatic",
    loader: { ".woff": "file", ".woff2": "file", ".ttf": "file", ".svg": "file", ".png": "file" },
    assetNames: "assets/[name]-[hash]",
    chunkNames: "chunks/[name]-[hash]",
    define: { "process.env.NODE_ENV": watch ? '"development"' : '"production"' },
    logLevel: "info",
  };
  await writeFile(join(out, "index.html"), html(cloud, TITLES[cloud]));
  if (watch) {
    const ctx = await esbuild.context({ ...opts, plugins: [emit(cloud, out)] });
    await ctx.watch();
    return;
  }
  await esbuild.build(opts);
  await publish(cloud, out);
}

const emit = (cloud, out) => ({ name: "emit", setup(b) { b.onEnd(() => publish(cloud, out)); } });

async function publish(cloud, out) {
  const h = createHash("sha256");
  for (const f of ["main.js", "main.css"]) h.update(await readFile(join(out, f)).catch(() => ""));
  assetVersion = h.digest("hex").slice(0, 12);
  await writeFile(join(out, "index.html"), html(cloud, TITLES[cloud]));
  for (const t of TARGETS) {
    const dst = join(t, cloud);
    await rm(dst, { recursive: true, force: true });
    await mkdir(dst, { recursive: true });
    await cp(out, dst, { recursive: true });
    if (t.includes(`${join("wasm", "v4")}`)) await writeFile(join(dst, "index.html"), html(cloud, TITLES[cloud], true));
  }
  console.log(`[v4] ${cloud} → static/v4/${cloud}, wasm/v4/${cloud}`);
}

const watch = argv.includes("--watch");
for (const c of CLOUDS) await buildCloud(c, watch);
