/* IAM over the native Query protocol (form POST, XML response). See core/iam_core.py
 * for the exact action set and XML shapes; awsQuery() in common/wire.js parses the XML
 * response into a plain JS object keyed by `${Action}Response`. */
import { asList, awsJson, awsQuery } from "../../../common/wire.js";

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
export const createVirtualMfaDevice = async (VirtualMFADeviceName) => {
  const d = (await call("CreateVirtualMFADevice", { VirtualMFADeviceName })).CreateVirtualMFADeviceResponse.CreateVirtualMFADeviceResult.VirtualMFADevice;
  // The seed is a base64 blob on the wire (BootstrapDatum); show the base32 secret an authenticator app takes.
  return { ...d, Base32StringSeed: atob(d.Base32StringSeed || "") };
};
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
export const simulatePrincipalPolicy = async (PolicySourceArn, actionNames = [], resourceArns = [], contextEntries = [], resourcePolicy = "") => {
  const r = (await call("SimulatePrincipalPolicy", {
    PolicySourceArn, ...members("ActionNames", actionNames), ...members("ResourceArns", resourceArns),
    ...contextEntriesParams(contextEntries), ...(resourcePolicy ? { ResourcePolicy: resourcePolicy } : {}),
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

// ── Last accessed (real IAM API) + policy-from-activity (Vyomi-only) — see
// core/iam_core.py's record_activity / GetServiceLastAccessedDetails / GeneratePolicyFromActivity ──
export const generateServiceLastAccessedDetails = async (Arn) =>
  (await call("GenerateServiceLastAccessedDetails", { Arn })).GenerateServiceLastAccessedDetailsResponse.GenerateServiceLastAccessedDetailsResult.JobId;
export const getServiceLastAccessedDetailsForJob = async (JobId) =>
  (await call("GetServiceLastAccessedDetails", { JobId })).GetServiceLastAccessedDetailsResponse.GetServiceLastAccessedDetailsResult;
export const getServiceLastAccessedDetails = async (Arn) => {
  const jobId = await generateServiceLastAccessedDetails(Arn);
  const r = await getServiceLastAccessedDetailsForJob(jobId);
  return asList(r.ServicesLastAccessed?.member);
};
export const generatePolicyFromActivity = async (Arn) =>
  (await call("GeneratePolicyFromActivity", { Arn })).GeneratePolicyFromActivityResponse.GeneratePolicyFromActivityResult.GeneratedPolicyDocument;

// ── Access Analyzer (Vyomi-only) — see core/iam_core.py ─────────────────
export const createAnalyzer = async (params) => (await call("CreateAnalyzer", params)).CreateAnalyzerResponse.CreateAnalyzerResult.AnalyzerSummary;
export const listAnalyzers = async () => asList((await call("ListAnalyzers", {})).ListAnalyzersResponse.ListAnalyzersResult.Analyzers?.AnalyzerSummary);
export const getAnalyzer = async (AnalyzerName) => (await call("GetAnalyzer", { AnalyzerName })).GetAnalyzerResponse.GetAnalyzerResult.AnalyzerSummary;
export const updateAnalyzer = (AnalyzerName, UnusedAccessAge) => call("UpdateAnalyzer", { AnalyzerName, UnusedAccessAge });
export const deleteAnalyzer = (AnalyzerName) => call("DeleteAnalyzer", { AnalyzerName });
export const listFindings = async (AnalyzerName, Status) => asList((await call("ListFindings", Status ? { AnalyzerName, Status } : { AnalyzerName })).ListFindingsResponse.ListFindingsResult.Findings?.member);
export const updateFindingStatus = (AnalyzerName, Id, Status) => call("UpdateFindingStatus", { AnalyzerName, Id, Status });

// ── IAM Roles Anywhere (Vyomi-only) — see core/iam_core.py ──────────────
export const createTrustAnchor = async (Name, SourceData) => (await call("CreateTrustAnchor", { Name, SourceData })).CreateTrustAnchorResponse.CreateTrustAnchorResult.TrustAnchorDetail;
export const listTrustAnchors = async () => asList((await call("ListTrustAnchors", {})).ListTrustAnchorsResponse.ListTrustAnchorsResult.TrustAnchors?.TrustAnchorDetail);
export const deleteTrustAnchor = (TrustAnchorArn) => call("DeleteTrustAnchor", { TrustAnchorArn });
export const createProfile = async (Name, RoleArns = []) => (await call("CreateProfile", { Name, ...members("RoleArns", RoleArns) })).CreateProfileResponse.CreateProfileResult.ProfileDetail;
export const listProfiles = async () => asList((await call("ListProfiles", {})).ListProfilesResponse.ListProfilesResult.Profiles?.ProfileDetail);
export const deleteProfile = (ProfileArn) => call("DeleteProfile", { ProfileArn });

// ── credentials lifecycle + account-level (sweep IAM-1) — see core/iam_core.py ──
export const getAccessKeyLastUsed = async (AccessKeyId) => (await call("GetAccessKeyLastUsed", { AccessKeyId })).GetAccessKeyLastUsedResponse.GetAccessKeyLastUsedResult.AccessKeyLastUsed;
export const getAccountSummary = async () => {
  const r = (await call("GetAccountSummary", {})).GetAccountSummaryResponse.GetAccountSummaryResult.SummaryMap;
  const out = {};
  asList(r?.entry).forEach((e) => { out[e.key] = Number(e.value); });
  return out;
};
export const getSecurityRecommendations = async () => {
  const r = (await call("GetSecurityRecommendations", {})).GetSecurityRecommendationsResponse.GetSecurityRecommendationsResult.Recommendations;
  return asList(r?.member).map((m) => ({ ...m, Resources: asList(m.Resources?.member) }));
};
export const listIamEvents = async (MaxItems = 100) => asList((await call("ListIamEvents", { MaxItems })).ListIamEventsResponse.ListIamEventsResult.Events?.member);
export const changePassword = (OldPassword, NewPassword) => call("ChangePassword", { OldPassword, NewPassword });
export const setStsPreferences = (GlobalEndpointTokenVersion) => call("SetSecurityTokenServicePreferences", { GlobalEndpointTokenVersion });

export const listSshPublicKeys = async (UserName) => asList((await call("ListSSHPublicKeys", { UserName })).ListSSHPublicKeysResponse.ListSSHPublicKeysResult.SSHPublicKeys?.member);
export const uploadSshPublicKey = async (UserName, SSHPublicKeyBody) => (await call("UploadSSHPublicKey", { UserName, SSHPublicKeyBody })).UploadSSHPublicKeyResponse.UploadSSHPublicKeyResult.SSHPublicKey;
export const getSshPublicKey = async (UserName, SSHPublicKeyId) => (await call("GetSSHPublicKey", { UserName, SSHPublicKeyId, Encoding: "SSH" })).GetSSHPublicKeyResponse.GetSSHPublicKeyResult.SSHPublicKey;
export const updateSshPublicKey = (UserName, SSHPublicKeyId, Status) => call("UpdateSSHPublicKey", { UserName, SSHPublicKeyId, Status });
export const deleteSshPublicKey = (UserName, SSHPublicKeyId) => call("DeleteSSHPublicKey", { UserName, SSHPublicKeyId });

export const listServiceCredentials = async (UserName) => asList((await call("ListServiceSpecificCredentials", { UserName })).ListServiceSpecificCredentialsResponse.ListServiceSpecificCredentialsResult.ServiceSpecificCredentials?.member);
export const createServiceCredential = async (UserName, ServiceName) => (await call("CreateServiceSpecificCredential", { UserName, ServiceName })).CreateServiceSpecificCredentialResponse.CreateServiceSpecificCredentialResult.ServiceSpecificCredential;
export const resetServiceCredential = async (UserName, ServiceSpecificCredentialId) => (await call("ResetServiceSpecificCredential", { UserName, ServiceSpecificCredentialId })).ResetServiceSpecificCredentialResponse.ResetServiceSpecificCredentialResult.ServiceSpecificCredential;
export const updateServiceCredential = (UserName, ServiceSpecificCredentialId, Status) => call("UpdateServiceSpecificCredential", { UserName, ServiceSpecificCredentialId, Status });
export const deleteServiceCredential = (UserName, ServiceSpecificCredentialId) => call("DeleteServiceSpecificCredential", { UserName, ServiceSpecificCredentialId });

export const listSigningCertificates = async (UserName) => asList((await call("ListSigningCertificates", { UserName })).ListSigningCertificatesResponse.ListSigningCertificatesResult.Certificates?.member);
export const uploadSigningCertificate = async (UserName, CertificateBody) => (await call("UploadSigningCertificate", { UserName, CertificateBody })).UploadSigningCertificateResponse.UploadSigningCertificateResult.Certificate;
export const updateSigningCertificate = (UserName, CertificateId, Status) => call("UpdateSigningCertificate", { UserName, CertificateId, Status });
export const deleteSigningCertificate = (UserName, CertificateId) => call("DeleteSigningCertificate", { UserName, CertificateId });

/** What the real console's "Delete user" does: remove the user's credentials first (the IAM API refuses
 *  DeleteUser while access keys, MFA devices, certificates or service credentials remain), then the user. */
export async function deleteUserWithCredentials(UserName) {
  const quiet = (p) => p.catch(() => {});
  for (const k of await listAccessKeys(UserName)) await deleteAccessKey(UserName, k.AccessKeyId);
  for (const k of await listSshPublicKeys(UserName)) await deleteSshPublicKey(UserName, k.SSHPublicKeyId);
  for (const c of await listSigningCertificates(UserName)) await deleteSigningCertificate(UserName, c.CertificateId);
  for (const c of await listServiceCredentials(UserName)) await deleteServiceCredential(UserName, c.ServiceSpecificCredentialId);
  for (const d of await listMfaDevices(UserName)) { await deactivateMfaDevice(UserName, d.SerialNumber); await deleteVirtualMfaDevice(d.SerialNumber); }
  await quiet(deleteLoginProfile(UserName));
  await deleteUser(UserName);
}


// ── AWS Organizations (native JSON 1.1 wire, core/organizations_core.py) ─────────────
const org = (op, payload = {}) => awsJson("organizations", `AWSOrganizationsV20161128.${op}`, payload, { version: "1.1" });
export const describeOrganization = async () => {
  try { return (await org("DescribeOrganization")).Organization; }
  catch (e) { if (e.code === "AWSOrganizationsNotInUseException") return null; throw e; }
};
export const createOrganization = async (FeatureSet = "ALL") => (await org("CreateOrganization", { FeatureSet })).Organization;
export const deleteOrganization = () => org("DeleteOrganization");
export const listRoots = async () => (await org("ListRoots")).Roots;
export const enablePolicyType = (RootId, PolicyType) => org("EnablePolicyType", { RootId, PolicyType });
export const listOUsForParent = async (ParentId) => (await org("ListOrganizationalUnitsForParent", { ParentId })).OrganizationalUnits;
export const createOU = async (ParentId, Name) => (await org("CreateOrganizationalUnit", { ParentId, Name })).OrganizationalUnit;
export const renameOU = (OrganizationalUnitId, Name) => org("UpdateOrganizationalUnit", { OrganizationalUnitId, Name });
export const deleteOU = (OrganizationalUnitId) => org("DeleteOrganizationalUnit", { OrganizationalUnitId });
export const listAccounts = async () => (await org("ListAccounts")).Accounts;
export const createAccount = async (Email, AccountName) => (await org("CreateAccount", { Email, AccountName })).CreateAccountStatus;
export const inviteAccount = async (Id, Type = "ACCOUNT") => (await org("InviteAccountToOrganization", { Target: { Id, Type } })).Handshake;
export const listHandshakes = async () => (await org("ListHandshakesForOrganization")).Handshakes;
export const acceptHandshake = (HandshakeId) => org("AcceptHandshake", { HandshakeId });
export const cancelHandshake = (HandshakeId) => org("CancelHandshake", { HandshakeId });
export const moveAccount = (AccountId, SourceParentId, DestinationParentId) => org("MoveAccount", { AccountId, SourceParentId, DestinationParentId });
export const removeAccount = (AccountId) => org("RemoveAccountFromOrganization", { AccountId });
export const closeAccount = (AccountId) => org("CloseAccount", { AccountId });
export const listParents = async (ChildId) => (await org("ListParents", { ChildId })).Parents;
export const orgListPolicies = async (Filter) => (await org("ListPolicies", { Filter })).Policies;
export const orgDescribePolicy = async (PolicyId) => (await org("DescribePolicy", { PolicyId })).Policy;
export const orgCreatePolicy = async (Name, Description, Type, Content) => (await org("CreatePolicy", { Name, Description, Type, Content })).Policy;
export const orgUpdatePolicy = (PolicyId, params) => org("UpdatePolicy", { PolicyId, ...params });
export const orgDeletePolicy = (PolicyId) => org("DeletePolicy", { PolicyId });
export const orgAttachPolicy = (PolicyId, TargetId) => org("AttachPolicy", { PolicyId, TargetId });
export const orgDetachPolicy = (PolicyId, TargetId) => org("DetachPolicy", { PolicyId, TargetId });
export const listTargetsForPolicy = async (PolicyId) => (await org("ListTargetsForPolicy", { PolicyId })).Targets;
export const enableServiceAccess = (ServicePrincipal) => org("EnableAWSServiceAccess", { ServicePrincipal });
export const disableServiceAccess = (ServicePrincipal) => org("DisableAWSServiceAccess", { ServicePrincipal });
export const listServiceAccess = async () => (await org("ListAWSServiceAccessForOrganization")).EnabledServicePrincipals;
export const registerDelegatedAdmin = (AccountId, ServicePrincipal) => org("RegisterDelegatedAdministrator", { AccountId, ServicePrincipal });
export const deregisterDelegatedAdmin = (AccountId, ServicePrincipal) => org("DeregisterDelegatedAdministrator", { AccountId, ServicePrincipal });
export const listDelegatedAdmins = async (ServicePrincipal) => (await org("ListDelegatedAdministrators", ServicePrincipal ? { ServicePrincipal } : {})).DelegatedAdministrators;

// ── centralized root access (real IAM API on the organization) ───────────────────────
export const listOrganizationsFeatures = async () => {
  try { return asList((await call("ListOrganizationsFeatures", {})).ListOrganizationsFeaturesResponse.ListOrganizationsFeaturesResult.EnabledFeatures?.member); }
  catch (e) { if (e.code === "OrganizationNotFoundException") return []; throw e; }
};
export const setOrganizationsFeature = (feature, on) => call(`${on ? "Enable" : "Disable"}Organizations${feature}`, {});

// ── server certificates (IAM certificate store) ──────────────────────────────────────
export const listServerCertificates = async () => asList((await call("ListServerCertificates", {})).ListServerCertificatesResponse.ListServerCertificatesResult.ServerCertificateMetadataList?.member);
export const uploadServerCertificate = (ServerCertificateName, CertificateBody, PrivateKey, CertificateChain) =>
  call("UploadServerCertificate", { ServerCertificateName, CertificateBody, PrivateKey, ...(CertificateChain ? { CertificateChain } : {}) });
export const renameServerCertificate = (ServerCertificateName, NewServerCertificateName) => call("UpdateServerCertificate", { ServerCertificateName, NewServerCertificateName });
export const deleteServerCertificate = (ServerCertificateName) => call("DeleteServerCertificate", { ServerCertificateName });
export const getServerCertificate = async (ServerCertificateName) => (await call("GetServerCertificate", { ServerCertificateName })).GetServerCertificateResponse.GetServerCertificateResult.ServerCertificate;

// ── identity-provider detail (OIDC client IDs / thumbprints, SAML metadata, tags) ────
export const addOidcClientId = (OpenIDConnectProviderArn, ClientID) => call("AddClientIDToOpenIDConnectProvider", { OpenIDConnectProviderArn, ClientID });
export const removeOidcClientId = (OpenIDConnectProviderArn, ClientID) => call("RemoveClientIDFromOpenIDConnectProvider", { OpenIDConnectProviderArn, ClientID });
export const updateOidcThumbprints = (OpenIDConnectProviderArn, list) => call("UpdateOpenIDConnectProviderThumbprint", { OpenIDConnectProviderArn, ...members("ThumbprintList", list) });
export const updateSamlProvider = (SAMLProviderArn, SAMLMetadataDocument) => call("UpdateSAMLProvider", { SAMLProviderArn, SAMLMetadataDocument });
export const tagProvider = (kind, Arn, tags) => call(`Tag${kind}Provider`, { [kind === "SAML" ? "SAMLProviderArn" : "OpenIDConnectProviderArn"]: Arn, ...tagsParams(tags) });
export const untagProvider = (kind, Arn, keys) => call(`Untag${kind}Provider`, { [kind === "SAML" ? "SAMLProviderArn" : "OpenIDConnectProviderArn"]: Arn, ...members("TagKeys", keys) });
export const listProviderTags = async (kind, Arn) => tagsFromXml((await call(`List${kind}ProviderTags`, { [kind === "SAML" ? "SAMLProviderArn" : "OpenIDConnectProviderArn"]: Arn }))[`List${kind}ProviderTagsResponse`][`List${kind}ProviderTagsResult`].Tags);
export const getAccountAuthorizationDetails = async () => (await call("GetAccountAuthorizationDetails", {})).GetAccountAuthorizationDetailsResponse.GetAccountAuthorizationDetailsResult;
