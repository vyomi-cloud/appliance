/* AWS-02/AWS-06 Marketplace: S3 Marketplace page (subscribe to a SaaS space with EULA, cancel), Get started page, and the EC2 AMI
 * catalog Marketplace/Community tabs (subscribe -> AMI appears in the catalog).
 *   BASE=http://127.0.0.1:9042 WIRE_PATH=/_wire node consoles/tests/smoke-aws-marketplace.mjs
 *   BASE=http://127.0.0.1:8743 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-marketplace.mjs   (Nano) */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9042";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH ?? "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const auth = "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/aws-marketplace/aws4_request, SignedHeaders=host, Signature=0";
await page.goto(UI + "#/s3");
const mp = (method, path, body) => page.evaluate(async ([u, m, p, b, a]) => { const r = await fetch(u + p, { method: m, headers: { authorization: a, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); return { status: r.status, body: await r.json().catch(() => ({})) }; }, [WIRE, method, path, body, auth]);
const body = () => page.locator("body").innerText();

// S3 Get started
await page.goto(UI + "#/s3/get-started");
await page.getByRole("heading", { name: "Amazon S3" }).first().waitFor();
await page.getByText("Storage classes").first().waitFor();
check("get-started is a real page", !/Not simulated in Vyomi/i.test(await body()) && /S3 Glacier Deep Archive/.test(await body()));
check("get-started shows live bucket count", /^\d+$/.test((await page.getByTestId("gs-bucket-count").innerText()).trim()));

// S3 Marketplace: subscribe via UI
await page.goto(UI + "#/s3/marketplace");
await page.getByRole("button", { name: "Vyomi Payments Sandbox" }).waitFor({ timeout: 10000 });
check("marketplace is not the Not-simulated panel", !/Not simulated in Vyomi/i.test(await body()));
await page.getByRole("button", { name: "Vyomi Payments Sandbox" }).click();
const sub = page.getByRole("dialog").getByRole("button", { name: "Subscribe" });
check("subscribe disabled until EULA accepted", await sub.isDisabled());
await page.getByTestId("mp-eula").click();
await sub.click();
await page.getByText("Successfully subscribed to Vyomi Payments Sandbox").first().waitFor({ timeout: 10000 });
const ag = await mp("GET", "/agreements?status=ACTIVE");
const a1 = ag.body.Agreements?.find((a) => a.ProductId === "vyomi-pay");
check("agreement + space on the wire", !!a1 && a1.Space?.Endpoint?.includes("vyomi-pay"));
await page.getByRole("tab", { name: "Manage subscriptions" }).click();
await page.getByText(a1.AgreementId).first().waitFor({ timeout: 10000 });
await page.getByRole("row", { name: new RegExp(a1.AgreementId) }).getByRole("button", { name: "Cancel" }).click();
await page.getByText("Subscription cancelled").first().waitFor({ timeout: 10000 });
check("cancel ends agreement", (await mp("GET", "/agreements?status=ACTIVE")).body.Agreements?.every((a) => a.ProductId !== "vyomi-pay"));

// EC2 AMI catalog
await page.goto(UI + "#/ec2/ami-catalog");
await page.getByRole("tab", { name: "AWS Marketplace AMIs" }).click();
await page.getByRole("button", { name: "Vyomi Nginx Web Server" }).waitFor({ timeout: 10000 });
check("AMI catalog marketplace tab is real", !/Not simulated in Vyomi/i.test(await body()));
await page.getByRole("button", { name: "Vyomi Nginx Web Server" }).click();
await page.getByTestId("mp-eula").click();
await page.getByRole("dialog").getByRole("button", { name: "Subscribe" }).click();
await page.getByText("Successfully subscribed to Vyomi Nginx Web Server").first().waitFor({ timeout: 10000 });
const ag2 = (await mp("GET", "/agreements?status=ACTIVE")).body.Agreements.find((a) => a.ProductId === "vyomi-ami-nginx");
check("AMI registered", !!ag2?.ImageId);
await page.getByRole("tab", { name: /^Quickstart AMIs/ }).click();
await page.getByRole("tab", { name: /^Quickstart AMIs/ }).waitFor();
check("quickstart tab lists Amazon AMIs", /Amazon Linux/.test(await body()));
await page.getByRole("tab", { name: "Community AMIs" }).click();
await page.getByText("Rocky Linux 9 (community)").first().waitFor({ timeout: 10000 });
check("community tab lists AMIs", true);
await page.screenshot({ path: `${OUT}/marketplace-community.png`, fullPage: true });
await mp("DELETE", `/agreements/${ag2.AgreementId}`);
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
