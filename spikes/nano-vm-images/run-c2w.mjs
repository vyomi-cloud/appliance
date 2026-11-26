// Drives the container2wasm PoC in headless Chrome: boot -> prompt -> run commands -> report timings.
// node run-c2w.mjs <url> <runs> [cmd]   (url e.g. http://127.0.0.1:8501/c2w/index.html?img=amd64-debian-wasi-container&chunks=5&net=none)
import { createRequire } from "module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
const [url, runs = "3", cmd = "cat /etc/os-release; uname -m"] = process.argv.slice(2);
const CHROME = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const text = (p) => Promise.race([p.evaluate(() => { const b = window.__term?.buffer.active; if (!b) return ""; let o = []; for (let i = 0; i < b.length; i++) o.push(b.getLine(i)?.translateToString(true) ?? ""); return o.join("\n"); }), new Promise((r) => setTimeout(() => r(""), 8000))]);
const out = [];
for (let r = 0; r < Number(runs); r++) {
  const prof = (process.env.PROF_ROOT || "/tmp") + "/nvs-prof-" + process.pid + "-" + r;
  const browser = await chromium.launchPersistentContext(prof, { executablePath: CHROME, headless: true, args: ["--no-sandbox"] }); // isolated profile dir => its processes can be told apart for RSS
  const page = await browser.newPage();
  const t0 = Date.now();
  await page.goto(url);
  let prompt = null, t = "", loginSent = false, loginMs = null;
  while (Date.now() - t0 < 600000) {
    t = await text(page);
    if (process.env.LOGIN && !loginSent && /login: *$/m.test(t.trimEnd().split("\n").pop() || "")) { loginMs = Date.now() - t0; loginSent = true; await page.click("#term"); await page.keyboard.type("root\n"); }
    if (/[#$] *$/m.test(t.trimEnd().split("\n").pop() || "") && t.length > 0) { prompt = Date.now() - t0; break; }
    await new Promise((s) => setTimeout(s, 200));
  }
  let cmdMs = null, cmdOut = "";
  if (prompt) {
    await page.click("#term"); const c0 = Date.now(); await page.keyboard.type(cmd + "; echo DONE_$((6*7))\n");
    while (Date.now() - c0 < 120000) { t = await text(page); if (/^DONE_42/m.test(t)) { cmdMs = Date.now() - c0; break; } await new Promise((s) => setTimeout(s, 200)); }
    cmdOut = t;
  }
  if (process.env.MEM) { const { execSync } = await import("child_process"); const rows = execSync("ps -axo rss=,command=").toString().split("\n").filter((l) => l.includes(prof)); console.log("chrome_tree_rss_MiB=" + Math.round(rows.reduce((a, l) => a + Number(l.trim().split(/\s+/)[0]), 0) / 1024) + " procs=" + rows.length); }
  console.log(`run ${r + 1}: login_prompt_ms=${loginMs} shell_prompt_ms=${prompt} cmd_ms=${cmdMs}`);
  if (r === 0) console.log("--- terminal ---\n" + cmdOut.trim().split("\n").slice(-25).join("\n") + "\n---");
  out.push({ prompt, cmdMs });
  await browser.close();
}
console.log(JSON.stringify(out));
