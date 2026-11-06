/* Booster outbound-link test: relay (local-relay.mjs) + booster-dial.mjs + a fake local simulator.
 *   NODE_PATH=/tmp/np/node_modules:<...>/portal-OLD/node_modules RELAY_PORT=8792 node wasm/relay/test-booster-link.mjs
 * Proves: valid token pairs; bad/expired/foreign token rejected; wrong Origin rejected; session_end closes the link;
 * existing (token-less) relay behaviour untouched. Exit 1 on any FAIL. */
import http from "node:http";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mint } from "./booster-session.mjs";
import { dial } from "./booster-dial.mjs";

const require = createRequire(import.meta.url);
const WS = require(process.env.WS_PKG || "ws");
const here = dirname(fileURLToPath(import.meta.url));
const RELAY = Number(process.env.RELAY_PORT || 8792), SIM = RELAY + 1;
const KEY = "relay-test-key-abcdef";
const relayHttp = `http://127.0.0.1:${RELAY}`, relayWs = `ws://127.0.0.1:${RELAY}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowS = () => Math.floor(Date.now() / 1000);
const tok = (o = {}) => mint(o.key ?? KEY, { sub: "acct-1", tier: "pro", primary_cloud: "aws", session_id: "sess-1", session_end: nowS() + 3600, ...o });

// fake local simulator: echoes what it received and demands the session token
const seen = [];
const sim = http.createServer((req, res) => {
  const chunks = []; req.on("data", (c) => chunks.push(c)); req.on("end", () => {
    seen.push({ url: req.url, method: req.method, token: req.headers["x-vyomi-session-token"], body: Buffer.concat(chunks).toString() });
    res.writeHead(200, { "content-type": "application/json", "x-sim": "1" });
    res.end(JSON.stringify({ echo: req.url, method: req.method, body: Buffer.concat(chunks).toString() }));
  });
}).listen(SIM, "127.0.0.1");

const relay = spawn(process.execPath, [join(here, "local-relay.mjs")], {
  env: { ...process.env, RELAY_PORT: String(RELAY), RELAY_HOST: "127.0.0.1", VYOMI_BOOSTER_SESSION_KEY: KEY }, stdio: ["ignore", "pipe", "pipe"] });
let relayLog = ""; relay.stdout.on("data", (d) => (relayLog += d)); relay.stderr.on("data", (d) => (relayLog += d));
const cleanup = () => { try { relay.kill(); } catch {} try { sim.close(); } catch {} };
process.on("exit", cleanup);
for (let i = 0; i < 50; i++) { try { if ((await fetch(relayHttp + "/health")).ok) break; } catch {} await sleep(100); }

const call = (path, headers = {}, init = {}) => fetch(relayHttp + path, { headers, ...init }).then(async (r) => ({ status: r.status, h: r.headers, text: await r.text() }));
const rawDial = (headers) => new Promise((resolve) => {
  const ws = new WS(`${relayWs}/booster`, { headers });
  ws.on("open", () => resolve({ opened: true, ws }));
  ws.on("unexpected-response", (_q, res) => resolve({ opened: false, status: res.statusCode }));
  ws.on("error", () => {});
});

const health = await (await fetch(relayHttp + "/health")).json();
check("relay advertises booster-link when a session key is set", health.features.includes("booster-link"), JSON.stringify(health.features));

// ── existing behaviour untouched
let r = await call("/anything");
check("token-less request still takes the Nano-tab path (503 no tab)", r.status === 503 && /no Nano tab/.test(r.text), `${r.status} ${r.text}`);

// existing Nano-tab round trip still works end to end
const tab = new WS(`${relayWs}/register`);
await new Promise((res) => tab.on("open", res));
tab.on("message", (m) => { const q = JSON.parse(m.toString()); if (q.id) tab.send(JSON.stringify({ id: q.id, status: 201, headers: { "x-tab": "1" }, body: Buffer.from("from-tab").toString("base64") })); });
r = await call("/plain/path");
check("Nano tab round trip unchanged (token-less request answered by the registered tab)", r.status === 201 && r.text === "from-tab" && r.h.get("x-tab") === "1", `${r.status} ${r.text}`);
tab.close();

// ── dial refusals
let d = await rawDial({ authorization: "Bearer " + tok({ key: "wrong-key" }) });
check("dial with a token signed by another key -> 401", !d.opened && d.status === 401, JSON.stringify(d.status));
d = await rawDial({ authorization: "Bearer not.a.token" });
check("dial with garbage token -> 401", !d.opened && d.status === 401, d.status);
d = await rawDial({});
check("dial with no token -> 401", !d.opened && d.status === 401, d.status);
d = await rawDial({ authorization: "Bearer " + tok({ session_end: nowS() - 5, iat: nowS() - 100 }) });
check("dial with an EXPIRED token -> 410", !d.opened && d.status === 410, d.status);
d = await rawDial({ authorization: "Bearer " + tok({ tier: "free" }) });
check("dial with a Free-tier token -> 403", !d.opened && d.status === 403, d.status);
d = await rawDial({ authorization: "Bearer " + tok(), origin: "https://evil.example" });
check("dial from a wrong Origin -> 403", !d.opened && d.status === 403, d.status);

// ── valid pairing
const token = tok();
const link = dial({ relayUrl: relayWs, token, localUrl: `http://127.0.0.1:${SIM}`, WS, log: () => {} });
for (let i = 0; i < 50 && !link.state.linked; i++) await sleep(100);
check("valid token: booster links (outbound WSS dial)", link.state.linked === true);
check("relay reports one linked booster session", (await (await fetch(relayHttp + "/health")).json()).booster_sessions === 1);

r = await call("/ec2?x=1", { "x-vyomi-session-token": token }, { method: "POST", body: "payload-bytes" });
let echo = {}; try { echo = JSON.parse(r.text); } catch {}
check("client with the session token is paired: request reaches the booster's simulator and the answer returns",
      r.status === 200 && echo.echo === "/ec2?x=1" && echo.method === "POST" && echo.body === "payload-bytes" && r.h.get("x-sim") === "1", `${r.status} ${r.text}`);
check("booster presents the session token to its local simulator", seen.at(-1)?.token === token);

r = await call("/s3", { "x-vyomi-session-token": token, origin: "https://vyomi.cloud" });
check("Nano origin https://vyomi.cloud allowed (CORS echoed)", r.status === 200 && r.h.get("access-control-allow-origin") === "https://vyomi.cloud", `${r.status} ${r.h.get("access-control-allow-origin")}`);
r = await call("/s3", { "x-vyomi-session-token": token, origin: "https://evil.example" });
check("client from a wrong Origin -> 403", r.status === 403 && /OriginNotAllowed/.test(r.text), `${r.status} ${r.text}`);
r = await call("/s3", { "x-vyomi-session-token": tok({ key: "wrong-key" }) });
check("client with a bad token -> 401", r.status === 401 && /BadSignature/.test(r.text), `${r.status} ${r.text}`);
r = await call("/s3", { "x-vyomi-session-token": tok({ session_id: "other-session" }) });
check("client with a valid token for a session with no booster -> 502 BoosterNotLinked", r.status === 502 && /BoosterNotLinked/.test(r.text), `${r.status} ${r.text}`);
r = await call("/s3", { "x-vyomi-session-token": tok({ sub: "someone-else" }) });
check("client token for the same session id but another account -> 403", r.status === 403 && /Mismatch/.test(r.text), `${r.status} ${r.text}`);
r = await call("/s3", { "x-vyomi-session-token": tok({ session_end: nowS() - 5, iat: nowS() - 100 }) });
check("client with an expired token -> 410", r.status === 410, r.status);
link.stop(); await sleep(300);
r = await call("/s3", { "x-vyomi-session-token": token });
check("after the booster disconnects the session is not linked (502)", r.status === 502, r.status);

// ── session_end closes the link (both sides)
const endsIn = 3;
const t2 = tok({ session_id: "sess-end", session_end: nowS() + endsIn });
const link2 = dial({ relayUrl: relayWs, token: t2, localUrl: `http://127.0.0.1:${SIM}`, WS, log: () => {} });
for (let i = 0; i < 50 && !link2.state.linked; i++) await sleep(100);
check("short session links", link2.state.linked === true);
r = await call("/x", { "x-vyomi-session-token": t2 });
check("short session serves before session_end", r.status === 200, r.status);
const why = await Promise.race([link2.done, sleep((endsIn + 3) * 1000).then(() => "timeout")]);
check("booster connector exits at session_end", why === "session_end", why);
r = await call("/x", { "x-vyomi-session-token": t2 });
check("relay refuses the session after session_end (410)", r.status === 410, `${r.status} ${r.text}`);
check("relay dropped the booster link at session_end", (await (await fetch(relayHttp + "/health")).json()).booster_sessions === 0);
d = await rawDial({ authorization: "Bearer " + t2 });
check("re-dial after session_end refused (410)", !d.opened && d.status === 410, d.status);

// ── the RELAY closes a link at session_end by itself (a booster that never hangs up)
const t4 = tok({ session_id: "sess-raw", session_end: nowS() + 2 });
const raw = await rawDial({ authorization: "Bearer " + t4 });
check("raw (non-cooperating) booster links", raw.opened === true);
const closedBy = await Promise.race([new Promise((res) => raw.ws.on("close", (code) => res(code))), sleep(5000).then(() => "timeout")]);
check("relay itself closes the link at session_end (4000)", closedBy === 4000, closedBy);

// ── refused dial: connector stops instead of hammering the relay
const link3 = dial({ relayUrl: relayWs, token: tok({ key: "wrong-key" }), localUrl: `http://127.0.0.1:${SIM}`, WS, log: () => {} });
const why3 = await Promise.race([link3.done, sleep(4000).then(() => "timeout")]);
check("connector gives up when the relay refuses its token", why3 === "refused-401", why3);

cleanup();
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
