/* v4.0.0 AWS console Monitoring tab draws MEASURED data (retarget of the legacy validate-aws-metrics.mjs, which counted /api/metrics/series).
 * SQS queue Monitoring (consoles/src/aws/services/sqs/QueueMetrics.jsx) = CloudWatch GetMetricStatistics over /_wire:
 *   - N messages sent to queue A  -> the UI's NumberOfMessagesSent latest datapoint equals the SDK's (and is > 0)
 *   - M empty receives on queue B -> NumberOfEmptyReceives is measured, and queue B's NumberOfMessagesSent shows "no data"
 *   - an idle queue C             -> every metric reads "no data" and its graphs render the empty state (never a synthetic line)
 *   - queue A and queue B differ (series are per resource)
 * Env: BASE, UI_PATH, WIRE_PATH, PY (python with boto3), PW_CHANNEL. */
import { chromium, sleep } from "./lib.mjs";
import { execFileSync } from "node:child_process";
const BASE = process.env.BASE || "http://127.0.0.1:8741";
const UI = BASE + (process.env.UI_PATH || "/v4/aws/"), WIRE = BASE + (process.env.WIRE_PATH || "/_wire");
const stamp = Date.now().toString(36).slice(-6), A = "mta" + stamp, B = "mtb" + stamp, C = "mtc" + stamp, N = 3, M = 2;
const PY = `
import boto3, datetime, json, sys
KW = dict(endpoint_url=sys.argv[1], region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t")
sqs = boto3.client("sqs", **KW); cw = boto3.client("cloudwatch", **KW)
A, B, C, N, M = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6])
ua, ub, uc = (sqs.create_queue(QueueName=q)["QueueUrl"] for q in (A, B, C))
for i in range(N): sqs.send_message(QueueUrl=ua, MessageBody="m%d" % i)
for i in range(M): sqs.receive_message(QueueUrl=ub, WaitTimeSeconds=0)
now = datetime.datetime.now(datetime.timezone.utc)
def last(q, m, st):
    r = cw.get_metric_statistics(Namespace="AWS/SQS", MetricName=m, Dimensions=[{"Name": "QueueName", "Value": q}], StartTime=now - datetime.timedelta(hours=3), EndTime=now + datetime.timedelta(minutes=1), Period=60, Statistics=[st])
    p = sorted(r["Datapoints"], key=lambda x: x["Timestamp"]); return p[-1][st] if p else None
print(json.dumps({"sentA": last(A, "NumberOfMessagesSent", "Sum"), "emptyB": last(B, "NumberOfEmptyReceives", "Sum"), "sentB": last(B, "NumberOfMessagesSent", "Sum"), "sentC": last(C, "NumberOfMessagesSent", "Sum")}))
`;
const sdk = JSON.parse(execFileSync(process.env.PY || "python3", ["-c", PY, WIRE, A, B, C, String(N), String(M)], { encoding: "utf8" }).trim().split("\n").pop());
const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
const results = [];
const check = (name, ok, extra = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + String(extra).slice(0, 220)}`); };
const latest = async (q, metric) => {
  await page.goto(`${UI}#/sqs/queues/${q}`); await page.reload(); await sleep(2500);
  await page.locator("[role=tab]", { hasText: /^monitoring$/i }).first().click(); await sleep(3500);
  return page.locator(`[data-testid="sqs-metric-${metric}"]`).first().innerText({ timeout: 8000 });
};
try {
  check(`SDK side: ${N} sends measured on queue A, ${M} empty receives on queue B, queue C idle`, sdk.sentA === N && sdk.emptyB === M && sdk.sentB === null && sdk.sentC === null, JSON.stringify(sdk));
  const a = await latest(A, "NumberOfMessagesSent");
  check(`queue A Monitoring: NumberOfMessagesSent latest = ${N} (the measured count)`, Number(a) === N, a);
  const aGraph = await page.evaluate(() => document.querySelectorAll("svg[aria-label='Metric graph']").length);
  check("queue A Monitoring: a real graph is drawn for the measured series", aGraph >= 1, String(aGraph));
  const bE = await latest(B, "NumberOfEmptyReceives");
  check(`queue B Monitoring: NumberOfEmptyReceives latest = ${M}`, Number(bE) === M, bE);
  const bS = await latest(B, "NumberOfMessagesSent");
  check("queue B (different resource) shows no sends: series are per resource", /no data/i.test(bS), bS);
  const cS = await latest(C, "NumberOfMessagesSent");
  const cNoData = await page.evaluate(() => [...document.querySelectorAll("[data-testid^='sqs-metric-']")].filter((e) => /no data/i.test(e.innerText)).length);
  const cEmpty = await page.evaluate(() => document.body.innerText.split("No data points for this time range.").length - 1);
  check("idle queue C: every measured metric reads 'no data'", /no data/i.test(cS) && cNoData >= 5, `${cS} noData=${cNoData}`);
  check("idle queue C: every 'no data' metric renders the empty state and every other metric a real graph (never a synthetic line)", cEmpty === cNoData && cNoData + (await page.evaluate(() => document.querySelectorAll("svg[aria-label='Metric graph']").length)) === 8, `empty=${cEmpty} noData=${cNoData}`);
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.length && results.every(Boolean) ? 0 : 1);
