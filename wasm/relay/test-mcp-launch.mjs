/* `vyomi-tunnel mcp` launcher (mcp-launch.mjs) against the packaged entry (packaging/tunnel/bin), in a temp copy of the package.
 *   WS_PKG=<path to ws> node --test wasm/relay/test-mcp-launch.mjs        (needs `go` for L1-26; skipped without it)
 * L1-26 no key: starts and answers initialize. L1-27 PATH fallback with VYOMI_TUNNEL_BIN; bundled binary at 0644 gets 0755 back.
 * L1-28 nothing found: exit 127, one stderr line, empty stdout. Plus: exit code and SIGTERM pass through. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const posix = process.platform !== "win32";
const plat = `${process.platform}-${process.arch}`;

/** A temp copy of packaging/tunnel: {dir, entry, bundled, home, emptyPath}. */
function pkg() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "vt-mcp-"));
  fs.cpSync(path.join(root, "packaging/tunnel/bin"), path.join(dir, "bin"), { recursive: true });
  const home = path.join(dir, "home"); fs.mkdirSync(home);
  const emptyPath = path.join(dir, "emptybin"); fs.mkdirSync(emptyPath);
  return { dir, entry: fs.realpathSync(path.join(dir, "bin/vyomi-tunnel.mjs")), bundled: path.join(dir, "mcp", plat, "vyomi-mcp" + (posix ? "" : ".exe")), home, emptyPath };
}
/** env with no Vyomi key anywhere: temp HOME/VYOMI_HOME, key vars removed. */
function env(p, extra = {}) {
  const e = { ...process.env, HOME: p.home, VYOMI_HOME: path.join(p.home, ".vyomi"), USERPROFILE: p.home, ...extra };
  for (const k of ["VYOMI_ACCESS_KEY_ID", "VYOMI_SECRET_ACCESS_KEY", "VYOMI_PROFILE", "VYOMI_CREDENTIALS_FILE", "VYOMI_TUNNEL_BIN"]) delete e[k];
  return e;
}
function script(file, body) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, "#!/bin/sh\n" + body + "\n", { mode: 0o755 }); }
const run = (p, args, e, input = "") => spawnSync(process.execPath, [p.entry, ...args], { env: e, input, encoding: "utf8", timeout: 30000 });

test("L1-26: no credentials, the bundled vyomi-mcp starts and answers initialize + tools/list", { skip: spawnSync("go", ["version"]).status !== 0 && "go not installed" }, () => {
  const p = pkg();
  const b = spawnSync("go", ["build", "-o", p.bundled, "."], { cwd: path.join(root, "cmd/vyomi"), env: { ...process.env, CGO_ENABLED: "0" }, encoding: "utf8", timeout: 300000 });
  assert.equal(b.status, 0, b.stderr);
  const e = env(p, { PATH: [p.emptyPath, path.dirname(process.execPath)].join(path.delimiter) });
  assert.ok(!fs.existsSync(path.join(p.home, ".vyomi/credentials")));
  const req = [{ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "t", version: "0" } } },
               { jsonrpc: "2.0", method: "notifications/initialized" }, { jsonrpc: "2.0", id: 2, method: "tools/list" }].map((m) => JSON.stringify(m)).join("\n") + "\n";
  const r = run(p, ["mcp"], e, req);
  assert.equal(r.status, 0, r.stderr);
  const lines = r.stdout.trim().split("\n").map((l) => JSON.parse(l));          // every stdout line is protocol: nothing else was printed
  assert.equal(lines[0].id, 1); assert.ok(lines[0].result.serverInfo.name, JSON.stringify(lines[0]));
  const tools = lines.find((l) => l.id === 2).result.tools.map((t) => t.name);
  for (const t of ["vyomi_status", "vyomi_env", "vyomi_reach", "vyomi_capability", "vyomi_snippet"]) assert.ok(tools.includes(t), t);
});

test("L1-27a: no bundled binary -> vyomi-mcp on PATH, with VYOMI_TUNNEL_BIN = this install's entry", { skip: !posix && "sh fakes" }, () => {
  const p = pkg(); const fake = path.join(p.dir, "pathbin");
  script(path.join(fake, "vyomi-mcp"), `echo "argv=$*" >&2; echo "bin=$VYOMI_TUNNEL_BIN" >&2; /bin/cat >/dev/null`);
  script(path.join(fake, "vyomi"), `echo "WRONG vyomi $*" >&2`);
  const r = run(p, ["mcp", "--x"], env(p, { PATH: [fake, path.dirname(process.execPath)].join(path.delimiter) }));
  assert.equal(r.status, 0, r.stderr); assert.equal(r.stdout, "");
  assert.match(r.stderr, /argv=--x/); assert.ok(r.stderr.includes("bin=" + p.entry), r.stderr); assert.doesNotMatch(r.stderr, /WRONG/);
});

test("L1-27a': no bundled binary and no vyomi-mcp -> `vyomi mcp` on PATH", { skip: !posix && "sh fakes" }, () => {
  const p = pkg(); const fake = path.join(p.dir, "pathbin");
  script(path.join(fake, "vyomi"), `echo "vyomi-argv=$*" >&2`);
  const r = run(p, ["mcp", "--x"], env(p, { PATH: fake }));
  assert.equal(r.status, 0, r.stderr); assert.match(r.stderr, /vyomi-argv=mcp --x/); assert.equal(r.stdout, "");
});

test("L1-27b: bundled binary at mode 0644 -> launcher restores 0755 and runs it (not the PATH one)", { skip: !posix && "exec bit" }, () => {
  const p = pkg(); const fake = path.join(p.dir, "pathbin");
  script(p.bundled, `echo "bundled $VYOMI_TUNNEL_BIN" >&2`); fs.chmodSync(p.bundled, 0o644);
  script(path.join(fake, "vyomi-mcp"), `echo "WRONG path binary" >&2`);
  const r = run(p, ["mcp"], env(p, { PATH: fake }));
  assert.equal(r.status, 0, r.stderr); assert.match(r.stderr, /^bundled /); assert.doesNotMatch(r.stderr, /WRONG/);
  assert.equal(fs.statSync(p.bundled).mode & 0o777, 0o755);
});

test("L1-28: nothing available -> exit 127, one stderr line naming the fix, nothing on stdout", () => {
  const p = pkg();
  const r = run(p, ["mcp"], env(p, { PATH: p.emptyPath }));
  assert.equal(r.status, 127); assert.equal(r.stdout, "");
  const lines = r.stderr.trim().split("\n"); assert.equal(lines.length, 1, r.stderr);
  assert.match(lines[0], /npm i -g vyomi-tunnel/); assert.match(lines[0], new RegExp(plat));
});

test("exit code and SIGTERM pass through", { skip: !posix && "signals" }, async () => {
  const p = pkg();
  script(p.bundled, `[ "$1" = exit7 ] && exit 7; trap 'exit 42' TERM; echo ready >&2; while :; do sleep 0.05; done`);
  assert.equal(run(p, ["mcp", "exit7"], env(p, { PATH: p.emptyPath })).status, 7);
  const c = spawn(process.execPath, [p.entry, "mcp"], { env: env(p, { PATH: "/usr/bin:/bin" }), stdio: ["pipe", "pipe", "pipe"] });
  let err = ""; c.stderr.on("data", (d) => { err += d; });
  for (let i = 0; i < 100 && !err.includes("ready"); i++) await new Promise((r) => setTimeout(r, 50));
  c.kill("SIGTERM");
  const code = await new Promise((r) => c.on("close", (code) => r(code)));
  assert.equal(code, 42, err);
});
