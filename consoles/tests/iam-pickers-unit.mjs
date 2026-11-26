/* Unit test (node, no browser) for the AWS IAM pickers' pure logic against the REAL verbatim catalogs in core/iam_catalog/aws.
 *   node consoles/tests/iam-pickers-unit.mjs */
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { statementsToPolicy, policyToStatements, validatePolicy, newStatement, byLevel, resourceTypesFor, actionsForType, expandAction, anyInAccountArn } from "../src/aws/kit/iamPolicy.js";
import { IAM_SERVICES } from "../src/aws/kit/iamServices.js";

const root = new URL("../../core/iam_catalog/aws/", import.meta.url);
const load = (s) => JSON.parse(readFileSync(new URL(`${s}.json`, root), "utf8"));
const cats = { s3: load("s3"), iam: load("iam"), ec2: load("ec2") };
let n = 0; const t = (name, fn) => { fn(); n++; console.log(`PASS ${name}`); };

t("service list matches every catalog file", () => { for (const [p, name] of IAM_SERVICES) assert.equal(load(p).name, name); assert.equal(IAM_SERVICES.length, 37); });
t("S3 access-level counts equal the real console (18/66/57/27/12)", () => {
  assert.deepEqual(["list", "read", "write", "permissions", "tagging"].map((l) => byLevel(cats.s3, l).length), [18, 66, 57, 27, 12]);
});
t("filter GetObject groups under Read with verbatim names", () => { const r = byLevel(cats.s3, "read", "GetObject"); assert.ok(r.includes("GetObject") && r.includes("GetObjectAcl") && r.includes("GetObjectVersionTorrent")); });
t("GetObject -> resource types accesspointobject + object", () => assert.deepEqual(resourceTypesFor(cats.s3, ["GetObject"]), ["accesspointobject", "object"]));
t("object type applies to 44 actions of all S3 (AbortMultipartUpload first)", () => { const a = actionsForType(cats.s3, Object.keys(cats.s3.actions), "object").sort(); assert.equal(a[0], "AbortMultipartUpload"); assert.equal(a.length, 44); });

t("visual model -> valid IAM JSON (service, action, specific ARN, condition)", () => {
  const st = newStatement("s3"); st.actions = ["GetObject"]; st.resMode = "specific"; st.arns = { object: ["arn:aws:s3:::my-bucket/*"] }; st.anyRes = {};
  st.mfa = true; st.conds = [{ id: "a", key: "s3:x-amz-server-side-encryption", op: "StringEquals", value: "AES256" }];
  const doc = statementsToPolicy([st], cats);
  assert.deepEqual(doc.Statement[0], { Sid: "Statement1", Effect: "Allow", Action: "s3:GetObject", Resource: "arn:aws:s3:::my-bucket/*", Condition: { Bool: { "aws:MultiFactorAuthPresent": "true" }, StringEquals: { "s3:x-amz-server-side-encryption": "AES256" } } });
  assert.equal(validatePolicy(doc, cats).errors.length, 0);
});
t("Any in this account fills the catalog ARN format", () => assert.equal(anyInAccountArn(cats.s3, "bucket"), "arn:aws:s3:::*"));
const doc = { Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: ["s3:GetObject", "s3:PutObject"], Resource: "arn:aws:s3:::b/*", Condition: { IpAddress: { "aws:SourceIp": "10.0.0.0/8" }, Bool: { "aws:MultiFactorAuthPresent": "true" } } }] };
const back = await policyToStatements(doc, async (s) => cats[s]); n++;
assert.equal(back.length, 1); assert.deepEqual(back[0].actions, ["GetObject", "PutObject"]); assert.deepEqual(back[0].arns.object, ["arn:aws:s3:::b/*"]); assert.ok(back[0].mfa && back[0].ipOn && back[0].effect === "Deny");
assert.deepEqual(statementsToPolicy(back, cats).Statement[0].Action, ["s3:GetObject", "s3:PutObject"]); console.log("PASS JSON -> visual -> JSON round trip");

t("unknown action -> error with the exact verbatim name", () => {
  const r = validatePolicy({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: "s3:GetObjekt", Resource: "*" }] }, cats);
  assert.equal(r.errors.length, 1); assert.match(r.errors[0].message, /"s3:GetObjekt" does not exist in the S3 service/);
});
t("wildcard expansion count", () => {
  const r = validatePolicy({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: "s3:GetObject*", Resource: "*" }] }, cats);
  assert.equal(r.expansions[0].count, expandAction("s3:GetObject*", cats).matches.length); assert.ok(r.expansions[0].count > 5);
});
t("invalid JSON and missing Effect are errors", () => {
  assert.match(validatePolicy("{ nope", cats).errors[0].message, /Invalid JSON/);
  assert.ok(validatePolicy({ Version: "2012-10-17", Statement: [{ Action: "s3:GetObject", Resource: "*" }] }, cats).errors.some((e) => /Effect/.test(e.message)));
});
console.log(`\n${n}/${n} unit checks passed`);
