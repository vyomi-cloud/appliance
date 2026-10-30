/* Groups | All groups — BrowseGrid over the real Microsoft Graph groups collection. */
import { ToolbarButton } from "@fluentui/react-components";
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
  { key: "displayName", label: "Name" },
  { key: "id", label: "Object Id" },
  { key: "groupType", label: "Group type", value: (r) => (r.groupTypes?.includes("Unified") ? "Microsoft 365" : "Security") },
  { key: "membershipType", label: "Membership type" },
  { key: "mail", label: "Email" },
  { key: "source", label: "Source", value: (r) => (r.onPremisesSyncEnabled ? "Windows Server AD" : "Cloud") },
];

export default function Groups() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listGroups(), []);

  return (
    <EntraShell active="groups" title="Groups | All groups">
      <div className="vy-page">
        <BrowseGrid
          resourceName="group"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteGroup(r.id);
            notify.success(`Deleted ${rows.length} group${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          csvName="groups.csv"
          filterPlaceholder="Search"
          columns={COLUMNS}
          extraCommands={<>
            <ToolbarButton icon={<Add20Regular />} onClick={() => navigate("entra", "groups", "new")}>New group</ToolbarButton>
            <ToolbarButton icon={<ArrowDownload20Regular />} onClick={() => downloadCsv("groups.csv", COLUMNS, data || [])} disabled={!data?.length}>Download groups</ToolbarButton>
          </>}
          emptyAction={<a href="#/entra/groups/new">New group</a>}
        />
        <NotSimulatedContainer title="More commands" feature="Got feedback?" note="Got feedback? is not simulated in Vyomi." />
      </div>
    </EntraShell>
  );
}
