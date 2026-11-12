/* IAM root "CloudFront key pairs": browser-generated key pair registers, a URL signed with the downloaded private key validates
 * (real RSA-SHA1 verify in the backend), a tampered URL does not. UI -> wire.
 *   BASE=http://127.0.0.1:9050 PW=... node consoles/tests/smoke-aws-cloudfrontkeys.mjs */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9050";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const results = [];
const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 2000 } });
const page = await ctx.newPage();
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/iam/security-credentials");
await page.getByText("CloudFront key pairs").first().waitFor();
check("not the Not-simulated panel", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));
const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Create new key pair" }).click()]);
const path = await dl.path();
const keyId = (/pk-(APKA\w+)\.pem/.exec(dl.suggestedFilename()) || [])[1];
check("key pair created and private key downloaded", !!keyId && readFileSync(path, "utf8").includes("BEGIN PRIVATE KEY"), dl.suggestedFilename());
await page.getByText(keyId).first().waitFor({ timeout: 8000 }).catch(() => {});
check("key pair listed Active", /Active/.test(await page.locator("body").innerText()));
const base = "https://d111111abcdef8.cloudfront.net/private/video.mp4";
const exp = Math.floor(Date.now() / 1000) + 600;
const policy = JSON.stringify({ Statement: [{ Resource: base, Condition: { DateLessThan: { "AWS:EpochTime": exp } } }] });
const sig = execFileSync("openssl", ["dgst", "-sha1", "-sign", path], { input: policy }).toString("base64").replace(/\+/g, "-").replace(/=/g, "_").replace(/\//g, "~");
const url = `${base}?Expires=${exp}&Signature=${sig}&Key-Pair-Id=${keyId}`;
await page.getByLabel("Signed URL").fill(url);
await page.getByRole("button", { name: "Validate", exact: true }).click();
await page.getByText(/Valid \(canned policy/).waitFor({ timeout: 8000 }).catch(() => {});
check("signed URL validates", /Valid \(canned policy/.test(await page.locator("body").innerText()));
await page.getByLabel("Signed URL").fill(url.replace("video.mp4", "other.mp4"));
await page.getByRole("button", { name: "Validate", exact: true }).click();
await page.getByText("Not valid").waitFor({ timeout: 8000 }).catch(() => {});
check("tampered URL is rejected", /Not valid/.test(await page.locator("body").innerText()));
check("no page errors", errors.length === 0, errors.join("; "));
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
