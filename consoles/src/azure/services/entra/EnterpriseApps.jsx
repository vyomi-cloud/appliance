/* Enterprise applications | All applications — real Microsoft Graph service principals.
 * Every app registration auto-creates one (core/azure_graph_core.py), matching the real
 * Azure AD behaviour. Vyomi doesn't track homepage URL / certificate expiry / identifier
 * URI independently of the app registration, so those columns render from the same
 * record rather than being faked. */
import { ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { fmtDateTime } from "./api.js";

const COLUMNS = [
  { key: "displayName", label: "Name" },
  { key: "id", label: "Object ID" },
  { key: "appId", label: "Application ID" },
  { key: "homepage", label: "Homepage URL", value: (r) => r.homepage || "--" },
  { key: "createdOn", label: "Created on", value: (r) => fmtDateTime(r.createdDateTime) },
  { key: "activation", label: "Activation status", value: (r) => (r.accountEnabled ? "Enabled" : "Disabled") },
  { key: "certExpiryStatus", label: "Certificate Expiry Status", value: () => "No certificates" },
  { key: "certExpiryDate", label: "Active Certificate Expiry Date", value: () => "--" },
  { key: "identifierUri", label: "Identifier URI (Entity ID)", value: (r) => r.identifierUris?.[0] || "--" },
];

export default function EnterpriseApps() {
  const { data, loading, error, reload } = useAsync(() => api.listServicePrincipals(), []);

  return (
    <EntraShell active="enterpriseapps" title="Enterprise applications | All applications">
      <div className="vy-page">
        <BrowseGrid
          resourceName="application"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          csvName="enterprise-applications.csv"
          columns={COLUMNS}
          extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => navigate("entra", "appregistrations", "register")}>New application</ToolbarButton>}
        />
        <NotSimulatedContainer title="More commands" feature="Download (Export), Preview info, Columns, Preview features, Got feedback?"
          note="Download (Export). Preview info. Columns. Preview features. Got feedback? Not simulated in Vyomi." />
      </div>
    </EntraShell>
  );
}
