// Find the GitHub CLI, or install a private pinned copy. vyomi-tunnel authenticates to a Codespace through `gh codespace ssh`
// (the user's own GitHub login), so users must never have to install gh themselves.
//   1. a system `gh` on PATH that is recent enough  -> use it
//   2. a managed copy in ~/.vyomi/bin               -> use it
//   3. otherwise download the pinned official release, verify its SHA-256 (hashes below come from the release's checksums file),
//      unpack into ~/.vyomi/bin. Never touches PATH, Homebrew or system directories.
import { spawn as nodeSpawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, existsSync, writeFileSync, copyFileSync, chmodSync, rmSync, readdirSync, statSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

export const GH_VERSION = "2.103.3";
export const GH_MIN = [2, 40, 0];                    // codespace ssh --config / --stdio need a reasonably recent gh
const SHA256 = {
  "linux_amd64.tar.gz": "4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d",
  "linux_arm64.tar.gz": "ee32df2323c8847f5fac6cb6b4b69ca75828e9329a8f22f677021f7b3306ce63",
  "macOS_amd64.zip": "a2f86418f4350ae6e9ec60d5000bdf7665728436946a97fc27fe50e6ae752682",
  "macOS_arm64.zip": "d700207eae9ae98fe2b89535c2c087c07823d4628c56364695a5a07ef311c062",
  "windows_amd64.zip": "98d0cfa794721665d7973dd728c78aff7bd836d58f10f6d7a03568eccb0a22e0",
  "windows_arm64.zip": "197211c98687d7770ac331fe8a3b6c198c389108c1536cdbedf659fe4703e484",
};

export const assetFor = (platform = process.platform, arch = process.arch) => {
  const a = arch === "arm64" ? "arm64" : arch === "x64" ? "amd64" : null;
  const os = { darwin: ["macOS", "zip"], linux: ["linux", "tar.gz"], win32: ["windows", "zip"] }[platform];
  if (!a || !os) return null;
  const key = `${os[0]}_${a}.${os[1]}`;
  return SHA256[key] ? { key, name: `gh_${GH_VERSION}_${key}`, sha256: SHA256[key] } : null;
};

const parseVersion = (text) => { const m = /gh version (\d+)\.(\d+)\.(\d+)/.exec(String(text)); return m ? [+m[1], +m[2], +m[3]] : null; };
const atLeast = (v, min) => { for (let i = 0; i < 3; i++) { if (v[i] !== min[i]) return v[i] > min[i]; } return true; };

function run(spawn, bin, args) {
  return new Promise((resolve) => {
    let out = "", c;
    try { c = spawn(bin, args, { stdio: ["ignore", "pipe", "pipe"] }); } catch { return resolve({ ok: false, out: "" }); }
    c.stdout?.on("data", (d) => { out += d; }); c.stderr?.on("data", (d) => { out += d; });
    c.on("error", () => resolve({ ok: false, out })); c.on("close", (code) => resolve({ ok: code === 0, out }));
  });
}
async function usable(spawn, bin) { const r = await run(spawn, bin, ["--version"]); const v = r.ok ? parseVersion(r.out) : null; return v && atLeast(v, GH_MIN) ? v.join(".") : null; }

/** @returns {Promise<{path:string, source:"system"|"managed"|"installed", version:string}>} */
export async function ensureGh({ env = process.env, spawn = nodeSpawn, fetchFn = globalThis.fetch, home = env.VYOMI_HOME || join(homedir(), ".vyomi"),
                                 platform = process.platform, arch = process.arch, log = () => {}, extract = null } = {}) {
  const exe = platform === "win32" ? "gh.exe" : "gh";
  if (env.VYOMI_GH) { const v = await usable(spawn, env.VYOMI_GH); if (v) return { path: env.VYOMI_GH, source: "system", version: v }; }
  const sys = await usable(spawn, "gh");
  if (sys) return { path: "gh", source: "system", version: sys };
  const dir = join(home, "bin"), managed = join(dir, exe);
  if (existsSync(managed)) { const v = await usable(spawn, managed); if (v) return { path: managed, source: "managed", version: v }; }

  const asset = assetFor(platform, arch);
  if (!asset) throw new Error(`GitHub CLI is required and there is no download for ${platform}/${arch}. Install it from https://cli.github.com and retry.`);
  const url = `https://github.com/cli/cli/releases/download/v${GH_VERSION}/${asset.name}`;
  log(`GitHub CLI not found; installing gh ${GH_VERSION} into ${dir}`);
  let buf;
  try { const r = await fetchFn(url); if (!r.ok) throw new Error("HTTP " + r.status); buf = Buffer.from(await r.arrayBuffer()); }
  catch (e) { throw new Error(`could not download the GitHub CLI (${e.message}). Install it from https://cli.github.com and retry.`); }
  const got = createHash("sha256").update(buf).digest("hex");
  if (got !== asset.sha256) throw new Error("the downloaded GitHub CLI failed its SHA-256 check; refusing to run it");
  const tmp = mkdtempSync(join(tmpdir(), "vyomi-gh-"));
  try {
    const file = join(tmp, asset.key.endsWith("zip") ? "gh.zip" : "gh.tgz");
    writeFileSync(file, buf);
    if (extract) await extract(file, tmp);
    else { const r = await run(spawn, "tar", ["-xf", file, "-C", tmp]); if (!r.ok) throw new Error("could not unpack the GitHub CLI: " + r.out.trim().slice(0, 200)); }
    const found = findExe(tmp, exe);
    if (!found) throw new Error("the GitHub CLI archive did not contain " + exe);
    mkdirSync(dir, { recursive: true });
    copyFileSync(found, managed); if (platform !== "win32") chmodSync(managed, 0o755);
  } finally { try { rmSync(tmp, { recursive: true, force: true }); } catch { /* */ } }
  const v = await usable(spawn, managed);
  if (!v) throw new Error("the installed GitHub CLI does not run on this machine");
  return { path: managed, source: "installed", version: v };
}
function findExe(dir, name) {
  for (const f of readdirSync(dir)) { const p = join(dir, f), s = statSync(p); if (s.isDirectory()) { const r = findExe(p, name); if (r) return r; } else if (f === name && p.includes(join("bin", name))) return p; }
  return null;
}

/** Is the user signed in to GitHub with the codespace scope? Returns {ok, reason}. */
export async function ghAuthOk(ghPath, { spawn = nodeSpawn, env = process.env } = {}) {
  if (env.GH_TOKEN || env.GITHUB_TOKEN) return { ok: true };
  const r = await run(spawn, ghPath, ["auth", "status"]);
  return r.ok ? { ok: true } : { ok: false, reason: "not signed in to GitHub. Run `vyomi-tunnel gh-login`." };
}
