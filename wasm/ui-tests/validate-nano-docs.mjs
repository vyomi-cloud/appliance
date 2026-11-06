/* Nano: the generated "API reference" + "SDK & CLI usage" docs (wasm/docs via wasm/nano-docs.js) render per cloud.
 * Samples services per cloud: service list, operation expand (wire request / params / examples), CLI+SDK snippet tabs
 * pointed at the endpoint, search, and the per-service usage cards.
 * Run: NANO_DIR=<worktree>/wasm node validate-nano-docs.mjs */
import { startServer, chromium } from "./lib.mjs";
const { base } = await startServer();
const b = await chromium.launch(); let ok = 0, bad = 0;
const check = (n, c, note = "") => { console.log(`[${c ? "PASS" : "FAIL"}] ${n}${c ? "" : " " + note}`); c ? ok++ : bad++; };
const SAMPLE = {
  aws: [["Simple Queue Service", "CreateQueue", ["AWS CLI", "Python (boto3)", "JavaScript (SDK v3)", "curl (wire)"], "create_queue"],
        ["Lambda", "Invoke", ["AWS CLI", "Python (boto3)"], "invoke"], ["DynamoDB", "PutItem", ["AWS CLI"], "put_item"], ["S3", "CreateBucket", ["AWS CLI"], "create_bucket"]],
  gcp: [["Pub/Sub", "projects.topics.create", ["gcloud", "Python (google-api-python-client)", "JavaScript (googleapis)", "curl (REST)"], "topics()"],
        ["Cloud Storage", "buckets.insert", ["curl (REST)"], "buckets()"], ["Secret Manager", "secrets.create", ["curl (REST)"], "secrets()"]],
  azure: [["Virtual machines", "Create or update", ["Azure CLI (az rest)", "Python (azure-mgmt)", "curl (ARM REST)"], "ComputeManagementClient"],
          ["Key vaults", "Get", ["Azure CLI (az rest)"], "Microsoft.KeyVault"], ["Storage accounts", "List by subscription", ["curl (ARM REST)"], "Microsoft.Storage"]],
};
const ctx = await b.newContext({ viewport: { width: 1300, height: 1000 } }); const p = await ctx.newPage();
const errs = []; p.on("pageerror", e => errs.push(String(e)));
for (const cloud of ["aws", "gcp", "azure"]) {
  await p.goto(base + "/clouds.html?embed=1#api"); await p.waitForSelector("#api-cloud-tabs");
  await p.click(`#api-cloud-tabs [data-c=${cloud}]`); await p.waitForSelector(".nd-svc", { timeout: 20000 });
  const n = await p.locator(".nd-svc").count();
  check(`${cloud}: API reference lists services (${n})`, n >= 20);
  for (const [svc, op, tabs, needle] of SAMPLE[cloud]) {
    await p.goto(base + "/clouds.html?embed=1#api"); await p.waitForSelector("#api-cloud-tabs");
    await p.click(`#api-cloud-tabs [data-c=${cloud}]`); await p.waitForSelector(".nd-svc");
    await p.locator(".nd-svc > .api-op").filter({ has: p.locator(".p", { hasText: new RegExp("^" + svc.replace(/[/]/g, "\\/") + "$") }) }).first().click();
    await p.waitForSelector(".nd-op", { timeout: 15000 });
    await p.locator(".nd-op > .api-op").filter({ has: p.locator(".p", { hasText: new RegExp("(^|\\.)" + op.replace(/[.]/g, "\\.") + "$") }) }).first().click();
    const det = p.locator(".nd-op.open .api-detail"); await det.waitFor();
    const txt = await det.innerText();
    check(`${cloud}/${svc}/${op}: wire request, parameters, response example`, /WIRE REQUEST/i.test(txt) && /PARAMETERS/i.test(txt) && /RESPONSE EXAMPLE/i.test(txt));
    const got = await det.locator(".nd-tab").allInnerTexts();
    check(`${cloud}/${svc}/${op}: snippet tabs ${tabs.join(" · ")}`, tabs.every(t => got.includes(t)), JSON.stringify(got));
    let all = "";
    for (let i = 0; i < got.length; i++) { await det.locator(".nd-tab").nth(i).click(); all += await det.locator(".nd-code code").innerText(); }
    check(`${cloud}/${svc}/${op}: snippets target the Nano endpoint + the op`, all.includes("127.0.0.1:8090") && all.includes(needle), needle);
  }
  // search narrows to matching services and auto-opens them
  await p.fill("#api-search", cloud === "aws" ? "CreateQueue" : cloud === "gcp" ? "topics.create" : "virtualMachines");
  await p.waitForTimeout(900);
  check(`${cloud}: search filters the reference`, (await p.locator(".nd-svc").count()) >= 1 && (await p.locator(".nd-svc").count()) < n);
  await p.fill("#api-search", "");
  // usage view: one card per service with CLI/SDK tabs
  await p.goto(base + "/clouds.html?embed=1#usage"); await p.waitForSelector(".u-cloud-tab"); await p.click(`.u-cloud-tab[data-cloud=${cloud}]`);
  await p.waitForSelector(".nd-ucard", { timeout: 30000 });
  const uc = await p.locator(".nd-ucard").count();
  check(`${cloud}: SDK & CLI usage shows a generated card per service (${uc})`, uc >= 20);
  const card = p.locator(".nd-ucard").first(); await card.locator(".nd-tab").nth(1).click();
  check(`${cloud}: usage card tab switch + copy button`, (await card.locator(".nd-code code").innerText()).length > 30 && (await card.locator(".nd-cp").count()) === 1);
}
check("no page errors", errs.filter(e => !/ResizeObserver/.test(e)).length === 0, JSON.stringify(errs.slice(0, 2)));
console.log(`\n${ok} passed, ${bad} failed`);
await b.close(); process.exit(bad ? 1 : 0);
