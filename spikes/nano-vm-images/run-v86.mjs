// Headless-Chrome driver for the v86 spike page. node run-v86.mjs <cfg> <runs> [mem_mb] [cmd] [promptRegex] [vga]
// Waits for a shell prompt on the serial console (or the VGA text screen with vga=1), sends cmd, waits for a marker.
import { createRequire } from "module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
const [cfg, runs = "3", mem = "512", cmd = "cat /etc/os-release; uname -m", prompt = "[#$] $", vga = "0"] = process.argv.slice(2);
const PORT = process.env.PORT || "8502";
const CHROME = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const TMO = Number(process.env.TMO || 300) * 1000;
const re = new RegExp(prompt, "m");
const out = [];
for (let r = 0; r < Number(runs); r++) {
  const prof = (process.env.PROF_ROOT || "/tmp") + "/nvs-prof-" + process.pid + "-" + r;
  const browser = await chromium.launchPersistentContext(prof, { executablePath: CHROME, headless: true, args: ["--no-sandbox"] }); // isolated profile dir => its processes can be told apart for RSS
  const page = await browser.newPage();
  page.on("console", (m) => { if (m.type() === "error") console.log("console.error", m.text().slice(0, 200)); });
  page.on("pageerror", (e) => console.log("pageerror", String(e).slice(0, 200)));
  const t0 = Date.now();
  await page.goto(`http://127.0.0.1:${PORT}/spikes/nano-vm-images/v86/index.html?cfg=${cfg}&mem=${mem}`);
  const get = () => page.evaluate((v) => (v === "1" ? window.__vgaText() : window.__ser), vga);
  let pm = null, t = "";
  while (Date.now() - t0 < TMO) { t = await get(); if (re.test(t.replace(/\s+$/, "") ) || re.test(t)) { pm = Date.now() - t0; break; } await new Promise((s) => setTimeout(s, 100)); }
  let cm = null;
  if (pm && cmd !== "-") {
    const c0 = Date.now();
    await page.evaluate(([c, v]) => { const line = c + "; echo DONE_$((6*7))\n"; v === "1" ? window.__emu.keyboard_send_text(line) : window.__emu.serial_send_bytes(0, new TextEncoder().encode(line)); }, [cmd, vga]);
    while (Date.now() - c0 < 180000) { t = await get(); if (/^DONE_42/m.test(t)) { cm = Date.now() - c0; break; } await new Promise((s) => setTimeout(s, 100)); }
  }
  if (process.env.MEM) { const { execSync } = await import("child_process"); const rows = execSync("ps -axo rss=,command=").toString().split("\n").filter((l) => l.includes(prof)); console.log("chrome_tree_rss_MiB=" + Math.round(rows.reduce((a, l) => a + Number(l.trim().split(/\s+/)[0]), 0) / 1024) + " procs=" + rows.length); }
  if (!pm) console.log("NO PROMPT; tail:", JSON.stringify(t.slice(-400)));
  console.log(`run ${r + 1}: prompt_ms=${pm} cmd_ms=${cm}`);
  if (r === 0) console.log("--- console tail ---\n" + t.split("\n").filter((l) => l.trim()).slice(-14).join("\n") + "\n---");
  out.push({ prompt: pm, cmd: cm });
  await browser.close();
}
console.log(JSON.stringify(out));
