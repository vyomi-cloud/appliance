/* Nano faithful-IAM: end-to-end in the real browser build (Chrome, Pyodide), REAL engines, REAL request maps, REAL host adapters.
 *
 *   NODE_PATH=/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules NANO_DIR=<worktree>/wasm \
 *     node wasm/ui-tests/iam/iam-hook-e2e.mjs
 *
 * Nothing is stubbed: core/iam_engine/* (gate, modes, audit, api, map_aws|gcp|azure, aws|gcp|azure_eval) and core/iam_state_nano.py are the vendored
 * bundle files. Identities and policies are created IN the in-browser stores through each cloud's own core (IAM Query API, GCP IAM REST, ARM roleAssignments),
 * then SDK-style signed / Bearer calls go through
 *   B  the service worker `/_wire` prefix -> page hook (nano-boot.js adispatch0)            (what the v4 consoles and in-page SDKs use)
 *   A  a real local relay (copy of wasm/relay/local-relay.mjs on :RELAY_TEST_PORT) -> WebSocket -> a relay SharedWorker (own Pyodide)  (SDK/CLI via the tunnel)
 * The page never connects to the owner's tunnel (:8090): the relay under test is started here on its own port and handed to its own worker.
 * Needs network for Pyodide (CDN) unless wasm/vendor/pyodide exists. */
import { cpSync, mkdtempSync, symlinkSync, existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join, delimiter } from "node:path";
import { startServer, bootConsole, chromium, NANO_DIR } from "../lib.mjs";

const RELAY_PORT = Number(process.env.RELAY_TEST_PORT || 18090);
const { server, base } = await startServer(NANO_DIR);
const browser = await chromium.launch({ channel: process.env.CHROME_CHANNEL || "chrome" });
const ctx = await browser.newContext();
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) console.log("[console.error]", m.text().slice(0, 200)); });

const results = [];
const check = (name, ok, detail = "") => { results.push(!!ok); console.error("[" + new Date().toISOString().slice(11, 19) + "]", ok ? "ok" : "FAIL", name.slice(0, 60)); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  - " + String(detail).slice(0, 300) : ""}`); };
const nums = {};

// ---------------------------------------------------------------------------------------------------------------- page-side helpers
const HELPERS = () => {
  const BASE = new URL(".", document.querySelector('script[src*="nano-boot"]')?.src || location.href).pathname.replace(/\/$/, "");
  const W = BASE + "/_wire";
  const b64u = (o) => btoa(JSON.stringify(o)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const jwt = (c) => "eyJhbGciOiJub25lIn0." + b64u(c) + ".sig";
  const sig = (k, svc) => `AWS4-HMAC-SHA256 Credential=${k}/20261123/us-east-1/${svc}/aws4_request, SignedHeaders=host;x-amz-date, Signature=` + "0".repeat(64);
  const fetch = (u, init = {}) => globalThis.fetch(u, { ...init, signal: AbortSignal.timeout(30000) }).catch((e) => { throw new Error("fetch " + (init.method || "GET") + " " + String(u).slice(0, 120) + ": " + e.name); });
  const out = async (x) => { const t = await x.text(); return { s: x.status, t, ct: x.headers.get("content-type") || "" }; };
  const T = {
    BASE, jwt,
    form: async (svc, params, key = "AKIAVYOMIDUMMY") => out(await fetch(W + "/", { method: "POST", headers: { authorization: sig(key, svc), "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Version: svc === "iam" ? "2010-05-08" : "2012-11-05", ...params }).toString() })),
    rest: async (key, m, p, body) => out(await fetch(W + p, { method: m, headers: { authorization: sig(key, "s3") }, body })),
    g: async (m, p, body, tok) => { const h = { "content-type": "application/json" }; if (tok) h.authorization = "Bearer " + tok; return out(await fetch(W + p, { method: m, headers: h, body: body === undefined ? undefined : (typeof body === "string" ? body : JSON.stringify(body)) })); },
    api: async (cloud, m, p, body, via = "api") => { const x = await fetch((via === "wire" ? W : BASE) + "/api/iam/" + cloud + p, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined }); return { s: x.status, b: await x.json().catch(() => null) }; },
    set: async (cloud, doc) => (await T.api(cloud, "PUT", "/enforcement", doc)).s,
    stats: () => ({ ...globalThis.NanoIamHook.stats }),
  };
  globalThis.T = T; globalThis.__fetch = fetch;
  return true;
};
const ev = (fn, arg) => page.evaluate(fn, arg);
const T0 = Date.now(), lg = (m) => console.error("[" + Math.round((Date.now() - T0) / 1000) + "s]", m);
async function boot(path = "/aws-console.html") {
  lg("boot " + path);
  await page.goto(base + "/clouds.html", { waitUntil: "domcontentloaded" });       // SW + fixtures first
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 60000 });
  lg("sw controlled");
  await bootConsole(page, base, path);
  lg("console booted");
  await page.waitForFunction(() => !!globalThis.NanoIamHook, null, { timeout: 90000 });
  await ev(HELPERS);
  lg("hook ready");
}

// ---------------------------------------------------------------------------------------------------------------- local relay (path A)
let relayProc = null;
async function startRelay() {
  const dir = mkdtempSync(join(tmpdir(), "iam-relay-"));
  cpSync(join(NANO_DIR, "relay"), join(dir, "relay"), { recursive: true });
  const nm = (process.env.NODE_PATH || "").split(delimiter).filter(Boolean).find((p) => existsSync(join(p, "ws")));
  if (nm) symlinkSync(nm, join(dir, "relay", "node_modules"));          // ESM does not honour NODE_PATH
  relayProc = spawn(process.execPath, [join(dir, "relay", "local-relay.mjs")], { cwd: join(dir, "relay"),
    env: { ...process.env, RELAY_PORT: String(RELAY_PORT), RELAY_HOST: "127.0.0.1", RELAY_AMQP_PORT: "0" }, stdio: "ignore" });
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${RELAY_PORT}/health`)).ok) return true; } catch (_) {} await new Promise((r) => setTimeout(r, 250)); }
  return false;
}
const relayCall = async (method, path, headers, body) => { const r = await fetch(`http://127.0.0.1:${RELAY_PORT}${path}`, { method, headers, body }); return { s: r.status, t: await r.text(), ct: r.headers.get("content-type") || "" }; };
const SIG = (k, svc) => `AWS4-HMAC-SHA256 Credential=${k}/20261123/us-east-1/${svc}/aws4_request, SignedHeaders=host;x-amz-date, Signature=` + "0".repeat(64);
const b64u = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const JWT = (c) => "eyJhbGciOiJub25lIn0." + b64u(c) + ".sig";

const POLICY = (stmts) => JSON.stringify({ Version: "2012-10-17", Statement: stmts });
const key = (r) => /<AccessKeyId>([^<]+)</.exec(r.t)[1];
const AZ_SUB = "00000000-0000-0000-0000-cloudlearn01", AZ_SC = "/subscriptions/" + AZ_SUB;
const AZ_READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7";
const OID_R = "11111111-2222-3333-4444-555555555555", OID_C = "22222222-2222-3333-4444-555555555555";
const SFX = Date.now().toString(36);

try {
  await boot();
  // =============================================================================================================== AWS (path B)
  const a = await ev(async (SFX) => {
    const r = {}, bkt = "iam-" + SFX;
    r.cu = (await T.form("iam", { Action: "CreateUser", UserName: "alice" })).s;
    r.key = await T.form("iam", { Action: "CreateAccessKey", UserName: "alice" });
    r.pol = (await T.form("iam", { Action: "PutUserPolicy", UserName: "alice", PolicyName: "ro", PolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [
      { Effect: "Allow", Action: ["sqs:ListQueues", "sqs:GetQueueUrl", "sqs:ReceiveMessage"], Resource: "*" },
      { Effect: "Allow", Action: ["s3:GetObject", "s3:ListBucket"], Resource: ["arn:aws:s3:::" + bkt, "arn:aws:s3:::" + bkt + "/*"] }] }) })).s;
    r.bkt = (await T.rest("AKIAVYOMIDUMMY", "PUT", "/" + bkt)).s;
    r.obj = (await T.rest("AKIAVYOMIDUMMY", "PUT", "/" + bkt + "/k", "hello")).s;
    r.q = (await T.form("sqs", { Action: "CreateQueue", QueueName: "qq" })).s;
    r.stats0 = T.stats();
    return r;
  }, SFX);
  const AK = key(a.key), BK = "iam-" + SFX;
  check("AWS setup: user + access key + inline policy created in the Nano IAM store through its IAM core; bucket, object, queue created (enforcement off)",
    a.cu === 200 && a.pol === 200 && a.bkt === 200 && a.obj === 200 && a.q === 200 && /^AKIA/.test(AK), JSON.stringify({ cu: a.cu, pol: a.pol, bkt: a.bkt, obj: a.obj, q: a.q }));
  check("AWS OFF: zero gate calls / engine mounts / catalog fetches after the whole setup", a.stats0.calls === 0 && a.stats0.engine_mounts === 0 && a.stats0.catalog_fetches === 0, JSON.stringify(a.stats0));

  const e = await ev(async ({ AK, BK }) => {
    const r = {};
    r.put = await T.set("aws", { space: "enforce" });
    r.listQ = await T.form("sqs", { Action: "ListQueues" }, AK);
    r.createQ = await T.form("sqs", { Action: "CreateQueue", QueueName: "q2" }, AK);
    r.getObj = await T.rest(AK, "GET", "/" + BK + "/k");
    r.putObj = await T.rest(AK, "PUT", "/" + BK + "/k2", "x");
    r.k2 = (await T.rest("AKIAVYOMIDUMMY", "GET", "/" + BK + "/k2")).s;
    r.rootUnknown = (await T.form("sqs", { Action: "CreateQueue", QueueName: "q3" }, "AKIAUNKNOWNKEY0001")).s;
    r.consoleUnsigned = (await __fetch(T.BASE + "/_wire/" + BK + "/k")).status;
    r.consoleApi = (await __fetch(T.BASE + "/api/iam/users")).status;
    r.denyMode = await T.set("aws", { space: "enforce", unknownPrincipal: "deny" });
    r.unknownDenied = (await T.form("sqs", { Action: "CreateQueue", QueueName: "q4" }, "AKIAUNKNOWNKEY0001")).s;
    await T.set("aws", { space: "enforce" });
    // explicit deny beats allow
    await T.form("iam", { Action: "PutUserPolicy", UserName: "alice", PolicyName: "deny", PolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: "s3:GetObject", Resource: "arn:aws:s3:::" + BK + "/secret/*" }] }) });
    r.denyObj = await T.rest(AK, "GET", "/" + BK + "/secret/x");
    r.allowObj2 = (await T.rest(AK, "GET", "/" + BK + "/k")).s;
    // per-service override: sqs off, s3 stays enforced
    r.svcPut = await T.set("aws", { space: "enforce", services: { sqs: "off" } });
    r.sqsOff = (await T.form("sqs", { Action: "CreateQueue", QueueName: "q5" }, AK)).s;
    r.s3Still = (await T.rest(AK, "PUT", "/" + BK + "/k3", "x")).s;
    // audit mode: would_deny is allowed
    await T.set("aws", { space: "audit" });
    r.auditPut = (await T.rest(AK, "PUT", "/" + BK + "/k4", "x")).s;
    const au = await T.api("aws", "GET", "/audit?limit=100");
    r.audit = (au.b.records || []).map((z) => z.decision + ":" + z.action);
    r.auditShape = !!(au.b.records && au.b.records[0] && ["id", "ts", "cloud", "principal", "action", "resource", "mode", "decision", "reason"].every((k) => k in au.b.records[0]));
    r.auditViaWire = ((await T.api("aws", "GET", "/audit?limit=3", undefined, "wire")).b.records || []).length;
    r.evaluate = (await T.api("aws", "POST", "/evaluate", { principal: { arn: "arn:aws:iam::123456789012:user/alice" }, action: "s3:PutObject", resource: "arn:aws:s3:::b/k" })).b;
    r.evaluateAllow = (await T.api("aws", "POST", "/evaluate", { principal: { arn: "arn:aws:iam::123456789012:user/alice" }, action: "s3:GetObject", resource: "arn:aws:s3:::" + BK + "/k" })).b;
    r.catalog = (await T.api("aws", "GET", "/catalog/sqs")).b;
    r.stats = T.stats();
    return r;
  }, { AK, BK });
  check("AWS enforce: limited user may ListQueues + GetObject (200); S3 + SQS reach the real cores", e.listQ.s === 200 && e.getObj.s === 200 && e.listQ.t.includes("qq"));
  check("AWS enforce: SQS CreateQueue -> 403 AccessDenied (IAM query error shape, names sqs:CreateQueue + the user ARN)",
    e.createQ.s === 403 && e.createQ.t.includes("<Code>AccessDenied</Code>") && e.createQ.t.includes("arn:aws:iam::123456789012:user/alice is not authorized to perform: sqs:CreateQueue") && /xml/.test(e.createQ.ct), e.createQ.t.slice(0, 220));
  check("AWS enforce: S3 PutObject -> 403 <Error><Code>AccessDenied</Code> naming s3:PutObject; denied request never reached the S3 core",
    e.putObj.s === 403 && e.putObj.t.includes("<Code>AccessDenied</Code>") && e.putObj.t.includes("s3:PutObject") && e.k2 === 404, e.putObj.t.slice(0, 200));
  check("AWS: credentials not in the IAM store act as account root (default unknownPrincipal) -> 200; `unknownPrincipal: deny` -> 403", e.rootUnknown === 200 && e.denyMode === 200 && e.unknownDenied === 403, JSON.stringify([e.rootUnknown, e.unknownDenied]));
  check("AWS: credential-less console traffic (/_wire unsigned, /api/*) is never gated", e.consoleUnsigned === 200 && e.consoleApi === 200, JSON.stringify([e.consoleUnsigned, e.consoleApi]));
  check("AWS: explicit Deny beats Allow (reason names the explicit deny); other objects still allowed", e.denyObj.s === 403 && /explicit deny/.test(e.denyObj.t) && e.allowObj2 === 200, e.denyObj.t.slice(0, 220));
  check("AWS: per-service off (sqs off) lets CreateQueue through while s3 stays enforced (403)", e.svcPut === 200 && e.sqsOff === 200 && e.s3Still === 403, JSON.stringify([e.sqsOff, e.s3Still]));
  check("AWS: audit mode allows a would-deny PUT and records it; records have the Mesh shape; same list on /api/iam and /_wire/api/iam",
    e.auditPut === 200 && e.auditShape && e.audit.some((z) => z === "would_deny:s3:PutObject") && e.audit.some((z) => z === "deny:sqs:CreateQueue") && e.audit.some((z) => z.startsWith("allow:sqs:ListQueues")) && e.auditViaWire > 0, JSON.stringify(e.audit.slice(0, 6)));
  check("AWS /api/iam/aws/evaluate runs the real engine on the in-browser store (alice: PutObject implicit_deny, GetObject allow); catalog/sqs served",
    e.evaluate && e.evaluate.allowed === false && e.evaluate.reason === "implicit_deny" && e.evaluateAllow.allowed === true && e.catalog && e.catalog.actions, JSON.stringify([e.evaluate && e.evaluate.reason, e.evaluateAllow && e.evaluateAllow.allowed]));
  check("AWS: engine mounted once, catalogs fetched lazily (s3 + sqs only)", e.stats.engine_mounts === 1 && e.stats.catalog_fetches >= 2 && e.stats.catalog_fetches <= 4 && e.stats.errors === 0, JSON.stringify(e.stats));

  // =============================================================================================================== GCP (path B)
  const g = await ev(async () => {
    const r = {};
    const P = "nano-project";
    r.bkt = (await T.g("POST", "/storage/v1/b?project=" + P, { name: "gb1" })).s;
    r.obj = (await T.g("POST", "/upload/storage/v1/b/gb1/o?uploadType=media&name=hello.txt", "hi")).s;
    r.keep = (await T.g("POST", "/upload/storage/v1/b/gb1/o?uploadType=media&name=keep.txt", "keep")).s;
    r.set = (await T.g("POST", "/v1/projects/" + P + ":setIamPolicy", { policy: { bindings: [{ role: "roles/storage.objectViewer", members: ["user:a@x.com"] }] } })).s;
    const A = T.jwt({ email: "a@x.com" }), B = T.jwt({ email: "b@x.com" });
    r.preOff = (await T.g("GET", "/storage/v1/b/gb1/o/hello.txt?alt=media", undefined, B)).s;
    const s0 = T.stats();
    r.en = await T.set("gcp", { space: "enforce" });
    r.read = await T.g("GET", "/storage/v1/b/gb1/o/hello.txt?alt=media", undefined, A);
    r.del = await T.g("DELETE", "/storage/v1/b/gb1/o/hello.txt", undefined, A);
    r.other = await T.g("GET", "/storage/v1/b/gb1/o/hello.txt?alt=media", undefined, B);
    r.opaque = (await T.g("GET", "/storage/v1/b/gb1/o/hello.txt?alt=media", undefined, "ya29.opaque-token")).s;
    r.consoleUnsigned = (await T.g("GET", "/storage/v1/b/gb1/o/hello.txt?alt=media")).s;
    r.denyMode = await T.set("gcp", { space: "enforce", unknownPrincipal: "deny" });
    r.opaqueDenied = (await T.g("GET", "/storage/v1/b/gb1/o/hello.txt?alt=media", undefined, "ya29.opaque-token")).s;
    await T.set("gcp", { space: "enforce" });
    // custom role (created through the GCP IAM REST core) granted to b -> delete allowed for b only
    r.role = (await T.g("POST", "/v1/projects/" + P + "/roles", { roleId: "objDeleter", role: { title: "d", includedPermissions: ["storage.objects.delete"], stage: "GA" } })).s;
    r.bind = (await T.g("POST", "/v1/projects/" + P + ":setIamPolicy", { policy: { bindings: [{ role: "roles/storage.objectViewer", members: ["user:a@x.com"] }, { role: "projects/" + P + "/roles/objDeleter", members: ["user:b@x.com"] }] } })).s;
    r.delB = (await T.g("DELETE", "/storage/v1/b/gb1/o/hello.txt", undefined, B)).s;
    r.audit = ((await T.api("gcp", "GET", "/audit?limit=20")).b.records || []).map((z) => z.decision + ":" + z.action + ":" + z.principal);
    r.ev = (await T.api("gcp", "POST", "/evaluate", { principal: { member: "user:a@x.com" }, action: "storage.objects.get", resource: "//storage.googleapis.com/projects/_/buckets/gb1/objects/hello.txt" })).b;
    r.catalog = (await T.api("gcp", "GET", "/catalog/storage", undefined, "wire")).s;
    r.stats = T.stats();
    r.dStats = { calls: r.stats.calls - s0.calls };
    await T.set("gcp", {});
    return r;
  });
  const gBody = (() => { try { return JSON.parse(g.del.t); } catch (_) { return {}; } })();
  check("GCP setup through the GCP cores: bucket, object, project IAM policy (user:a@x.com objectViewer)", g.bkt === 200 && g.obj === 200 && g.set === 200 && g.preOff === 200);
  check("GCP enforce: user:a (objectViewer on the project, inherited by the bucket) reads the object -> 200", g.read.s === 200 && g.read.t === "hi", g.read.t.slice(0, 80));
  check("GCP enforce: user:a DELETE -> 403 PERMISSION_DENIED naming storage.objects.delete and the full resource name",
    g.del.s === 403 && gBody.error && gBody.error.code === 403 && gBody.error.status === "PERMISSION_DENIED" && /storage\.objects\.delete/.test(gBody.error.message) && /\/\/storage\.googleapis\.com\/projects\/_\/buckets\/gb1\/objects\/hello\.txt/.test(gBody.error.message), g.del.t.slice(0, 260));
  check("GCP enforce: user:b (no binding) -> 403; opaque ya29 token (no identity) acts as project owner -> 200; unknownPrincipal=deny -> 403; unsigned console 200",
    g.other.s === 403 && g.opaque === 200 && g.opaqueDenied === 403 && g.consoleUnsigned === 200, JSON.stringify([g.other.s, g.opaque, g.opaqueDenied, g.consoleUnsigned]));
  check("GCP: custom role from the GCP IAM core (storage.objects.delete) grants b the delete (200) via state.custom_roles", g.role === 200 && g.bind === 200 && g.delB === 204, JSON.stringify([g.role, g.bind, g.delB]));
  check("GCP: audit records carry the principal + permission; /api/iam/gcp/evaluate (real gcp_eval + state from the store) allows a; catalog/storage via /_wire/api/iam",
    g.audit.some((z) => z === "deny:storage.objects.delete:user:a@x.com") && g.audit.some((z) => z === "allow:storage.objects.get:user:a@x.com") && g.ev && g.ev.allowed === true && g.catalog === 200, JSON.stringify(g.audit.slice(0, 4)) + " " + JSON.stringify(g.ev && g.ev.reason));
  check("GCP: no engine errors; role catalogs fetched lazily (storage + _methods + iam/ others only as roles require)", g.stats.errors === 0 && g.stats.engine_mounts === 1, JSON.stringify(g.stats));

  // =============================================================================================================== Azure (ARM through /_wire/subscriptions, path B)
  const z = await ev(async ({ AZ_SC, AZ_READER, OID_R, OID_C }) => {
    const r = {};
    const A = (m, p, body, tok) => T.g(m, p, body, tok);
    r.rg = (await A("PUT", AZ_SC + "/resourcegroups/rg1?api-version=2021-04-01", { location: "eastus" })).s;
    r.ra = (await A("PUT", AZ_SC + "/providers/Microsoft.Authorization/roleAssignments/aaaaaaaa-0000-0000-0000-000000000001?api-version=2022-04-01",
      { properties: { roleDefinitionId: AZ_SC + "/providers/Microsoft.Authorization/roleDefinitions/" + AZ_READER, principalId: OID_R, principalType: "User" } })).s;
    // custom role: only resource-group write
    r.rd = (await A("PUT", AZ_SC + "/providers/Microsoft.Authorization/roleDefinitions/bbbbbbbb-0000-0000-0000-000000000002?api-version=2022-04-01",
      { properties: { roleName: "RG Writer", type: "CustomRole", permissions: [{ actions: ["Microsoft.Resources/subscriptions/resourceGroups/read", "Microsoft.Resources/subscriptions/resourceGroups/write"], notActions: [] }], assignableScopes: [AZ_SC] } })).s;
    r.rc = (await A("PUT", AZ_SC + "/providers/Microsoft.Authorization/roleAssignments/aaaaaaaa-0000-0000-0000-000000000003?api-version=2022-04-01",
      { properties: { roleDefinitionId: AZ_SC + "/providers/Microsoft.Authorization/roleDefinitions/bbbbbbbb-0000-0000-0000-000000000002", principalId: OID_C, principalType: "User" } })).s;
    const R = T.jwt({ oid: OID_R, tid: "t" }), C = T.jwt({ oid: OID_C, tid: "t" }), X = T.jwt({ oid: "99999999-2222-3333-4444-555555555555" });
    r.preOff = (await A("GET", AZ_SC + "/resourcegroups/rg1?api-version=2021-04-01", undefined, X)).s;
    const s0 = T.stats();
    r.en = await T.set("azure", { space: "enforce" });
    r.read = (await A("GET", AZ_SC + "/resourcegroups/rg1?api-version=2021-04-01", undefined, R)).s;
    r.write = await A("PUT", AZ_SC + "/resourcegroups/rg2?api-version=2021-04-01", { location: "eastus" }, R);
    r.rg2 = (await A("GET", AZ_SC + "/resourcegroups/rg2?api-version=2021-04-01")).s;
    r.custW = (await A("PUT", AZ_SC + "/resourcegroups/rg3?api-version=2021-04-01", { location: "eastus" }, C)).s;
    r.custD = (await A("DELETE", AZ_SC + "/resourcegroups/rg3?api-version=2021-04-01", undefined, C)).s;
    r.other = await A("GET", AZ_SC + "/resourcegroups/rg1?api-version=2021-04-01", undefined, X);
    r.consoleUnsigned = (await A("GET", AZ_SC + "/resourcegroups/rg1?api-version=2021-04-01")).s;
    r.tokenless = await T.set("azure", { space: "enforce", unknownPrincipal: "deny" });
    r.noIdDenied = (await A("GET", AZ_SC + "/resourcegroups/rg1?api-version=2021-04-01", undefined, "opaque")).s;
    await T.set("azure", { space: "enforce" });
    r.audit = ((await T.api("azure", "GET", "/audit?limit=20")).b.records || []).map((q) => q.decision + ":" + q.action + ":" + q.principal);
    r.ev = (await T.api("azure", "POST", "/evaluate", { principal: { object_id: OID_R, type: "User" }, action: "Microsoft.Resources/subscriptions/resourceGroups/read", resource: AZ_SC + "/resourcegroups/rg1" })).b;
    r.evNo = (await T.api("azure", "POST", "/evaluate", { principal: { object_id: OID_R, type: "User" }, action: "Microsoft.Resources/subscriptions/resourceGroups/write", resource: AZ_SC + "/resourcegroups/rg1" })).b;
    r.stats = T.stats();
    await T.set("azure", {});
    return r;
  }, { AZ_SC, AZ_READER, OID_R, OID_C });
  const zBody = (() => { try { return JSON.parse(z.write.t); } catch (_) { return {}; } })();
  check("Azure setup through ARM: resource group, built-in Reader assignment, custom role definition + assignment", z.rg === 201 && z.ra === 201 && z.rd < 300 && z.rc === 201 && z.preOff === 200, JSON.stringify([z.rg, z.ra, z.rd, z.rc, z.preOff]));
  check("Azure enforce: Reader (assigned at the subscription) may GET the resource group -> 200", z.read === 200);
  check("Azure enforce: Reader PUT -> 403 AuthorizationFailed naming the client, object id, action and scope; denied PUT never created rg2",
    z.write.s === 403 && zBody.error && zBody.error.code === "AuthorizationFailed" && /does not have authorization to perform action 'Microsoft.Resources\/subscriptions\/resourceGroups\/write' over scope '\/subscriptions\/00000000-0000-0000-0000-cloudlearn01\/resourcegroups\/rg2'/.test(zBody.error.message) && z.rg2 === 404, z.write.t.slice(0, 260));
  check("Azure: custom role definition from ARM grants write (201) but not delete (403); unknown object id -> 403; unsigned console 200; token without identity + unknownPrincipal=deny -> 403",
    z.custW === 201 && z.custD === 403 && z.other.s === 403 && z.consoleUnsigned === 200 && z.noIdDenied === 403, JSON.stringify([z.custW, z.custD, z.other.s, z.consoleUnsigned, z.noIdDenied]));
  check("Azure: audit lists deny/allow with object id + action; /api/iam/azure/evaluate (real azure_eval + store state): Reader read allow, write implicit_deny",
    z.audit.some((q) => q.startsWith("deny:Microsoft.Resources/subscriptions/resourceGroups/write:" + OID_R)) && z.ev && z.ev.allowed === true && z.evNo && z.evNo.allowed === false, JSON.stringify(z.audit.slice(0, 3)));
  check("Azure: no engine errors, built-in role catalog (_roles) fetched lazily", z.stats.errors === 0 && z.stats.engine_mounts === 1, JSON.stringify(z.stats));

  // ---- overhead (real engines). Chrome clamps performance.now() to ~0.1 ms: batches of 20 calls.
  const o = await ev(async ({ AK, BK, OID_R }) => {
    const hook = globalThis.NanoIamHook;
    await T.set("aws", { space: "enforce" }); await T.set("gcp", { space: "enforce" }); await T.set("azure", { space: "enforce" });
    const pct = (a, q) => { const s = [...a].sort((x, y) => x - y); return +s[Math.min(s.length - 1, Math.floor(q * s.length))].toFixed(3); };
    const SIG = (k, svc) => `AWS4-HMAC-SHA256 Credential=${k}/20261123/us-east-1/${svc}/aws4_request, SignedHeaders=host;x-amz-date, Signature=` + "0".repeat(64);
    const mk = (cloud, method, path, auth, query = {}) => ({ cloud, req: { method, path, query, headers: { authorization: auth }, body_b64: "" } });
    const AZ = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourcegroups/rg1";
    const cases = {
      "aws allow (S3 GET)": mk("aws", "GET", "/" + BK + "/k", SIG(AK, "s3")),
      "aws deny (S3 PUT)": mk("aws", "PUT", "/" + BK + "/kx", SIG(AK, "s3")),
      "gcp allow (GCS GET)": mk("gcp", "GET", "/storage/v1/b/gb1/o/hello.txt", "Bearer " + T.jwt({ email: "a@x.com" }), { alt: "media" }),
      "gcp deny (GCS DELETE)": mk("gcp", "DELETE", "/storage/v1/b/gb1/o/hello.txt", "Bearer " + T.jwt({ email: "a@x.com" })),
      "azure allow (ARM GET)": mk("azure", "GET", AZ, "Bearer " + T.jwt({ oid: OID_R }), { "api-version": "2021-04-01" }),
      "azure deny (ARM PUT)": mk("azure", "PUT", AZ + "x", "Bearer " + T.jwt({ oid: OID_R }), { "api-version": "2021-04-01" }),
    };
    const out = {};
    for (const [name, c] of Object.entries(cases)) {
      for (let i = 0; i < 40; i++) await hook.guard(c.cloud, c.req);              // warm: engine, catalogs, caches
      const t = []; for (let b = 0; b < 30; b++) { const a = performance.now(); for (let i = 0; i < 20; i++) await hook.guard(c.cloud, c.req); t.push((performance.now() - a) / 20); }
      out[name] = { p50: pct(t, .5), p95: pct(t, .95) };
    }
    // state-building cost grows with the store: add 20 resource groups (Azure) and 20 IAM users (AWS), re-measure allow
    for (let i = 0; i < 20; i++) { await T.g("PUT", "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourcegroups/scale" + i + "?api-version=2021-04-01", { location: "eastus" }); }
    for (let i = 0; i < 20; i++) { await T.form("iam", { Action: "CreateUser", UserName: "scale" + i }); await T.form("iam", { Action: "PutUserPolicy", UserName: "scale" + i, PolicyName: "p", PolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: "s3:*", Resource: "*" }] }) }); }
    const big = {};
    for (const name of ["aws allow (S3 GET)", "azure allow (ARM GET)"]) {
      const c = cases[name]; const t = []; for (let b = 0; b < 30; b++) { const a = performance.now(); for (let i = 0; i < 20; i++) await hook.guard(c.cloud, c.req); t.push((performance.now() - a) / 20); }
      big[name] = { p50: pct(t, .5), p95: pct(t, .95) };
    }
    // end-to-end SDK-style GET through the SW: gate off vs enforce (alternating rounds)
    const e2e = async () => { const t = []; for (let i = 0; i < 60; i++) { const a = performance.now(); await T.rest(AK, "GET", "/" + BK + "/k"); t.push(performance.now() - a); } return { p50: pct(t, .5), p95: pct(t, .95) }; };
    const rounds = [];
    for (const mode of ["off", "enforce", "off", "enforce"]) { await T.set("aws", mode === "off" ? {} : { space: "enforce" }); rounds.push([mode, await e2e()]); }
    // first request after enabling: engine mount + catalog fetch (cold) is measured in a fresh context below
    const st = hook.stats;
    await T.set("aws", {}); await T.set("gcp", {}); await T.set("azure", {});
    return { out, big, rounds, stats: { ...st } };
  }, { AK, BK, OID_R });
  console.log("\nOVERHEAD per request (ms, Chrome, Pyodide 0.26.2; REAL engines + REAL state adapters; page context; batches of 20, 30 batches)");
  for (const [k, v] of Object.entries(o.out)) console.log(`  decision ${k.padEnd(24)} p50 ${v.p50}  p95 ${v.p95}`);
  for (const [k, v] of Object.entries(o.big)) console.log(`  decision ${k.padEnd(24)} p50 ${v.p50}  p95 ${v.p95}   (store grown: +20 IAM users / +20 resource groups)`);
  for (const [m, v] of o.rounds) console.log(`  SDK-style S3 GET end-to-end, space=${m.padEnd(7)} p50 ${v.p50}  p95 ${v.p95}`);
  const worst = Math.max(...Object.values(o.out).map((v) => v.p95));
  check("overhead: every decision (3 clouds, allow + deny, real engines + state build) p95 under 5 ms", worst < 5, "worst p95 " + worst + " ms");
  check("overhead: no gate errors over the whole measurement", o.stats.errors === 0, JSON.stringify(o.stats));

  // =============================================================================================================== path A: relay -> WebSocket -> SharedWorker
  const relayUp = await startRelay();
  check("path A: local relay copy started on :" + RELAY_PORT + " (own port; the owner's tunnel is untouched)", relayUp);
  if (relayUp) {
    const started = await ev(async (port) => {
      const w = new SharedWorker(T.BASE + "/relay/relay-shared-worker.js?v=4", { type: "module", name: "iam-e2e-relay" });
      w.port.start();
      w.port.postMessage({ type: "start", session: "iam-e2e", noIdle: true, config: { localHealth: `http://127.0.0.1:${port}/health`, localWs: `ws://127.0.0.1:${port}/register`, localExternal: `http://127.0.0.1:${port}`,
        cloudWsBase: "wss://invalid.invalid/register", cloudExternal: "https://invalid.invalid" } });
      globalThis.__relayPort = w.port;
      return true;
    }, RELAY_PORT);
    let up = false;
    for (let i = 0; i < 240 && !up; i++) { const h = await fetch(`http://127.0.0.1:${RELAY_PORT}/health`).then((r) => r.json()).catch(() => ({})); up = !!(h.tabs || h.registered || h.ok && h.tab); if (!up) await new Promise((r) => setTimeout(r, 500)); }
    // The worker answers only once its own Pyodide has booted; probe with an S3 list as root.
    let booted = false;
    for (let i = 0; i < 200 && !booted; i++) { const r = await relayCall("GET", "/", { authorization: SIG("AKIAVYOMIDUMMY", "s3") }).catch(() => ({ s: 0 })); booted = r.s === 200; if (!booted) await new Promise((r) => setTimeout(r, 500)); }
    check("path A: relay SharedWorker (own Pyodide) booted and registered with the relay; serves root-credential S3 list", started && booted);
    if (booted) {
      await ev(async () => { await T.set("aws", { space: "enforce" }); await T.set("gcp", { space: "enforce" }); await T.set("azure", { space: "enforce" }); return 1; });
      await new Promise((r) => setTimeout(r, 400));          // BroadcastChannel -> worker settings cache
      const rl = {};
      rl.get = await relayCall("GET", `/${BK}/k`, { authorization: SIG(AK, "s3") });
      rl.put = await relayCall("PUT", `/${BK}/k9`, { authorization: SIG(AK, "s3") }, "x");
      rl.list = await relayCall("POST", "/", { authorization: SIG(AK, "sqs"), "content-type": "application/x-www-form-urlencoded" }, "Action=ListQueues&Version=2012-11-05");
      rl.create = await relayCall("POST", "/", { authorization: SIG(AK, "sqs"), "content-type": "application/x-www-form-urlencoded" }, "Action=CreateQueue&QueueName=q9&Version=2012-11-05");
      rl.root = await relayCall("PUT", `/${BK}/k10`, { authorization: SIG("AKIAVYOMIDUMMY", "s3") }, "x");
      rl.gcpOk = await relayCall("GET", "/storage/v1/b/gb1/o/keep.txt?alt=media", { authorization: "Bearer " + JWT({ email: "a@x.com" }) });
      rl.gcpDeny = await relayCall("GET", "/storage/v1/b/gb1/o/keep.txt?alt=media", { authorization: "Bearer " + JWT({ email: "zz@x.com" }) });
      rl.azOk = await relayCall("GET", `${AZ_SC}/resourcegroups/rg1?api-version=2021-04-01`, { authorization: "Bearer " + JWT({ oid: OID_R }) });
      rl.azDeny = await relayCall("PUT", `${AZ_SC}/resourcegroups/rg7?api-version=2021-04-01`, { authorization: "Bearer " + JWT({ oid: OID_R }), "content-type": "application/json" }, JSON.stringify({ location: "eastus" }));
      check("path A AWS: SigV4 S3 GET allowed, PUT -> 403 AccessDenied XML (s3:PutObject); SQS ListQueues allowed, CreateQueue -> 403; root key allowed",
        rl.get.s === 200 && rl.put.s === 403 && rl.put.t.includes("s3:PutObject") && rl.list.s === 200 && rl.create.s === 403 && rl.create.t.includes("sqs:CreateQueue") && rl.root.s === 200, JSON.stringify([rl.get.s, rl.put.s, rl.list.s, rl.create.s, rl.root.s]) + " " + rl.put.t.slice(0, 160));
      check("path A GCP: Bearer (email claim) allowed 200 / denied 403 PERMISSION_DENIED through the relay", rl.gcpOk.s === 200 && rl.gcpDeny.s === 403 && /PERMISSION_DENIED/.test(rl.gcpDeny.t), JSON.stringify([rl.gcpOk.s, rl.gcpDeny.s]));
      check("path A Azure: ARM through the relay: Reader read allowed / write -> 403 AuthorizationFailed", rl.azOk.s === 200 && rl.azDeny.s === 403 && /AuthorizationFailed/.test(rl.azDeny.t), JSON.stringify([rl.azOk.s, rl.azDeny.s]) + " " + rl.azDeny.t.slice(0, 140));
      const shared = await ev(async (BK) => ((await T.api("aws", "GET", "/audit?limit=1000")).b.records || []).filter((r) => r.decision === "deny" && r.action === "s3:PutObject" && r.resource.endsWith(BK + "/k9")).length, BK);
      check("path A: the relay worker's deny record (its own Pyodide context) appears in the page's /api/iam audit (shared ring)", shared === 1, String(shared));
      await ev(async () => { await T.set("aws", {}); await T.set("gcp", {}); await T.set("azure", {}); return 1; });
    }
  }

  // =============================================================================================================== persistence across reload + overhead
  await ev(async () => { await T.set("aws", { space: "enforce", services: { s3: "enforce", sqs: "audit" } }); await T.set("gcp", { space: "audit" }); await T.set("azure", { global: "enforce" }); return 1; });
  await page.reload({ waitUntil: "domcontentloaded" });
  await boot();
  const rl2 = await ev(async ({ AK, BK }) => {
    await globalThis.NanoIamHook.ready;
    const r = { aws: globalThis.NanoIamHook.settings("aws"), gcp: globalThis.NanoIamHook.settings("gcp"), azure: globalThis.NanoIamHook.settings("azure") };
    r.api = (await T.api("aws", "GET", "/enforcement")).b;
    r.apiWire = (await T.api("gcp", "GET", "/enforcement", undefined, "wire")).b;
    r.put = (await T.rest(AK, "PUT", "/" + BK + "/k11", "x")).s;          // the IAM store (alice + her policies) was restored too
    return r;
  }, { AK, BK });
  check("settings persist across reload for all three clouds (IndexedDB), served on /api/iam and /_wire/api/iam; still enforcing (alice PUT 403 after reload: IAM store restored)",
    rl2.aws && rl2.aws.services.s3 === "enforce" && rl2.aws.services.sqs === "audit" && rl2.gcp.space === "audit" && rl2.azure.global === "enforce" && rl2.api.space === "enforce" && rl2.apiWire.space === "audit" && rl2.put === 403, JSON.stringify([rl2.aws, rl2.put]));

} catch (err) { console.log("FAIL  harness:", err.stack || err.message); results.push(false); }
if (relayProc) relayProc.kill();
await browser.close(); server.close();
const ok = results.length > 0 && results.every(Boolean);
console.log(`\nRESULT: ${ok ? "PASS" : "FAIL"} (${results.filter(Boolean).length}/${results.length})`);
process.exit(ok ? 0 : 1);
