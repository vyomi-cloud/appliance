import { open, check, BASE, SHOTS } from "../lib.mjs";
const { browser, page, errs } = await open();
const BOB = "arn:aws:iam::123456789012:user/vfy-bob";
async function addStmt({ sid, principal, action, resource }) {
  await page.getByRole("button", { name: "Add statement" }).click();
  const card = page.getByTestId("policy-statement").last();
  await card.getByLabel("Statement ID").fill(sid);
  await card.getByLabel("Principal", { exact: true }).fill(principal);
  await card.getByRole("button", { name: "Add Principal" }).click();
  await card.getByRole("button", { name: /Choose actions/ }).click();
  await page.keyboard.type(action);
  await page.getByRole("option").filter({ hasText: new RegExp(`^${action}[a-z0-9-]+:${action}$`) }).first().click();
  await page.keyboard.press("Escape");
  if (resource) { await card.getByLabel("Resource", { exact: true }).fill(resource); await card.getByRole("button", { name: "Add Resource" }).click(); }
}
await page.goto(`${BASE}/v4/aws/#/s3/buckets/vfy-bkt-rp?tab=permissions`);
await page.getByText("Bucket policy", { exact: true }).first().waitFor({ timeout: 30000 });
await page.getByTestId("rpol-s3-bucket").getByRole("button", { name: /^(Edit|Add)/ }).first().click();
await addStmt({ sid: "AllowBobRead", principal: BOB, action: "GetObject" });
await page.screenshot({ path: `${SHOTS}/aws-a2-s3-editor.png`, fullPage: true });
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByText("Bucket policy saved.").first().waitFor({ timeout: 10000 }).catch(() => {});
check("S3 bucket policy saved via UI", await page.getByRole("cell", { name: "AllowBobRead" }).count() > 0);
await page.goto(`${BASE}/v4/aws/#/sqs/queues/vfy-q-rp`);
await page.getByRole("tab", { name: "Access policy" }).click({ timeout: 30000 });
await page.getByTestId("rpol-sqs-queue").getByRole("button", { name: /^(Edit|Add)/ }).first().click();
await addStmt({ sid: "AllowBobSend", principal: BOB, action: "SendMessage", resource: "arn:aws:sqs:us-east-1:123456789012:vfy-q-rp" });
await page.screenshot({ path: `${SHOTS}/aws-a2-sqs-editor.png`, fullPage: true });
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByRole("cell", { name: "AllowBobSend" }).waitFor({ timeout: 10000 }).catch(()=>{});
check("SQS access policy saved via UI", await page.getByRole("cell", { name: "AllowBobSend" }).count() > 0);
console.log(errs);
await browser.close();
