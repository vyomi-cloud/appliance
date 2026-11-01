/* Key policy construction — the same Sids/actions the real KMS console's visual policy
 * editor manages (Key administrators / Key users / Other AWS accounts); everything else
 * in the document (including the root "Enable IAM User Permissions" statement and any
 * statement the raw JSON editor introduced) passes through untouched. Vyomi stores and
 * returns the policy exactly as written (kms.key.policy) — this module only decides what
 * JSON the visual editor writes, the write itself goes through the real PutKeyPolicy call. */
export const DEFAULT_ACCOUNT_ID = "123456789012";

export const ROOT_SID = "Enable IAM User Permissions";
export const ADMIN_SID = "Allow access for Key Administrators";
export const USER_SID = "Allow use of the key";
export const GRANT_SID = "Allow attachment of persistent resources";
export const EXTERNAL_SID = "Allow use of the key by authorized external accounts";
const MANAGED_SIDS = new Set([ROOT_SID, ADMIN_SID, USER_SID, GRANT_SID, EXTERNAL_SID]);

const ADMIN_ACTIONS = ["kms:Create*", "kms:Describe*", "kms:Enable*", "kms:List*", "kms:Put*", "kms:Update*", "kms:Revoke*", "kms:Disable*", "kms:Get*", "kms:Delete*", "kms:TagResource", "kms:UntagResource", "kms:CancelKeyDeletion", "kms:RotateKeyOnDemand"];
const USER_ACTIONS = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"];
const GRANT_ACTIONS = ["kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"];

const asArray = (v) => (v === undefined || v === null ? [] : Array.isArray(v) ? v : [v]);
const parse = (policyText) => { try { return JSON.parse(policyText || "{}"); } catch { return {}; } };
const statement = (doc, sid) => (doc.Statement || []).find((s) => s.Sid === sid);

export const accountIdFromArn = (arn) => String(arn || "").split(":")[4] || DEFAULT_ACCOUNT_ID;

/** Principal ARNs (users/roles) a managed statement currently grants. */
export function principalArnsFromPolicy(policyText, sid) {
  return asArray(statement(parse(policyText), sid)?.Principal?.AWS);
}

/** Other AWS accounts: account IDs pulled out of the external-accounts statement's root ARNs. */
export function externalAccountIdsFromPolicy(policyText) {
  return principalArnsFromPolicy(policyText, EXTERNAL_SID).map(accountIdFromArn);
}

export function adminDeleteAllowedFromPolicy(policyText) {
  const actions = asArray(statement(parse(policyText), ADMIN_SID)?.Action);
  return actions.length === 0 ? true : actions.includes("kms:ScheduleKeyDeletion");
}

/** Statements the visual editor doesn't own (custom Sids, or none at all) — carried through untouched. */
export function extraStatementsFromPolicy(policyText) {
  return (parse(policyText).Statement || []).filter((s) => !MANAGED_SIDS.has(s.Sid));
}

const principal = (arns) => (arns.length === 1 ? arns[0] : arns);

/** Rebuild the full key policy document from the visual editor's selections. */
export function buildKeyPolicy({ accountId = DEFAULT_ACCOUNT_ID, adminArns = [], allowAdminDelete = true, userArns = [], otherAccountIds = [], extraStatements = [] }) {
  const statements = [
    { Sid: ROOT_SID, Effect: "Allow", Principal: { AWS: `arn:aws:iam::${accountId}:root` }, Action: "kms:*", Resource: "*" },
  ];
  if (adminArns.length) {
    const actions = allowAdminDelete ? [...ADMIN_ACTIONS, "kms:ScheduleKeyDeletion"] : ADMIN_ACTIONS;
    statements.push({ Sid: ADMIN_SID, Effect: "Allow", Principal: { AWS: principal(adminArns) }, Action: actions, Resource: "*" });
  }
  if (userArns.length) {
    statements.push({ Sid: USER_SID, Effect: "Allow", Principal: { AWS: principal(userArns) }, Action: USER_ACTIONS, Resource: "*" });
    statements.push({ Sid: GRANT_SID, Effect: "Allow", Principal: { AWS: principal(userArns) }, Action: GRANT_ACTIONS, Resource: "*", Condition: { Bool: { "kms:GrantIsForAWSResource": "true" } } });
  }
  if (otherAccountIds.length) {
    const arns = otherAccountIds.map((id) => `arn:aws:iam::${id}:root`);
    statements.push({ Sid: EXTERNAL_SID, Effect: "Allow", Principal: { AWS: principal(arns) }, Action: USER_ACTIONS, Resource: "*" });
  }
  statements.push(...extraStatements);
  return JSON.stringify({ Version: "2012-10-17", Id: "key-default-1", Statement: statements }, null, 2);
}
