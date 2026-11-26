/* v4.0.0 AWS console: create-form VALIDATION. Invalid input is refused with a field-level error and NOTHING is sent to the wire
 * (no Create call), as in the real console. Covers the core create forms (S3 bucket, SQS queue, SNS topic, DynamoDB table, IAM user).
 * Also: a valid name on the same form DOES create. Env: BASE (default http://127.0.0.1:8741), UI_PATH, PW_CHANNEL. */
import { chromium, sleep } from "./lib.mjs";
const BASE = process.env.BASE || "http://127.0.0.1:8741", UI = BASE + (process.env.UI_PATH || "/v4/aws/");
const s = Date.now().toString(36).slice(-6);
const FORMS = [
  { name: "S3 bucket", route: "s3/create", bad: "Bad_Bucket_NAME!", good: "vb" + s, action: /PUT .*\/vb|CreateBucket/i, method: "PUT" },
  { name: "SQS queue", route: "sqs/create-queue", bad: "bad queue name!", good: "vq" + s, action: /CreateQueue/ },
  { name: "SNS topic", route: "sns/create-topic", bad: "bad topic name!", good: "vt" + s, action: /CreateTopic/ },
  { name: "DynamoDB table", route: "dynamodb/create-table", bad: "a", good: "vd" + s, action: /CreateTable/ },
  { name: "IAM user", route: "iam/create-user", bad: "bad user name!", good: "vu" + s, action: /CreateUser/ },
];
const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
const results = [];
const check = (n, ok, x = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " :: " + String(x).replace(/\s+/g, " ").slice(0, 220)}`); };
let sent = [];
page.on("request", (r) => { if (r.method() !== "GET" && r.url().includes("/_wire")) sent.push(`${r.method()} ${r.url().replace(BASE, "")} ${r.postData() || ""}`.slice(0, 300)); });
const INP = "input:visible:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=number]):not([type=search]):not([placeholder*=earch])";
const CREATE = page.locator("button:not(.vyfb-send):not([role=dialog] *)", { hasText: /^\s*(create|add|launch)\b/i }).filter({ visible: true });
const errors = () => page.evaluate(() => [...document.querySelectorAll("[class*=awsui_error]")].filter((e) => e.offsetParent && e.innerText.trim()).map((e) => e.innerText.trim()).join(" | "));
for (const f of FORMS) {
  try {
    await page.goto(`${UI}#/${f.route}`); await page.reload(); await sleep(2200);
    const first = page.locator(INP).first(); await first.fill(f.bad); await first.blur(); await sleep(300);
    sent = []; await CREATE.last().click({ timeout: 8000 }); await sleep(1500);
    const err = await errors(), creates = sent.filter((x) => f.action.test(x));
    check(`${f.name}: invalid name "${f.bad}" shows a field-level error`, !!err, "no error element after Create");
    check(`${f.name}: invalid name sends NO create call to the wire`, creates.length === 0, creates.join(" ; "));
    check(`${f.name}: stays on the create form`, page.url().includes(f.route.split("/").pop()), page.url());
    await first.fill(f.good); await first.blur(); await sleep(300); sent = [];
    await CREATE.last().click({ timeout: 8000 }); await sleep(3000);
    check(`${f.name}: a valid name on the same form does create (control)`, sent.some((x) => f.action.test(x) || (f.method && x.startsWith(f.method) && x.includes(f.good))), sent.slice(0, 2).join(" ; ") + " | " + (await errors()));
  } catch (e) { check(`${f.name}: run`, false, String(e).split("\n")[0]); }
}
await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.length && results.every(Boolean) ? 0 : 1);
