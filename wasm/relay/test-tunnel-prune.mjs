/* `vyomi-tunnel prune [--yes]`: stopped Mesh Codespaces are listed, and deleted only with --yes; a running Mesh, the current Mesh
 * (named by the Vyomi session), the newest Mesh and non-Mesh Codespaces are never touched. Fake gh records every call.
 *   node --test wasm/relay/test-tunnel-prune.mjs */
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { startStubPortal } from "./test-fixtures/stub-portal.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const bin = path.resolve(here, "../../packaging/tunnel/bin/vyomi-tunnel.mjs");
const portal = await startStubPortal({ codespace: "vyomi-mesh-current", meshState: "Shutdown" });
after(() => portal.close());

const CODESPACES = [
  { name: "vyomi-mesh-newest", state: "Shutdown", createdAt: "2026-11-19T00:00:00Z" },     // newest: kept
  { name: "vyomi-mesh-current", state: "Shutdown", createdAt: "2026-11-17T00:00:00Z" },    // the session's Mesh: kept
  { name: "vyomi-mesh-running", state: "Available", createdAt: "2026-11-16T00:00:00Z" },   // running: kept
  { name: "vyomi-mesh-old1", state: "Shutdown", createdAt: "2026-11-14T00:00:00Z" },       // deleted
  { name: "vyomi-mesh-old2", state: "Failed", createdAt: "2026-11-13T00:00:00Z" },         // deleted
  { name: "my-app-codespace", state: "Shutdown", createdAt: "2026-11-01T00:00:00Z" },      // not a Mesh: kept
];

function sandbox() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "vt-prune-")); const log = path.join(home, "gh.log");
  const gh = path.join(home, "fake-gh");
  fs.writeFileSync(gh, `#!/bin/sh
[ "$1" = --version ] && { echo 'gh version 2.99.0 (2026-01-01)'; exit 0; }
echo "$* token=$GH_TOKEN" >> ${log}
[ "$1 $2" = 'codespace list' ] && { cat <<'J'
${JSON.stringify(CODESPACES)}
J
exit 0; }
[ "$1 $2" = 'codespace delete' ] && exit 0
exit 1
`, { mode: 0o755 });
  return { home, gh, log };
}
const run = (sb, args, extra = {}) => new Promise((resolve) => {
  const env = { ...process.env, HOME: sb.home, USERPROFILE: sb.home, VYOMI_HOME: path.join(sb.home, ".vyomi"), VYOMI_PORTAL_URL: portal.url, VYOMI_GH: sb.gh,
    VYOMI_ACCESS_KEY_ID: "VYKAPRO", VYOMI_SECRET_ACCESS_KEY: "pro-secret", ...extra };
  for (const k of ["VYOMI_PROFILE", "VYOMI_CREDENTIALS_FILE", "GH_TOKEN", "GITHUB_TOKEN", "VYOMI_MESH_CODESPACE"]) delete env[k];
  const c = spawn(process.execPath, [bin, "prune", ...args], { env, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "", stderr = ""; c.stdout.on("data", (d) => { stdout += d; }); c.stderr.on("data", (d) => { stderr += d; });
  c.on("close", (status) => resolve({ status, stdout, stderr, calls: fs.existsSync(sb.log) ? fs.readFileSync(sb.log, "utf8").trim().split("\n") : [] }));
});

test("prune without --yes only lists the stopped Meshes it would delete", { skip: process.platform === "win32" && "sh fake gh" }, async () => {
  const sb = sandbox(); const r = await run(sb, []);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /vyomi-mesh-old1/); assert.match(r.stdout, /vyomi-mesh-old2/); assert.match(r.stdout, /prune --yes/);
  for (const keep of ["vyomi-mesh-newest", "vyomi-mesh-current", "vyomi-mesh-running", "my-app-codespace"]) assert.doesNotMatch(r.stdout, new RegExp(keep));
  assert.ok(!r.calls.some((c) => c.startsWith("codespace delete")), "nothing deleted without --yes");
  assert.ok(r.calls.every((c) => c.endsWith("token=gho_stub")), "uses the session's GitHub token: " + r.calls.join(" | "));
});

test("prune --yes deletes exactly the stopped, old Mesh Codespaces", { skip: process.platform === "win32" && "sh fake gh" }, async () => {
  const sb = sandbox(); const r = await run(sb, ["--yes"]);
  assert.equal(r.status, 0, r.stderr);
  const deleted = r.calls.filter((c) => c.startsWith("codespace delete")).map((c) => c.split(" ")[3]).sort();
  assert.deepEqual(deleted, ["vyomi-mesh-old1", "vyomi-mesh-old2"]);
  assert.match(r.stdout, /deleted vyomi-mesh-old1/);
});
