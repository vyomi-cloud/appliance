/* Keeper unit test with a fake ssh (a node child that records what it receives).  node wasm/relay/test-keeper.mjs */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { keep, sshArgs } from "./keeper.mjs";

let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "keeper-"));
const rec = path.join(dir, "rec.txt");

// fake "ssh": appends a line per connect, then every stdin line; FAIL=1 exits at once (like a refused connect); DIE=ms exits after.
const script = `const fs=require("fs");fs.appendFileSync(${JSON.stringify(rec)},"CONNECT "+process.argv.slice(3).join(" ")+"\\n");
if(process.env.FAIL){process.stderr.write("Permission denied\\n");process.exit(255)}
process.stdin.on("data",d=>fs.appendFileSync(${JSON.stringify(rec)},"IN "+d));
if(process.env.DIE)setTimeout(()=>process.exit(1),Number(process.env.DIE));
process.stdin.on("end",()=>process.exit(0));`;
const fake = (extraEnv = {}) => (_c, args, o) => spawn(process.execPath, ["-e", script, "--", ...args], { ...o, env: { ...process.env, ...extraEnv } });
const lines = () => { try { return fs.readFileSync(rec, "utf8").split("\n").filter(Boolean); } catch { return []; } };
const reset = () => { try { fs.rmSync(rec); } catch { /* none */ } };

// 1. argv: target host, ProxyCommand, key, batch mode, no token anywhere
const a = sshArgs({ user: "vscode", key: "/k/id", proxy: "vyomi-tunnel connect codespace" });
check("ssh targets codespace.vyomi", a.includes("vscode@codespace.vyomi"));
check("ProxyCommand + key + BatchMode set", a.includes("ProxyCommand=vyomi-tunnel connect codespace") && a.includes("/k/id") && a.includes("BatchMode=yes"));

// 2. writes on a schedule over ONE held session
reset();
let k = keep({ spawnFn: fake(), proxy: "p", settleMs: 20, intervalMs: 120, jitter: 0 });
await sleep(900);
k.stop(); const s2 = await k.done;
const ins = lines().filter((l) => l.startsWith("IN "));
check("one held session (single CONNECT)", lines().filter((l) => l.startsWith("CONNECT")).length === 1);
check("writes repeat every interval (>=5 in 900 ms)", ins.length >= 5, ins.length);
check("each write is a keepalive line", ins.every((l) => /vyomi-keepalive \d{4}-/.test(l)));
check("status reports alive writes then stopped", s2.writes >= 5 && s2.state === "stopped" && s2.reason === "stopped", JSON.stringify(s2));

// 3. reconnects after the session drops, with back-off
reset();
k = keep({ spawnFn: fake({ DIE: "700" }), proxy: "p", settleMs: 20, intervalMs: 100, jitter: 0, backoffMs: [50] });
await sleep(2600);
k.stop(); await k.done;
check("reconnects after a dropped session", lines().filter((l) => l.startsWith("CONNECT")).length >= 2, lines().filter((l) => l.startsWith("CONNECT")).length);

// 4. gives up after maxFailures refused connects
reset();
const log = []; 
k = keep({ spawnFn: fake({ FAIL: "1" }), proxy: "p", settleMs: 20, intervalMs: 100, maxFailures: 3, backoffMs: [20], log: (m) => log.push(m) });
const s4 = await k.done;
check("stops after maxFailures with a reason", s4.state === "stopped" && /too many/.test(s4.reason || ""), JSON.stringify(s4));
check("exactly maxFailures connect attempts", lines().filter((l) => l.startsWith("CONNECT")).length === 3);
check("failure log carries ssh's message", log.some((m) => /Permission denied/.test(m)));

// 5. stops at session_end by itself
reset();
k = keep({ spawnFn: fake(), proxy: "p", settleMs: 20, intervalMs: 80, jitter: 0, sessionEndMs: Date.now() + 700 });
const s5 = await Promise.race([k.done, sleep(4000).then(() => null)]);
check("stops at session_end on its own", s5 && s5.state === "stopped" && s5.reason === "session ended", JSON.stringify(s5));

// 6. observer errors never stop it; token never appears in args/logs
reset();
const seen = []; 
k = keep({ spawnFn: fake(), proxy: "vyomi-tunnel connect codespace", settleMs: 20, intervalMs: 80, jitter: 0, onStatus: () => { throw new Error("boom"); }, log: (m) => seen.push(m), env: { ...process.env, VYOMI_SESSION_TOKEN: "v1.SECRET.sig" } });
await sleep(500); k.stop(); await k.done;
check("a throwing status observer does not stop writes", lines().filter((l) => l.startsWith("IN ")).length >= 2);
check("token never in ssh args or log", !lines().join("\n").includes("SECRET") && !seen.join("\n").includes("SECRET"));

console.log(bad ? `\n${bad} FAILED` : "\nALL PASS");
process.exit(bad ? 1 : 0);
