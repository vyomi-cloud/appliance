/* Build the v4 consoles once and emit them to every substrate:
 *   static/v4/<cloud>/  — offline appliance + Codespaces sandbox (served at /v4/<cloud>/)
 *   wasm/v4/<cloud>/    — Nano canonical (served by the portal at /nano/v4/<cloud>/)
 * Everything is bundled locally (no CDN) so Nano and air-gapped appliances work offline.
 *
 *   node build.mjs [--watch] [--cloud aws]
 */
import * as esbuild from "esbuild";
import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const TARGETS = [join(ROOT, "static", "v4"), join(ROOT, "wasm", "v4")];
const argv = process.argv.slice(2);
const only = argv.includes("--cloud") ? argv[argv.indexOf("--cloud") + 1] : null;
const TITLES = { aws: "Vyomi · AWS", gcp: "Vyomi · Google Cloud", azure: "Vyomi · Azure" };
const CLOUDS = ["aws"].filter((c) => !only || c === only);

// Nano: the page must boot the in-browser backend — nano-boot.js registers the service
// worker (which answers /_wire) and runs Pyodide in this page; nano-kernel.js shows the
// once-per-launch loader. Offline/sandbox pages talk to the appliance and need neither.
const NANO_HEAD = `<script type="module" src="../../nano-boot.js?v=4"></script>\n`;
const NANO_BODY = `<script src="../../nano-kernel.js"></script>\n<script>window.__nk = window.NanoKernel && NanoKernel.start("Vyomi console");</script>\n`;

const html = (cloud, title, nano = false) => `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<link rel="stylesheet" href="./main.css">
${nano ? NANO_HEAD : ""}</head>
<body>
${nano ? NANO_BODY : ""}<div id="root"></div>
<script type="module" src="./main.js"></script>
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
