/* Issue reporter (JS): scrubber parity with core/issue_report.py on the SAME fixtures, the
 * report/no-report rules, dedupe, and the two transports (offline appliance vs Nano portal).
 * Runs the real wasm/ and static/ copies in a bare VM (no DOM = the service-worker mode).
 *   node tests/conformance/test_issue_reporter_js.mjs */
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
let failed = false;
const check = (n, ok, x = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " " + x}`); failed ||= !ok; };

const a = readFileSync(join(ROOT, "static/issue-reporter.js"), "utf8");
const b = readFileSync(join(ROOT, "wasm/issue-reporter.js"), "utf8");
check("static/ and wasm/ copies are byte-identical", a === b);

function load(nano) {
  const calls = [];
  const ctx = { location: { pathname: "/console/aws" }, fetch: async (u, o) => { calls.push({ u, o }); return { ok: true, status: 200 }; }, console };
  if (nano) ctx.__NANO_BASE = "/nano";
  ctx.self = ctx;
  vm.createContext(ctx);
  vm.runInContext(a, ctx);
  return { R: ctx.VyomiIssueReporter, calls };
}
const fixtures = JSON.parse(readFileSync(join(HERE, "issue_report_fixtures.json"), "utf8")).cases;
const { R, calls } = load(false);
for (const c of fixtures) {
  const out = R.scrub(c.message, 1000).toLowerCase();
  const left = c.forbidden.filter((f) => out.includes(f.toLowerCase()));
  check(`scrub[${c.name}] removes sensitive values`, left.length === 0, JSON.stringify(left) + " in " + out);
}
check("shouldReport: 5xx yes", R.shouldReport({ status: 500 }) && R.shouldReport({ kind: "js-error" }) && R.shouldReport({ kind: "exception" }));
check("shouldReport: tier lock / 4xx / cancelled no",
  !R.shouldReport({ status: 403, code: "tier_locked" }) && !R.shouldReport({ status: 404 }) && !R.shouldReport({ status: 500, cancelled: true })
  && !R.shouldReport({ kind: "console-action", status: 422 }));
check("framesFromStack keeps file:function, max 5",
  JSON.stringify(R.framesFromStack("Error\n at doThing (https://x.io/app/console.js:10:5)\n at async go (https://x.io/a/b.js:2:1)")) === JSON.stringify(["console.js:doThing", "b.js:go"]));
check("python traceback frames parse",
  JSON.stringify(R.framesFromStack('Traceback\n  File "/lib/py/core/sqs_core.py", line 4, in send\n    x')) === JSON.stringify(["sqs_core.py:send"]));

await R.send({ kind: "js-error", message: "boom for user@x.com", stack: "at f (a.js:1:1)" });
check("offline: posts to the appliance intake, scrubbed", calls.length === 1 && calls[0].u === "/api/issue-reporting/report"
  && !calls[0].o.body.includes("user@x.com"), JSON.stringify(calls));
await R.send({ kind: "js-error", message: "boom for other@x.com", stack: "at f (a.js:1:1)" });
check("repeat of the same fingerprint is not re-sent", calls.length === 1);
await R.send({ kind: "console-action", status: 404, message: "nf" });
check("4xx console action not sent", calls.length === 1);

const n = load(true);
await n.R.send({ kind: "exception", service: "sqs", action: "SendMessage", status: 500, message: "py boom 'q-orders'" });
check("nano: posts to the portal endpoint (via the service worker)", n.calls.length === 1 && n.calls[0].u === "/api/issues/report", JSON.stringify(n.calls));
const body = JSON.parse(n.calls[0].o.body);
check("nano: scrubbed report envelope, queue name hashed", body.report.surface === "nano" && !JSON.stringify(body).includes("q-orders"), n.calls[0].o.body);
process.exit(failed ? 1 : 0);
