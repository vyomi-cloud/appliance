/* GCP validation + meaningful errors (nightly dimension 4), against the native REST wire (/_wire) the SDKs, gcloud and the v4 console share.
 * Invalid input must be refused with a real-Google-shaped 4xx: {"error":{"code":<http>,"message":"<sentence>","status":"INVALID_ARGUMENT|ALREADY_EXISTS|NOT_FOUND|..."}}
 * and never a 5xx, a stack trace, "Internal Server Error", "undefined", "[object Object]", "None" or an empty message.
 * Env: BASE (unset -> start consoles/dev_server.py on a free port), PROJECT (nano-project), OUT. A failure is a real finding, never weaken a case. */
import { spawn } from "node:child_process";
import net from "node:net";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const P = process.env.PROJECT || "nano-project";
const R = "us-central1", Z = "us-central1-a";
const OUT = process.env.OUT || resolve(HERE, "../hourly/out/gcp-validation.json");
let dev = null, BASE = process.env.BASE || "";
if (!BASE) {
  const port = await new Promise((res) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
  dev = spawn(process.env.PY || "python3", [resolve(HERE, "../../../consoles/dev_server.py"), "--port", String(port)], { stdio: "ignore", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  BASE = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/v4/gcp/")).ok) break; } catch (_) {} await new Promise((r) => setTimeout(r, 500)); }
}
const call = async (method, path, body) => {
  const r = await fetch(BASE + "/_wire" + path, { method, headers: { "content-type": "application/json" }, body: body === undefined || method === "GET" || method === "DELETE" ? undefined : JSON.stringify(body) });
  const text = await r.text(); let j = null; try { j = JSON.parse(text); } catch (_) {}
  return { status: r.status, json: j, text };
};
const BAD = /Traceback|Internal Server Error|undefined|\[object|NoneType|KeyError|TypeError|AttributeError|Something went wrong|\bNone\b/;
const results = [];
let seq = 0; const u = () => "rtv" + Date.now().toString(36).slice(-5) + (seq++);

// [label, setup?, method, path, body, expected statuses, expected google status (optional)]
const gA = u(), gB = u(), sA = u(), tA = u(), iA = u(), vA = u(), kA = u(), rA = u();
const CASES = [
  ["storage: invalid bucket name", null, "POST", `/storage/v1/b?project=${P}`, { name: "A" }, [400]],
  ["storage: duplicate bucket", ["POST", `/storage/v1/b?project=${P}`, { name: sA }], "POST", `/storage/v1/b?project=${P}`, { name: sA }, [409]],
  ["storage: missing bucket", null, "GET", `/storage/v1/b/${u()}`, undefined, [404]],
  ["pubsub: invalid topic id", null, "PUT", `/v1/projects/${P}/topics/1bad`, {}, [400]],
  ["pubsub: duplicate topic", ["PUT", `/v1/projects/${P}/topics/${tA}`, {}], "PUT", `/v1/projects/${P}/topics/${tA}`, {}, [409]],
  ["pubsub: missing topic", null, "GET", `/v1/projects/${P}/topics/${u()}`, undefined, [404]],
  ["pubsub: subscription on a missing topic", null, "PUT", `/v1/projects/${P}/subscriptions/${u()}`, { topic: `projects/${P}/topics/${u()}` }, [404]],
  ["iam: service account id too short", null, "POST", `/v1/projects/${P}/serviceAccounts`, { accountId: "a", serviceAccount: {} }, [400]],
  ["iam: duplicate service account", ["POST", `/v1/projects/${P}/serviceAccounts`, { accountId: iA, serviceAccount: {} }], "POST", `/v1/projects/${P}/serviceAccounts`, { accountId: iA, serviceAccount: {} }, [409]],
  ["iam: missing service account", null, "GET", `/v1/projects/${P}/serviceAccounts/${u()}@${P}.iam.gserviceaccount.com`, undefined, [404]],
  ["compute: instance without machineType", null, "POST", `/compute/v1/projects/${P}/zones/${Z}/instances`, { name: u() }, [400]],
  ["compute: invalid instance name", null, "POST", `/compute/v1/projects/${P}/zones/${Z}/instances`, { name: "BAD_NAME", machineType: `zones/${Z}/machineTypes/e2-micro` }, [400]],
  ["compute: missing instance", null, "GET", `/compute/v1/projects/${P}/zones/${Z}/instances/${u()}`, undefined, [404]],
  ["vpc: invalid network name", null, "POST", `/compute/v1/projects/${P}/global/networks`, { name: "BAD_NAME" }, [400]],
  ["vpc: duplicate network", ["POST", `/compute/v1/projects/${P}/global/networks`, { name: vA, autoCreateSubnetworks: false }], "POST", `/compute/v1/projects/${P}/global/networks`, { name: vA, autoCreateSubnetworks: false }, [409]],
  ["cloudsql: instance without a name", null, "POST", `/sql/v1beta4/projects/${P}/instances`, { region: R, databaseVersion: "POSTGRES_15", settings: { tier: "db-f1-micro" } }, [400]],
  ["cloudsql: unknown database version", null, "POST", `/sql/v1beta4/projects/${P}/instances`, { name: u(), region: R, databaseVersion: "NOPE_99", settings: { tier: "db-f1-micro" } }, [400]],
  ["cloudsql: missing instance", null, "GET", `/sql/v1beta4/projects/${P}/instances/${u()}`, undefined, [404]],
  ["firestore: invalid database id", null, "POST", `/v1/projects/${P}/databases?databaseId=BAD_ID`, { type: "FIRESTORE_NATIVE", locationId: R }, [400]],
  ["kms: invalid key ring id", null, "POST", `/v1/projects/${P}/locations/global/keyRings?keyRingId=bad%20ring`, {}, [400]],
  ["kms: missing key ring", null, "GET", `/v1/projects/${P}/locations/global/keyRings/${u()}`, undefined, [404]],
  ["secretmanager: invalid secret id", null, "POST", `/v1/projects/${P}/secrets?secretId=bad%20id`, { replication: { automatic: {} } }, [400]],
  ["secretmanager: duplicate secret", ["POST", `/v1/projects/${P}/secrets?secretId=${kA}`, { replication: { automatic: {} } }], "POST", `/v1/projects/${P}/secrets?secretId=${kA}`, { replication: { automatic: {} } }, [409]],
  ["redis: invalid tier", null, "POST", `/v1/projects/${P}/locations/${R}/instances?instanceId=${u()}`, { tier: "GIGANTIC", memorySizeGb: 1 }, [400]],
  ["redis: memory size 0", null, "POST", `/v1/projects/${P}/locations/${R}/instances?instanceId=${u()}`, { tier: "BASIC", memorySizeGb: 0 }, [400]],
  ["cloudscheduler: invalid cron schedule", null, "POST", `/v1/projects/${P}/locations/${R}/jobs`, { name: `projects/${P}/locations/${R}/jobs/${u()}`, schedule: "not a cron", timeZone: "UTC", httpTarget: { uri: "https://example.com/", httpMethod: "GET" } }, [400]],
  ["cloudscheduler: job without a target", null, "POST", `/v1/projects/${P}/locations/${R}/jobs`, { name: `projects/${P}/locations/${R}/jobs/${u()}`, schedule: "* * * * *", timeZone: "UTC" }, [400]],
  ["run: service without a container image", null, "POST", `/v2/projects/${P}/locations/${R}/services?serviceId=${u()}`, { template: { containers: [{}] } }, [400]],
  ["run: invalid service id", null, "POST", `/v2/projects/${P}/locations/${R}/services?serviceId=BAD_ID`, { template: { containers: [{ image: "us-docker.pkg.dev/cloudrun/container/hello" }] } }, [400]],
  ["artifactregistry: invalid repository id", null, "POST", `/v1/projects/${P}/locations/${R}/repositories?repositoryId=BAD_ID`, { format: "DOCKER" }, [400]],
  ["artifactregistry: repository without a format", null, "POST", `/v1/projects/${P}/locations/${R}/repositories?repositoryId=${rA}`, {}, [400]],
  ["eventarc: trigger without a type filter", null, "POST", `/v1/projects/${P}/locations/${R}/triggers?triggerId=${u()}`, { eventFilters: [], destination: { cloudRun: { service: "x", region: R } } }, [400]],
  ["eventarc: invalid trigger id", null, "POST", `/v1/projects/${P}/locations/${R}/triggers?triggerId=Bad_ID`, { eventFilters: [{ attribute: "type", value: "google.cloud.storage.object.v1.finalized" }] }, [400]],
  ["eventarc: missing trigger", null, "GET", `/v1/projects/${P}/locations/${R}/triggers/${u()}`, undefined, [404]],
  ["apigateway: invalid api id", null, "POST", `/v1/projects/${P}/locations/global/apis?apiId=Bad_ID`, {}, [400]],
  ["apigateway: duplicate api", ["POST", `/v1/projects/${P}/locations/global/apis?apiId=${gA}`, {}], "POST", `/v1/projects/${P}/locations/global/apis?apiId=${gA}`, {}, [409]],
  ["apigateway: config on a missing api", null, "POST", `/v1/projects/${P}/locations/global/apis/${u()}/configs?apiConfigId=c1x`, { openapiDocuments: [{ document: { contents: "e30=" } }] }, [404]],
  ["apigateway: config without a document", ["POST", `/v1/projects/${P}/locations/global/apis?apiId=${gB}`, {}], "POST", `/v1/projects/${P}/locations/global/apis/${gB}/configs?apiConfigId=c1x`, {}, [400]],
  ["apigateway: security requirement on an undefined scheme", null, "POST", `/v1/projects/${P}/locations/global/apis/${gB}/configs?apiConfigId=c2x`, { openapiDocuments: [{ document: { path: "o.json", contents: Buffer.from(JSON.stringify({ swagger: "2.0", info: { title: "t", version: "1" }, security: [{ ghost: [] }], paths: { "/a": { get: { operationId: "a", "x-google-backend": { address: "https://example.com" } } } } })).toString("base64") } }] }, [400]],
  ["apigateway: quota limit on an undefined metric", null, "POST", `/v1/projects/${P}/locations/global/apis/${gB}/configs?apiConfigId=c3x`, { openapiDocuments: [{ document: { path: "o.json", contents: Buffer.from(JSON.stringify({ swagger: "2.0", info: { title: "t", version: "1" }, "x-google-management": { metrics: [], quota: { limits: [{ name: "l", metric: "ghost", unit: "1/min/{project}", values: { STANDARD: 1 } }] } }, paths: { "/a": { get: { operationId: "a", "x-google-backend": { address: "https://example.com" } } } } })).toString("base64") } }] }, [400]],
  ["apigateway: gateway pointing at a missing config", null, "POST", `/v1/projects/${P}/locations/${R}/gateways?gatewayId=${u()}`, { apiConfig: `projects/${P}/locations/global/apis/${gB}/configs/nope` }, [404]],
];

for (const [label, setup, method, path, body, expect] of CASES) {
  if (setup) await call(...setup);
  const r = await call(method, path, body);
  const e = r.json && r.json.error;
  const probs = [];
  if (!expect.includes(r.status)) probs.push(`HTTP ${r.status}, wanted ${expect.join("/")}`);
  if (r.status >= 500) probs.push("server error (5xx)");
  if (!e) probs.push("body is not a Google error object");
  else {
    if (e.code !== r.status) probs.push(`error.code ${e.code} != HTTP ${r.status}`);
    if (!e.message || String(e.message).trim().length < 8) probs.push("empty/too short error.message");
    // Google API errors carry a gRPC status name; the Cloud Storage JSON API instead carries errors[].reason (no "status").
    const gcsStyle = Array.isArray(e.errors) && e.errors[0] && e.errors[0].reason;
    if (!gcsStyle && (!e.status || !/^[A-Z_]+$/.test(String(e.status)))) probs.push(`error.status "${e.status}" is not a gRPC status name`);
    if (BAD.test(String(e.message))) probs.push(`unfriendly message: ${String(e.message).slice(0, 120)}`);
  }
  if (BAD.test(r.text) && !BAD.test(String(e && e.message))) probs.push("body contains a raw stack/placeholder token");
  const ok = probs.length === 0;
  console.log(`[${ok ? "PASS" : "FAIL"}] ${label}${ok ? "" : " :: " + probs.join("; ") + " :: " + r.text.slice(0, 160).replace(/\s+/g, " ")}`);
  results.push({ step: label, ok, detail: ok ? "" : probs.join("; ") + " :: " + r.text.slice(0, 200) });
}
if (dev) dev.kill();
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ cloud: "gcp", dimension: "validation", project: P, results }, null, 1));
const pass = results.filter((r) => r.ok).length;
console.log(`RESULT ${pass} passed, ${results.length - pass} failed`);
process.exit(pass === results.length ? 0 : 1);
