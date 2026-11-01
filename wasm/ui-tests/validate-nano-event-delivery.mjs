/* Nano: events are DELIVERED and uploaded function code RUNS, in the in-browser stores.
 *  - Lambda created with a real zip archive runs the uploaded handler (Pyodide sandbox), error -> functionError
 *  - EventBridge rule with an SQS target AND a Lambda target: only events matching the pattern language
 *    (numeric / prefix / anything-but / exists) land in the queue and invoke the function
 *  - Step Functions Lambda Task completes with that Lambda's output
 * Run: NODE_PATH=.../portal-OLD/node_modules NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-nano-event-delivery.mjs */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
try {
  await bootConsole(page, base, "/aws-console.html");
  await sleep(2000);
  const api = (m, p, b) => page.evaluate(async ([m, p, b]) => {
    const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
    let j = null; try { j = await r.json(); } catch (_) {}
    return { status: r.status, j };
  }, [m, p, b]);

  const src = "def handler(event, context):\n    print('hi')\n    if event.get('boom'):\n        raise ValueError('boom')\n    return {'echo': event, 'fn': context.function_name}\n";
  let r = await api("POST", "/api/lambda/functions", { name: "evfn", code: src, handler: "index.handler" });
  check("create Lambda", r.j && r.j.ok, JSON.stringify(r.j));
  r = await api("POST", "/api/lambda/functions/evfn/invoke", { payload: { n: 3 } });
  check("uploaded handler runs on invoke with real context",
    r.j && r.j.result && r.j.result.fn === "evfn" && r.j.result.echo.n === 3, JSON.stringify(r.j));
  r = await api("POST", "/api/lambda/functions/evfn/invoke", { payload: { boom: 1 } });
  check("handler exception -> functionError", r.j && r.j.functionError === "ValueError", JSON.stringify(r.j));

  r = await api("POST", "/api/sqs/queues", { name: "ev-q", queue_name: "ev-q" });
  check("create queue", r.status < 300, JSON.stringify(r.j));
  const pattern = { source: ["nano.app"], detail: { price: [{ numeric: [">", 10] }], kind: [{ prefix: "ord" }],
                                                   env: [{ "anything-but": "test" }], ok: [{ exists: true }] } };
  r = await api("POST", "/api/eventbridge/rules", { name: "ev-rule", pattern, targetQueue: "ev-q", targetLambda: "evfn" });
  check("create rule with SQS + Lambda targets", r.j && r.j.ok, JSON.stringify(r.j));
  const put = (detail) => api("POST", "/api/eventbridge/put-event", { source: "nano.app", detailType: "t", detail });
  await put({ price: 5, kind: "order", env: "prod", ok: 1 });
  await put({ price: 50, kind: "order", env: "test", ok: 1 });
  await put({ price: 50, kind: "xorder", env: "prod", ok: 1 });
  await put({ price: 50, kind: "order", env: "prod" });
  await put({ price: 50, kind: "order-1", env: "prod", ok: 1 });
  r = await api("POST", "/api/sqs/queues/ev-q/receive", { max: 10, maxMessages: 10 });
  const msgs = (r.j && (r.j.messages || r.j.Messages)) || [];
  check("only the matching event is delivered to the SQS target", msgs.length === 1 && JSON.parse(msgs[0].Body).detail.price === 50, JSON.stringify(r.j).slice(0, 300));
  r = await api("GET", "/api/lambda/functions/evfn");
  check("Lambda target invoked exactly once by the matching event (2 manual + 1 event)",
    r.j && r.j.invocation_count === 3, JSON.stringify(r.j));

  const def = JSON.stringify({ StartAt: "L", States: { L: { Type: "Task", Resource: "arn:aws:lambda:us-east-1:123456789012:function:evfn", End: true } } });
  r = await api("POST", "/api/stepfunctions/machines", { name: "ev-sm", definition: def });
  check("create state machine", r.status < 300, JSON.stringify(r.j));
  r = await api("POST", "/api/stepfunctions/machines/ev-sm/executions", { input: JSON.stringify({ n: 9 }) });
  await sleep(1500);
  r = await api("GET", "/api/stepfunctions/machines/ev-sm/executions");
  const ex = ((r.j && (r.j.items || r.j.executions)) || [])[0] || {};
  check("Step Functions Lambda Task SUCCEEDED", /SUCCEEDED/.test(JSON.stringify(ex)) && /echo/.test(JSON.stringify(ex)), JSON.stringify(ex).slice(0, 300));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.ok ? "" : r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
