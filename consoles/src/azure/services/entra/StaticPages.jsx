/* The Default Directory blade's many menu items the real console captures as a single
 * screen with no further structure (no table, no form — just the page title). Nothing to
 * fake here: each one is honestly built as its title, same pattern as
 * ../cost/StaticPages.jsx, grouped to avoid one tiny file per page. */
import EntraShell from "./EntraShell.jsx";

const NOTES = {
  previewfeatures: "Preview features let you opt in to pre-release Microsoft Entra ID capabilities. Vyomi ships every simulated feature at general availability, so there is nothing to opt into here.",
  diagnose: "Diagnostic playbooks for sign-in and provisioning problems. Vyomi has no sign-in flow to diagnose; see Audit logs for a real record of directory changes.",
  delegatedadminpartners: "Partners who manage this tenant under a Granular Delegated Admin Privileges (GDAP) relationship. Vyomi does not model multi-tenant partner delegation.",
  agents: "AI agent identities registered in this directory. Vyomi does not model agent identity blueprints.",
  identitygovernance: "Access reviews, entitlement management and Privileged Identity Management. Vyomi does not model time-bound or workflow-driven access governance.",
  licenses: "License SKUs (Microsoft Entra ID P1/P2, Microsoft 365, ...) and per-user assignment. Not modelled in Vyomi — every feature in this console is available regardless of license.",
  appproxy: "Application Proxy publishes on-premises web apps for remote access through a connector. Vyomi has no on-premises connector to simulate.",
  customsecurityattributes: "Custom security attributes let you define and assign tenant-specific attributes on users and apps. Not modelled in Vyomi.",
  crosstenantsync: "Cross-tenant synchronization automatically provisions users from other Microsoft Entra tenants. Not modelled in Vyomi.",
  entraconnect: "Microsoft Entra Connect synchronizes an on-premises Active Directory with this tenant. Vyomi has no on-premises directory to sync from.",
  mobility: "Mobile device management (Intune) and Windows Information Protection enrollment. Not modelled in Vyomi — see Devices.",
  passwordreset: "Self-service password reset policy for users in this directory. Not modelled in Vyomi.",
  companybranding: "Sign-in page branding (logos, background image, text). Not modelled in Vyomi.",
  security: "A security overview surfacing Conditional Access, Identity Protection and authentication methods. Each sub-capability is modelled individually where Vyomi supports it (see Roles and administrators, Audit logs).",
  provisioninglogs: "Provisioning logs record automatic user/group provisioning from connected apps. Vyomi has no provisioning connectors; see Audit logs for real directory changes.",
  health: "Microsoft Entra Connect Health monitors on-premises sync infrastructure. Vyomi has no on-premises sync agent to monitor.",
  loganalytics: "Streams directory logs into a Log Analytics workspace for KQL queries. Not modelled in Vyomi.",
  diagnosticsettings: "Routes Microsoft Entra logs to Log Analytics, Storage or Event Hubs. Not modelled in Vyomi.",
  workbooks: "Saved Azure Monitor workbook reports over directory telemetry. Not modelled in Vyomi.",
  usageinsights: "License and feature usage trends across the tenant. Not modelled in Vyomi.",
  bulkresults: "Results of bulk create/update/delete operations submitted as CSV. Vyomi's user and group actions are single-resource only.",
  support: "Open a support request with Microsoft. Vyomi is a simulator; there is no support ticketing to open.",
};

const TITLES = {
  previewfeatures: "Default Directory | Preview features",
  diagnose: "Default Directory | Diagnose and solve problems",
  delegatedadminpartners: "Default Directory | Delegated admin partners",
  agents: "Default Directory | Agents",
  identitygovernance: "Default Directory | Identity Governance",
  appproxy: "Default Directory | Application proxy",
  customsecurityattributes: "Default Directory | Custom security attributes",
  licenses: "Licenses | License usage",
  crosstenantsync: "Default Directory | Cross-tenant synchronization",
  entraconnect: "Default Directory | Microsoft Entra Connect",
  mobility: "Default Directory | Mobility (MDM and WIP)",
  passwordreset: "Default Directory | Password reset",
  companybranding: "Default Directory | Company branding",
  security: "Default Directory | Security",
  provisioninglogs: "Default Directory | Provisioning logs",
  health: "Default Directory | Health",
  loganalytics: "Default Directory | Log Analytics",
  diagnosticsettings: "Default Directory | Diagnostic settings",
  workbooks: "Default Directory | Workbooks",
  usageinsights: "Default Directory | Usage & insights",
  bulkresults: "Default Directory | Bulk operation results (Preview)",
  support: "Default Directory | Support + Troubleshooting",
};

export default function StaticPage({ id }) {
  return (
    <EntraShell active={id} title={TITLES[id] || id}>
      <div className="vy-page">
        <section className="vy-form-section">
          <p>{NOTES[id]}</p>
        </section>
      </div>
    </EntraShell>
  );
}
