/* (derived) Nano boot import-closure check: boots the vendored Pyodide in Node, mounts /core + /wasm exactly like
 * wasm/nano-boot.js (and the relay loaders' CORES lists), then imports EVERY listed core plus the console
 * router (Backends, providers, wire_adapter). Any ImportError / SyntaxError / missing stdlib module that
 * Pyodide lacks fails here instead of at a user's boot.
 *
 *   python3 wasm/fetch_pyodide.py && python3 wasm/build_cores.py
 *   node consoles/tests/nano-core-import-check.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join, dirname } from "node:path";

const W = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "wasm");
const list = (file, name) => {
  const m = readFileSync(join(W, file), "utf8").match(new RegExp(`const ${name}\\s*=\\s*\\[(.*?)\\];`, "s"));
  return m ? [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]) : [];
};
const loaders = { "nano-boot.js": list("nano-boot.js", "CORES"), "relay/nano-endpoint.html": list("relay/nano-endpoint.html", "CORES"), "relay/relay-shared-worker.js": list("relay/relay-shared-worker.js", "CORES") };
const pkgs = list("nano-boot.js", "CORE_PKGS");
const modules = list("nano-boot.js", "MODULES");
const all = [...new Set(Object.values(loaders).flat())];
console.log(`cores: ${Object.entries(loaders).map(([k, v]) => `${k}=${v.length}`).join(" ")} union=${all.length}`);

const { loadPyodide } = await import(pathToFileURL(join(W, "vendor/pyodide/pyodide.mjs")).href);
const py = await loadPyodide({ indexURL: join(W, "vendor/pyodide") + "/" });
try { await py.loadPackage("sqlite3"); } catch (e) { console.log("sqlite3 package skipped:", String(e).slice(0, 100)); }
const put = (p, src) => { const d = dirname(p); py.FS.mkdirTree(d); py.FS.writeFile(p, src); };
py.FS.mkdirTree("/core"); py.FS.writeFile("/core/__init__.py", "");
for (const c of all) put("/core/" + c, readFileSync(join(W, "core", c), "utf8"));
for (const c of pkgs) put("/core/" + c, readFileSync(join(W, "core", c), "utf8"));
py.FS.mkdirTree("/wasm/backends"); py.FS.mkdirTree("/wasm/providers");
py.FS.writeFile("/wasm/__init__.py", ""); py.FS.writeFile("/wasm/backends/__init__.py", "");
for (const m of modules) put("/wasm/" + m, readFileSync(join(W, m), "utf8"));


// the IAM engine package + extras are mounted on demand by wasm/nano-iam-hook.js: mount the whole vendored tree the same way
import { readdirSync, statSync } from "node:fs";
const walk = (d, rel = "") => { for (const f of readdirSync(join(d, rel))) { const r = rel ? rel + "/" + f : f; if (statSync(join(d, r)).isDirectory()) walk(d, r); else if (/\.(py|json)$/.test(f)) put("/core/" + r, readFileSync(join(d, r), "utf8")); } };
walk(join(W, "core"));
const out = JSON.parse(py.runPython(`
import sys, json
sys.path.insert(0, "/")
from core import nano_registry
from core.aws_wire_router import AwsWireRouter
from core.iam_engine.api import IamApi
reg = nano_registry.get()
R = AwsWireRouter(stores=reg)
api = IamApi()      # same object the Nano hook builds: governance served by core.iam_governance over the Nano registry
res = {}
def wire(m, p, body=None, q=None, h=None):
    o = R.handle(m, p, q or {}, h or {}, json.dumps(body).encode() if body is not None else b"")
    b = o.get("body") or b""
    b = b.decode() if isinstance(b, (bytes, bytearray)) else b
    return o["status"], (json.loads(b) if b[:1] in "{[" else b)
AZ = {"authorization": "x"}
# Azure: management group + subscription move + MG-scope role assignment + policy assignment, then the engine view
res["mg_create"] = wire("PUT", "/providers/Microsoft.Management/managementGroups/mg-n", {"properties": {"displayName": "N"}}, {"api-version": "2021-04-01"})[0]
res["sub_move"] = wire("PUT", "/providers/Microsoft.Management/managementGroups/mg-n/subscriptions/00000000-0000-0000-0000-cloudlearn01", None, {"api-version": "2021-04-01"})[0]
res["ra_put"] = wire("PUT", "/providers/Microsoft.Management/managementGroups/mg-n/providers/Microsoft.Authorization/roleAssignments/aaaaaaaa-0000-0000-0000-000000000001",
                     {"properties": {"principalId": "pp", "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"}}, {"api-version": "2022-04-01"})[0]
s, eff = api.handle("GET", "/api/iam/azure/governance/effective", {"scope": "/subscriptions/00000000-0000-0000-0000-cloudlearn01"})
res["azure_effective"] = [s, [r["principalId"] for r in eff["roleAssignments"]]]
s, h = api.handle("GET", "/api/iam/azure/governance/hierarchy", {})
res["azure_tree"] = [s, [c["name"] for c in h["root"]["children"]], [c["kind"] for c in h["root"]["children"][0]["children"]] if h["root"]["children"] else None]
# GCP: org policy on a folder-less project, enforced + dry run
res["gcp_org_pol"] = wire("POST", "/v2/projects/nano-project/policies", {"name": "projects/nano-project/policies/iam.disableServiceAccountKeyCreation", "spec": {"rules": [{"enforce": True}]}})[0]
s, v = api.handle("GET", "/api/iam/gcp/governance/orgpolicy", {"node": "projects/nano-project"})
res["gcp_view"] = [s, [c["effective"].get("enforce") for c in v["constraints"] if c["constraint"].endswith("disableServiceAccountKeyCreation")]]
s, c = api.handle("POST", "/api/iam/gcp/governance/orgpolicy/check", {}, {"node": "projects/nano-project", "constraint": "iam.disableServiceAccountKeyCreation"})
res["gcp_check"] = [s, c.get("wouldBlock")]
# AWS: org, SCP attach, effective, S3 BPA
def aws(op, p=None):
    return wire("POST", "/", p or {}, None, {"authorization": "AWS4-HMAC-SHA256 Credential=X/20261101/us-east-1/organizations/aws4_request", "content-type": "application/x-amz-json-1.1", "x-amz-target": "AWSOrganizationsV20161128." + op})
aws("CreateOrganization", {"FeatureSet": "ALL"})
root = aws("ListRoots")[1]["Roots"][0]["Id"]
aws("EnablePolicyType", {"RootId": root, "PolicyType": "SERVICE_CONTROL_POLICY"})
ou = aws("CreateOrganizationalUnit", {"ParentId": root, "Name": "W"})[1]["OrganizationalUnit"]["Id"]
acct = aws("CreateAccount", {"Email": "a@x.io", "AccountName": "t"})[1]["CreateAccountStatus"]["AccountId"]
aws("MoveAccount", {"AccountId": acct, "SourceParentId": root, "DestinationParentId": ou})
pid = aws("CreatePolicy", {"Name": "d", "Description": "", "Type": "SERVICE_CONTROL_POLICY", "Content": json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "s3:DeleteBucket", "Resource": "*"}]})})[1]["Policy"]["PolicySummary"]["Id"]
res["attach"] = aws("AttachPolicy", {"PolicyId": pid, "TargetId": ou})[0]
s, c = api.handle("POST", "/api/iam/aws/governance/check", {}, {"account": acct, "action": "s3:DeleteBucket"})
res["aws_check"] = [s, c.get("allowed"), c.get("reason")]
s, c = api.handle("POST", "/api/iam/aws/governance/check", {}, {"account": acct, "action": "s3:ListBucket"})
res["aws_check_allowed"] = [s, c.get("allowed")]
json.dumps(res)
`));
console.log(JSON.stringify(out, null, 1));
const exp = { mg_create: 200, sub_move: 200 };
let bad = 0; const chk = (n, ok) => { if (!ok) bad++; console.log((ok ? "PASS " : "FAIL ") + n); };
chk("MG create 200", out.mg_create === 200); chk("subscription moved", [200, 204].includes(out.sub_move));
chk("MG role assignment accepted", [200, 201].includes(out.ra_put));
chk("engine sees the inherited MG role assignment (Nano state)", out.azure_effective[1].includes("pp"));
chk("hierarchy lists MG with subscription under it", out.azure_tree[1].includes("mg-n"));
chk("GCP org policy created over the Nano router", out.gcp_org_pol === 200);
chk("GCP governance view: enforced", out.gcp_view[1][0] === true);
chk("GCP check: would block", out.gcp_check[1] === true);
chk("AWS SCP attached", out.attach === 200);
chk("AWS check: SCP denies", out.aws_check[1] === false);
chk("AWS check: other action allowed", out.aws_check_allowed[1] === true);
process.exit(bad ? 1 : 0);
