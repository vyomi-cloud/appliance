/* IAM over the native Query protocol (form POST, XML response). See core/iam_core.py
 * for the exact action set and XML shapes; awsQuery() in common/wire.js parses the XML
 * response into a plain JS object keyed by `${Action}Response`. */
import { asList, awsQuery } from "../../../common/wire.js";

const call = (action, params = {}) => awsQuery("iam", action, params);

/** Flatten list params the AWS Query protocol expects: base.member.1, base.member.2, … */
export function members(base, values = []) {
  const out = {};
  values.forEach((v, i) => { out[`${base}.member.${i + 1}`] = v; });
  return out;
}

export function tagsParams(tags = []) {
  const out = {};
  tags.forEach((t, i) => { out[`Tags.member.${i + 1}.Key`] = t.key ?? t.Key; out[`Tags.member.${i + 1}.Value`] = t.value ?? t.Value ?? ""; });
  return out;
}

export const tagsFromXml = (t) => Object.entries(t || {}).length === 0 ? [] : asList(t.member).map((m) => ({ Key: m.Key, Value: m.Value }));

// ── users ────────────────────────────────────────────────────────────────
export const createUser = async (params) => (await call("CreateUser", params)).CreateUserResponse.CreateUserResult.User;
export const getUser = async (UserName) => (await call("GetUser", { UserName })).GetUserResponse.GetUserResult.User;
export const listUsers = async () => asList((await call("ListUsers", {})).ListUsersResponse.ListUsersResult.Users?.User);
export const deleteUser = (UserName) => call("DeleteUser", { UserName });
export const updateUser = (UserName, params) => call("UpdateUser", { UserName, ...params });
export const tagUser = (UserName, tags) => call("TagUser", { UserName, ...tagsParams(tags) });
export const untagUser = (UserName, keys) => call("UntagUser", { UserName, ...members("TagKeys", keys) });
export const listUserTags = async (UserName) => tagsFromXml((await call("ListUserTags", { UserName })).ListUserTagsResponse.ListUserTagsResult.Tags);
export const putUserPermissionsBoundary = (UserName, PermissionsBoundary) => call("PutUserPermissionsBoundary", { UserName, PermissionsBoundary });
export const deleteUserPermissionsBoundary = (UserName) => call("DeleteUserPermissionsBoundary", { UserName });

// ── console sign-in (login profile) ─────────────────────────────────────
export const createLoginProfile = async (UserName, Password, PasswordResetRequired) =>
  (await call("CreateLoginProfile", { UserName, Password, PasswordResetRequired: String(!!PasswordResetRequired) })).CreateLoginProfileResponse.CreateLoginProfileResult.LoginProfile;
export const getLoginProfile = async (UserName) => {
  try { return (await call("GetLoginProfile", { UserName })).GetLoginProfileResponse.GetLoginProfileResult.LoginProfile; }
  catch (e) { if (e.code === "NoSuchEntity") return null; throw e; }
};
export const updateLoginProfile = (UserName, params) => call("UpdateLoginProfile", { UserName, ...params });
export const deleteLoginProfile = (UserName) => call("DeleteLoginProfile", { UserName });

// ── groups ───────────────────────────────────────────────────────────────
export const createGroup = async (params) => (await call("CreateGroup", params)).CreateGroupResponse.CreateGroupResult.Group;
export const listGroups = async () => asList((await call("ListGroups", {})).ListGroupsResponse.ListGroupsResult.Groups?.Group);
export const getGroup = async (GroupName) => {
  const r = (await call("GetGroup", { GroupName })).GetGroupResponse.GetGroupResult;
  return { group: r.Group, users: asList(r.Users?.User) };
};
export const deleteGroup = (GroupName) => call("DeleteGroup", { GroupName });
export const addUserToGroup = (GroupName, UserName) => call("AddUserToGroup", { GroupName, UserName });
export const removeUserFromGroup = (GroupName, UserName) => call("RemoveUserFromGroup", { GroupName, UserName });
export const listGroupsForUser = async (UserName) => asList((await call("ListGroupsForUser", { UserName })).ListGroupsForUserResponse.ListGroupsForUserResult.Groups?.Group);
export const attachGroupPolicy = (GroupName, PolicyArn) => call("AttachGroupPolicy", { GroupName, PolicyArn });
export const detachGroupPolicy = (GroupName, PolicyArn) => call("DetachGroupPolicy", { GroupName, PolicyArn });
export const listAttachedGroupPolicies = async (GroupName) => asList((await call("ListAttachedGroupPolicies", { GroupName })).ListAttachedGroupPoliciesResponse.ListAttachedGroupPoliciesResult.AttachedPolicies?.member);
export const putGroupPolicy = (GroupName, PolicyName, PolicyDocument) => call("PutGroupPolicy", { GroupName, PolicyName, PolicyDocument });
export const getGroupPolicy = async (GroupName, PolicyName) => (await call("GetGroupPolicy", { GroupName, PolicyName })).GetGroupPolicyResponse.GetGroupPolicyResult;
export const listGroupPolicies = async (GroupName) => asList((await call("ListGroupPolicies", { GroupName })).ListGroupPoliciesResponse.ListGroupPoliciesResult.PolicyNames?.member);
export const deleteGroupPolicy = (GroupName, PolicyName) => call("DeleteGroupPolicy", { GroupName, PolicyName });

// ── user permissions (attach/detach, inline) ────────────────────────────
export const attachUserPolicy = (UserName, PolicyArn) => call("AttachUserPolicy", { UserName, PolicyArn });
export const detachUserPolicy = (UserName, PolicyArn) => call("DetachUserPolicy", { UserName, PolicyArn });
export const listAttachedUserPolicies = async (UserName) => asList((await call("ListAttachedUserPolicies", { UserName })).ListAttachedUserPoliciesResponse.ListAttachedUserPoliciesResult.AttachedPolicies?.member);
export const putUserPolicy = (UserName, PolicyName, PolicyDocument) => call("PutUserPolicy", { UserName, PolicyName, PolicyDocument });
export const getUserPolicy = async (UserName, PolicyName) => (await call("GetUserPolicy", { UserName, PolicyName })).GetUserPolicyResponse.GetUserPolicyResult;
export const listUserPolicies = async (UserName) => asList((await call("ListUserPolicies", { UserName })).ListUserPoliciesResponse.ListUserPoliciesResult.PolicyNames?.member);
export const deleteUserPolicy = (UserName, PolicyName) => call("DeleteUserPolicy", { UserName, PolicyName });

// ── access keys ──────────────────────────────────────────────────────────
export const createAccessKey = async (UserName) => (await call("CreateAccessKey", { UserName })).CreateAccessKeyResponse.CreateAccessKeyResult.AccessKey;
export const listAccessKeys = async (UserName) => asList((await call("ListAccessKeys", { UserName })).ListAccessKeysResponse.ListAccessKeysResult.AccessKeyMetadata?.member);
export const updateAccessKey = (UserName, AccessKeyId, Status) => call("UpdateAccessKey", { UserName, AccessKeyId, Status });
export const deleteAccessKey = (UserName, AccessKeyId) => call("DeleteAccessKey", { UserName, AccessKeyId });

// ── multi-factor authentication (virtual MFA devices) ───────────────────
export const createVirtualMfaDevice = async (VirtualMFADeviceName) =>
  (await call("CreateVirtualMFADevice", { VirtualMFADeviceName })).CreateVirtualMFADeviceResponse.CreateVirtualMFADeviceResult.VirtualMFADevice;
export const deleteVirtualMfaDevice = (SerialNumber) => call("DeleteVirtualMFADevice", { SerialNumber });
export const enableMfaDevice = (UserName, SerialNumber, AuthenticationCode1, AuthenticationCode2) =>
  call("EnableMFADevice", { UserName, SerialNumber, AuthenticationCode1, AuthenticationCode2 });
export const deactivateMfaDevice = (UserName, SerialNumber) => call("DeactivateMFADevice", { UserName, SerialNumber });
export const resyncMfaDevice = (UserName, SerialNumber, AuthenticationCode1, AuthenticationCode2) =>
  call("ResyncMFADevice", { UserName, SerialNumber, AuthenticationCode1, AuthenticationCode2 });
export const listMfaDevices = async (UserName) => asList((await call("ListMFADevices", { UserName })).ListMFADevicesResponse.ListMFADevicesResult.MFADevices?.member);
export const listVirtualMfaDevices = async (AssignmentStatus) =>
  asList((await call("ListVirtualMFADevices", AssignmentStatus ? { AssignmentStatus } : {})).ListVirtualMFADevicesResponse.ListVirtualMFADevicesResult.VirtualMFADevices?.member);

// ── roles ────────────────────────────────────────────────────────────────
export const createRole = async (params) => (await call("CreateRole", params)).CreateRoleResponse.CreateRoleResult.Role;
export const getRole = async (RoleName) => (await call("GetRole", { RoleName })).GetRoleResponse.GetRoleResult.Role;
export const listRoles = async () => asList((await call("ListRoles", {})).ListRolesResponse.ListRolesResult.Roles?.Role);
export const deleteRole = (RoleName) => call("DeleteRole", { RoleName });
export const updateRole = (RoleName, params) => call("UpdateRole", { RoleName, ...params });
export const updateAssumeRolePolicy = (RoleName, PolicyDocument) => call("UpdateAssumeRolePolicy", { RoleName, PolicyDocument });
export const listAttachedRolePolicies = async (RoleName) => asList((await call("ListAttachedRolePolicies", { RoleName })).ListAttachedRolePoliciesResponse.ListAttachedRolePoliciesResult.AttachedPolicies?.member);
export const attachRolePolicy = (RoleName, PolicyArn) => call("AttachRolePolicy", { RoleName, PolicyArn });
export const detachRolePolicy = (RoleName, PolicyArn) => call("DetachRolePolicy", { RoleName, PolicyArn });
export const putRolePolicy = (RoleName, PolicyName, PolicyDocument) => call("PutRolePolicy", { RoleName, PolicyName, PolicyDocument });
export const getRolePolicy = async (RoleName, PolicyName) => (await call("GetRolePolicy", { RoleName, PolicyName })).GetRolePolicyResponse.GetRolePolicyResult;
export const listRolePolicies = async (RoleName) => asList((await call("ListRolePolicies", { RoleName })).ListRolePoliciesResponse.ListRolePoliciesResult.PolicyNames?.member);
export const deleteRolePolicy = (RoleName, PolicyName) => call("DeleteRolePolicy", { RoleName, PolicyName });
export const tagRole = (RoleName, tags) => call("TagRole", { RoleName, ...tagsParams(tags) });
export const untagRole = (RoleName, keys) => call("UntagRole", { RoleName, ...members("TagKeys", keys) });
export const listRoleTags = async (RoleName) => tagsFromXml((await call("ListRoleTags", { RoleName })).ListRoleTagsResponse.ListRoleTagsResult.Tags);
export const putRolePermissionsBoundary = (RoleName, PermissionsBoundary) => call("PutRolePermissionsBoundary", { RoleName, PermissionsBoundary });
export const deleteRolePermissionsBoundary = (RoleName) => call("DeleteRolePermissionsBoundary", { RoleName });

// ── managed policies ─────────────────────────────────────────────────────
export const createPolicy = async (params) => (await call("CreatePolicy", params)).CreatePolicyResponse.CreatePolicyResult.Policy;
export const getPolicy = async (PolicyArn) => (await call("GetPolicy", { PolicyArn })).GetPolicyResponse.GetPolicyResult.Policy;
export const listPolicies = async () => asList((await call("ListPolicies", {})).ListPoliciesResponse.ListPoliciesResult.Policies?.Policy);
export const deletePolicy = (PolicyArn) => call("DeletePolicy", { PolicyArn });
export const createPolicyVersion = async (PolicyArn, PolicyDocument, SetAsDefault) =>
  (await call("CreatePolicyVersion", { PolicyArn, PolicyDocument, SetAsDefault: String(!!SetAsDefault) })).CreatePolicyVersionResponse.CreatePolicyVersionResult.PolicyVersion;
export const listPolicyVersions = async (PolicyArn) => asList((await call("ListPolicyVersions", { PolicyArn })).ListPolicyVersionsResponse.ListPolicyVersionsResult.Versions?.member);
export const getPolicyVersion = async (PolicyArn, VersionId) => (await call("GetPolicyVersion", { PolicyArn, VersionId })).GetPolicyVersionResponse.GetPolicyVersionResult.PolicyVersion;
export const setDefaultPolicyVersion = (PolicyArn, VersionId) => call("SetDefaultPolicyVersion", { PolicyArn, VersionId });
export const deletePolicyVersion = (PolicyArn, VersionId) => call("DeletePolicyVersion", { PolicyArn, VersionId });
export const listEntitiesForPolicy = async (PolicyArn) => {
  const r = (await call("ListEntitiesForPolicy", { PolicyArn })).ListEntitiesForPolicyResponse.ListEntitiesForPolicyResult;
  return {
    users: asList(r.PolicyUsers?.member), groups: asList(r.PolicyGroups?.member), roles: asList(r.PolicyRoles?.member),
    boundaryUsers: asList(r.PolicyBoundaryUsers?.member), boundaryRoles: asList(r.PolicyBoundaryRoles?.member),
  };
};

// ── identity providers ───────────────────────────────────────────────────
export const createSamlProvider = async (Name, SAMLMetadataDocument) => (await call("CreateSAMLProvider", { Name, SAMLMetadataDocument })).CreateSAMLProviderResponse.CreateSAMLProviderResult.SAMLProviderArn;
export const getSamlProvider = async (SAMLProviderArn) => (await call("GetSAMLProvider", { SAMLProviderArn })).GetSAMLProviderResponse.GetSAMLProviderResult;
export const listSamlProviders = async () => asList((await call("ListSAMLProviders", {})).ListSAMLProvidersResponse.ListSAMLProvidersResult.SAMLProviderList?.member);
export const deleteSamlProvider = (SAMLProviderArn) => call("DeleteSAMLProvider", { SAMLProviderArn });
export const createOidcProvider = async (Url, ClientIDList = []) =>
  (await call("CreateOpenIDConnectProvider", { Url, ...members("ClientIDList", ClientIDList) })).CreateOpenIDConnectProviderResponse.CreateOpenIDConnectProviderResult.OpenIDConnectProviderArn;
export const getOidcProvider = async (OpenIDConnectProviderArn) => (await call("GetOpenIDConnectProvider", { OpenIDConnectProviderArn })).GetOpenIDConnectProviderResponse.GetOpenIDConnectProviderResult;
export const listOidcProviders = async () => asList((await call("ListOpenIDConnectProviders", {})).ListOpenIDConnectProvidersResponse.ListOpenIDConnectProvidersResult.OpenIDConnectProviderList?.member);
export const deleteOidcProvider = (OpenIDConnectProviderArn) => call("DeleteOpenIDConnectProvider", { OpenIDConnectProviderArn });

// ── account settings ─────────────────────────────────────────────────────
export const getAccountPasswordPolicy = async () => {
  try { return (await call("GetAccountPasswordPolicy", {})).GetAccountPasswordPolicyResponse.GetAccountPasswordPolicyResult.PasswordPolicy; }
  catch (e) { if (e.code === "NoSuchEntity") return null; throw e; }
};
export const updateAccountPasswordPolicy = (params) => call("UpdateAccountPasswordPolicy", params);
export const deleteAccountPasswordPolicy = () => call("DeleteAccountPasswordPolicy", {});
export const listAccountAliases = async () => asList((await call("ListAccountAliases", {})).ListAccountAliasesResponse.ListAccountAliasesResult.AccountAliases?.member);
export const createAccountAlias = (AccountAlias) => call("CreateAccountAlias", { AccountAlias });
export const deleteAccountAlias = (AccountAlias) => call("DeleteAccountAlias", { AccountAlias });

// ── credential report ────────────────────────────────────────────────────
export const generateCredentialReport = () => call("GenerateCredentialReport", {});
export const getCredentialReport = async () => (await call("GetCredentialReport", {})).GetCredentialReportResponse.GetCredentialReportResult;

// ── policy simulator ─────────────────────────────────────────────────────
// contextEntries: [{key: "aws:MultiFactorAuthPresent", value: "true"}, …] — the real
// AWS ContextEntries mechanism for supplying condition keys the simulator can't read
// off a live request (see core/iam_core.py's SimulatePrincipalPolicy).
const contextEntriesParams = (entries = []) => {
  const out = {};
  entries.forEach((e, i) => {
    out[`ContextEntries.member.${i + 1}.ContextKeyName`] = e.key;
    out[`ContextEntries.member.${i + 1}.ContextKeyValues.member.1`] = e.value;
  });
  return out;
};
export const simulatePrincipalPolicy = async (PolicySourceArn, actionNames = [], resourceArns = [], contextEntries = []) => {
  const r = (await call("SimulatePrincipalPolicy", {
    PolicySourceArn, ...members("ActionNames", actionNames), ...members("ResourceArns", resourceArns),
    ...contextEntriesParams(contextEntries),
  })).SimulatePrincipalPolicyResponse.SimulatePrincipalPolicyResult;
  return asList(r.EvaluationResults?.member);
};

// ── Organizations policies (SCP/RCP) — Vyomi-only, see core/iam_core.py ──
export const createOrgPolicy = async (params) => (await call("CreateOrgPolicy", params)).CreateOrgPolicyResponse.CreateOrgPolicyResult.Policy;
export const listOrgPolicies = async (Type) => asList((await call("ListOrgPolicies", Type ? { Type } : {})).ListOrgPoliciesResponse.ListOrgPoliciesResult.Policies?.Policy);
export const describeOrgPolicy = async (PolicyId) => (await call("DescribeOrgPolicy", { PolicyId })).DescribeOrgPolicyResponse.DescribeOrgPolicyResult.Policy;
export const deleteOrgPolicy = (PolicyId) => call("DeleteOrgPolicy", { PolicyId });

// ── Account access requests ("Temporary delegation requests") — Vyomi-only ──
export const requestAccountAccess = async (params) => (await call("RequestAccountAccess", params)).RequestAccountAccessResponse.RequestAccountAccessResult.AccountAccessRequest;
export const listAccountAccessRequests = async () => asList((await call("ListAccountAccessRequests", {})).ListAccountAccessRequestsResponse.ListAccountAccessRequestsResult.AccountAccessRequests?.AccountAccessRequest);
