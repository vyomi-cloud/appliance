/* AWS-05 EC2 Connect: the Connect modal on the instance list/detail shows the SSH client tab (real command + key download) and an
 * EC2 Instance Connect terminal that runs commands through the appliance's console exec endpoint.
 * On the dev server there is no appliance backend, so /api/... is answered by Playwright route stubs shaped exactly like
 * server.py's connect-info / console exec responses (the backend itself is covered live: see the worker report). On the real offline
 * appliance run with LIVE=1 to skip the stubs. Nano: the capability is not simulated; set SUBSTRATE=nano to assert the honest panel.
 *   BASE=http://127.0.0.1:9042 node consoles/tests/smoke-aws-ec2connect.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9042";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH ?? "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const LIVE = !!process.env.LIVE;
const NANO = process.env.SUBSTRATE === "nano";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/ec2");
const ec2 = (action, params) => page.evaluate(async ([u, a, p]) => (await fetch(u + "/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2016-11-15", ...p }).toString() })).text(), [WIRE, action, params]);
const ami = (await ec2("DescribeImages", {})).match(/<imageId>(ami-\w+)<\/imageId>/)[1];
const iid = (await ec2("RunInstances", { ImageId: ami, MinCount: "1", MaxCount: "1", InstanceType: "t3.micro" })).match(/<instanceId>(i-\w+)<\/instanceId>/)[1];
const execCalls = [];
if (!LIVE && !NANO) {
  await page.route(`**/api/aws/ec2/instances/${iid}/connect-info`, (r) => r.fulfill({ json: { ok: true, instance_id: iid, backend: "docker",
    ssh: { command: `ssh -i ~/.vyomi/instance-keys/id_ed25519 -o StrictHostKeyChecking=no -p 43531 ubuntu@127.0.0.1`, user: "ubuntu", host: "127.0.0.1", port: 43531, key_download_url: `/api/aws/ec2/instances/${iid}/private-key.pem`, key_local_filename: `vyomi-${iid}.pem` },
    lxc: { command: `docker exec -it vyomi-${iid} bash` } } }));
  await page.route(`**/api/ec2/instances/${iid}/console/exec`, (r) => { const c = JSON.parse(r.request().postData()).command; execCalls.push(c); r.fulfill({ json: { cwd: "/root", command: c, exit_code: 0, output: c === "echo hello" ? "hello\n" : "ok\n" } }); });
}
if (!LIVE && !NANO) {
  await page.route(`**/api/aws/ec2/instances/${iid}/instance-connect`, (r) => r.fulfill({ json: { ok: true, success: true, delivered: true, expires_in_seconds: 60, os_user: "ubuntu", ssh_command: "ssh -i key -p 43531 ubuntu@127.0.0.1" } }));
  await page.route("**/api/ssm/sessions", (r) => r.fulfill({ json: { ok: true, SessionId: "root-0abc", Target: iid, Status: "Connected" } }));
  await page.route("**/api/ssm/sessions/root-0abc/exec", (r) => r.fulfill({ json: { output: "ssm-ok\n" } }));
  await page.route("**/api/ssm/sessions/root-0abc/terminate", (r) => r.fulfill({ json: { ok: true } }));
}
await page.goto(UI + `#/ec2/instances/${iid}`);
await page.getByRole("button", { name: "Connect" }).first().click();
if (NANO) {
  await page.getByText(/Not simulated in Vyomi/i).first().waitFor({ timeout: 10000 });
  check("Nano shows the honest Not-simulated panel for Connect", true);
} else {
  await page.getByRole("tab", { name: "SSH client" }).waitFor({ timeout: 10000 });
  check("Connect modal is not the Not-simulated panel", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));
  await page.getByRole("tab", { name: "SSH client" }).click();
  const cmd = await page.getByTestId("ssh-command").innerText();
  check("SSH tab shows the ssh command and key download", /^ssh -i .* -p \d+ ubuntu@/.test(cmd) && await page.getByRole("link", { name: /Download private key/ }).isVisible().catch(() => false) || /Download private key/.test(await page.locator("body").innerText()), cmd);
  await page.getByRole("tab", { name: "Send SSH public key" }).click();
  await page.getByRole("textbox", { name: "SSH public key" }).fill("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl test");
  await page.getByRole("button", { name: "Send public key" }).click();
  await page.getByTestId("eic-command").waitFor({ timeout: 10000 });
  check("Instance Connect pushes the key and shows the ssh command", /ssh -i/.test(await page.getByTestId("eic-command").innerText()));
  await page.getByRole("tab", { name: "Session Manager" }).click();
  await page.getByRole("button", { name: "Start session" }).click();
  await page.getByLabel("Session command").fill("echo x");
  await page.getByRole("button", { name: "Run", exact: true }).last().click();
  await page.waitForFunction(() => /ssm-ok/.test(document.querySelector('[data-testid="ssm-terminal"]')?.innerText || ""), null, { timeout: 10000 });
  check("Session Manager starts a session and runs a command", true);
  await page.getByRole("tab", { name: "EC2 Instance Connect" }).click();
  await page.getByLabel("Terminal command").fill("echo hello");
  await page.getByRole("button", { name: "Run" }).click();
  await page.waitForFunction(() => /^hello$/m.test(document.querySelector('[data-testid="connect-terminal"]')?.innerText || ""), null, { timeout: 10000 });
  check("terminal runs a command and prints its output", true);
  if (!LIVE) check("command went to the console exec endpoint", execCalls[0] === "echo hello");
}
await page.screenshot({ path: `${OUT}/ec2-connect.png`, fullPage: true });
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
