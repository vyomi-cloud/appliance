/* "Vyomi Mesh" top drawer on the Nano consoles (wasm/nano-mesh-drawer.js, shared by the v4 AWS / GCP / Azure pages):
 * contract = EXPANDED by default (only a user's explicit collapse "0" is remembered), it sits IN the page flow right after
 * the console header so it PUSHES the console down (never position:fixed / overlaying), and it casts NO shadow
 * (border only). Static checks on the real file + the real page includes; the layout itself is measured in Chrome
 * (docs/architecture/v4.0/branches/mesh-drawer-push.md).
 *   node tests/conformance/test_mesh_drawer_push.mjs */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
let failed = false;
const check = (n, ok, x = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " " + x}`); failed ||= !ok; };
const src = readFileSync(join(ROOT, "wasm/nano-mesh-drawer.js"), "utf8");

// the CSS the script injects (string-concatenated literals)
const cssBlock = src.slice(src.indexOf("var CSS ="), src.indexOf("function header()"));
const css = [...cssBlock.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]).join("");

check("default state is EXPANDED (open unless the user stored an explicit collapse)", /open\s*=\s*LS\("g"\)\s*!==\s*"0"/.test(src));
check("only the collapse is the exception: the toggle still stores '1'/'0'", /LS\("s",\s*open\s*\?\s*"1"\s*:\s*"0"\)/.test(src));
check("drawer root is in flow (position:relative, flex:none), not fixed", /#vy-md\{position:relative;flex:none/.test(css) && !/position:fixed/.test(css));
// the one deliberate exception: AWS service page, side nav open, drawer COLLAPSED (see the check below)
const cssNoNavCollapse = css.replace(/#vy-md\.c-aws\.nav:not\(\.open\) \.md-tab\{[^}]*\}/, "");
check("no absolute/fixed tab, no pointer-events overlay hacks (except the collapsed-with-nav tab)", !/\.md-tab\{[^}]*position:absolute/.test(cssNoNavCollapse) && !/pointer-events:auto/.test(css));
check("AWS side nav + collapsed drawer: tab row is 0px tall so the nav's vertical divider starts at the header (no top gap)",
  /#vy-md\.c-aws\.nav:not\(\.open\) \.md-tabrow\{height:0\}/.test(css) && /#vy-md\.c-aws\.nav:not\(\.open\) \.md-tab\{position:absolute;top:0;/.test(css));
check("the tab row takes real height (no hanging pill over the console)", /\.md-tabrow\{[^}]*height:calc\(var\(--md-bh,32px\) \+ 8px\)/.test(css));
check("no box-shadow value anywhere in the drawer CSS", !/box-shadow:(?!none)/.test(css) && !/--md-shadow:(?!none)/.test(css) && !/--md-bsh:(?!none)/.test(css), (css.match(/box-shadow:[^;}]*/g) || []).join(" | "));
check("safety net: nothing inside #vy-md may cast a shadow / filter", /#vy-md,#vy-md \*\{box-shadow:none!important/.test(css) && /#vy-md\{filter:none!important\}/.test(css));
check("1px border is the only edge", /#vy-md\{[^}]*border-bottom:1px solid var\(--md-line\)/.test(css));
check("body max-height leaves room for the console (no 100vh-150px overlay sizing)", /max-height:min\(56vh,calc\(100vh - 220px\)\)/.test(css) && !/100vh - 150px/.test(css));
check("mounts right after the console header and re-mounts if React re-creates it", /h\.parentNode\.insertBefore\(box,\s*h\.nextSibling\)/.test(src) && /setInterval\(place,\s*1500\)/.test(src));
check("falls back to the top of <body> when a page has no header", /document\.body\.insertBefore\(box,\s*document\.body\.firstChild\)/.test(src));
check("--mesh-drawer-h tracks the drawer height (ResizeObserver) for any shell that needs it", /setProperty\("--mesh-drawer-h"/.test(src) && /new ResizeObserver\(publish\)/.test(src));
check("collapsed / expanded states still toggle via .open + grid rows", /#vy-md\.open \.md-panel\{grid-template-rows:1fr\}/.test(css) && /#vy-md \.md-panel\{display:grid;grid-template-rows:0fr/.test(css));
check("the three clouds keep their header selectors", /aws:\s*"#vyomi-top"/.test(src) && /gcp:\s*"header"/.test(src) && /azure:\s*"header\.vy-top"/.test(src));
check("syntax parses", (() => { try { new Function(src); return true; } catch (e) { return false; } })());

// each v4 page loads the drawer with a cache-buster equal to the file's content hash (so the new behaviour is not served stale)
const h = createHash("sha256").update(readFileSync(join(ROOT, "wasm/nano-mesh-drawer.js"))).digest("hex").slice(0, 12);
for (const c of ["aws", "gcp", "azure"]) {
  const html = readFileSync(join(ROOT, `wasm/v4/${c}/index.html`), "utf8");
  const m = html.match(/nano-mesh-drawer\.js\?v=([0-9a-f]{12})"[^>]*data-cloud="([a-z]+)"/);
  check(`wasm/v4/${c}/index.html loads the drawer with data-cloud="${c}" and the current content hash`, !!m && m[2] === c && m[1] === h, m ? `${m[1]} != ${h}` : "no include");
}
const build = readFileSync(join(ROOT, "consoles/build.mjs"), "utf8");
check("consoles/build.mjs derives the drawer cache-buster from the file (no manual hash to forget)", /nano-mesh-drawer\.js\?v=\$\{_bootHash\("nano-mesh-drawer\.js"\)\}/.test(build));

process.exit(failed ? 1 : 0);
