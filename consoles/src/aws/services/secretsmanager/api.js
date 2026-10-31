/* Secrets Manager over the native JSON wire (X-Amz-Target secretsmanager.*). */
import { awsJson, awsQuery, asList } from "../../../common/wire.js";

const call = (op, body) => awsJson("secretsmanager", `secretsmanager.${op}`, body, { version: "1.1" });

export const createSecret = (input) => call("CreateSecret", input);
export const getSecretValue = (secretId, opts = {}) => call("GetSecretValue", { SecretId: secretId, ...opts });
export const putSecretValue = (secretId, value) => call("PutSecretValue", { SecretId: secretId, ...value });
export const updateSecret = (secretId, input) => call("UpdateSecret", { SecretId: secretId, ...input });
export const describeSecret = (secretId) => call("DescribeSecret", { SecretId: secretId });
export const listSecrets = async () => {
  const out = [];
  let token;
  do {
    const r = await call("ListSecrets", token ? { NextToken: token } : {});
    out.push(...(r.SecretList || []));
    token = r.NextToken;
  } while (token);
  return out;
};
export const listSecretVersionIds = (secretId) => call("ListSecretVersionIds", { SecretId: secretId }).then((r) => r.Versions || []);
export const deleteSecret = (secretId, recoveryWindowInDays) => call("DeleteSecret", { SecretId: secretId, RecoveryWindowInDays: recoveryWindowInDays });
export const restoreSecret = (secretId) => call("RestoreSecret", { SecretId: secretId });
export const rotateSecret = (secretId, input = {}) => call("RotateSecret", { SecretId: secretId, ...input });

export const tagResource = (secretId, tags) => call("TagResource", { SecretId: secretId, Tags: tags });
export const untagResource = (secretId, tagKeys) => call("UntagResource", { SecretId: secretId, TagKeys: tagKeys });

export const getResourcePolicy = (secretId) => call("GetResourcePolicy", { SecretId: secretId }).then((r) => r.ResourcePolicy);
export const putResourcePolicy = (secretId, policy) => call("PutResourcePolicy", { SecretId: secretId, ResourcePolicy: policy });
export const deleteResourcePolicy = (secretId) => call("DeleteResourcePolicy", { SecretId: secretId });

/** KMS key aliases, for the Encryption key picker — a real cross-service read (same
 * TrentService wire the KMS console speaks), not a canned list. */
export const listKmsAliases = () => awsJson("kms", "TrentService.ListAliases", {}, { version: "1.1" }).then((r) => (r.Aliases || []).map((a) => a.AliasName.replace(/^alias\//, "")));

/** RDS DB instances, for the "Credentials for Amazon RDS database" wizard step's
 * Database picker — a real cross-service read (the same DescribeDBInstances the RDS
 * console speaks) of the account's actual instances; DocumentDB/Redshift have no core
 * yet (core/capabilities/aws/secretsmanager.json: secretsmanager.secret.database-picker). */
export const listDbInstances = async () => {
  const r = await awsQuery("rds", "DescribeDBInstances", {});
  return asList(r.DescribeDBInstancesResponse?.DescribeDBInstancesResult?.DBInstances?.DBInstance);
};

export const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
export const unb64 = (s) => decodeURIComponent(escape(atob(s)));

/** The secret's JSON value as key/value pairs, or null if it isn't a flat JSON object
 * (in which case it's shown/edited as plaintext — the same rule the real console uses). */
export function asKeyValue(secretString) {
  if (secretString == null) return null;
  try {
    const obj = JSON.parse(secretString);
    if (obj && typeof obj === "object" && !Array.isArray(obj)) return Object.entries(obj).map(([key, value]) => ({ key, value: String(value) }));
  } catch { /* not JSON — plaintext */ }
  return null;
}
