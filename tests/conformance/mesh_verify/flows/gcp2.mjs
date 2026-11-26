import { open, check, BASE, SHOTS } from "../lib.mjs";
const { browser, page, errs } = await open();
const posts=[]; page.on("request",(r)=>{ if(r.method()==="POST") posts.push(r.url().slice(BASE.length)+" "+(r.postData()||"").slice(0,150)); });
async function run(resource, perm) {
  await page.goto(`${BASE}/v4/gcp/#/iam-admin/troubleshooter`);
  await page.getByRole("textbox", { name: /^Principal/ }).fill("gcpuser@example.com");
  await page.getByRole("textbox", { name: /^Resource 1/ }).fill(resource);
  await page.getByRole("textbox", { name: /^Permission 1/ }).fill(perm);
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByText(/Granted:|Denied:/).first().waitFor({ timeout: 15000 });
  const t = await page.getByText(/Granted:|Denied:/).first().innerText();
  await page.screenshot({ path: `${SHOTS}/gcp-g2-${perm}-${resource.includes("allowed")?"allowed":"other"}.png` });
  return t;
}
const a = await run("projects/_/buckets/vfy-gcp/objects/allowed/a.txt", "storage.objects.get");
const o = await run("projects/_/buckets/vfy-gcp/objects/other/b.txt", "storage.objects.get");
const d = await run("projects/_/buckets/vfy-gcp/objects/allowed/a.txt", "storage.objects.delete");
console.log(a,"|",o,"|",d); console.log(posts.join("\n"));
check("Troubleshooter: Granted for allowed prefix (condition true)", /Granted/.test(a), a);
check("Troubleshooter: Denied for other prefix (condition false)", /Denied/.test(o), o);
check("Troubleshooter: Denied for permission not in role", /Denied/.test(d), d);
console.log(errs);
await browser.close();
