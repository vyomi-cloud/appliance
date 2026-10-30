/* Default Directory | Audit logs — real: every user/group/application/domain/
 * administrative-unit mutation made through this console or the native wire appends an
 * entry here (core/azure_graph_core.py's GraphStore.audit()), so a freshly created
 * resource shows up immediately — no sample data. */
import { useState } from "react";
import { Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { ArrowDownload20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { downloadCsv } from "./csv.js";

const COLUMNS = [
  { key: "date", label: "Date", value: (r) => r.activityDateTime },
  { key: "service", label: "Service", value: (r) => r.loggedByService },
  { key: "category", label: "Category" },
  { key: "activity", label: "Activity", value: (r) => `${r.activityDisplayName}: ${r.targetResources?.[0]?.displayName || ""}` },
  { key: "status", label: "Status", value: (r) => r.result },
  { key: "statusReason", label: "Status Reason", value: (r) => r.resultReason || "--" },
];

export default function AuditLogs() {
  const [tab, setTab] = useState("directory");
  const { data, loading, error, reload } = useAsync(() => api.listAuditLogs(), []);

  return (
    <EntraShell active="auditlogs" title="Default Directory | Audit logs">
      <div className="vy-page">
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Audit logs">
          <Tab value="directory">Directory</Tab>
          <Tab value="customsecurity">Custom Security</Tab>
        </TabList>
        <div style={{ marginTop: 12 }}>
          <BrowseGrid
            resourceName="audit log entry"
            rowKey={(r) => r.id}
            items={tab === "directory" ? (data || []) : []}
            loading={loading}
            error={error}
            onRefresh={reload}
            columns={COLUMNS}
            csvName="audit-logs.csv"
            extraCommands={<ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv("audit-logs.csv", COLUMNS, data || [])} disabled={!data?.length}>Download</ToolbarButton>}
          />
        </div>
        <NotSimulatedContainer title="More commands" feature="Export Data Settings, Got feedback?" note="Export Data Settings. Got feedback? are not simulated in Vyomi." />
      </div>
    </EntraShell>
  );
}
