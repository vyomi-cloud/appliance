/* Nano /_wire must hand out simulator URLs (the local relay), never the real cloud host.
 * Regression for: SQS QueueUrl showed https://sqs.us-east-1.amazonaws.com/... in the in-browser Nano console
 * (the service worker sets no Host header, so core/public_origin was empty). Also checks the URL round-trips
 * (GetQueueAttributes + SendMessage by that URL), which is what the console does next. */
import { chromium, sleep, startServer } from "./lib.mjs";
const { server: srv, base: BASE } = await startServer();
const b = await chromium.launch(); const p = await b.newPage();
const first = p.waitForResponse((r) => r.url().includes("/_wire/") && r.status() < 500, { timeout: 120000 }).catch(() => null);
await p.goto(BASE + "/v4/aws/#/sqs/home", { waitUntil: "domcontentloaded", timeout: 120000 }); await first; await sleep(3000);
const call = (t, bd) => p.evaluate(async ([t, bd]) => { const r = await fetch("/_wire/", { method: "POST", headers: { "Content-Type": "application/x-amz-json-1.0", "X-Amz-Target": "AmazonSQS." + t, "Authorization": "AWS4-HMAC-SHA256 Credential=AKIAFAKE/20260101/us-east-1/sqs/aws4_request, SignedHeaders=host, Signature=x" }, body: JSON.stringify(bd) }); let j = null; try { j = await r.json(); } catch {} return { status: r.status, j }; }, [t, bd]);
let pass = 0, fail = 0; const ck = (n, ok, d = "") => { ok ? pass++ : fail++; console.log((ok ? "PASS " : "FAIL ") + n + (ok ? "" : "  " + d)); };
const q = "EndpointOriginQ" + Date.now() % 100000;
const c = await call("CreateQueue", { QueueName: q }); const url = c.j && c.j.QueueUrl || "";
ck("CreateQueue QueueUrl is not the real AWS host", c.status === 200 && url && !/amazonaws\.com/.test(url), url);
ck("QueueUrl points at the local relay", url.startsWith("http://127.0.0.1:8090/"), url);
const g = await call("GetQueueUrl", { QueueName: q }); ck("GetQueueUrl matches CreateQueue", g.j && g.j.QueueUrl === url, JSON.stringify(g.j));
const l = await call("ListQueues", {}); ck("ListQueues has the relay URL", (l.j?.QueueUrls || []).includes(url), JSON.stringify(l.j));
const a = await call("GetQueueAttributes", { QueueUrl: url, AttributeNames: ["All"] }); ck("GetQueueAttributes by that URL works", a.status === 200 && !!a.j?.Attributes?.QueueArn, JSON.stringify(a.j).slice(0, 160));
const s = await call("SendMessage", { QueueUrl: url, MessageBody: "hi" }); ck("SendMessage by that URL works", s.status === 200 && !!s.j?.MessageId, JSON.stringify(s.j).slice(0, 160));
console.log(`${pass} passed, ${fail} failed`); await b.close(); try { srv.close(); } catch {} process.exit(fail ? 1 : 0);
