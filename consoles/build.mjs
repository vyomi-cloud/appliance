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
const CLOUDS = ["aws"].filter((c) => !only || c === only);

const html = (cloud, title) => `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<link rel="stylesheet" href="./main.css">
</head>
<body>
<div id="root"></div>
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
  await writeFile(join(out, "index.html"), html(cloud, { aws: "Vyomi · AWS" }[cloud]));
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
  }
  console.log(`[v4] ${cloud} → static/v4/${cloud}, wasm/v4/${cloud}`);
}

const watch = argv.includes("--watch");
for (const c of CLOUDS) await buildCloud(c, watch);
