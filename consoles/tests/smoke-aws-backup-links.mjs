/* RDS / S3 / DynamoDB pages link into the AWS Backup console.  BASE=http://127.0.0.1:9084 node consoles/tests/smoke-aws-backup-links.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const UI = `${process.env.BASE || "http://127.0.0.1:9084"}${process.env.UI_PATH || "/v4/aws/"}`;
const results = [];
const check = (n, ok) => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
for (const [name, hash] of [["RDS automated backups", "#/rds/automated-backups"], ["DynamoDB backups", "#/dynamodb/backups"]]) {
  await page.goto(UI + hash);
  await page.getByText("Centralized backup with AWS Backup").first().waitFor({ timeout: 15000 }).catch(() => {});
  check(`${name} shows the AWS Backup entry`, await page.getByText("Centralized backup with AWS Backup").count() > 0);
  await page.getByRole("link", { name: "Protected resources" }).first().click();
  await page.waitForTimeout(500);
  check(`${name} link opens the Backup console`, page.url().includes("#/backup/protected-resources"));
}
check("no page errors", errors.length === 0);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
