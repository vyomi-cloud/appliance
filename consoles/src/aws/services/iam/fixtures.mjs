/* UI-conformance fixtures for IAM (native Query-protocol form POST). See s3/fixtures.mjs
 * and dynamodb/fixtures.mjs for the harness contract: each export is async (wire, uniq) →
 * the unique resource name the page must then show. `wire` POSTs form-encoded Query
 * protocol params to the "iam" service and returns the parsed XML-as-object body. */
const Q = (Action, body) => ({ svc: "iam", body: new URLSearchParams({ Action, ...body }).toString(), headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8" } });

async function ensureUser(wire, name) {
  await wire("POST", "/", Q("CreateUser", { UserName: name })).catch(() => {});
}
async function ensureGroup(wire, name) {
  await wire("POST", "/", Q("CreateGroup", { GroupName: name })).catch(() => {});
}
async function ensureRole(wire, name) {
  await wire("POST", "/", Q("CreateRole", { RoleName: name, AssumeRolePolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: "ec2.amazonaws.com" }, Action: "sts:AssumeRole" }] }) })).catch(() => {});
}
async function ensurePolicy(wire, name) {
  await wire("POST", "/", Q("CreatePolicy", { PolicyName: name, PolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: "s3:ListAllMyBuckets", Resource: "*" }] }) })).catch(() => {});
}

export default {
  "iam-user": async (wire) => { await ensureUser(wire, "uic-user"); return "uic-user"; },
  "live-user": async (wire, uniq) => { await ensureUser(wire, uniq); return uniq; },

  "iam-group": async (wire) => { await ensureGroup(wire, "uic-group"); return "uic-group"; },
  "live-group": async (wire, uniq) => { await ensureGroup(wire, uniq); return uniq; },

  "iam-role": async (wire) => { await ensureRole(wire, "uic-role"); return "uic-role"; },
  "live-role": async (wire, uniq) => { await ensureRole(wire, uniq); return uniq; },

  "iam-policy": async (wire) => { await ensurePolicy(wire, "uic-policy"); return "uic-policy"; },
  "live-policy": async (wire, uniq) => { await ensurePolicy(wire, uniq); return uniq; },

  "live-idp": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateSAMLProvider", { Name: uniq, SAMLMetadataDocument: "<EntityDescriptor/>" }));
    return uniq;
  },

  "live-alias": async (wire, uniq) => {
    const alias = uniq.toLowerCase();
    await wire("POST", "/", Q("CreateAccountAlias", { AccountAlias: alias }));
    return alias;
  },

  // Vyomi-only (core/iam_core.py): Organizations SCP/RCP + account access requests.
  "live-scp": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateOrgPolicy", { Name: uniq, Type: "SERVICE_CONTROL_POLICY", Content: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: "*", Resource: "*" }] }) }));
    return uniq;
  },
  "live-rcp": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateOrgPolicy", { Name: uniq, Type: "RESOURCE_CONTROL_POLICY", Content: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: "*", Resource: "*" }] }) }));
    return uniq;
  },
  "live-access-request": async (wire, uniq) => {
    await wire("POST", "/", Q("RequestAccountAccess", { RequestorId: uniq, InitiatedBy: uniq }));
    return uniq;
  },
};
