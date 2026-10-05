/* Honest Goal-1 characterization for core AWS services at the API level (the layer
 * the console UI + the aws CLI both drive). Create → list → confirm round-trip. */
import { startServer, bootConsole, chromium } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
try {
  await bootConsole(page, base, "/aws-console.html");
  const probe = async (svc, createPath, body, listPath, listKey, nameField) => {
    const r = await page.evaluate(async ([createPath, body, listPath, listKey, nameField]) => {
      const cr = await fetch(createPath, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const cj = await cr.json().catch(() => ({}));
      const lj = await (await fetch(listPath)).json().catch(() => ({}));
      const arr = lj[listKey] || lj.value || lj.items || [];
      const want = body[nameField] || body.name || body.TableName || body.QueueName || body.UserName;
      return { cstatus: cr.status, cok: cj.ok !== false, listed: arr.some((x) => JSON.stringify(x).includes(want)), count: arr.length };
    }, [createPath, body, listPath, listKey, nameField]);
    results.push({ svc, pass: r.cstatus < 300 && r.listed, ...r });
  };
  await probe("S3", "/api/s3/buckets", { name: "apitest-bucket" }, "/api/s3/buckets", "buckets", "name");
  await probe("DynamoDB", "/api/dynamodb/tables", { name: "apitab", TableName: "apitab", hashKey: "id", KeySchema: [{ AttributeName: "id", KeyType: "HASH" }], AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }] }, "/api/dynamodb/tables", "tables", "TableName");
  await probe("SQS", "/api/sqs/queues", { name: "apiq" }, "/api/sqs/queues", "queues", "name");
  await probe("KMS", "/api/aws/kms/keys", { description: "api test key" }, "/api/aws/kms/keys", "keys", "description");
  await probe("Secrets", "/api/aws/secrets", { name: "apisecret", value: "s" }, "/api/aws/secrets", "secrets", "name");
  await probe("IAM", "/api/iam/users", { name: "apiuser", UserName: "apiuser" }, "/api/iam/users", "users", "UserName");
} catch (e) { results.push({ svc: "(boot)", pass: false, err: String(e).split("\n")[0] }); }
await browser.close(); server.close();

console.log("===== AWS core services — API create→list round-trip =====");
for (const r of results) console.log(`  [${r.pass ? "PASS" : "FAIL"}] ${String(r.svc).padEnd(10)} create:${r.cstatus} listed:${r.listed} count:${r.count ?? "-"} ${r.err || ""}`);
const n = results.filter((r) => r.pass).length;
console.log(`\n${n}/${results.length} AWS core services round-trip at the API`);
