/* Compute size pickers offer ONLY sizes the substrate can run, and the launch payload carries a listed size.
 * Needs two dev servers whose core engines run as the substrate under test (the env drives core/compute_sizes.py):
 *   VYOMI_COMPUTE_SUBSTRATE=nano VYOMI_MESH_CAP_MB=11468 VYOMI_MESH_CPUS=4 python3 consoles/dev_server.py --port 9461
 *   VYOMI_COMPUTE_SUBSTRATE=mesh VYOMI_MESH_CAP_MB=11468 VYOMI_MESH_CPUS=4 python3 consoles/dev_server.py --port 9462
 * Run:  NANO=http://127.0.0.1:9461 MESH=http://127.0.0.1:9462 node consoles/tests/smoke-compute-sizes.mjs
 * (CHROME=/path/to/chrome overrides the browser; PW=playwright module path.) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const SUBS = { nano: process.env.NANO || "http://127.0.0.1:9461", mesh: process.env.MESH || "http://127.0.0.1:9462" };
const NOTE = { nano: "Showing sizes available on Nano (browser VM)", mesh: "Showing sizes available on Mesh (Docker)" };
// what each substrate must list (core/compute_sizes.py; Mesh numbers are the default 4 vCPU / 16 GB Codespace)
const AWS = { nano: ["t2.nano", "t3.nano", "t3a.nano", "t2.micro", "t3.micro", "t3a.micro"],
              mesh: ["t2.nano", "t3.nano", "t3a.nano", "t2.micro", "t3.micro", "t3a.micro", "t2.small", "t3.small", "t3a.small", "c5.large", "c6i.large", "t2.medium", "t3.medium", "t3a.medium"] };
const GCP = { nano: ["f1-micro", "e2-micro"], mesh: ["f1-micro", "e2-micro", "g1-small", "e2-small", "e2-medium"] };
const AZ = { nano: ["Standard_B1ls", "Standard_B1s"], mesh: ["Standard_B1ls", "Standard_B1s", "Standard_B1ms", "Standard_B2s", "Standard_F2s_v2"] };
const BIG = { aws: ["m5.2xlarge", "r5.xlarge", "m5.xlarge", "t3.large"], gcp: ["e2-standard-4", "n2-standard-8", "e2-standard-2"], azure: ["Standard_D4s_v5", "Standard_E4s_v5", "Standard_B2ms"] };
const results = [];
const check = (n, ok, extra = "") => { results.push(!!ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${ok ? "" : "  " + extra}`); };
const same = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
const names = (labels) => labels.map((l) => l.split(" ")[0]);
const browser = await pw.chromium.launch({ executablePath: CHROME });

for (const [sub, base] of Object.entries(SUBS)) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1500 } });
  const page = await ctx.newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  const posts = []; page.on("request", (r) => { if (r.method() !== "GET" && r.url().includes("_wire")) posts.push({ url: r.url(), body: r.postData() || "" }); });

  // ── AWS: EC2 > Launch instance ──
  await page.goto(`${base}/v4/aws/#/ec2/launch-instance`);
  await page.getByText(NOTE[sub]).first().waitFor({ timeout: 20000 }).catch(() => {});
  check(`[${sub}] aws note`, await page.getByText(NOTE[sub]).count() > 0);
  await page.getByText("All generations").first().click();          // the console hides t2.small / m4.large until this is ticked
  await page.getByLabel("Instance type").first().click();
  await page.waitForTimeout(400);
  const enabledOpts = async () => (await page.getByRole("option").evaluateAll((els) => els.filter((e) => e.getAttribute("aria-disabled") !== "true" && !e.disabled).map((e) => e.innerText)));
  let opts = names([...new Set(await enabledOpts())].map((s) => s.split("\n")[0]));
  check(`[${sub}] aws picker lists exactly the runnable sizes`, same(opts, AWS[sub]), opts.join(","));
  check(`[${sub}] aws picker hides big sizes`, !BIG.aws.some((t) => opts.includes(t)), opts.join(","));
  await page.getByRole("option").filter({ hasText: "t3.micro (" }).first().click();
  await page.getByLabel("Name").first().fill("sizes-smoke");
  posts.length = 0;
  await page.getByRole("button", { name: "Launch instance" }).last().click();
  await page.waitForTimeout(2500);
  const run = posts.find((p) => /RunInstances/.test(p.body));
  check(`[${sub}] aws RunInstances payload carries t3.micro`, run && /InstanceType=t3\.micro/.test(run.body), JSON.stringify(run));

  // ── GCP: Compute Engine > Create instance ──
  await page.goto(`${base}/v4/gcp/#/compute/instances/create`);
  await page.getByText(NOTE[sub]).first().waitFor({ timeout: 20000 }).catch(() => {});
  check(`[${sub}] gcp note`, await page.getByText(NOTE[sub]).count() > 0);
  // every family with machine types, so the full runnable set is visible
  const seen = new Set();
  for (const fam of ["General purpose", "Compute optimized", "Memory optimized", "Storage optimized", "GPUs"]) {
    const radio = page.getByRole("radio", { name: fam });
    if (await radio.count() && await radio.first().isEnabled()) {
      await radio.first().check();
      await page.getByLabel("Machine type").first().click();
      await page.waitForTimeout(250);
      for (const l of await enabledOpts()) seen.add(l.split(" ")[0]);
      await page.keyboard.press("Escape");
    }
  }
  check(`[${sub}] gcp picker lists exactly the runnable machine types`, same([...seen], GCP[sub]), [...seen].join(","));
  check(`[${sub}] gcp picker hides big machine types`, !BIG.gcp.some((t) => seen.has(t)));
  await page.getByLabel("Name").first().fill("sizes-smoke-" + sub);
  posts.length = 0;
  await page.getByRole("button", { name: "Create", exact: true }).last().click();
  await page.waitForTimeout(2500);
  const ins = posts.find((p) => /\/instances/.test(p.url) && p.body);
  check(`[${sub}] gcp insert payload carries a listed machineType`, ins && GCP[sub].includes(JSON.parse(ins.body).machineType.split("/").pop()), JSON.stringify(ins));

  // ── Azure: Create a virtual machine ──
  await page.goto(`${base}/v4/azure/#/vms/create`);
  await page.getByTestId("compute-sizes-note").first().waitFor({ timeout: 20000 }).catch(() => {});
  check(`[${sub}] azure note`, (await page.getByTestId("compute-sizes-note").allInnerTexts()).some((t) => t.startsWith(NOTE[sub])));
  const az = names(await page.locator("#vm-size option:not([disabled])").allInnerTexts());
  check(`[${sub}] azure picker lists exactly the runnable sizes`, same(az, AZ[sub]), az.join(","));
  check(`[${sub}] azure picker hides big sizes`, !BIG.azure.some((t) => az.includes(t)));
  const sel = await page.locator("#vm-size").inputValue();
  check(`[${sub}] azure default size is one of the listed sizes`, AZ[sub].includes(sel), sel);
  check(`[${sub}] no page errors`, errors.length === 0, errors.join(" | "));
  await ctx.close();
}
await browser.close();
const bad = results.filter((x) => !x).length;
console.log(bad ? `FAILED ${bad}/${results.length}` : `ALL PASS ${results.length}/${results.length}`);
process.exit(bad ? 1 : 0);
