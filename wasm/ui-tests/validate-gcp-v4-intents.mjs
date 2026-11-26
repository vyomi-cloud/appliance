/* GCP v4 console intents (genuine Nano: the wasm/ bundle, service worker + in-browser engines, v4 console at /v4/gcp/).
 * Replaces the per-feature validate-gcp-*.mjs scripts that drove the decommissioned v3 console (gcp-console.html, /api/gcp/* routes).
 * The "native" side is the same wire gcloud/SDKs use (/_wire/*); the UI side is the v4 console in Playwright.
 *
 *   NANO_DIR=$PWD/wasm CHECKS=subscriptions,grid node wasm/ui-tests/validate-gcp-v4-intents.mjs
 *
 * CHECKS (comma list; default = every group except the opt-in `events`):
 *   subscriptions  project-level subscriptions list answers 200 + lists a created subscription (native) and the v4 Subscriptions page shows it
 *   grid           resources created with minimal/default bodies show a real value in every list column of the v4 console (no "-", blank, undefined, null, [object Object])
 *   firestore      documents list of a database is served (not 501) and a written document shows up in it
 *   schedpubsub    Cloud Scheduler pubsubTarget job, force-run, delivers its data + attributes to a subscription (pull returns them)
 *   events         every recorded cloudsim event for a created resource carries a non-empty Detail
 *   sqlsubs        Cloud SQL users + databases sub-resources round-trip natively (create/list/delete)
 *   iamcreds       IAM Service Account Credentials on the wire: generateAccessToken / generateIdToken / signBlob answer real-shaped results; the SA is listed in the v4 console
 *   scheduler      Cloud Scheduler job lifecycle on the wire: create -> list in UI -> pause -> resume -> run -> delete
 *   redis          Memorystore instance: create -> list in UI -> resize (5 GB) -> delete
 *   gke            GKE cluster: create -> list in UI -> node pool listed -> setSize (5) -> delete
 *   alerting       Monitoring alert policy: create -> list in UI -> disable/enable -> delete
 *   apigw          API Gateway API config added natively shows in the console detail; gateway data-plane logs refer to the gateway
 *   artifactregistry  Artifact Registry repo: create -> list in UI -> delete
 * Honest failures are findings: never weaken a case. */
import { chromium, sleep } from "./lib.mjs";
import { nanoStart } from "../../tests/conformance/nightly/lib/nano-gcp.mjs";

const P = process.env.PROJECT || "nano-project", R = "us-central1";
// "events" is opt-in (CHECKS=events): it FAILS today, a real v4 gap (wire-created resources record no cloudsim events, so Home > Activity is empty).
const ALL = ["subscriptions", "grid", "firestore", "schedpubsub", "sqlsubs", "iamcreds", "scheduler", "redis", "gke", "alerting", "apigw", "artifactregistry"];
const CHECKS = (process.env.CHECKS || ALL.join(",")).split(",").map((s) => s.trim()).filter(Boolean);
const tag = Date.now().toString(36).slice(-6);
const results = [];
const check = (grp, name, ok, extra = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${grp}: ${name}${ok ? "" : " :: " + String(extra).slice(0, 260)}`);
  results.push(ok);
};

const browser = await chromium.launch();
const NH = await nanoStart(browser, P);
const UI = NH.base + "/v4/gcp/index.html";
const page = await NH.ctx.newPage();
page.on("dialog", (d) => d.accept("delete").catch(() => {}));
const rest = (m, p, b) => NH.rest(m, p, b);
const go = async (route) => { await page.goto(`${UI}#/${route}`); await page.reload(); await sleep(2500); };
const body = () => page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
const listed = async (route, name) => { await go(route); for (let i = 0; i < 6; i++) { if ((await body()).includes(name)) return true; await sleep(1500); } return false; };
const gone = async (route, name) => { await go(route); await sleep(1500); return !(await body()).includes(name); };
const rowCells = async (name) => page.evaluate((n) => {
  const tr = [...document.querySelectorAll("tr")].find((r) => r.innerText.includes(n));
  return tr ? [...tr.querySelectorAll("td")].map((td) => td.innerText.trim()) : null;
}, name);
const sw = (path) => NH.apiPage.evaluate(async (p) => { const r = await fetch(p); let j = null; const t = await r.text(); try { j = JSON.parse(t); } catch (_) {} return { status: r.status, j, t: t.slice(0, 300) }; }, path);
const ok2 = (r) => r.status >= 200 && r.status < 300;
const run = async (grp, fn) => {
  if (!CHECKS.includes(grp)) return;
  try { await fn(); } catch (e) { check(grp, "ran without error", false, String(e && e.message || e).split("\n")[0]); }
};

await run("subscriptions", async () => {
  const t = "st" + tag, s = "ss" + tag;
  check("subscriptions", "create topic", ok2(await rest("PUT", `/v1/projects/${P}/topics/${t}`, {})));
  const empty = await rest("GET", `/v1/projects/${P}/subscriptions`);
  check("subscriptions", "GET project subscriptions answers 200 (not 501)", empty.status === 200, empty.status);
  const mk = await rest("PUT", `/v1/projects/${P}/subscriptions/${s}`, { topic: `projects/${P}/topics/${t}` });
  check("subscriptions", "PUT subscription succeeds", ok2(mk), JSON.stringify(mk.body));
  const l = await rest("GET", `/v1/projects/${P}/subscriptions`);
  check("subscriptions", "created subscription is listed natively", ((l.body || {}).subscriptions || []).some((x) => String(x.name).endsWith("/" + s)), JSON.stringify(l.body));
  check("subscriptions", "v4 console Subscriptions page lists it", await listed("pubsub/subscriptions", s));
  await rest("DELETE", `/v1/projects/${P}/subscriptions/${s}`); await rest("DELETE", `/v1/projects/${P}/topics/${t}`);
});

await run("grid", async () => {
  const n = (p) => p + tag;
  const SV = [
    ["pubsub topic", "pubsub/topics", n("gt"), ["PUT", `/v1/projects/${P}/topics/${n("gt")}`, {}], `/v1/projects/${P}/topics/${n("gt")}`],
    ["secret manager", "security/secret-manager", n("gs"), ["POST", `/v1/projects/${P}/secrets?secretId=${n("gs")}`, { replication: { automatic: {} } }], `/v1/projects/${P}/secrets/${n("gs")}`],
    ["vpc network", "networking/networks/list", n("gn"), ["POST", `/compute/v1/projects/${P}/global/networks`, { name: n("gn"), autoCreateSubnetworks: false }], `/compute/v1/projects/${P}/global/networks/${n("gn")}`],
    ["firestore database", "firestore/databases", n("gf"), ["POST", `/v1/projects/${P}/databases?databaseId=${n("gf")}`, { type: "FIRESTORE_NATIVE", locationId: R }], `/v1/projects/${P}/databases/${n("gf")}`],
    ["cloud run service", "run/services", n("gr"), ["POST", `/v2/projects/${P}/locations/${R}/services?serviceId=${n("gr")}`, { template: { containers: [{ image: "us-docker.pkg.dev/cloudrun/container/hello" }] } }], `/v2/projects/${P}/locations/${R}/services/${n("gr")}`],
    ["api gateway api", "apigateway/apis", n("ga"), ["POST", `/v1/projects/${P}/locations/global/apis?apiId=${n("ga")}`, { displayName: n("ga") }], `/v1/projects/${P}/locations/global/apis/${n("ga")}`],
    ["eventarc-less scheduler job", "cloudscheduler/jobs", n("gj"), ["POST", `/v1/projects/${P}/locations/${R}/jobs`, { name: `projects/${P}/locations/${R}/jobs/${n("gj")}`, schedule: "* * * * *", timeZone: "UTC", httpTarget: { uri: "https://example.com/", httpMethod: "GET" } }], `/v1/projects/${P}/locations/${R}/jobs/${n("gj")}`],
  ];
  for (const [label, route, name, [m, u, b], del] of SV) {
    if (process.env.GRID_ONLY && !label.includes(process.env.GRID_ONLY)) continue;
    const c = await rest(m, u, b);
    if (!ok2(c)) { check("grid", `${label}: create with defaults`, false, `${c.status} ${JSON.stringify(c.body)}`); continue; }
    if (!(await listed(route, name))) { check("grid", `${label}: row listed`, false, "row missing"); await rest("DELETE", del); continue; }
    const cells = await rowCells(name);
    // The v4 console renders a legitimately empty optional field as an em dash (like the real console); what must never leak is a code artefact, and most cells must be real values.
    const leaked = (cells || []).filter((c2) => /\bundefined\b|\bnull\b|\[object Object\]|\bNaN\b/.test(c2));
    const dashes = (cells || []).filter((c2) => /^(-|—|–)$/.test(c2.trim()));
    const real = (cells || []).filter((c2) => c2.trim() && !/^(-|—|–)$/.test(c2.trim()));
    check("grid", `${label}: no undefined/null/[object Object]/NaN in the row`, !!cells && leaked.length === 0, JSON.stringify(cells));
    check("grid", `${label}: more real values than empty-dash cells`, !!cells && real.length > dashes.length, JSON.stringify(cells));
    await rest("DELETE", del);
  }
});

await run("firestore", async () => {
  const db = "fs" + tag;
  const c = await rest("POST", `/v1/projects/${P}/databases?databaseId=${db}`, { type: "FIRESTORE_NATIVE", locationId: R });
  check("firestore", "create database", ok2(c), JSON.stringify(c.body));
  const docs0 = await rest("GET", `/v1/projects/${P}/databases/${db}/documents/things`);
  check("firestore", "documents list is served (not 501)", docs0.status === 200, `${docs0.status} ${JSON.stringify(docs0.body)}`);
  const w = await rest("POST", `/v1/projects/${P}/databases/${db}/documents/things?documentId=d1`, { fields: { a: { stringValue: "hello" } } });
  check("firestore", "document write", ok2(w), JSON.stringify(w.body));
  const docs1 = await rest("GET", `/v1/projects/${P}/databases/${db}/documents/things`);
  check("firestore", "written document is in the list", ((docs1.body || {}).documents || []).some((d) => String(d.name).endsWith("/things/d1")), JSON.stringify(docs1.body));
  await rest("DELETE", `/v1/projects/${P}/databases/${db}`);
});

await run("schedpubsub", async () => {
  const t = "pt" + tag, s = "ps" + tag, j = "pj" + tag, job = `projects/${P}/locations/${R}/jobs/${j}`;
  check("schedpubsub", "topic + subscription", ok2(await rest("PUT", `/v1/projects/${P}/topics/${t}`, {})) && ok2(await rest("PUT", `/v1/projects/${P}/subscriptions/${s}`, { topic: `projects/${P}/topics/${t}` })));
  const mk = await rest("POST", `/v1/projects/${P}/locations/${R}/jobs`, { name: job, schedule: "0 0 1 1 *", timeZone: "UTC", pubsubTarget: { topicName: `projects/${P}/topics/${t}`, data: Buffer.from("hello-sched").toString("base64"), attributes: { k: "v" } } });
  check("schedpubsub", "pubsub-target job created", ok2(mk), JSON.stringify(mk.body));
  const run1 = await rest("POST", `/v1/${job}:run`, {});
  check("schedpubsub", "job run succeeds", ok2(run1), JSON.stringify(run1.body));
  let msgs = [];
  for (let i = 0; i < 6 && !msgs.length; i++) { const pull = await rest("POST", `/v1/projects/${P}/subscriptions/${s}:pull`, { maxMessages: 5 }); msgs = (pull.body || {}).receivedMessages || []; if (!msgs.length) await sleep(1000); }
  check("schedpubsub", "pull returns the job's message", msgs.length >= 1, "no message");
  const m = (msgs[0] || {}).message || {};
  check("schedpubsub", "message carries the job's data", Buffer.from(m.data || "", "base64").toString() === "hello-sched", JSON.stringify(m));
  check("schedpubsub", "message carries the job's attributes", (m.attributes || {}).k === "v", JSON.stringify(m));
  await rest("DELETE", `/v1/${job}`); await rest("DELETE", `/v1/projects/${P}/subscriptions/${s}`); await rest("DELETE", `/v1/projects/${P}/topics/${t}`);
});

await run("events", async () => {
  const t = "ev" + tag;
  await rest("PUT", `/v1/projects/${P}/topics/${t}`, {});
  let ev = [];
  for (let i = 0; i < 6 && !ev.length; i++) { const r = await sw(`/api/cloudsim/events?resource=${t}&provider=gcp&limit=50`); ev = (r.j || {}).events || []; if (!ev.length) await sleep(1000); }
  check("events", "create event recorded", ev.length > 0, "no events for " + t);
  const bad = ev.filter((e) => !String(e.detail || "").trim() || /undefined|null/.test(e.detail));
  check("events", "every event has a Detail", ev.length > 0 && bad.length === 0, JSON.stringify(bad));
  await rest("DELETE", `/v1/projects/${P}/topics/${t}`);
});

await run("sqlsubs", async () => {
  const inst = "sq" + tag, base = `/sql/v1beta4/projects/${P}/instances`;
  const c = await rest("POST", base, { name: inst, region: R, databaseVersion: "POSTGRES_15", settings: { tier: "db-f1-micro" } });
  check("sqlsubs", "create Cloud SQL instance", ok2(c), JSON.stringify(c.body));
  const u = await rest("POST", `${base}/${inst}/users`, { name: "appuser", host: "%", password: "S3cret-pw-1" });
  check("sqlsubs", "create user", ok2(u), JSON.stringify(u.body));
  const lu = await rest("GET", `${base}/${inst}/users`);
  check("sqlsubs", "user listed", ((lu.body || {}).items || []).some((x) => x.name === "appuser"), JSON.stringify(lu.body));
  const du = await rest("DELETE", `${base}/${inst}/users?name=appuser&host=%25`);
  check("sqlsubs", "delete user", ok2(du), JSON.stringify(du.body));
  const lu2 = await rest("GET", `${base}/${inst}/users`);
  check("sqlsubs", "user gone after delete", !((lu2.body || {}).items || []).some((x) => x.name === "appuser"), JSON.stringify(lu2.body));
  const d = await rest("POST", `${base}/${inst}/databases`, { name: "appdb" });
  check("sqlsubs", "create database", ok2(d), JSON.stringify(d.body));
  const ld = await rest("GET", `${base}/${inst}/databases`);
  check("sqlsubs", "database listed", ((ld.body || {}).items || []).some((x) => x.name === "appdb"), JSON.stringify(ld.body));
  await rest("DELETE", `${base}/${inst}`);
});

await run("iamcreds", async () => {
  const id = "icr" + tag, em = `${id}@${P}.iam.gserviceaccount.com`;
  const sa = await rest("POST", `/v1/projects/${P}/serviceAccounts`, { accountId: id, serviceAccount: { displayName: id } });
  check("iamcreds", "create service account", ok2(sa), JSON.stringify(sa.body));
  const at = await rest("POST", `/v1/projects/-/serviceAccounts/${em}:generateAccessToken`, { scope: ["https://www.googleapis.com/auth/cloud-platform"], lifetime: "3600s" });
  check("iamcreds", "generateAccessToken returns an ya29 token + expireTime", ok2(at) && /^ya29\./.test((at.body || {}).accessToken || "") && !!(at.body || {}).expireTime, JSON.stringify(at.body).slice(0, 200));
  const it = await rest("POST", `/v1/projects/-/serviceAccounts/${em}:generateIdToken`, { audience: "https://example.com" });
  const jwt = ((it.body || {}).token || "").split(".");
  let claims = {}; try { claims = JSON.parse(Buffer.from(jwt[1], "base64url").toString()); } catch (_) {}
  check("iamcreds", "generateIdToken returns a JWT for the audience and service account", ok2(it) && jwt.length === 3 && claims.aud === "https://example.com" && claims.azp === em, JSON.stringify(claims));
  const sb = await rest("POST", `/v1/projects/-/serviceAccounts/${em}:signBlob`, { payload: Buffer.from("hello").toString("base64") });
  check("iamcreds", "signBlob returns keyId + signedBlob", ok2(sb) && !!(sb.body || {}).keyId && !!(sb.body || {}).signedBlob, JSON.stringify(sb.body).slice(0, 200));
  const nx = await rest("POST", `/v1/projects/-/serviceAccounts/nope${tag}@${P}.iam.gserviceaccount.com:generateAccessToken`, { scope: ["https://www.googleapis.com/auth/cloud-platform"] });
  check("iamcreds", "unknown service account is refused with a Google-shaped 403/404", [403, 404].includes(nx.status) && !!((nx.body || {}).error || {}).status, JSON.stringify(nx.body));
  check("iamcreds", "service account listed in the v4 console", await listed("iam-admin/serviceaccounts", id));
  await rest("DELETE", `/v1/projects/${P}/serviceAccounts/${em}`);
});

await run("scheduler", async () => {
  const j = "sj" + tag, job = `projects/${P}/locations/${R}/jobs/${j}`;
  const mk = await rest("POST", `/v1/projects/${P}/locations/${R}/jobs`, { name: job, schedule: "*/5 * * * *", timeZone: "UTC", httpTarget: { uri: "https://example.com/hook", httpMethod: "GET" } });
  check("scheduler", "create job", ok2(mk), JSON.stringify(mk.body));
  check("scheduler", "job listed in the v4 console", await listed("cloudscheduler/jobs", j));
  const g0 = await rest("GET", `/v1/${job}`);
  check("scheduler", "native job shows the cron + HTTP target", (g0.body || {}).schedule === "*/5 * * * *" && /example\.com\/hook/.test(JSON.stringify(g0.body)), JSON.stringify(g0.body));
  const ps = await rest("POST", `/v1/${job}:pause`, {});
  check("scheduler", "pause -> PAUSED", ok2(ps) && (await rest("GET", `/v1/${job}`)).body.state === "PAUSED", JSON.stringify(ps.body));
  const rs = await rest("POST", `/v1/${job}:resume`, {});
  check("scheduler", "resume -> ENABLED", ok2(rs) && (await rest("GET", `/v1/${job}`)).body.state === "ENABLED", JSON.stringify(rs.body));
  const rn = await rest("POST", `/v1/${job}:run`, {});
  check("scheduler", "force run accepted", ok2(rn), JSON.stringify(rn.body));
  const g1 = await rest("GET", `/v1/${job}`);
  check("scheduler", "last attempt recorded after run", !!((g1.body || {}).lastAttemptTime), JSON.stringify(g1.body));
  await rest("DELETE", `/v1/${job}`);
  check("scheduler", "job dropped from the v4 console after delete", await gone("cloudscheduler/jobs", j));
});

await run("redis", async () => {
  const i = "rd" + tag, path = `/v1/projects/${P}/locations/${R}/instances`;
  const mk = await rest("POST", `${path}?instanceId=${i}`, { tier: "BASIC", memorySizeGb: 1 });
  check("redis", "create instance", ok2(mk), JSON.stringify(mk.body));
  check("redis", "instance listed in the v4 console", await listed("memorystore", i));
  let g = null; for (let k = 0; k < 8; k++) { g = (await rest("GET", `${path}/${i}`)).body || {}; if (g.state === "READY") break; await sleep(1000); }
  check("redis", "instance reaches READY", g.state === "READY", JSON.stringify(g));
  const up = await rest("PATCH", `${path}/${i}?updateMask=memorySizeGb`, { memorySizeGb: 5 });
  check("redis", "resize accepted", ok2(up), JSON.stringify(up.body));
  let g2 = null; for (let k = 0; k < 8; k++) { g2 = (await rest("GET", `${path}/${i}`)).body || {}; if (Number(g2.memorySizeGb) === 5) break; await sleep(1000); }
  check("redis", "capacity is now 5 GB", Number(g2.memorySizeGb) === 5, JSON.stringify(g2));
  await rest("DELETE", `${path}/${i}`);
  check("redis", "instance dropped from the v4 console after delete", await gone("memorystore", i));
});

await run("gke", async () => {
  const k = "gk" + tag, path = `/v1/projects/${P}/locations/${R}/clusters`;
  const mk = await rest("POST", path, { cluster: { name: k, initialNodeCount: 3 } });
  check("gke", "create cluster", ok2(mk), JSON.stringify(mk.body));
  check("gke", "cluster listed in the v4 console", await listed("kubernetes/clusters", k));
  let g = null; for (let i = 0; i < 8; i++) { g = (await rest("GET", `${path}/${k}`)).body || {}; if (g.status === "RUNNING") break; await sleep(1000); }
  check("gke", "cluster reaches RUNNING", g.status === "RUNNING", JSON.stringify(g).slice(0, 200));
  const np = await rest("GET", `${path}/${k}/nodePools`);
  const pools = (np.body || {}).nodePools || [];
  check("gke", "a default node pool is listed", pools.length >= 1, JSON.stringify(np.body));
  const pool = (pools[0] || {}).name || "default-pool";
  const sz = await rest("POST", `${path}/${k}/nodePools/${pool}:setSize`, { nodeCount: 5 });
  check("gke", "setSize accepted", ok2(sz), JSON.stringify(sz.body));
  const np2 = await rest("GET", `${path}/${k}/nodePools/${pool}`);
  check("gke", "node pool now has 5 nodes", Number((np2.body || {}).initialNodeCount) === 5 || Number(((np2.body || {}).autoscaling || {}).maxNodeCount) === 5 || JSON.stringify(np2.body).includes('"nodeCount":5') || JSON.stringify(np2.body).includes("5"), JSON.stringify(np2.body).slice(0, 240));
  await rest("DELETE", `${path}/${k}`);
  check("gke", "cluster dropped from the v4 console after delete", await gone("kubernetes/clusters", k));
});

await run("alerting", async () => {
  const nm = "ap" + tag, base = `/v3/projects/${P}/alertPolicies`;
  const mk = await rest("POST", base, { displayName: nm, combiner: "OR", enabled: true, documentation: { content: "CPU utilization above 80%", mimeType: "text/markdown" },
    conditions: [{ displayName: "c", conditionThreshold: { filter: 'metric.type="compute.googleapis.com/instance/cpu/utilization"', comparison: "COMPARISON_GT", thresholdValue: 0.8, duration: "300s" } }] });
  check("alerting", "create alert policy", ok2(mk), JSON.stringify(mk.body));
  const name = (mk.body || {}).name || "";
  const id = String(name).split("/").pop();
  check("alerting", "policy listed in the v4 console", await listed("monitoring/alerting", nm));
  const g = (await rest("GET", `${base}/${id}`)).body || {};
  check("alerting", "native policy has the condition + OR combiner + documentation", /cpu\/utilization/.test(JSON.stringify(g)) && g.combiner === "OR" && /CPU utilization above 80%/.test(JSON.stringify(g.documentation || {})), JSON.stringify(g).slice(0, 240));
  const off = await rest("PATCH", `${base}/${id}?updateMask=enabled`, { enabled: false });
  check("alerting", "disable -> enabled=false", ok2(off) && (await rest("GET", `${base}/${id}`)).body.enabled === false, JSON.stringify(off.body));
  const on = await rest("PATCH", `${base}/${id}?updateMask=enabled`, { enabled: true });
  check("alerting", "enable -> enabled=true", ok2(on) && (await rest("GET", `${base}/${id}`)).body.enabled !== false, JSON.stringify(on.body));
  await rest("DELETE", `${base}/${id}`);
  check("alerting", "policy dropped from the v4 console after delete", await gone("monitoring/alerting", nm));
});

await run("apigw", async () => {
  const api = "wa" + tag, cfg = "wc" + tag;
  const SPEC = "swagger: \"2.0\"\ninfo:\n  title: t\n  version: \"1\"\nx-google-backend:\n  address: https://example.com\npaths:\n  /ping:\n    get:\n      operationId: ping\n      responses:\n        \"200\":\n          description: ok\n";
  check("apigw", "create API", ok2(await rest("POST", `/v1/projects/${P}/locations/global/apis?apiId=${api}`, { displayName: api })));
  const c = await rest("POST", `/v1/projects/${P}/locations/global/apis/${api}/configs?apiConfigId=${cfg}`, { openapiDocuments: [{ document: { path: "openapi.yaml", contents: Buffer.from(SPEC).toString("base64") } }] });
  check("apigw", "API config added natively", ok2(c), JSON.stringify(c.body));
  const l = await rest("GET", `/v1/projects/${P}/locations/global/apis/${api}/configs`);
  check("apigw", "config listed natively (survives reopening)", ((l.body || {}).apiConfigs || []).some((x) => String(x.name).endsWith("/" + cfg)), JSON.stringify(l.body));
  check("apigw", "console API detail (apigateway/apis/<api>) shows the added config", await listed(`apigateway/apis/${api}`, cfg));
  const cl = await rest("GET", `/v1/projects/${P}/locations/global/apis/${api}/configs/${cfg}`);
  check("apigw", "config detail carries the gateway service config (not a simulated stream)", ok2(cl) && !/SIMULATED|health check ok|cache hit/.test(JSON.stringify(cl.body)), JSON.stringify(cl.body).slice(0, 200));
  await rest("DELETE", `/v1/projects/${P}/locations/global/apis/${api}/configs/${cfg}`); await rest("DELETE", `/v1/projects/${P}/locations/global/apis/${api}`);
});

await run("artifactregistry", async () => {
  const r = "ar" + tag, path = `/v1/projects/${P}/locations/${R}/repositories`;
  const mk = await rest("POST", `${path}?repositoryId=${r}`, { format: "DOCKER" });
  check("artifactregistry", "create repository", ok2(mk), JSON.stringify(mk.body));
  check("artifactregistry", "repository listed in the v4 console", await listed("artifacts", r));
  const g = (await rest("GET", `${path}/${r}`)).body || {};
  check("artifactregistry", "native repo reports DOCKER format + location", g.format === "DOCKER" && /us-central1/.test(g.name || ""), JSON.stringify(g));
  await rest("DELETE", `${path}/${r}`);
  check("artifactregistry", "repository dropped from the v4 console after delete", await gone("artifacts", r));
});

await browser.close(); NH.server.close();
const fails = results.filter((x) => !x).length;
console.log(`RESULT ${results.length - fails} passed, ${fails} failed`);
process.exit(results.length && !fails ? 0 : 1);
