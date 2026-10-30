import { Overview, GroupsOverview, ExternalIdentities, DevicesOverview } from "./Dashboards.jsx";
import StaticPage from "./StaticPages.jsx";
import Users from "./Users.jsx";
import CreateUser from "./CreateUser.jsx";
import UserBlade from "./UserBlade.jsx";
import Groups from "./Groups.jsx";
import NewGroup from "./NewGroup.jsx";
import AppRegistrations from "./AppRegistrations.jsx";
import RegisterApplication from "./RegisterApplication.jsx";
import AppBlade from "./AppBlade.jsx";
import EnterpriseApps from "./EnterpriseApps.jsx";
import Roles from "./Roles.jsx";
import AdminUnits from "./AdminUnits.jsx";
import CustomDomains from "./CustomDomains.jsx";
import UserSettings from "./UserSettings.jsx";
import Properties from "./Properties.jsx";
import SignInLogs from "./SignInLogs.jsx";
import AuditLogs from "./AuditLogs.jsx";

const STATIC_IDS = [
  "previewfeatures", "diagnose", "delegatedadminpartners", "agents", "identitygovernance", "appproxy",
  "customsecurityattributes", "licenses", "crosstenantsync", "entraconnect", "mobility", "passwordreset",
  "companybranding", "security", "provisioninglogs", "health", "loganalytics", "diagnosticsettings",
  "workbooks", "usageinsights", "bulkresults", "support",
];

const staticRoute = (id) => ({ pattern: `/entra/${id}`, component: () => <StaticPage id={id} />, crumbs: () => [{ text: id, href: `#/entra/${id}` }] });

const appCrumb = (p) => [{ text: p.id, href: `#/entra/appregistrations/${p.id}` }];
const userCrumb = (p) => [{ text: p.id, href: `#/entra/users/${p.id}` }];

export default {
  routes: [
    { pattern: "/entra", component: Overview },
    { pattern: "/entra/overview", component: Overview },
    ...STATIC_IDS.map(staticRoute),

    { pattern: "/entra/users", component: Users },
    { pattern: "/entra/users/create", component: CreateUser, crumbs: () => [{ text: "Create new user", href: "#/entra/users/create" }] },
    { pattern: "/entra/users/:id", component: UserBlade, crumbs: userCrumb },
    { pattern: "/entra/users/:id/:panel", component: UserBlade, crumbs: userCrumb },

    { pattern: "/entra/groups", component: GroupsOverview },
    { pattern: "/entra/groups/all", component: Groups },
    { pattern: "/entra/groups/new", component: NewGroup, crumbs: () => [{ text: "New Group", href: "#/entra/groups/new" }] },

    { pattern: "/entra/externalidentities", component: ExternalIdentities },
    { pattern: "/entra/roles", component: Roles },
    { pattern: "/entra/adminunits", component: AdminUnits },
    { pattern: "/entra/enterpriseapps", component: EnterpriseApps },
    { pattern: "/entra/devices", component: DevicesOverview },

    { pattern: "/entra/appregistrations", component: AppRegistrations },
    { pattern: "/entra/appregistrations/register", component: RegisterApplication, crumbs: () => [{ text: "Register an application", href: "#/entra/appregistrations/register" }] },
    { pattern: "/entra/appregistrations/:id", component: AppBlade, crumbs: appCrumb },
    { pattern: "/entra/appregistrations/:id/:panel", component: AppBlade, crumbs: appCrumb },

    { pattern: "/entra/customdomains", component: CustomDomains },
    { pattern: "/entra/usersettings", component: UserSettings },
    { pattern: "/entra/properties", component: Properties },
    { pattern: "/entra/signinlogs", component: SignInLogs },
    { pattern: "/entra/auditlogs", component: AuditLogs },
  ],
};
