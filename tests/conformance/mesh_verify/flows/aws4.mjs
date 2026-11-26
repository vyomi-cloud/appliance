import { open, check, BASE, SHOTS } from "../lib.mjs";
const { browser, page, errs } = await open();
await page.goto(`${BASE}/v4/aws/#/iam/policy-simulator`);
await page.getByRole("button", { name: /Choose a user or role/ }).click({ timeout: 30000 });
await page.getByRole("option").filter({ hasText: /vfy-alice/ }).first().click();
async function addAction(svc, act, prev="Choose a service") {
  await page.getByRole("button", { name: new RegExp(prev) }).first().click();
  await page.getByPlaceholder("Search services").fill(svc);
  await page.getByRole("option", { name: svc, exact: true }).first().click();
  await page.getByRole("button", { name: /Choose an action/ }).first().click();
  await page.keyboard.type(act);
  await page.getByRole("option").filter({ hasText: new RegExp("^"+act) }).first().click();
  await page.getByRole("button", { name: "Add actions" }).click();
}
await addAction("S3","ListAllMyBuckets");
await addAction("SQS","ListQueues","S3");
await page.getByRole("button", { name: "Simulate" }).click();
await page.getByRole("row").filter({ hasText: "sqs:ListQueues" }).waitFor({ timeout: 15000 });
await page.screenshot({ path: `${SHOTS}/aws-a3-simulate.png`, fullPage: true });
const s3 = await page.getByRole("row").filter({ hasText: "s3:ListAllMyBuckets" }).innerText();
const sq = await page.getByRole("row").filter({ hasText: "sqs:ListQueues" }).innerText();
console.log(s3.replace(/\s+/g," "),"|",sq.replace(/\s+/g," "));
check("UI Policy simulator: allowed for UI-created policy action", /allowed/i.test(s3));
check("UI Policy simulator: sqs:ListQueues implicitDeny/denied", /deny|denied/i.test(sq));
console.log(errs);
await browser.close();
