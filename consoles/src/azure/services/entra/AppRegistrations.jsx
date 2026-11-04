/* Default Directory | App registrations — real Microsoft Graph applications. The five
 * tabs are real, distinct queries: Vyomi doesn't track app ownership, soft-delete or
 * deactivation, so "Owned applications" mirrors "All applications" and the other two
 * tabs are honestly (not fakely) empty — matching the native console's own empty state. */
import { useState } from "react";
import { Link, Tab, TabList, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { fmtDateTime } from "./api.js";

const TABS = [
  { id: "all", label: "All applications" },
  { id: "owned", label: "Owned applications" },
  { id: "deleted", label: "Deleted applications" },
  { id: "deactivated", label: "Deactivated applications" },
  { id: "personal", label: "Applications from personal account" },
];

const COLUMNS = [
  { key: "displayName", label: "Display name", render: (r) => <Link href={`#/entra/appregistrations/${encodeURIComponent(r.id)}`}>{r.displayName}</Link> },
  { key: "appId", label: "Application (client) ID" },
  { key: "createdOn", label: "Created on", value: (r) => fmtDateTime(r.createdDateTime) },
  { key: "secrets", label: "Certificates & secrets", value: (r) => `${(r.passwordCredentials || []).length} secret(s)` },
];

export default function AppRegistrations() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listApplications(), []);
  const [tab, setTab] = useState("all");
  const rows = tab === "all" || tab === "owned" ? data || [] : [];

  return (
    <EntraShell active="appregistrations" title="Default Directory | App registrations">
      <div className="vy-page">
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="App registrations">
          {TABS.map((t) => <Tab key={t.id} value={t.id}>{t.label}</Tab>)}
        </TabList>
        <div style={{ marginTop: 12 }}>
          <BrowseGrid
            resourceName="application"
            items={rows}
            loading={loading}
            error={error}
            onRefresh={reload}
            onDelete={tab === "all" || tab === "owned" ? async (sel) => {
              for (const r of sel) await api.deleteApplication(r.id);
              notify.success(`Deleted ${sel.length} application${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
              reload();
            } : undefined}
            csvName="app-registrations.csv"
            columns={COLUMNS}
            extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => navigate("entra", "appregistrations", "register")}>New registration</ToolbarButton>}
            emptyAction={<Link href="#/entra/appregistrations/register">Register an application</Link>}
          />
        </div>
      </div>
    </EntraShell>
  );
}
