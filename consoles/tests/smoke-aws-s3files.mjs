/* AWS-02 S3 file systems + Access Points for FSx: create a file system on a bucket, write files in the UI, see them via the S3 API,
 * add a mount target against a real subnet, create an FSx volume, attach an S3 access point and read the volume file through its alias.
 *   BASE=http://127.0.0.1:9042 node consoles/tests/smoke-aws-s3files.mjs                                                  (dev server / offline)
 *   BASE=http://127.0.0.1:8743 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-s3files.mjs        (Nano) */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9042";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH ?? "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const BUCKET = `fsmoke-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1500 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const A = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/s3");
const raw = (svc, method, path, body, extra = {}) => page.evaluate(async ([u, s, m, p, b, a, ex]) => { const r = await fetch(u + p, { method: m, headers: { authorization: a, ...ex }, body: b }); return { status: r.status, text: await r.text() }; }, [WIRE, svc, method, path, body, A(svc), extra]);
const ec2 = async (action, params) => (await raw("ec2", "POST", "/", new URLSearchParams({ Action: action, Version: "2016-11-15", ...params }).toString(), { "content-type": "application/x-www-form-urlencoded" })).text;
const fsx = async (op, payload) => { const r = await raw("fsx", "POST", "/", JSON.stringify(payload || {}), { "x-amz-target": `AmazonFSx.${op}`, "content-type": "application/x-amz-json-1.1" }); return { status: r.status, body: JSON.parse(r.text || "{}") }; };
const body = () => page.locator("body").innerText();

check("create bucket via S3 API", (await raw("s3", "PUT", `/${BUCKET}`)).status === 200);
const vpcXml = await ec2("CreateVpc", { CidrBlock: "10.9.0.0/16" });
const vpc = vpcXml.match(/<vpcId>(vpc-\w+)<\/vpcId>/)[1];
const sub = (await ec2("CreateSubnet", { VpcId: vpc, CidrBlock: "10.9.1.0/24", AvailabilityZone: "us-east-1a" })).match(/<subnetId>(subnet-\w+)<\/subnetId>/)[1];

// ── S3 file systems ──
await page.goto(UI + "#/s3/file-systems");
await page.getByRole("button", { name: "Create file system" }).first().waitFor();
check("file systems page is not Not-simulated", !/Not simulated in Vyomi/i.test(await body()));
await page.getByRole("button", { name: "Create file system" }).first().click();
await page.getByLabel("File system name").fill(`team-${N}`);
await page.getByRole("button", { name: /S3 bucket/ }).click();
await page.getByRole("option", { name: BUCKET }).click();
await page.getByLabel("Prefix").fill("share");
await page.getByRole("dialog").getByRole("button", { name: "Create file system" }).click();
await page.getByRole("row", { name: new RegExp(`team-${N}`) }).waitFor({ timeout: 10000 });
const fsId = (await page.getByRole("row", { name: new RegExp(`team-${N}`) }).innerText()).match(/fs-[0-9a-f]+/)[0];
check("file system created (wire)", (await raw("s3files", "GET", `/file-systems/${fsId}`)).status === 200);
await page.getByRole("row", { name: new RegExp(fsId) }).getByRole("radio").check();
await page.getByRole("button", { name: "New file" }).click();
await page.getByLabel("File or directory name").fill("hello.txt");
await page.getByRole("dialog").locator("textarea").fill("hello from the file system");
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByText("hello.txt").first().waitFor({ timeout: 10000 });
const obj = await raw("s3", "GET", `/${BUCKET}/share/hello.txt`);
check("UI-created file is an S3 object", obj.status === 200 && obj.text === "hello from the file system");
await raw("s3", "PUT", `/${BUCKET}/share/from-s3.txt`, "written via S3");
await page.getByRole("button", { name: "Refresh files" }).click();
await page.getByText("from-s3.txt").first().waitFor({ timeout: 10000 });
check("S3-written object appears as a file", true);
await page.screenshot({ path: `${OUT}/s3files-files.png`, fullPage: true });
await page.getByRole("tab", { name: "Mount targets" }).click();
await page.getByRole("button", { name: "Create mount target" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: /Subnet/ }).first().click();
await page.getByRole("option", { name: new RegExp(sub) }).click();
await page.getByRole("dialog").getByRole("button", { name: "Create mount target" }).click();
await page.getByText(/10\.9\.1\.\d+/).first().waitFor({ timeout: 10000 });
check("mount target created against a real subnet", true);
await page.getByRole("button", { name: "Delete", exact: true }).first().click().catch(() => {});
await raw("s3files", "DELETE", `/file-systems/${fsId}`);
check("delete blocked by mount target (wire)", (await raw("s3files", "GET", `/file-systems/${fsId}`)).status === 200);

// ── Access Points for FSx ──
const fs = (await fsx("CreateFileSystem", { FileSystemType: "OPENZFS", StorageCapacity: 64, SubnetIds: [sub], OpenZFSConfiguration: { DeploymentType: "SINGLE_AZ_2", ThroughputCapacity: 160 } })).body.FileSystem;
const root = fs.OpenZFSConfiguration.RootVolumeId;
await page.goto(UI + "#/s3/access-points-fsx");
await page.getByRole("button", { name: "Create and attach access point" }).first().waitFor();
check("FSx access points page is not Not-simulated", !/Not simulated in Vyomi/i.test(await body()));
await page.getByRole("button", { name: "Create and attach access point" }).first().click();
await page.getByLabel("Access point name").fill(`fsx-ap-${N}`);
await page.getByRole("button", { name: /FSx for OpenZFS volume/ }).click();
await page.getByRole("option", { name: new RegExp(root) }).click();
await page.getByRole("dialog").getByRole("button", { name: "Create and attach" }).click();
await page.getByText(`fsx-ap-${N}`).first().waitFor({ timeout: 10000 });
const att = (await fsx("DescribeS3AccessPointAttachments", { Names: [`fsx-ap-${N}`] })).body.S3AccessPointAttachments[0];
check("access point attached (wire)", att?.Lifecycle === "AVAILABLE" && att.S3AccessPoint.Alias.endsWith("-ext-s3alias"));
await fsx("VyomiPutVolumeFile", { VolumeId: root, Path: "/data/report.csv", Content: "a,b" });
await page.getByRole("row", { name: new RegExp(`fsx-ap-${N}`) }).getByRole("radio").check();
await page.getByText("data/", { exact: true }).first().waitFor({ timeout: 10000 });
check("UI lists the volume folder through the alias", true);
const g = await raw("s3", "GET", `/${att.S3AccessPoint.Alias}/data/report.csv`);
check("S3 GetObject via alias returns the file", g.status === 200 && g.text === "a,b");
await page.screenshot({ path: `${OUT}/s3files-fsx.png`, fullPage: true });
await page.getByRole("button", { name: "Detach and delete" }).click();
await page.waitForTimeout(800);
check("detached", (await fsx("DescribeS3AccessPointAttachments", { Names: [`fsx-ap-${N}`] })).body.S3AccessPointAttachments.length === 0);
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
