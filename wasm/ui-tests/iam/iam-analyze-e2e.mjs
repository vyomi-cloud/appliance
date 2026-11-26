/* Nano IAM simulate / analyze APIs end-to-end in the real browser build (Chrome, Pyodide): the SAME engine modules Mesh runs, answering
 * SimulatePrincipalPolicy, Access Analyzer REST, GCP Policy Troubleshooter + analyzeIamPolicy and Azure checkAccess / permissions / filtered role assignments.
 *
 *   NODE_PATH=/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules NANO_DIR=<worktree>/wasm \
 *     node wasm/ui-tests/iam/iam-analyze-e2e.mjs
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
// The trunk bundle ships no generated aws-console.html (wasm/make_pages.py output), so the harness boots nano-boot.js from a throwaway page it writes
// next to it (removed at exit). nano-boot.js is the page-side hook host the real consoles load.
import { writeFileSync, unlinkSync } from "node:fs";
const HARNESS = join(NANO_DIR, "__iam_analyze_e2e.html");
writeFileSync(HARNESS, '<!doctype html><html><head><meta charset="utf-8"><title>iam analyze e2e</title><script type="module" src="./nano-boot.js?v=4"></script></head><body><div id="rail"></div></body></html>');
process.on("exit", () => { try { unlinkSync(HARNESS); } catch (_) {} });
async function boot(path = "/__iam_analyze_e2e.html") {
  lg("boot " + path);
  await page.goto(base + path, { waitUntil: "domcontentloaded" });       // SW + fixtures first
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 60000 });
  lg("sw controlled");
  await page.waitForTimeout(3000);                                       // v4 trunk: nano-boot.js is loaded by clouds.html (the consoles are served from the app shell)
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


const AZ_SUB = "00000000-0000-0000-0000-cloudlearn01", AZ_SC = "/subscriptions/" + AZ_SUB;
const AZ_READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7", OID_R = "11111111-2222-3333-4444-555555555555";
const SFX = Date.now().toString(36);
const POLICY = (stmts) => JSON.stringify({ Version: "2012-10-17", Statement: stmts });

try {
  await boot();
  // =============================================================================================================== AWS (path B: /_wire)
  const a = await ev(async (SFX) => {
    const r = {}, bkt = "aa-" + SFX, SIG = (svc) => `AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261125/us-east-1/${svc}/aws4_request, SignedHeaders=host;x-amz-date, Signature=` + "0".repeat(64);
    const rest = async (m, p, body, svc = "access-analyzer") => { const x = await __fetch(T.BASE + "/_wire" + p, { method: m, headers: { authorization: SIG(svc), "content-type": "application/json" }, body }); const t = await x.text(); let j = null; try { j = JSON.parse(t); } catch (_) {} return { s: x.status, t, j }; };
    await T.form("iam", { Action: "CreateUser", UserName: "sim" + SFX });
    await T.form("iam", { Action: "PutUserPolicy", UserName: "sim" + SFX, PolicyName: "p", PolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [
      { Sid: "ro", Effect: "Allow", Action: ["s3:GetObject"], Resource: "*" }, { Sid: "nodel", Effect: "Deny", Action: "s3:GetObject", Resource: "arn:aws:s3:::secret/*" }] }) });
    r.bkt = (await T.rest("AKIAVYOMIDUMMY", "PUT", "/" + bkt)).s;
    r.pol = (await T.rest("AKIAVYOMIDUMMY", "PUT", "/" + bkt + "?policy", JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: "*", Action: "s3:GetObject", Resource: "arn:aws:s3:::" + bkt + "/*" }] }))).s;
    const acct = /arn:aws:iam::(\d+):user/.exec((await T.form("iam", { Action: "GetUser", UserName: "sim" + SFX })).t)[1];
    r.sim = await T.form("iam", { Action: "SimulatePrincipalPolicy", PolicySourceArn: `arn:aws:iam::${acct}:user/sim${SFX}`, "ActionNames.member.1": "s3:GetObject", "ActionNames.member.2": "s3:PutObject",
      "ResourceArns.member.1": "arn:aws:s3:::secret/x", "ResourceArns.member.2": "arn:aws:s3:::open/x" });
    r.ctx = await T.form("iam", { Action: "GetContextKeysForCustomPolicy", "PolicyInputList.member.1": JSON.stringify({ Statement: [{ Effect: "Allow", Action: "s3:*", Resource: "*", Condition: { StringEquals: { "s3:prefix": "a" } } }] }) });
    r.mk = await rest("PUT", "/analyzer", JSON.stringify({ analyzerName: "an" + SFX, type: "ACCOUNT" }));
    r.find = await rest("POST", "/finding", JSON.stringify({ analyzerArn: r.mk.j && r.mk.j.arn }));
    r.val = await rest("POST", "/policy/validation", JSON.stringify({ policyType: "IDENTITY_POLICY", policyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: ["s3:GetObjectXX", "iam:PassRole"], Resource: "*" }] }) }));
    r.noNew = await rest("POST", "/policy/check-no-new-access", JSON.stringify({ policyType: "IDENTITY_POLICY", newPolicyDocument: POLICY0("s3:PutObject"), existingPolicyDocument: POLICY0("s3:GetObject") }));
    r.bkt_name = bkt; r.stats = T.stats();
    function POLICY0(act) { return JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: act, Resource: "*" }] }); }
    return r;
  }, SFX);
  const decs = {}; for (const m of a.sim.t.matchAll(/<EvalActionName>([^<]+)<\/EvalActionName><EvalResourceName>([^<]+)<\/EvalResourceName><EvalDecision>([^<]+)</g)) decs[m[1] + "@" + m[2]] = m[3];
  check("AWS SimulatePrincipalPolicy in the browser (enforcement OFF): explicitDeny / allowed / implicitDeny from the engine, MatchedStatements with positions",
    a.sim.s === 200 && decs["s3:GetObject@arn:aws:s3:::secret/x"] === "explicitDeny" && decs["s3:GetObject@arn:aws:s3:::open/x"] === "allowed" && decs["s3:PutObject@arn:aws:s3:::open/x"] === "implicitDeny" && /<StartPosition><Line>\d+<\/Line>/.test(a.sim.t), a.sim.t.slice(0, 300));
  check("AWS GetContextKeysForCustomPolicy: s3:prefix", a.ctx.s === 200 && /<member>s3:prefix<\/member>/.test(a.ctx.t), a.ctx.t.slice(0, 200));
  const f = a.find.j && (a.find.j.findings || []).find((x) => x.resource === "arn:aws:s3:::" + a.bkt_name);
  check("AWS Access Analyzer REST: CreateAnalyzer 200, ListFindings reports the public bucket policy (isPublic, AWS::S3::Bucket, principal {AWS:*})",
    a.mk.s === 200 && a.find.s === 200 && f && f.isPublic === true && f.resourceType === "AWS::S3::Bucket" && f.principal.AWS === "*", a.find.t.slice(0, 300));
  const codes = ((a.val.j || {}).findings || []).map((x) => x.issueCode);
  check("AWS ValidatePolicy: INVALID_ACTION (catalog fetched lazily) + PASS_ROLE_WITH_STAR_IN_RESOURCE; CheckNoNewAccess FAIL (PutObject is new)",
    a.val.s === 200 && codes.includes("INVALID_ACTION") && codes.includes("PASS_ROLE_WITH_STAR_IN_RESOURCE") && a.noNew.j && a.noNew.j.result === "FAIL", JSON.stringify([codes, a.noNew.t.slice(0, 160)]));
  check("AWS: engine mounted once, no engine errors", a.stats.engine_mounts === 1 && a.stats.errors === 0, JSON.stringify(a.stats));

  // =============================================================================================================== GCP (path B)
  const g = await ev(async () => {
    const r = {}, P = "nano-project", who = "user:ts@x.com";
    r.bkt = (await T.g("POST", "/storage/v1/b?project=" + P, { name: "gtb" })).s;
    r.set = (await T.g("POST", "/v1/projects/" + P + ":setIamPolicy", { policy: { bindings: [{ role: "roles/storage.objectViewer", members: [who] }] } })).s;
    const tup = (perm) => ({ accessTuple: { principal: who, fullResourceName: "//cloudresourcemanager.googleapis.com/projects/" + P, permission: perm } });
    r.v1 = await T.g("POST", "/v1/iam:troubleshoot", tup("storage.objects.get"));
    r.v1no = await T.g("POST", "/v1/iam:troubleshoot", tup("storage.objects.delete"));
    r.v3 = await T.g("POST", "/v3/iam:troubleshoot", tup("storage.objects.get"));
    r.bad = (await T.g("POST", "/v1/iam:troubleshoot", tup("storage.objects.nope"))).s;
    r.an = await T.g("GET", "/v1/projects/" + P + ":analyzeIamPolicy?analysisQuery.identitySelector.identity=" + encodeURIComponent(who));
    r.stats = T.stats();
    return r;
  });
  const j = (x) => { try { return JSON.parse(x.t); } catch (_) { return {}; } };
  const pol1 = (j(g.v1).explainedPolicies || []).find((p) => /projects\/nano-project$/.test(p.fullResourceName));
  check("GCP Policy Troubleshooter v1: GRANTED for the project binding (per-binding GRANTED, memberships), NOT_GRANTED for a permission the role lacks, 400 for an unknown permission",
    g.set === 200 && j(g.v1).access === "GRANTED" && pol1 && pol1.bindingExplanations[0].access === "GRANTED" && pol1.bindingExplanations[0].memberships["user:ts@x.com"].membership === "MEMBERSHIP_INCLUDED"
    && j(g.v1no).access === "NOT_GRANTED" && g.bad === 400, JSON.stringify([g.set, j(g.v1).access, j(g.v1no).access, g.bad, g.bad === 400 ? "" : "", Object.keys(pol1 || {}), JSON.stringify(((pol1 || {}).bindingExplanations || [{}])[0].memberships)]));
  check("GCP Policy Troubleshooter v3: overallAccessState CAN_ACCESS with allow/deny/PAB explanations", j(g.v3).overallAccessState === "CAN_ACCESS" && j(g.v3).denyPolicyExplanation && j(g.v3).pabPolicyExplanation, g.v3.t.slice(0, 200));
  const roles = ((j(g.an).mainAnalysis || {}).analysisResults || []).map((r) => r.iamBinding.role);
  check("GCP analyzeIamPolicy: identity query returns the objectViewer binding attached to the project", g.an.s === 200 && roles.length === 1 && roles[0] === "roles/storage.objectViewer", g.an.t.slice(0, 300));
  check("GCP: no engine errors", g.stats.errors === 0, JSON.stringify(g.stats));

  // =============================================================================================================== Azure (ARM through /_wire, path B)
  const z = await ev(async ({ AZ_SC, AZ_READER, OID_R }) => {
    const r = {}, rg = AZ_SC + "/resourcegroups/rgan";
    r.rg = (await T.g("PUT", rg + "?api-version=2021-04-01", { location: "eastus" })).s;
    r.ra = (await T.g("PUT", rg + "/providers/Microsoft.Authorization/roleAssignments/aaaaaaaa-0000-0000-0000-0000000000a1?api-version=2022-04-01",
      { properties: { roleDefinitionId: AZ_SC + "/providers/Microsoft.Authorization/roleDefinitions/" + AZ_READER, principalId: OID_R, principalType: "User", scope: rg } })).s;
    r.ca = await T.g("POST", rg + "/providers/Microsoft.Authorization/checkAccess?api-version=2018-09-01-preview", { Subject: { Attributes: { ObjectId: OID_R } },
      Actions: [{ Id: "Microsoft.Compute/virtualMachines/read", IsDataAction: false }, { Id: "Microsoft.Compute/virtualMachines/write", IsDataAction: false }], Resource: { Id: rg } });
    r.pm = await T.g("GET", rg + "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01", undefined, T.jwt({ oid: OID_R }));
    r.fl = await T.g("GET", rg + "/providers/Microsoft.Authorization/roleAssignments?$filter=" + encodeURIComponent("principalId eq '" + OID_R + "'") + "&api-version=2022-04-01");
    r.el = await T.g("GET", rg + "/providers/Microsoft.Authorization/roleEligibilityScheduleInstances?api-version=2020-10-01");
    r.stats = T.stats();
    return r;
  }, { AZ_SC, AZ_READER, OID_R });
  const ca = j(z.ca);
  check("Azure checkAccess (native PascalCase body -> bare array): read Allowed with the role assignment, write NotAllowed", z.ra === 201 && Array.isArray(ca) && ca[0].accessDecision === "Allowed" && ca[1].accessDecision === "NotAllowed"
    && ca[0].roleAssignment && ca[0].roleAssignment.roleDefinitionId.endsWith(AZ_READER) && ca[0].timeToLiveInMs === 300000, z.ca.t.slice(0, 300));
  check("Azure effective permissions (Microsoft.Authorization/permissions) for the Reader: */read; $filter=principalId eq lists the assignment; eligibility instances answer {value:[]}",
    z.pm.s === 200 && JSON.stringify(j(z.pm).value[0].actions) === '["*/read"]' && z.fl.s === 200 && j(z.fl).value.length === 1 && j(z.fl).value[0].properties.principalId === OID_R && z.el.s === 200 && Array.isArray(j(z.el).value), JSON.stringify([z.pm.t.slice(0, 120), z.fl.t.slice(0, 120)]));
  check("Azure: no engine errors, built-in role catalog fetched lazily", z.stats.errors === 0, JSON.stringify(z.stats));

  // =============================================================================================================== path A: the same Access Analyzer / checkAccess through a real local relay -> relay SharedWorker
  const relayUp = await startRelay();
  check("path A: local relay copy started on :" + RELAY_PORT + " (own port; the owner's tunnel is untouched)", relayUp);
  if (relayUp) {
    await ev(async (port) => {
      const w = new SharedWorker(T.BASE + "/relay/relay-shared-worker.js?v=4", { type: "module", name: "iam-analyze-relay" });
      w.port.start();
      w.port.postMessage({ type: "start", session: "iam-analyze", noIdle: true, config: { localHealth: `http://127.0.0.1:${port}/health`, localWs: `ws://127.0.0.1:${port}/register`, localExternal: `http://127.0.0.1:${port}`,
        cloudWsBase: "wss://invalid.invalid/register", cloudExternal: "https://invalid.invalid" } });
      globalThis.__relayPort = w.port;
      return true;
    }, RELAY_PORT);
    let booted = false;
    for (let i = 0; i < 240 && !booted; i++) { const r = await relayCall("GET", "/", { authorization: SIG("AKIAVYOMIDUMMY", "s3") }).catch(() => ({ s: 0 })); booted = r.s === 200; if (!booted) await new Promise((r) => setTimeout(r, 500)); }
    check("path A: relay SharedWorker (own Pyodide) booted and serves a root S3 list", booted);
    if (booted) {
      const rv = await relayCall("POST", "/policy/validation", { authorization: SIG("AKIAVYOMIDUMMY", "access-analyzer"), "content-type": "application/json" },
        JSON.stringify({ policyType: "IDENTITY_POLICY", policyDocument: JSON.stringify({ Statement: [{ Effect: "Allow", Action: "s3:Nope", Resource: "*" }] }) }));
      const rt = await relayCall("POST", "/v1/iam:troubleshoot", { "content-type": "application/json", authorization: "Bearer " + JWT({ email: "ts@x.com" }) },
        JSON.stringify({ accessTuple: { principal: "user:ts@x.com", fullResourceName: "//cloudresourcemanager.googleapis.com/projects/nano-project", permission: "storage.objects.get" } }));
      const rc = await relayCall("POST", `${AZ_SC}/resourcegroups/rgan/providers/Microsoft.Authorization/checkAccess?api-version=2018-09-01-preview`, { "content-type": "application/json", authorization: "Bearer " + JWT({ oid: OID_R }) },
        JSON.stringify({ Subject: { Attributes: { ObjectId: OID_R } }, Actions: [{ Id: "Microsoft.Compute/virtualMachines/read" }], Resource: { Id: AZ_SC + "/resourcegroups/rgan" } }));
      const jj = (x) => { try { return JSON.parse(x.t); } catch (_) { return null; } };
      check("path A (relay SDK/CLI traffic): Access Analyzer ValidatePolicy -> INVALID_ACTION; GCP troubleshoot -> GRANTED; Azure checkAccess -> Allowed",
        rv.s === 200 && jj(rv).findings.some((x) => x.issueCode === "INVALID_ACTION") && rt.s === 200 && jj(rt).access === "GRANTED" && rc.s === 200 && jj(rc)[0].accessDecision === "Allowed",
        JSON.stringify([rv.s, rv.t.slice(0, 120), rt.s, rt.t.slice(0, 120), rc.s, rc.t.slice(0, 120)]));
    }
  }
} catch (err) { console.log("FAIL  harness:", err.stack || err.message); results.push(false); }
if (relayProc) relayProc.kill();
await browser.close(); server.close();
const ok = results.length > 0 && results.every(Boolean);
console.log(`\nRESULT: ${ok ? "PASS" : "FAIL"} (${results.filter(Boolean).length}/${results.length})`);
process.exit(ok ? 0 : 1);
