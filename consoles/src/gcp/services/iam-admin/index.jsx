import IamIcon from "@mui/icons-material/esm/AdminPanelSettingsOutlined.js";
import AccountCircleIcon from "@mui/icons-material/esm/AccountCircleOutlined.js";
import GroupIcon from "@mui/icons-material/esm/GroupOutlined.js";
import SecurityIcon from "@mui/icons-material/esm/SecurityOutlined.js";
import BadgeIcon from "@mui/icons-material/esm/BadgeOutlined.js";
import HubIcon from "@mui/icons-material/esm/HubOutlined.js";
import GroupWorkIcon from "@mui/icons-material/esm/GroupWorkOutlined.js";
import ShieldIcon from "@mui/icons-material/esm/ShieldOutlined.js";
import DeviceHubIcon from "@mui/icons-material/esm/DeviceHubOutlined.js";
import PolicyIcon from "@mui/icons-material/esm/PolicyOutlined.js";
import InventoryIcon from "@mui/icons-material/esm/InventoryOutlined.js";
import SettingsIcon from "@mui/icons-material/esm/SettingsOutlined.js";
import LabelIcon from "@mui/icons-material/esm/LabelOutlined.js";
import SellIcon from "@mui/icons-material/esm/SellOutlined.js";
import InsightsIcon from "@mui/icons-material/esm/InsightsOutlined.js";
import TroubleshootIcon from "@mui/icons-material/esm/TroubleshootOutlined.js";
import QueryStatsIcon from "@mui/icons-material/esm/QueryStatsOutlined.js";
import SpeedIcon from "@mui/icons-material/esm/SpeedOutlined.js";
import ArticleIcon from "@mui/icons-material/esm/ArticleOutlined.js";
import DomainIcon from "@mui/icons-material/esm/DomainOutlined.js";
import ContactsIcon from "@mui/icons-material/esm/ContactsOutlined.js";
import PrivacyTipIcon from "@mui/icons-material/esm/PrivacyTipOutlined.js";
import VpnLockIcon from "@mui/icons-material/esm/VpnLockOutlined.js";

import Iam from "./Iam.jsx";
import ServiceAccounts from "./ServiceAccounts.jsx";
import CreateServiceAccount from "./CreateServiceAccount.jsx";
import ServiceAccountDetail from "./ServiceAccountDetail.jsx";
import Roles from "./Roles.jsx";
import CreateRole from "./CreateRole.jsx";
import RoleDetail from "./RoleDetail.jsx";
import Settings from "./Settings.jsx";
import Labels from "./Labels.jsx";
import Tags from "./Tags.jsx";
import AuditLogs from "./AuditLogs.jsx";
import OrgPolicies from "./OrgPolicies.jsx";
import Pam from "./Pam.jsx";
import EssentialContacts from "./EssentialContacts.jsx";
import PolicyTroubleshooter from "./PolicyTroubleshooter.jsx";
import PolicyAnalyzer from "./PolicyAnalyzer.jsx";
import WorkloadIdentity from "./WorkloadIdentity.jsx";
import {
  AssetInventory, Groups, IdentityAwareProxy, IdentityOrganization, ManagedWorkloadIdentities,
  PrincipalAccessBoundary, PrivacySecurity, QuotasSystemLimits, SecurityInsights, WorkforceIdentityFederation,
} from "./InfoPages.jsx";

const IamAllow = () => <Iam tab="allow" />;
const IamDeny = () => <Iam tab="deny" />;
const IamLog = () => <Iam tab="recommendations" />;
const IamGrant = () => <Iam tab="allow" openGrant />;

export default {
  nav: [
    {
      section: "Identity & Access",
      items: [
        { text: "IAM", href: "#/iam-admin/iam", icon: IamIcon, match: ["#/iam-admin/iam"] },
        { text: "Service Accounts", href: "#/iam-admin/serviceaccounts", icon: AccountCircleIcon, match: ["#/iam-admin/serviceaccounts"] },
        { text: "Groups", href: "#/iam-admin/groups", icon: GroupIcon },
        { text: "Privileged Access Manager", href: "#/iam-admin/pam", icon: SecurityIcon },
        { text: "Roles", href: "#/iam-admin/roles", icon: BadgeIcon, match: ["#/iam-admin/roles"] },
        { text: "Workload Identity Federation", href: "#/iam-admin/workload-identity-pools", icon: HubIcon },
        { text: "Workforce Identity Federation", href: "#/iam-admin/workforce-identity-pools", icon: GroupWorkIcon },
        { text: "Principal Access Boundary", href: "#/iam-admin/principal-access-boundary", icon: ShieldIcon },
        { text: "Managed Workload Identities", href: "#/iam-admin/managed-workload-identity-pools", icon: DeviceHubIcon },
      ],
    },
    {
      section: "Resource Management",
      items: [
        { text: "Organization Policies", href: "#/iam-admin/orgpolicies", icon: PolicyIcon },
        { text: "Asset Inventory", href: "#/iam-admin/asset-inventory", icon: InventoryIcon },
        { text: "Settings", href: "#/iam-admin/settings", icon: SettingsIcon },
        { text: "Labels", href: "#/iam-admin/labels", icon: LabelIcon },
        { text: "Tags", href: "#/iam-admin/tags", icon: SellIcon },
      ],
    },
    {
      section: "Diagnostic Tools",
      items: [
        { text: "Security Insights", href: "#/iam-admin/security-insights", icon: InsightsIcon },
        { text: "Policy Analyzer", href: "#/iam-admin/analyzer", icon: QueryStatsIcon },
        { text: "Policy Troubleshooter", href: "#/iam-admin/troubleshooter", icon: TroubleshootIcon },
      ],
    },
    {
      section: "Cloud Administration",
      items: [
        { text: "Quotas & System Limits", href: "#/iam-admin/quotas", icon: SpeedIcon },
        { text: "Audit logs", href: "#/iam-admin/audit", icon: ArticleIcon },
      ],
    },
    { text: "Identity & Organization", href: "#/iam-admin/cloudidentity/consumer", icon: DomainIcon },
    { text: "Essential Contacts", href: "#/iam-admin/essential-contacts", icon: ContactsIcon },
    { text: "Privacy & Security", href: "#/iam-admin/privacy", icon: PrivacyTipIcon },
    { text: "Identity-Aware Proxy", href: "#/iam-admin/iap", icon: VpnLockIcon },
  ],
  routes: [
    { pattern: "/iam-admin/iam", component: IamAllow },
    { pattern: "/iam-admin/iam/grant-access", component: IamGrant },
    { pattern: "/iam-admin/iam/deny", component: IamDeny },
    { pattern: "/iam-admin/iam/log", component: IamLog },
    { pattern: "/iam-admin/serviceaccounts", component: ServiceAccounts },
    { pattern: "/iam-admin/serviceaccounts/create", component: CreateServiceAccount },
    { pattern: "/iam-admin/serviceaccounts/details/:resource-name", component: ServiceAccountDetail },
    { pattern: "/iam-admin/roles", component: Roles },
    { pattern: "/iam-admin/roles/create", component: CreateRole },
    { pattern: "/iam-admin/roles/details/:resource-name", component: RoleDetail },
    { pattern: "/iam-admin/settings", component: Settings },
    { pattern: "/iam-admin/labels", component: Labels },
    { pattern: "/iam-admin/tags", component: Tags },
    { pattern: "/iam-admin/audit", component: AuditLogs },
    { pattern: "/iam-admin/orgpolicies", component: OrgPolicies },
    { pattern: "/iam-admin/pam", component: Pam },
    { pattern: "/iam-admin/essential-contacts", component: EssentialContacts },
    { pattern: "/iam-admin/troubleshooter", component: PolicyTroubleshooter },
    { pattern: "/iam-admin/analyzer", component: PolicyAnalyzer },
    { pattern: "/iam-admin/workload-identity-pools", component: WorkloadIdentity },
    { pattern: "/iam-admin/groups", component: Groups },
    { pattern: "/iam-admin/workforce-identity-pools", component: WorkforceIdentityFederation },
    { pattern: "/iam-admin/principal-access-boundary", component: PrincipalAccessBoundary },
    { pattern: "/iam-admin/managed-workload-identity-pools", component: ManagedWorkloadIdentities },
    { pattern: "/iam-admin/asset-inventory", component: AssetInventory },
    { pattern: "/iam-admin/security-insights", component: SecurityInsights },
    { pattern: "/iam-admin/quotas", component: QuotasSystemLimits },
    { pattern: "/iam-admin/cloudidentity/consumer", component: IdentityOrganization },
    { pattern: "/iam-admin/privacy", component: PrivacySecurity },
    { pattern: "/iam-admin/iap", component: IdentityAwareProxy },
  ],
};
