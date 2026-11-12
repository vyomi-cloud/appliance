/* Microsoft Entra ID's own left nav (the service IS the nav tree, like Cost Management —
 * see ../cost/CostShell.jsx). Every panel renders its own exact title row ("Default
 * Directory | <panel>", or the bare title the real console uses for a few blades), since
 * the real portal re-titles the title row per panel rather than keeping one fixed header. */
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Glyph } from "../../kit/common.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "previewfeatures", label: "Preview features" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Manage", items: [
    { id: "users", label: "Users" },
    { id: "groups", label: "Groups" },
    { id: "externalidentities", label: "External Identities" },
    { id: "roles", label: "Roles and administrators" },
    { id: "adminunits", label: "Administrative units" },
    { id: "delegatedadminpartners", label: "Delegated admin partners" },
    { id: "agents", label: "Agents" },
    { id: "enterpriseapps", label: "Enterprise applications" },
    { id: "devices", label: "Devices" },
    { id: "appregistrations", label: "App registrations" },
    { id: "identitygovernance", label: "Identity Governance" },
    { id: "appproxy", label: "Application proxy" },
    { id: "customsecurityattributes", label: "Custom security attributes" },
    { id: "licenses", label: "Licenses" },
    { id: "crosstenantsync", label: "Cross-tenant synchronization" },
    { id: "entraconnect", label: "Microsoft Entra Connect" },
    { id: "customdomains", label: "Custom domain names" },
    { id: "mobility", label: "Mobility (MDM and WIP)" },
    { id: "passwordreset", label: "Password reset" },
    { id: "companybranding", label: "Company branding" },
    { id: "usersettings", label: "User settings" },
    { id: "properties", label: "Properties" },
    { id: "security", label: "Security" },
  ] },
  { group: "Monitoring", items: [
    { id: "signinlogs", label: "Sign-in logs" },
    { id: "auditlogs", label: "Audit logs" },
    { id: "provisioninglogs", label: "Provisioning logs" },
    { id: "health", label: "Health" },
    { id: "loganalytics", label: "Log Analytics" },
    { id: "diagnosticsettings", label: "Diagnostic settings" },
    { id: "workbooks", label: "Workbooks" },
    { id: "usageinsights", label: "Usage & insights" },
    { id: "bulkresults", label: "Bulk operation results (Preview)" },
  ] },
  { group: "Help", items: [
    { id: "support", label: "Support + Troubleshooting" },
  ] },
];

export default function EntraShell({ active, title, children }) {
  return (
    <ResourceBlade title={title} glyph={<Glyph id="entra" />} closeHref="#/" menu={MENU} active={active} hrefFor={(id) => `#/entra/${id}`}>
      {children}
    </ResourceBlade>
  );
}
