import assert from "node:assert/strict";
import { resolveMode, withMode, filterAudit, normalizeAudit, auditLabel, iamApi, mockIam, iamBase, emptySettings } from "./iamEnforce.js";

let s = emptySettings();
assert.deepEqual(resolveMode(s, "s3", "arn:b"), { mode: "off", source: "space" });
assert.deepEqual(resolveMode(null, "s3", "x"), { mode: "off", source: "default" });
s = withMode(s, "global", null, "audit");
s = withMode(s, "space", null, "enforce");
assert.deepEqual(resolveMode(s, "s3", "arn:b"), { mode: "enforce", source: "space" });
s = withMode(s, "service", "s3", "audit");
assert.deepEqual(resolveMode(s, "s3", "arn:b"), { mode: "audit", source: "service" });
assert.deepEqual(resolveMode(s, "sqs", "arn:q"), { mode: "enforce", source: "space" });
s = withMode(s, "resource", "arn:b", "off");
assert.deepEqual(resolveMode(s, "s3", "arn:b"), { mode: "off", source: "resource" });
s = withMode(s, "resource", "arn:b", "inherit");            // clears
assert.deepEqual(resolveMode(s, "s3", "arn:b"), { mode: "audit", source: "service" });
assert.throws(() => withMode(s, "space", null, "bogus"));
assert.equal(iamBase("/nano/_wire"), "/nano/_wire/api/iam");
assert.equal(iamBase("/_wire"), "/_wire/api/iam");

const rows = [
  { mode: "audit", allowed: false, principal: "u", action: "s3:Get", resource: "r" },
  { mode: "enforce", allowed: false }, { mode: "enforce", allowed: true }, { mode: "audit", allowed: true },
].map(normalizeAudit);
assert.equal(rows[0].wouldDeny, true); assert.equal(auditLabel(rows[0]), "Would deny"); assert.equal(auditLabel(rows[1]), "Denied");
assert.equal(filterAudit(rows, { decision: "would_deny" }).length, 1);
assert.equal(filterAudit(rows, { mode: "enforce", decision: "deny" }).length, 1);
assert.equal(filterAudit(rows, { mode: "audit" }).length, 2);

const mock = mockIam("aws", { allow: (r) => r.action !== "s3:DeleteBucket" });
const api = iamApi("aws", { base: "/api/iam", fetcher: mock.fetcher });
await api.putEnforcement(withMode(await api.getEnforcement(), "service", "s3", "audit"));
assert.equal((await api.getEnforcement()).services.s3, "audit");
const d = await api.evaluate({ principal: "arn:aws:iam::1:user/a", action: "s3:DeleteBucket", resource: "arn:aws:s3:::b" });
assert.equal(d.allowed, false);
const a = await api.audit(10);
assert.equal(a.length, 1); assert.equal(a[0].wouldDeny, true);
console.log("iamEnforce tests passed");
