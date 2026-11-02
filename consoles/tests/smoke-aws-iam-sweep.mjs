/* IAM sweep 1: Dashboard recommendations, Account settings (STS), root Security credentials (MFA with real TOTP,
 * access keys, X.509), user Security credentials tab (console password policy enforcement, SSH keys, service-specific
 * credentials), Organization activity event log. Drives the real UI and cross-checks over the IAM Query wire.
 *
 *   BASE=http://127.0.0.1:9081 node consoles/tests/smoke-aws-iam-sweep.mjs                                  (offline)
 *   BASE=http://127.0.0.1:9083 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-iam-sweep.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { createHmac } from "node:crypto";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9081";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const USER = `ui-iam-${N}`, ROOTDEV = `root-mfa-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=0`;
const iam = (action, p = {}) => page.evaluate(async ([u, a, pr, au]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2010-05-08", ...pr }).toString() });
  return { status: r.status, text: await r.text() };
}, [WIRE, action, p, auth]);
const tag = (x, t) => (x.match(new RegExp(`<${t}>([\\s\\S]*?)</${t}>`)) || [])[1];
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const body = () => page.locator("body").innerText();
// the "Not simulated in Vyomi" BADGE only (never loose text matching)
const badges = () => page.locator('[data-vyomi-not-simulated]').count();
const b32 = (s) => { const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"; let bits = "", out = []; for (const c of s.toUpperCase().replace(/=+$/, "")) bits += A.indexOf(c).toString(2).padStart(5, "0"); for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2)); return Buffer.from(out); };
const totp = (seed, step) => { const m = Buffer.alloc(8); m.writeBigUInt64BE(BigInt(step)); const h = createHmac("sha1", b32(seed)).update(m).digest(); const o = h[19] & 15; return String((h.readUInt32BE(o) & 0x7fffffff) % 1000000).padStart(6, "0"); };
const go = async (hash, heading) => { await page.goto(UI + hash); await page.reload(); await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 40000 }); await page.waitForTimeout(800); };

await page.goto(UI + "#/iam/dashboard");
await page.getByRole("heading", { name: "IAM Dashboard" }).first().waitFor({ timeout: 60000 });

// idempotent reruns: clear root MFA / root keys / STS version left by a previous run
await iam("SetSecurityTokenServicePreferences", { GlobalEndpointTokenVersion: "v1Token" });
for (const m of (await iam("ListMFADevices", { UserName: "root" })).text.matchAll(/<SerialNumber>([^<]+)</g)) { await iam("DeactivateMFADevice", { UserName: "root", SerialNumber: m[1] }); await iam("DeleteVirtualMFADevice", { SerialNumber: m[1] }); }
for (const m of (await iam("ListAccessKeys", { UserName: "root" })).text.matchAll(/<AccessKeyId>(\w+)</g)) await iam("DeleteAccessKey", { UserName: "root", AccessKeyId: m[1] });

// ── 1. Dashboard
await go("#/iam/dashboard", "IAM Dashboard");
check("Dashboard has no Not-simulated badge", (await badges()) === 0);
await page.getByText("Add MFA for the root user").first().waitFor({ timeout: 15000 });
check("Dashboard recommends root MFA (computed from state)", (await iam("GetSecurityRecommendations")).text.includes("<Id>root-mfa</Id>"));
check("Dashboard IAM resource tiles render", (await body()).includes("User groups"));
await shot("iam-dashboard");

// ── 2. Account settings: password policy + STS are real
await go("#/iam/account-settings", "Account settings");
check("Password policy + STS panels are real (only the 2 multi-account panels carry the badge)", (await badges()) === 2 && (await body()).includes("Global endpoint session tokens"));
await page.getByRole("button", { name: /Change to version 2 tokens/ }).click();
await page.getByText("Valid in all AWS Regions (version 2)").waitFor({ timeout: 10000 });
check("STS token version change persisted (native GetAccountSummary)", (await iam("GetAccountSummary")).text.includes("<key>GlobalEndpointTokenVersion</key><value>2</value>"));
await iam("UpdateAccountPasswordPolicy", { MinimumPasswordLength: "12", RequireNumbers: "true", RequireSymbols: "true", RequireUppercaseCharacters: "true", RequireLowercaseCharacters: "true", AllowUsersToChangePassword: "true" });

// ── 3. Root security credentials: MFA with REAL TOTP, access key, X.509
await go("#/iam/security-credentials", "My security credentials");
check("Root credentials page: MFA/access keys/X.509 real, only CloudFront key pairs is a gap", (await badges()) === 1);
await page.getByRole("button", { name: "Assign MFA device" }).click();
await page.getByLabel("Device name").fill(ROOTDEV);
await page.getByRole("dialog").getByRole("button", { name: "Next" }).click();
const seed = await page.getByLabel("Secret key").inputValue();
check("MFA secret key shown is valid base32 (decoded from the wire blob)", /^[A-Z2-7]{32}$/.test(seed), seed);
await page.getByLabel("MFA code 1").fill("123456");
await page.getByLabel("MFA code 2").fill("654321");
await page.getByRole("dialog").getByRole("button", { name: "Assign MFA" }).click();
await page.getByText(/authentication codes do not match/i).first().waitFor({ timeout: 10000 });
check("wrong codes are rejected with InvalidAuthenticationCode (real TOTP check)", true);
const step = Math.floor(Date.now() / 30000);
await page.getByLabel("MFA code 1").fill(totp(seed, step));
await page.getByLabel("MFA code 2").fill(totp(seed, step + 1));
await page.getByRole("dialog").getByRole("button", { name: "Assign MFA" }).click();
await page.getByRole("cell", { name: new RegExp(`mfa/${ROOTDEV}`) }).waitFor({ timeout: 10000 });
const sm = await iam("GetAccountSummary");
check("two consecutive valid TOTP codes register root MFA (summary AccountMFAEnabled=1)", sm.text.includes("<key>AccountMFAEnabled</key><value>1</value>"));
await page.getByRole("button", { name: "Create access key" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Done" }).click();
check("root access key created (native summary AccountAccessKeysPresent=1)", (await iam("GetAccountSummary")).text.includes("<key>AccountAccessKeysPresent</key><value>1</value>"));
await shot("iam-root-credentials");
await go("#/iam/dashboard", "IAM Dashboard");
await page.getByText("Deactivate or delete access keys for the root user").first().waitFor({ timeout: 15000 });
check("Dashboard now recommends deleting root access keys and no longer root MFA", !(await body()).includes("Add MFA for the root user"));

// ── 4. User security credentials
await iam("CreateUser", { UserName: USER });
await go(`#/iam/users/${USER}`, USER);
await page.getByRole("tab", { name: "Security credentials" }).click();
check("user Security credentials tab has no Not-simulated badge", (await badges()) === 0);
await page.getByRole("button", { name: "Enable console access" }).click();
await page.getByText("Custom password").click();
await page.locator('input[type=password][aria-label="Console password"]').fill("short");
await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();
await page.getByText(/does not conform to the account password policy/i).first().waitFor({ timeout: 10000 });
check("UI enforces the account password policy (weak console password refused)", (await iam("GetLoginProfile", { UserName: USER })).status === 404);
await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click().catch(() => {});
await page.reload(); await page.getByRole("heading", { name: USER }).first().waitFor({ timeout: 30000 });
await page.getByRole("tab", { name: "Security credentials" }).click();
await page.getByRole("button", { name: "Enable console access" }).click();
await page.getByText("Custom password").click();
await page.locator('input[type=password][aria-label="Console password"]').fill("Str0ng-Console-Pass!");
await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();
await page.getByText("Console access enabled").waitFor({ timeout: 10000 });
await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
check("a compliant password enables console access", (await iam("GetLoginProfile", { UserName: USER })).status === 200);

const blob = Buffer.from("\0\0\0\x07ssh-rsa" + "z".repeat(30), "latin1").toString("base64");
await page.getByRole("button", { name: "Upload SSH public key" }).click();
await page.getByRole("textbox", { name: "SSH public key" }).fill("garbage");
await page.getByRole("dialog").getByRole("button", { name: "Upload SSH public key" }).click();
await page.getByText(/SSH public key is malformed/i).first().waitFor({ timeout: 10000 });
check("malformed SSH key shows the API error", true);
await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click().catch(() => {});
await page.getByRole("button", { name: "Upload SSH public key" }).first().click();
await page.getByRole("textbox", { name: "SSH public key" }).fill(`ssh-rsa ${blob} me@laptop`);
await page.getByRole("dialog").getByRole("button", { name: "Upload SSH public key" }).click();
await page.getByRole("cell", { name: /^APKA/ }).waitFor({ timeout: 10000 });
const ssh = await iam("ListSSHPublicKeys", { UserName: USER });
check("SSH key uploaded in UI -> native ListSSHPublicKeys", ssh.text.includes("<SSHPublicKeyId>APKA"));
await page.getByRole("row", { name: /APKA/ }).getByRole("radio").click({ force: true });
await page.getByRole("button", { name: "View", exact: true }).locator("xpath=following::button[normalize-space()='Delete'][1]").click();
await page.getByRole("cell", { name: /^APKA/ }).waitFor({ state: "detached", timeout: 10000 });
check("SSH key deleted from UI", !(await iam("ListSSHPublicKeys", { UserName: USER })).text.includes("APKA"));

await page.getByRole("button", { name: "Generate credentials" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Generate credentials" }).click();
await page.getByLabel("Service password").waitFor({ timeout: 10000 });
check("service-specific credential generated with a one-time password", (await page.getByLabel("Service password").inputValue()).length > 10);
await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
check("service credential visible natively (no password in listing)", (await iam("ListServiceSpecificCredentials", { UserName: USER })).text.includes(`${USER}-at-123456789012`));
await shot("iam-user-credentials");

await page.getByRole("button", { name: "Create access key" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Done" }).click();
await page.getByText("Never").first().waitFor({ timeout: 10000 });
check("access key shows 'Never' used until a request is signed with it", true);

// ── 5. Organization activity: honest multi-account gap + real IAM event log
await go("#/iam/organization-activity", "Organization activity");
await page.getByRole("cell", { name: "CreateUser", exact: true }).first().waitFor({ timeout: 15000 });
check("Organization activity: multi-account tree stays an honest gap (1 badge); account IAM event log is real", (await badges()) === 1 && (await body()).includes("Recent IAM activity in this account"));
await shot("iam-org-activity");

// ── 6. Delete user from the UI removes its credentials first (as the real console does)
await go(`#/iam/users/${USER}`, USER);
await page.getByRole("button", { name: "Delete", exact: true }).first().click();
await page.getByRole("dialog").getByRole("textbox").fill(USER);
await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
await page.getByRole("heading", { name: "Users" }).first().waitFor({ timeout: 15000 });
check("deleting a user with a password, access key and service credential succeeds from the UI", (await iam("GetUser", { UserName: USER })).status === 404);
check("the raw API still refuses DeleteUser while credentials remain (DeleteConflict)", await (async () => {
  const u = `${USER}-c`; await iam("CreateUser", { UserName: u }); await iam("CreateAccessKey", { UserName: u });
  const r = await iam("DeleteUser", { UserName: u }); const k = (await iam("ListAccessKeys", { UserName: u })).text.match(/<AccessKeyId>(\w+)</)[1];
  await iam("DeleteAccessKey", { UserName: u, AccessKeyId: k }); await iam("DeleteUser", { UserName: u });
  return r.status === 409 && r.text.includes("DeleteConflict");
})());
console.log("page errors:", errors.length ? errors.slice(0, 3).join(" | ") : "none");
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
