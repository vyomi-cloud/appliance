/* Nano post-create probe, AWS EC2 (PLAN: tests/conformance/post_create/PLAN.md; offline twin:
 * tests/conformance/post_create/probes/vm_ssh.py aws). Launch through the console's EC2 wizard,
 * then hold the instance to the offline contract: connect-info -> key -> REAL `ssh` from this
 * machine through vyomi-tunnel -> whoami / uname / file round trip / python http.server ->
 * console exec -> stop/start keeps files -> terminate closes the port. The instance is a real
 * v86 VM in the browser (wasm/vm). Needs RELAY_HTTP = a vyomi-tunnel >= 1.1.0. */
import { openNano, probeVm, reporter } from "./vm-ssh-lib.mjs";
import { sleep } from "./lib.mjs";
const { check, finish } = reporter();
let nano;
try {
  nano = await openNano("/aws-console.html");
  const { page, call } = nano;
  await page.locator("#rail >> text=EC2").first().click();
  await sleep(1500);
  await page.locator("#main button").filter({ hasText: /launch instances/i }).first().click();
  await sleep(1200);
  await page.locator("#main button").filter({ hasText: /^\s*(rocket_launch)?\s*Launch instance\s*$/i }).last().click();
  await sleep(3000);
  const list = (await call("GET", "/api/ec2/instances")).body;
  const items = (list && list.items) || [];
  const id = (items[items.length - 1] || {}).instance_id;
  check("instance launched through the console", /^i-/.test(id || ""), JSON.stringify(list).slice(0, 160));
  if (id) {
    const user = (await call("GET", `/api/ec2/instances/${id}`)).body;
    const img = String((user && (user.image_id || (user.instance || {}).image_id)) || "");
    await probeVm(nano, {
      cloud: "aws", user: /ubuntu/i.test(img) ? "ubuntu" : "ec2-user",
      ciPath: `/api/aws/ec2/instances/${id}/connect-info`,
      execPath: `/api/aws/ec2/instances/${id}/exec`,
      stop: () => call("POST", `/api/ec2/instances/${id}/stop`),
      start: () => call("POST", `/api/ec2/instances/${id}/start`),
      del: () => call("POST", `/api/ec2/instances/${id}/terminate`),
      openConnect: async (page) => {   // EC2 list -> the instance -> Connect tab
        await page.locator("#rail >> text=EC2").first().click();
        await sleep(1500);
        await page.locator("#main tr", { hasText: id }).first().locator("a.id").first().click({ timeout: 15000 });
        await sleep(1500);
        await page.locator(".top-tabs button", { hasText: /^\s*Connect\s*$/ }).first().click();
      },
    }, check);
  }
} catch (e) { check("probe ran without error", false, String(e && e.stack || e).split("\n").slice(0, 3).join(" ")); }
if (nano) await nano.close();
finish();
