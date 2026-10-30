/* Users (Default Directory | Users) — the Entra ID peer of StorageAccounts.jsx: a
 * BrowseGrid over the real Microsoft Graph users collection. */
import { Link, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowDownload20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { downloadCsv } from "./csv.js";

const COLUMNS = [
  { key: "displayName", label: "Display name", render: (r) => <Link href={`#/entra/users/${encodeURIComponent(r.id)}`}>{r.displayName}</Link> },
  { key: "userPrincipalName", label: "User principal name" },
  { key: "userType", label: "User type" },
  { key: "isAgent", label: "Is Agent", value: () => "No" },
  { key: "onPremisesSyncEnabled", label: "On-premises sync enabled", value: (r) => (r.onPremisesSyncEnabled ? "Yes" : "No") },
  { key: "signInIdentifiers", label: "Sign-in identifiers", value: (r) => r.userPrincipalName },
  { key: "companyName", label: "Company name" },
  { key: "creationType", label: "Creation type", value: (r) => r.creationType || "--" },
  { key: "deletionProtection", label: "Permanent deletion protection status", value: () => "Disabled" },
];

export default function Users() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listUsers(), []);

  return (
    <EntraShell active="users" title="Users">
      <div className="vy-page">
        <BrowseGrid
          resourceName="user"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteUser(r.id);
            notify.success(`Deleted ${rows.length} user${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          csvName="users.csv"
          filterPlaceholder="Search"
          columns={COLUMNS}
          extraCommands={<>
            <ToolbarButton icon={<Add20Regular />} onClick={() => navigate("entra", "users", "create")}>New user</ToolbarButton>
            <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv("users.csv", COLUMNS, data || [])} disabled={!data?.length}>Download users (Preview)</ToolbarButton>
          </>}
          emptyAction={<Link href="#/entra/users/create">New user</Link>}
        />
        <NotSimulatedContainer title="More commands" feature="Edit, Bulk operations, Per-user MFA, Got feedback?"
          note="Edit (inline bulk edit). Bulk operations (CSV-driven create/update/delete). Per-user MFA. Got feedback? These are not simulated in Vyomi; edit a single user from its own page, and see Audit logs for a real record of changes." />
      </div>
    </EntraShell>
  );
}
