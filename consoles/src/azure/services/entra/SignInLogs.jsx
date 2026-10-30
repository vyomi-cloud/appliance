/* Default Directory | Sign-in logs — azure.entra.sign_in_logs is not_simulated: Vyomi has
 * no interactive sign-in flow, so this honestly shows no sign-ins rather than fabricating
 * sample rows. The grid and its columns are real; the data is a real (empty) query. */
import { useState } from "react";
import { Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { ArrowDownload20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { downloadCsv } from "./csv.js";

const TABS = [
  { id: "interactive", label: "User sign-ins (interactive)" },
  { id: "noninteractive", label: "User sign-ins (non-interactive)" },
  { id: "serviceprincipal", label: "Service principal sign-ins" },
  { id: "managedidentity", label: "Managed identity sign-ins" },
];

const COLUMNS = [
  { key: "date", label: "Date" }, { key: "requestId", label: "Request ID" }, { key: "user", label: "User" },
  { key: "application", label: "Application" }, { key: "status", label: "Status" }, { key: "errorCode", label: "Sign-in error code" },
  { key: "ip", label: "IP address" }, { key: "location", label: "Location" }, { key: "ca", label: "Conditional Access" },
  { key: "agentType", label: "Agent Type" }, { key: "authRequirement", label: "Authentication requirement" },
];

export default function SignInLogs() {
  const [tab, setTab] = useState("interactive");
  const { data } = useAsync(() => api.listSignInLogs(), []);

  return (
    <EntraShell active="signinlogs" title="Default Directory | Sign-in logs">
      <div className="vy-page">
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Sign-in logs">
          {TABS.map((t) => <Tab key={t.id} value={t.id}>{t.label}</Tab>)}
        </TabList>
        <div style={{ marginTop: 12 }}>
          <BrowseGrid
            resourceName="sign-in"
            items={data || []}
            columns={COLUMNS}
            csvName="sign-in-logs.csv"
            extraCommands={<ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv("sign-in-logs.csv", COLUMNS, data || [])} disabled={!data?.length}>Download</ToolbarButton>}
          />
        </div>
        <NotSimulatedContainer title="More commands" feature="Export Data Settings, Troubleshoot, Columns, Got feedback?"
          note="Export Data Settings. Troubleshoot. Columns. Got feedback? Vyomi has no interactive sign-in flow to generate telemetry from." />
      </div>
    </EntraShell>
  );
}
