/* vyomi-gate: the only privileged door to Docker. A fake `docker` records what it is asked; no real Docker needed.
 *   node wasm/relay/test-mesh-gate.mjs */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync, chmodSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const MESH = join(here, "../../codespace/.devcontainer/mesh");
const dir = mkdtempSync(join(tmpdir(), "gate-"));
const log = join(dir, "calls.log");
const fake = join(dir, "docker");
writeFileSync(fake, `#!/bin/bash
echo "$*" >> "${log}"
case "$1" in
  ps) if [[ "$*" == *label=com.docker.compose.service=simulator* ]]; then echo vyomi-mesh-simulator-1; else printf 'vyomi-mesh-simulator-1\\nvyomi-mesh-llm-1\\nvyomi-i-web\\nvyomi-k3s-0123456789\\n'; fi ;;
  inspect) echo "10.0.0.5 " ;;
  exec) echo KEYDATA ;;
esac
`); chmodSync(fake, 0o755);
const gate = (...a) => { const r = spawnSync("bash", [join(MESH, "vyomi-gate"), ...a], { env: { ...process.env, VYOMI_GATE_DOCKER: fake }, encoding: "utf8" }); return { code: r.status, out: r.stdout, err: r.stderr }; };
const calls = () => (existsSync(log) ? readFileSync(log, "utf8") : "");
const denied = (r) => r.code === 2 && /not allowed/.test(r.err);

// allowed
assert.equal(gate("ip", "vyomi-i-web").out.trim(), "10.0.0.5");
assert.equal(gate("ip", "vyomi-k3s-0123456789").code, 0);
const l = gate("list");
assert.equal(l.out.trim().split("\n").length, 2, "only the two user containers are listed");
assert.ok(!/simulator|llm/.test(l.out));
assert.equal(gate("k3s").out.trim(), "vyomi-k3s-0123456789");
assert.equal(gate("compose", "simulator").out.trim(), "vyomi-mesh-simulator-1");
assert.equal(gate("instance-key").out.trim(), "KEYDATA");

// refused: Vyomi's own containers, other services, shell tricks, extra args, unknown verbs
for (const bad of [["ip", "vyomi-mesh-simulator-1"], ["ip", "simulator"], ["ip", "vyomi-mesh-llm-1"], ["ip", "llm"], ["ip", "vyomi-i-"], ["ip", "-a"], ["ip", "vyomi-i-x;id"],
  ["ip", "vyomi-i-x y"], ["ip", "vyomi-i-$(id)"], ["ip", "vyomi-k3s-ZZ"], ["ip"], ["compose", "llm"], ["compose", "simulator;id"], ["list", "x"], ["exec", "vyomi-mesh-simulator-1", "sh"],
  ["exec"], ["inspect", "vyomi-mesh-simulator-1"], ["logs", "vyomi-mesh-simulator-1"], ["cp", "a"], ["run"], [""], ["ip", "vyomi-i-a", "extra"], ["instance-key", "x"]]) {
  const before = calls().length; const r = gate(...bad);
  assert.ok(denied(r), "should refuse: " + JSON.stringify(bad) + " got " + JSON.stringify(r));
  assert.equal(calls().length, before, "docker never called for: " + JSON.stringify(bad));
}
assert.ok(denied(gate()), "no verb");
// the gate never prints anything about the core containers' images or config
assert.ok(!/image|\\.Config\\.Env|Env/.test(readFileSync(join(MESH, "vyomi-gate"), "utf8").replace(/#.*$/gm, "").replace(/\.Config\.ExposedPorts/g, "")));

// lockdown: plan changes nothing; apply (into a scratch root) installs only the gate sudoers rule and removes general sudo; admins are untouched
const lock = (mode, env = {}) => spawnSync("bash", [join(MESH, "vyomi-lockdown"), mode], { env: { ...process.env, ...env }, encoding: "utf8" });
assert.match(lock("plan").stdout, /group docker/); assert.equal(lock("plan").status, 0);
const root = join(dir, "root"); mkdirSync(join(root, "etc/sudoers.d"), { recursive: true });
writeFileSync(join(root, "etc/sudoers.d/vscode"), "vscode ALL=(ALL) NOPASSWD:ALL\n");
const ad = lock("apply", { VYOMI_LOCKDOWN_ROOT: root, VYOMI_ADMIN: "1" }); assert.match(ad.stdout, /admin Codespace/); assert.ok(existsSync(join(root, "etc/sudoers.d/vscode")), "admin keeps sudo");
const ap = lock("apply", { VYOMI_LOCKDOWN_ROOT: root }); assert.equal(ap.status, 0, ap.stderr);
assert.ok(!existsSync(join(root, "etc/sudoers.d/vscode")), "general sudo removed");
assert.equal(readFileSync(join(root, "etc/sudoers.d/vyomi-gate"), "utf8").trim(), "vscode ALL=(root) NOPASSWD: /usr/local/sbin/vyomi-gate");
assert.equal(lock("bogus").status, 2);
console.log("mesh gate: all checks passed");
