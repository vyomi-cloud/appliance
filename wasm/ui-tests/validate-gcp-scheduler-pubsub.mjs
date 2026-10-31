/* #149 (Nano): a Cloud Scheduler pubsubTarget job, force-run, must deliver its data +
 * attributes to a subscription on the topic (pull returns them). Same flow as
 * tests/cli/gcp-scheduler-pubsub-cli-smoke.sh against the in-browser Nano core.
 *   NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-gcp-scheduler-pubsub.mjs */
import { startServer, bootConsole, chromium } from "./lib.mjs";

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); };
const s = await startServer();
try {
  await bootConsole(page, s.base, "/gcp-console.html");
  const tag = Date.now().toString(36);
  const r = await page.evaluate(async (tag) => {
    const base = `/api/gcp/pubsub/v1/projects/${PROJECT}`;
    const j = (b, method = "POST") => ({ method, headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    const out = {};
    out.topic = (await fetch(`${base}/topics`, j({ name: "t" + tag }))).status;
    out.sub = (await fetch(`${base}/subscriptions/s${tag}`, j({ topic: `projects/${PROJECT}/topics/t${tag}` }, "PUT"))).status;
    const mk = await fetch(`/api/gcp/cloudscheduler/jobs`, j({
      name: "j" + tag, region: "us-central1", targetType: "Pub/Sub", schedule: "0 0 1 1 *", topic: `projects/${PROJECT}/topics/t${tag}`,
      message: "hello-sched" }));
    out.job = mk.status; out.jobBody = (await mk.text()).slice(0, 200);
    out.run = (await fetch(`/api/gcp/sub/cloudscheduler/run/j${tag}`, j({}))).status;
    const pull = await fetch(`/api/gcp/sub/pubsub/pullMessages/t${tag}`, j({ subscription: "s" + tag, maxMessages: 5, ack: true }));
    out.pull = pull.status;
    const body = pull.ok ? await pull.json() : {};
    out.msgs = body.items || body.messages || [];
    return out;
  }, tag);
  check("topic + subscription created", r.topic < 300 && r.sub < 300, JSON.stringify(r));
  check("pubsub job created", r.job < 300, JSON.stringify(r));
  check("job run succeeds", r.run < 300, JSON.stringify(r));
  check("pull returns the job's message", r.msgs.length === 1, JSON.stringify(r));
  const m = r.msgs[0] || {};
  check("pulled message has the job's data", JSON.stringify(m).includes("hello-sched"), JSON.stringify(m));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); s.server.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
