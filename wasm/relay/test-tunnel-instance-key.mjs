/* `ssh <instance>.vyomi` works with no manual step: the tunnel fetches the Mesh's VM key, and its ssh config names the user + that key.
 * Run: node wasm/relay/test-tunnel-instance-key.mjs  (no network; ssh -G only prints the effective config) */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const home = mkdtempSync(join(tmpdir(), "vyomi-ik-"));
process.env.VYOMI_HOME = home;
const cli = await import("../../packaging/tunnel/bin/mesh-cli.mjs");

// 1. ssh config: an instance gets ubuntu + the Mesh VM key; host.vyomi keeps the Codespace user.
const sshDir = mkdtempSync(join(tmpdir(), "vyomi-ik-ssh-"));
await cli.configureSsh({ yes: true, sshDir });
const eff = (h) => execFileSync("ssh", ["-G", "-F", join(sshDir, "config"), h], { encoding: "utf8" });
const inst = eff("i-0123456789ab.vyomi"), host = eff("host.vyomi");
assert.match(inst, /^user ubuntu$/m, inst);
assert.ok(inst.split("\n").some((l) => l.startsWith("identityfile ") && l.includes("mesh-instance-key")), "instance offers the Mesh VM key");
assert.match(inst, /^identitiesonly yes$/m);
assert.match(inst, /^proxycommand .*connect %h$/m, "goes through the tunnel");
assert.match(host, /^user vscode$/m, "host.vyomi still logs in as the Codespace user");

// 2. the key is fetched once per Codespace, written 0600, and never from a non-key answer
const PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----";
let calls = 0; const tr = (out) => ({ exec: async () => { calls++; return out; } });
const key = cli.INSTANCE_KEY;
assert.equal(await cli.ensureInstanceKey(tr("denied"), "cs-1"), false); assert.ok(!existsSync(key), "garbage is not written");
assert.equal(await cli.ensureInstanceKey(tr(PEM), "cs-1"), true);
assert.equal(readFileSync(key, "utf8").trim(), PEM); assert.equal(statSync(key).mode & 0o777, 0o600);
calls = 0; assert.equal(await cli.ensureInstanceKey(tr(PEM), "cs-1"), false); assert.equal(calls, 0, "same Codespace: no refetch");
const PEM2 = PEM.replace("AAAA", "BBBB");
assert.equal(await cli.ensureInstanceKey(tr(PEM2), "cs-2"), true); assert.match(readFileSync(key, "utf8"), /BBBB/, "new Mesh renews the key");
assert.equal(await cli.ensureInstanceKey({ exec: async () => { throw new Error("mesh down"); } }, "cs-3"), false, "failure is swallowed");
console.log("PASS instance ssh: ubuntu + Mesh VM key in the ssh config, key fetched once per Codespace (0600), failures harmless\n\nall passed");
