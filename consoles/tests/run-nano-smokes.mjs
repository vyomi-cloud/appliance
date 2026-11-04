/* Run every consoles/tests/smoke-*.mjs against the Nano preview (the Pyodide/service-worker substrate).
 *
 *   node consoles/tests/run-nano-smokes.mjs [--port 8781] [--only aws-s3] [--skip aws-ec2] [--timeout 600] [--json out.json]
 *
 * Starts consoles/nano_preview.mjs itself if nothing listens on the port. Each smoke gets a fresh browser (and so a
 * fresh Nano boot). Env per smoke: BASE, UI_PATH=/nano/v4/<cloud>/, WIRE_PATH=/nano/_wire, NANO=1, SUBSTRATE=nano.
 * Playwright: $PW, else the smoke's own fallback. Exit code 1 if any smoke fails or times out. */
import { spawn } from "node:child_process";
import { readdir, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const PORT = Number(arg("--port", 8781));
const ONLY = arg("--only", ""), SKIP = arg("--skip", ""), TIMEOUT = Number(arg("--timeout", 600)) * 1000, JSON_OUT = arg("--json", "");
const BASE = `http://127.0.0.1:${PORT}`;

let preview = null;
const up = async () => { try { return (await fetch(`${BASE}/nano/`, { redirect: "manual" })).status < 500; } catch { return false; } };
if (!(await up())) {
  preview = spawn("node", [join(here, "..", "nano_preview.mjs"), "--port", String(PORT)], { stdio: "ignore" });
  for (let i = 0; i < 40 && !(await up()); i++) await new Promise((r) => setTimeout(r, 500));
}

const files = (await readdir(here)).filter((f) => /^smoke-.*\.mjs$/.test(f)).sort()
  .filter((f) => !ONLY || f.includes(ONLY)).filter((f) => !SKIP || !SKIP.split(",").some((s) => f.includes(s)));
const out = join(tmpdir(), `nano-smokes-${Date.now()}`);
await mkdir(out, { recursive: true });
const rows = [];

for (const f of files) {
  const cloud = (f.match(/^smoke-(aws|azure|gcp)/) || [])[1] || "aws";
  const env = { ...process.env, BASE, UI_PATH: `/nano/v4/${cloud}/`, WIRE_PATH: "/nano/_wire", NANO: "1", SUBSTRATE: "nano", OUT: join(out, f) };
  const t0 = Date.now();
  const res = await new Promise((resolve) => {
    const p = spawn("node", [join(here, f)], { env });
    let buf = "", timedOut = false;
    const timer = setTimeout(() => { timedOut = true; p.kill("SIGKILL"); }, TIMEOUT);
    p.stdout.on("data", (d) => (buf += d)); p.stderr.on("data", (d) => (buf += d));
    p.on("close", (code) => { clearTimeout(timer); resolve({ code, buf, timedOut }); });
  });
  const fails = res.buf.split("\n").filter((l) => /^FAIL /.test(l));
  const pass = (res.buf.match(/^PASS /gm) || []).length;
  const ok = res.code === 0 && !res.timedOut && !fails.length;
  rows.push({ file: f, ok, pass, fails, timedOut: res.timedOut, code: res.code, secs: Math.round((Date.now() - t0) / 1000), tail: ok ? "" : res.buf.split("\n").slice(-12).join("\n") });
  console.log(`${ok ? "OK  " : "FAIL"} ${f}  pass=${pass} fail=${fails.length}${res.timedOut ? " TIMEOUT" : ""} (${rows.at(-1).secs}s)`);
  for (const l of fails) console.log("     " + l.slice(0, 200));
  if (!ok && !fails.length) console.log("     " + rows.at(-1).tail.split("\n").slice(-4).join("\n     "));
}
const bad = rows.filter((r) => !r.ok);
console.log(`\n${rows.length - bad.length}/${rows.length} smokes green on Nano`);
if (bad.length) console.log("failing: " + bad.map((r) => r.file).join(" "));
if (JSON_OUT) await writeFile(JSON_OUT, JSON.stringify(rows, null, 1));
preview?.kill();
process.exit(bad.length ? 1 : 0);
