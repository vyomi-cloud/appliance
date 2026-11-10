/* The REAL JavaScript @azure/service-bus SDK (AMQP 1.0 via rhea, unchanged) against the simulator's Service Bus
 * AMQP data plane. Driven by tests/conformance/test_azure_servicebus_amqp_js_sdk.py (starts the broker, supplies the
 * port and the entity-creation REST hook through a tiny control socket is NOT needed: entities are created by the
 * python side before this runs, named in argv[3] as JSON).
 *
 *   node servicebus_amqp_js_sdk.cjs <connection-string> <entities-json> [ws-url]
 * Prints one "ok <name>" / "FAIL <name>: <why>" per check; exit code 1 when anything failed.
 */
const { ServiceBusClient } = require("@azure/service-bus");
const assert = require("assert");

const [, , CS, ENT_JSON, WS_URL] = process.argv;
const E = JSON.parse(ENT_JSON);   // {queue, dlqQueue, sessionQueue, topic, subAll, subSql, subCorr, subNone, maxDeliveryQueue}
let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const body = (m) => (Buffer.isBuffer(m.body) ? m.body.toString() : typeof m.body === "string" ? m.body : JSON.stringify(m.body));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function client() {
  if (WS_URL) {
    const WebSocket = require("ws");
    return new ServiceBusClient(CS, {
      webSocketOptions: {
        // route the SDK's wss://<host>/$servicebus/websocket to the simulator's plain ws endpoint
        webSocket: class extends WebSocket { constructor(url, protocols, opts) { super(WS_URL, protocols, opts); } },
      },
    });
  }
  return new ServiceBusClient(CS);
}

test("send + receive peekLock + complete, properties round-trip", async (c) => {
  const s = c.createSender(E.queue);
  await s.sendMessages({ body: "hello-js", messageId: "js-1", subject: "subj", contentType: "text/plain", correlationId: "corr",
    applicationProperties: { n: 5, s: "x", b: true }, partitionKey: undefined });
  await s.close();
  const r = c.createReceiver(E.queue);
  const [m] = await r.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  assert.ok(m, "no message");
  assert.strictEqual(m.body, "hello-js");
  assert.strictEqual(m.messageId, "js-1");
  assert.strictEqual(m.subject, "subj");
  assert.strictEqual(m.contentType, "text/plain");
  assert.strictEqual(m.correlationId, "corr");
  assert.deepStrictEqual({ ...m.applicationProperties }, { n: 5, s: "x", b: true });
  assert.ok(m.sequenceNumber, "sequence number");
  assert.ok(m.lockedUntilUtc instanceof Date, "locked until");
  assert.ok(m.enqueuedTimeUtc instanceof Date, "enqueued time");
  assert.strictEqual(m.deliveryCount, 0);
  await r.completeMessage(m);
  assert.deepStrictEqual(await r.receiveMessages(1, { maxWaitTimeInMs: 1000 }), []);
  await r.close();
});

test("abandon redelivers with deliveryCount, then complete", async (c) => {
  const s = c.createSender(E.queue); await s.sendMessages({ body: "abn" }); await s.close();
  const r = c.createReceiver(E.queue);
  const [m] = await r.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  await r.abandonMessage(m);
  const [m2] = await r.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  assert.strictEqual(m2.deliveryCount, 1);
  assert.strictEqual(m2.sequenceNumber.toString(), m.sequenceNumber.toString());
  await r.completeMessage(m2); await r.close();
});

test("dead-letter with reason, read from the DLQ sub-queue", async (c) => {
  const s = c.createSender(E.dlqQueue); await s.sendMessages({ body: "bad", applicationProperties: { k: "v" } }); await s.close();
  const r = c.createReceiver(E.dlqQueue);
  const [m] = await r.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  await r.deadLetterMessage(m, { deadLetterReason: "Because", deadLetterErrorDescription: "details" });
  await r.close();
  const d = c.createReceiver(E.dlqQueue, { subQueueType: "deadLetter" });
  const [dm] = await d.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  assert.ok(dm, "dlq message");
  assert.strictEqual(dm.body, "bad");
  assert.strictEqual(dm.deadLetterReason, "Because");
  assert.strictEqual(dm.deadLetterErrorDescription, "details");
  await d.completeMessage(dm); await d.close();
});

test("defer + receiveDeferredMessages", async (c) => {
  const s = c.createSender(E.queue); await s.sendMessages({ body: "defer-me" }); await s.close();
  const r = c.createReceiver(E.queue);
  const [m] = await r.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  assert.strictEqual(m.body, "defer-me");
  await r.deferMessage(m);
  assert.deepStrictEqual(await r.receiveMessages(1, { maxWaitTimeInMs: 1000 }), []);
  const got = await r.receiveDeferredMessages(m.sequenceNumber);
  assert.strictEqual(got.length, 1); assert.strictEqual(got[0].body, "defer-me");
  await r.completeMessage(got[0]); await r.close();
});

test("receiveAndDelete + peekMessages + batch send", async (c) => {
  const s = c.createSender(E.queue);
  const batch = await s.createMessageBatch();
  for (let i = 0; i < 4; i++) assert.ok(batch.tryAddMessage({ body: "b" + i }));
  await s.sendMessages(batch); await s.close();
  const p = c.createReceiver(E.queue);
  const peeked = await p.peekMessages(10);
  assert.deepStrictEqual(peeked.map((x) => x.body), ["b0", "b1", "b2", "b3"]);
  await p.close();
  const r = c.createReceiver(E.queue, { receiveMode: "receiveAndDelete" });
  const got = await r.receiveMessages(10, { maxWaitTimeInMs: 3000 });
  assert.deepStrictEqual(got.map((x) => x.body), ["b0", "b1", "b2", "b3"]);
  await r.close();
});

test("scheduleMessages + cancelScheduledMessages", async (c) => {
  const s = c.createSender(E.queue);
  const seqs = await s.scheduleMessages({ body: "later" }, new Date(Date.now() + 2000));
  const never = await s.scheduleMessages({ body: "never" }, new Date(Date.now() + 60000));
  assert.strictEqual(seqs.length, 1);
  await s.cancelScheduledMessages(never);
  await s.close();
  const r = c.createReceiver(E.queue, { receiveMode: "receiveAndDelete" });
  assert.deepStrictEqual(await r.receiveMessages(1, { maxWaitTimeInMs: 800 }), []);
  await sleep(1800);
  const got = await r.receiveMessages(5, { maxWaitTimeInMs: 3000 });
  assert.deepStrictEqual(got.map((x) => x.body), ["later"]);
  await r.close();
});

test("renewMessageLock", async (c) => {
  const s = c.createSender(E.queue); await s.sendMessages({ body: "renew" }); await s.close();
  const r = c.createReceiver(E.queue);
  const [m] = await r.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  const t0 = m.lockedUntilUtc.getTime();
  const t1 = await r.renewMessageLock(m);
  assert.ok(t1.getTime() >= t0);
  await r.completeMessage(m); await r.close();
});

test("maxDeliveryCount dead-letters", async (c) => {
  const s = c.createSender(E.maxDeliveryQueue); await s.sendMessages({ body: "loop" }); await s.close();
  const r = c.createReceiver(E.maxDeliveryQueue);
  for (let i = 0; i < 2; i++) { const [m] = await r.receiveMessages(1, { maxWaitTimeInMs: 3000 }); await r.abandonMessage(m); }
  assert.deepStrictEqual(await r.receiveMessages(1, { maxWaitTimeInMs: 800 }), []);
  await r.close();
  const d = c.createReceiver(E.maxDeliveryQueue, { subQueueType: "deadLetter" });
  const [dm] = await d.receiveMessages(1, { maxWaitTimeInMs: 3000 });
  assert.strictEqual(dm.deadLetterReason, "MaxDeliveryCountExceeded");
  await d.completeMessage(dm); await d.close();
});

test("sessions: accept, state, ordering", async (c) => {
  const s = c.createSender(E.sessionQueue);
  await s.sendMessages([{ body: "a1", sessionId: "A" }, { body: "b1", sessionId: "B" }, { body: "a2", sessionId: "A" }]);
  await s.close();
  const r = await c.acceptSession(E.sessionQueue, "A");
  assert.strictEqual(r.sessionId, "A");
  await r.setSessionState("st-A");
  assert.strictEqual(await r.getSessionState(), "st-A");
  const got = await r.receiveMessages(5, { maxWaitTimeInMs: 3000 });
  assert.deepStrictEqual(got.map((x) => x.body), ["a1", "a2"]);
  for (const m of got) await r.completeMessage(m);
  await r.close();
  const nx = await c.acceptNextSession(E.sessionQueue);
  assert.strictEqual(nx.sessionId, "B");
  const gb = await nx.receiveMessages(5, { maxWaitTimeInMs: 3000 });
  assert.deepStrictEqual(gb.map((x) => x.body), ["b1"]);
  await nx.completeMessage(gb[0]); await nx.close();
});

test("subscribe (streaming) receives and settles", async (c) => {
  const s = c.createSender(E.queue); await s.sendMessages([{ body: "st1" }, { body: "st2" }]); await s.close();
  const r = c.createReceiver(E.queue);
  const seen = [];
  await new Promise((resolve, reject) => {
    const sub = r.subscribe({
      processMessage: async (m) => { seen.push(m.body); if (seen.length === 2) { await sleep(50); await sub.close(); resolve(); } },
      processError: async (e) => { if (e.error && !/closed/i.test(String(e.error))) reject(e.error); },
    }, { autoCompleteMessages: true });
    setTimeout(() => reject(new Error("subscribe timeout")), 8000);
  });
  assert.deepStrictEqual(seen, ["st1", "st2"]);
  await r.close();
  const chk = c.createReceiver(E.queue); assert.deepStrictEqual(await chk.receiveMessages(1, { maxWaitTimeInMs: 800 }), []); await chk.close();
});

test("topic fan-out with subscription rules (SQL, correlation, false) via ruleManager", async (c) => {
  const T = E.topic;
  const mgrSql = c.createRuleManager(T, E.subSql);
  await mgrSql.deleteRule("$Default");
  await mgrSql.createRule("red-only", { sqlExpression: "color = 'red' AND qty > 5" });
  const mgrCorr = c.createRuleManager(T, E.subCorr);
  await mgrCorr.deleteRule("$Default");
  await mgrCorr.createRule("subj", { subject: "invoice", applicationProperties: { region: "eu" } });
  const mgrNone = c.createRuleManager(T, E.subNone);
  await mgrNone.deleteRule("$Default");
  await mgrNone.createRule("never", { sqlExpression: "1=0" });
  const rules = await mgrSql.getRules();
  assert.deepStrictEqual(rules.map((x) => x.name), ["red-only"]);
  assert.strictEqual(rules[0].filter.sqlExpression, "color = 'red' AND qty > 5");
  const corr = await mgrCorr.getRules();
  assert.strictEqual(corr[0].filter.subject, "invoice");
  assert.strictEqual(corr[0].filter.applicationProperties.region, "eu");
  await assert.rejects(() => mgrSql.createRule("bad", { sqlExpression: "color === " }));

  const s = c.createSender(T);
  await s.sendMessages([
    { body: "m1", subject: "invoice", applicationProperties: { color: "red", qty: 10, region: "eu" } },
    { body: "m2", subject: "order", applicationProperties: { color: "blue", qty: 10, region: "us" } },
    { body: "m3", subject: "invoice", applicationProperties: { color: "red", qty: 1, region: "eu" } },
  ]);
  await s.close();
  const take = async (sub) => { const r = c.createReceiver(T, sub, { receiveMode: "receiveAndDelete" }); const g = await r.receiveMessages(10, { maxWaitTimeInMs: 2000 }); await r.close(); return g.map((x) => x.body).sort(); };
  assert.deepStrictEqual(await take(E.subAll), ["m1", "m2", "m3"]);
  assert.deepStrictEqual(await take(E.subSql), ["m1"]);
  assert.deepStrictEqual(await take(E.subCorr), ["m1", "m3"]);
  assert.deepStrictEqual(await take(E.subNone), []);
  const mgr = c.createRuleManager(T, E.subCorr);
  await mgr.deleteRule("subj");
  assert.deepStrictEqual(await mgr.getRules(), []);
});

test("missing entity is a MessagingEntityNotFound", async (c) => {
  const s = c.createSender("no-such-queue-js");
  await assert.rejects(() => s.sendMessages({ body: "x" }), (e) => /not.?found|MessagingEntityNotFound/i.test(String(e.code) + e.message));
  await s.close();
});

(async () => {
  for (const [name, fn] of tests) {
    const c = client();
    try { await fn(c); console.log("ok " + name); }
    catch (e) { failed++; console.log("FAIL " + name + ": " + ((e && e.stack) || e).toString().split("\n").slice(0, 4).join(" | ")); }
    finally { try { await c.close(); } catch (_) {} }
  }
  process.exit(failed ? 1 : 0);
})();
