import Dashboard from "./Dashboard.jsx";
import Users from "./Users.jsx";
import UserDetail from "./UserDetail.jsx";
import CreateUser from "./CreateUser.jsx";
import CreateAccessKey from "./CreateAccessKey.jsx";
import Groups from "./Groups.jsx";
import GroupDetail from "./GroupDetail.jsx";
import CreateGroup from "./CreateGroup.jsx";
import Roles from "./Roles.jsx";
import RoleDetail from "./RoleDetail.jsx";
import CreateRole from "./CreateRole.jsx";
import Policies from "./Policies.jsx";
import PolicyDetail from "./PolicyDetail.jsx";
import CreatePolicy from "./CreatePolicy.jsx";
import IdentityProviders from "./IdentityProviders.jsx";
import AccountSettings from "./AccountSettings.jsx";
import EditPasswordPolicy from "./EditPasswordPolicy.jsx";
import SecurityCredentials from "./SecurityCredentials.jsx";
import PolicySimulator from "./PolicySimulator.jsx";
import CredentialReport from "./CredentialReport.jsx";
import TemporaryDelegationRequests from "./TemporaryDelegationRequests.jsx";
import ServiceControlPolicies from "./ServiceControlPolicies.jsx";
import ServiceControlPolicyDetail from "./ServiceControlPolicyDetail.jsx";
import ResourceControlPolicies from "./ResourceControlPolicies.jsx";
import {
  AssignDelegatedAdministrator, RootAccessManagement, OrganizationActivity, AccountAccessManager,
} from "./HonestPages.jsx";
import AccessAnalyzer from "./AccessAnalyzer.jsx";
import ResourceAnalysis from "./ResourceAnalysis.jsx";
import UnusedAccess from "./UnusedAccess.jsx";
import AnalyzerSettings from "./AnalyzerSettings.jsx";

const iamCrumb = { text: "IAM", href: "#/iam" };

export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/iam/dashboard" },
    { type: "section", text: "Access Management", items: [
      { type: "link", text: "Roles", href: "#/iam/roles" },
      { type: "link", text: "Policies", href: "#/iam/policies" },
      { type: "link", text: "IAM users", href: "#/iam/users" },
      { type: "link", text: "IAM user groups", href: "#/iam/groups" },
      { type: "link", text: "Identity providers", href: "#/iam/identity-providers" },
      { type: "link", text: "Account settings", href: "#/iam/account-settings" },
      { type: "link", text: "Root access management", href: "#/iam/root-access-management" },
      { type: "link", text: "Temporary delegation requests", href: "#/iam/temporary-delegation-requests" },
    ] },
    { type: "section", text: "Access reports", items: [
      { type: "link", text: "Access Analyzer", href: "#/iam/access-analyzer" },
      { type: "link", text: "Resource analysis", href: "#/iam/resource-analysis" },
      { type: "link", text: "Unused access", href: "#/iam/unused-access" },
      { type: "link", text: "Analyzer settings", href: "#/iam/analyzer-settings" },
      { type: "link", text: "Policy simulator", href: "#/iam/policy-simulator" },
      { type: "link", text: "Credential report", href: "#/iam/credential-report" },
    ] },
    { type: "section", text: "Multi-account access", items: [
      { type: "link", text: "Account access manager", href: "#/iam/account-access-manager" },
      { type: "link", text: "Organization activity", href: "#/iam/organization-activity" },
      { type: "link", text: "Service control policies", href: "#/iam/service-control-policies" },
      { type: "link", text: "Resource control policies", href: "#/iam/resource-control-policies" },
    ] },
  ],
  routes: [
    { pattern: "/iam", component: Dashboard, crumbs: () => [iamCrumb, { text: "Dashboard", href: "#/iam/dashboard" }] },
    { pattern: "/iam/dashboard", component: Dashboard, crumbs: () => [iamCrumb, { text: "Dashboard", href: "#/iam/dashboard" }] },

    { pattern: "/iam/users", component: Users, crumbs: () => [iamCrumb, { text: "IAM users", href: "#/iam/users" }] },
    { pattern: "/iam/create-user", component: CreateUser, crumbs: () => [iamCrumb, { text: "IAM users", href: "#/iam/users" }, { text: "Create user", href: "#/iam/create-user" }] },
    { pattern: "/iam/users/:name", component: UserDetail, crumbs: (p) => [iamCrumb, { text: "IAM users", href: "#/iam/users" }, { text: p.name, href: `#/iam/users/${p.name}` }] },
    { pattern: "/iam/users/:name/create-access-key", component: CreateAccessKey, crumbs: (p) => [iamCrumb, { text: "Users", href: "#/iam/users" }, { text: p.name, href: `#/iam/users/${p.name}` }, { text: "Create access key", href: `#/iam/users/${p.name}/create-access-key` }] },

    { pattern: "/iam/groups", component: Groups, crumbs: () => [iamCrumb, { text: "IAM user groups", href: "#/iam/groups" }] },
    { pattern: "/iam/create-user-group", component: CreateGroup, crumbs: () => [iamCrumb, { text: "IAM user groups", href: "#/iam/groups" }, { text: "Create user group", href: "#/iam/create-user-group" }] },
    { pattern: "/iam/groups/:name", component: GroupDetail, crumbs: (p) => [iamCrumb, { text: "IAM user groups", href: "#/iam/groups" }, { text: p.name, href: `#/iam/groups/${p.name}` }] },

    { pattern: "/iam/roles", component: Roles, crumbs: () => [iamCrumb, { text: "Roles", href: "#/iam/roles" }] },
    { pattern: "/iam/create-role", component: CreateRole, crumbs: () => [iamCrumb, { text: "Roles", href: "#/iam/roles" }, { text: "Create role", href: "#/iam/create-role" }] },
    { pattern: "/iam/roles/:name", component: RoleDetail, crumbs: (p) => [iamCrumb, { text: "Roles", href: "#/iam/roles" }, { text: p.name, href: `#/iam/roles/${p.name}` }] },

    { pattern: "/iam/policies", component: Policies, crumbs: () => [iamCrumb, { text: "Policies", href: "#/iam/policies" }] },
    { pattern: "/iam/create-policy", component: CreatePolicy, crumbs: () => [iamCrumb, { text: "Policies", href: "#/iam/policies" }, { text: "Create policy", href: "#/iam/create-policy" }] },
    { pattern: "/iam/policies/:name", component: PolicyDetail, crumbs: (p) => [iamCrumb, { text: "Policies", href: "#/iam/policies" }, { text: p.name, href: `#/iam/policies/${p.name}` }] },

    { pattern: "/iam/identity-providers", component: IdentityProviders, crumbs: () => [iamCrumb, { text: "Identity providers", href: "#/iam/identity-providers" }] },

    { pattern: "/iam/account-settings", component: AccountSettings, crumbs: () => [iamCrumb, { text: "Account settings", href: "#/iam/account-settings" }] },
    { pattern: "/iam/account-settings/edit-password-policy", component: EditPasswordPolicy, crumbs: () => [iamCrumb, { text: "Account Settings", href: "#/iam/account-settings" }, { text: "Edit password policy", href: "#/iam/account-settings/edit-password-policy" }] },
    { pattern: "/iam/account-settings/assign-delegated-administrator", component: AssignDelegatedAdministrator, crumbs: () => [iamCrumb, { text: "Account Settings", href: "#/iam/account-settings" }, { text: "Assign delegated administrator for centralized root access", href: "#/iam/account-settings/assign-delegated-administrator" }] },

    { pattern: "/iam/root-access-management", component: RootAccessManagement, crumbs: () => [iamCrumb, { text: "Root access management", href: "#/iam/root-access-management" }] },
    { pattern: "/iam/temporary-delegation-requests", component: TemporaryDelegationRequests, crumbs: () => [iamCrumb, { text: "Temporary delegation requests", href: "#/iam/temporary-delegation-requests" }] },

    { pattern: "/iam/policy-simulator", component: PolicySimulator, crumbs: () => [iamCrumb, { text: "Policy simulator", href: "#/iam/policy-simulator" }] },
    { pattern: "/iam/credential-report", component: CredentialReport, crumbs: () => [iamCrumb, { text: "Credential report", href: "#/iam/credential-report" }] },
    { pattern: "/iam/security-credentials", component: SecurityCredentials, crumbs: () => [iamCrumb, { text: "My security credentials", href: "#/iam/security-credentials" }] },

    { pattern: "/iam/organization-activity", component: OrganizationActivity, crumbs: () => [iamCrumb, { text: "Organization activity", href: "#/iam/organization-activity" }] },
    { pattern: "/iam/service-control-policies", component: ServiceControlPolicies, crumbs: () => [iamCrumb, { text: "AWS Organizations: Service control policies (SCPs)", href: "#/iam/service-control-policies" }] },
    { pattern: "/iam/service-control-policies/:name", component: ServiceControlPolicyDetail, crumbs: (p) => [iamCrumb, { text: "AWS Organizations: Service control policies (SCPs)", href: "#/iam/service-control-policies" }, { text: p.name, href: `#/iam/service-control-policies/${p.name}` }] },
    { pattern: "/iam/resource-control-policies", component: ResourceControlPolicies, crumbs: () => [iamCrumb, { text: "AWS Organizations: Resource control policies (RCPs)", href: "#/iam/resource-control-policies" }] },
    { pattern: "/iam/account-access-manager", component: AccountAccessManager, crumbs: () => [iamCrumb, { text: "Account access manager", href: "#/iam/account-access-manager" }] },

    { pattern: "/iam/access-analyzer", component: AccessAnalyzer, crumbs: () => [iamCrumb, { text: "Access Analyzer", href: "#/iam/access-analyzer" }] },
    { pattern: "/iam/resource-analysis", component: ResourceAnalysis, crumbs: () => [iamCrumb, { text: "Resource analysis", href: "#/iam/resource-analysis" }] },
    { pattern: "/iam/unused-access", component: UnusedAccess, crumbs: () => [iamCrumb, { text: "Unused access", href: "#/iam/unused-access" }] },
    { pattern: "/iam/analyzer-settings", component: AnalyzerSettings, crumbs: () => [iamCrumb, { text: "Analyzer settings", href: "#/iam/analyzer-settings" }] },
  ],
};
