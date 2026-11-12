/* Credentials (the AWS-CLI model): ~/.vyomi/credentials -> signed exchange -> session; every command needs a key; Mesh needs Pro/Max. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseIni, loadCredentials, fetchSession, createSessionManager, sign, TunnelAuthError, NO_CREDENTIALS } from "./credentials.mjs";
import { startStubPortal } from "./test-fixtures/stub-portal.mjs";

// INI + env
const ini = parseIni("; c\n[default]\nvyomi_access_key_id = VYKAPRO ; trailing\nvyomi_secret_access_key=pro-secret\n[work]\nvyomi_access_key_id = W\nvyomi_secret_access_key = S\ngithub_token = ghp_x\n");
assert.equal(ini.default.vyomi_access_key_id, "VYKAPRO"); assert.equal(ini.work.github_token, "ghp_x");
const file = (txt) => () => txt;
assert.equal(loadCredentials({ env: {}, read: () => { throw new Error("none"); } }), null);
let c = loadCredentials({ env: {}, read: file("[default]\nvyomi_access_key_id=A\nvyomi_secret_access_key=B\n") }); assert.deepEqual([c.accessKeyId, c.secretAccessKey, c.portal], ["A", "B", "https://vyomi.cloud"]);
c = loadCredentials({ env: { VYOMI_PROFILE: "work" }, read: file("[work]\nvyomi_access_key_id=W\nvyomi_secret_access_key=S\ngithub_token=ghp_x\nportal=https://p.example/") }); assert.deepEqual([c.accessKeyId, c.githubToken, c.portal], ["W", "ghp_x", "https://p.example"]);
c = loadCredentials({ env: { VYOMI_ACCESS_KEY_ID: "E", VYOMI_SECRET_ACCESS_KEY: "F" }, read: file("[default]\nvyomi_access_key_id=A\nvyomi_secret_access_key=B") }); assert.equal(c.accessKeyId, "E");   // env wins
assert.equal(sign({ secret: "s", method: "POST", path: "/p", date: "d", body: "b" }), sign({ secret: "s", method: "POST", path: "/p", date: "d", body: "b" }));
assert.notEqual(sign({ secret: "s", method: "POST", path: "/p", date: "d", body: "b" }), sign({ secret: "s", method: "POST", path: "/p", date: "d", body: "B" }));

const portal = await startStubPortal({ codespace: "vyomi-mesh-stub", sessionEnd: Math.floor(Date.now() / 1000) + 3600 });
const cred = (id, secret) => ({ accessKeyId: id, secretAccessKey: secret, portal: portal.url, githubToken: "" });
// pro key: session with Codespace, GitHub token, session end
const s = await fetchSession({ creds: cred("VYKAPRO", "pro-secret") });
assert.deepEqual([s.tier, s.meshAllowed, s.codespace, s.githubToken], ["pro", true, "vyomi-mesh-stub", "gho_stub"]); assert.ok(s.sessionEnd > Date.now() / 1000);
// free key: valid (Nano ok) but Mesh not allowed
const f = await fetchSession({ creds: cred("VYKAFREE", "free-secret") }); assert.deepEqual([f.tier, f.meshAllowed, f.codespace], ["free", false, ""]);
// errors, with friendly messages
const code = async (cr, o) => fetchSession({ creds: cr, ...o }).then(() => "ok", (e) => e.code);
assert.equal(await code(cred("NOPE", "x")), "InvalidAccessKey");
assert.equal(await code(cred("VYKAPRO", "wrong")), "SignatureMismatch");
assert.equal(await code(cred("VYKAREVOKED", "r")), "KeyRevoked");
assert.equal(await code(cred("VYKAPRO", "pro-secret"), { now: () => new Date(Date.now() - 3600000) }), "RequestTimeSkew");
assert.equal(await code({ ...cred("VYKAPRO", "pro-secret"), portal: "http://127.0.0.1:1" }), "Unreachable");
// manager: no credentials, caching, refresh
await assert.rejects(() => createSessionManager({ loader: () => null }).get(), (e) => e.code === "NoCredentials" && e.message === NO_CREDENTIALS);
const before = portal.calls.length; const m = createSessionManager({ loader: () => cred("VYKAPRO", "pro-secret") });
await m.get(); await m.get(); await m.get(); assert.equal(portal.calls.length, before + 1);                          // cached
const short = await startStubPortal({ ttl: 60 });                                                                                 // under the 120 s margin: every get() refreshes
const m2 = createSessionManager({ loader: () => ({ ...cred("VYKAPRO", "pro-secret"), portal: short.url }) });
await m2.get(); await m2.get(); assert.equal(short.calls.length, 2); short.close();
const ended = await startStubPortal({ sessionEnd: Math.floor(Date.now() / 1000) - 5 });
await assert.rejects(() => createSessionManager({ loader: () => ({ ...cred("VYKAPRO", "pro-secret"), portal: ended.url }) }).get(), (e) => e.code === "SessionEnded"); ended.close();

// the CLI: nothing at all without a key (Nano included); Free key = Nano only; Pro key = Mesh passes the gate
const bin = new URL("../../packaging/tunnel/bin/vyomi-tunnel.mjs", import.meta.url).pathname;
const home = mkdtempSync(join(tmpdir(), "vtc-"));
const run = (args, env = {}) => new Promise((res) => {                       // async: the stub portal lives in this process
  const c = spawn(process.execPath, [bin, ...args], { env: { ...process.env, VYOMI_HOME: home, VYOMI_PORTAL_URL: portal.url, RELAY_PORT: "8999", HOME: home, ...env } });
  let stdout = "", stderr = ""; c.stdout.on("data", (d) => { stdout += d; }); c.stderr.on("data", (d) => { stderr += d; });
  const t = setTimeout(() => c.kill(), 40000); c.on("close", (status) => { clearTimeout(t); res({ status, stdout, stderr }); });
});
for (const a of [["list"], ["list", "nano"], ["list", "nano", "vm"], ["list", "mesh"], ["connect", "host"], ["forward", "k3s", "6443:6443"]]) {
  const r = await run(a); assert.equal(r.status, 2, a.join(" ")); assert.match(r.stderr, /No Vyomi credentials/); assert.equal(r.stdout.trim(), "", "no details without a key: " + a.join(" "));
}
const rl = await run([], { RELAY_PORT: "8998" }); assert.equal(rl.status, 2); assert.match(rl.stderr, /No Vyomi credentials/);               // the relay refuses to start
const lg = await run(["login"]); assert.equal(lg.status, 2); assert.match(lg.stderr, /no login/);
const free = { VYOMI_ACCESS_KEY_ID: "VYKAFREE", VYOMI_SECRET_ACCESS_KEY: "free-secret" };
const fn = await run(["list", "nano", "--json"], free); assert.equal(fn.status, 1);                                                                      // valid key; just nothing running -> no targets
assert.ok(Array.isArray(JSON.parse(fn.stdout).targets));
for (const a of [["nano", "vm"], ["nano", "vms"], ["nano", "db"], ["nano", "dbs"], ["nano", "api"], ["vms"], ["all"], ["mesh", "k3s"]]) assert.ok(Array.isArray(JSON.parse((await run(["list", ...a, "--json"], free)).stdout).targets), "list " + a.join(" "));
for (const a of [["nano", "k3s"], ["mesh", "vm"], ["all", "vm"], ["bogus"]]) assert.equal((await run(["list", ...a], free)).status, 2, "list " + a.join(" "));      // wrong type for the scope
const fm = await run(["list", "mesh", "--json"], free); assert.match(JSON.parse(fm.stdout).notes.join(" "), /Pro or Max/);               // free key: Mesh refused
const ff = await run(["forward", "k3s", "6443:6443"], free); assert.equal(ff.status, 1); assert.match(ff.stderr, /Pro or Max/);
writeFileSync(join(home, "credentials"), "[default]\nvyomi_access_key_id = VYKAPRO\nvyomi_secret_access_key = wrong\n");
assert.match((await run(["list", "nano"])).stderr, /secret key does not match/);                                                           // the file is read, signature checked
portal.close(); console.log("tunnel credentials: all checks passed"); process.exit(0);
