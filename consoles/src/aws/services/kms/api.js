/* KMS over the native JSON wire (X-Amz-Target TrentService.*). */
import { asList, awsJson, awsQuery } from "../../../common/wire.js";

const call = (op, body) => awsJson("kms", `TrentService.${op}`, body, { version: "1.1" });

/** This account's IAM users/roles, for the key policy visual editor's principal pickers. */
export const listIamUsers = async () => asList((await awsQuery("iam", "ListUsers", {})).ListUsersResponse.ListUsersResult.Users?.User);
export const listIamRoles = async () => asList((await awsQuery("iam", "ListRoles", {})).ListRolesResponse.ListRolesResult.Roles?.Role);

export const createKey = (input) => call("CreateKey", input).then((r) => r.KeyMetadata);
export const describeKey = (keyId) => call("DescribeKey", { KeyId: keyId }).then((r) => r.KeyMetadata);
export const listKeys = async () => {
  const out = [];
  let marker;
  do {
    const r = await call("ListKeys", marker ? { Marker: marker } : {});
    out.push(...(r.Keys || []));
    marker = r.Truncated ? r.NextMarker : undefined;
  } while (marker);
  return out;
};
export const enableKey = (keyId) => call("EnableKey", { KeyId: keyId });
export const disableKey = (keyId) => call("DisableKey", { KeyId: keyId });
export const scheduleKeyDeletion = (keyId, pendingWindowInDays) => call("ScheduleKeyDeletion", { KeyId: keyId, PendingWindowInDays: pendingWindowInDays });
export const cancelKeyDeletion = (keyId) => call("CancelKeyDeletion", { KeyId: keyId });

export const createAlias = (aliasName, targetKeyId) => call("CreateAlias", { AliasName: aliasName, TargetKeyId: targetKeyId });
export const updateAlias = (aliasName, targetKeyId) => call("UpdateAlias", { AliasName: aliasName, TargetKeyId: targetKeyId });
export const deleteAlias = (aliasName) => call("DeleteAlias", { AliasName: aliasName });
export const listAliases = (keyId) => call("ListAliases", keyId ? { KeyId: keyId } : {}).then((r) => r.Aliases || []);

export const getKeyPolicy = (keyId) => call("GetKeyPolicy", { KeyId: keyId, PolicyName: "default" }).then((r) => r.Policy);
export const putKeyPolicy = (keyId, policy) => call("PutKeyPolicy", { KeyId: keyId, PolicyName: "default", Policy: policy });

export const listResourceTags = (keyId) => call("ListResourceTags", { KeyId: keyId }).then((r) => r.Tags || []);
export const tagResource = (keyId, tags) => call("TagResource", { KeyId: keyId, Tags: tags });
export const untagResource = (keyId, tagKeys) => call("UntagResource", { KeyId: keyId, TagKeys: tagKeys });

export const getKeyRotationStatus = (keyId) => call("GetKeyRotationStatus", { KeyId: keyId });
export const enableKeyRotation = (keyId, rotationPeriodInDays) => call("EnableKeyRotation", { KeyId: keyId, ...(rotationPeriodInDays ? { RotationPeriodInDays: rotationPeriodInDays } : {}) });
export const disableKeyRotation = (keyId) => call("DisableKeyRotation", { KeyId: keyId });
export const rotateKeyOnDemand = (keyId) => call("RotateKeyOnDemand", { KeyId: keyId });
export const listKeyRotations = (keyId) => call("ListKeyRotations", { KeyId: keyId }).then((r) => r.Rotations || []);

export const encrypt = (keyId, plaintextB64) => call("Encrypt", { KeyId: keyId, Plaintext: plaintextB64 });
export const decrypt = (ciphertextBlobB64, keyId) => call("Decrypt", { CiphertextBlob: ciphertextBlobB64, ...(keyId ? { KeyId: keyId } : {}) });
export const generateDataKey = (keyId, keySpec) => call("GenerateDataKey", { KeyId: keyId, KeySpec: keySpec || "AES_256" });

export const createCustomKeyStore = (input) => call("CreateCustomKeyStore", input);
export const describeCustomKeyStores = (filter) => call("DescribeCustomKeyStores", filter || {}).then((r) => r.CustomKeyStores || []);
export const connectCustomKeyStore = (id) => call("ConnectCustomKeyStore", { CustomKeyStoreId: id });
export const disconnectCustomKeyStore = (id) => call("DisconnectCustomKeyStore", { CustomKeyStoreId: id });
export const deleteCustomKeyStore = (id) => call("DeleteCustomKeyStore", { CustomKeyStoreId: id });

/** Customer managed keys: every key whose KeyManager isn't AWS, with its aliases. */
export async function listCustomerManagedKeys() {
  const [keys, aliases] = await Promise.all([listKeys(), listAliases()]);
  const aliasesOf = (keyId) => aliases.filter((a) => a.TargetKeyId === keyId && !a.AliasName.startsWith("alias/aws/")).map((a) => a.AliasName.replace(/^alias\//, ""));
  const out = [];
  for (const k of keys) {
    const md = await describeKey(k.KeyId);
    if (md.KeyManager !== "AWS") out.push({ ...md, aliases: aliasesOf(md.KeyId) });
  }
  return out;
}

export const keyType = (md) => (/^(RSA_|ECC_|ML_DSA|ML_KEM)/.test(md.KeySpec) ? "Asymmetric" : "Symmetric");

/** AWS managed keys: aliases named "aws/<service>". They auto-provision on first
 * use (Encrypt/GenerateDataKey), so the list is whatever has been used so far. */
export async function listAwsManagedKeys() {
  const aliases = (await listAliases()).filter((a) => a.AliasName.startsWith("alias/aws/"));
  const out = [];
  for (const a of aliases) {
    try { out.push({ alias: a.AliasName, ...(await describeKey(a.TargetKeyId)) }); }
    catch { /* alias target vanished; skip */ }
  }
  return out;
}

export const b64 = (s) => btoa(unescape(encodeURIComponent(s)));
export const unb64 = (s) => decodeURIComponent(escape(atob(s)));
