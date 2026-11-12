/* Maintenance Windows — real CreateMaintenanceWindow/DescribeMaintenanceWindows/Delete. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function MaintenanceWindows() {
  const notify = useNotify();
  const t = useAsync(() => api.listMaintenanceWindows(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Maintenance Windows"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="WindowId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search maintenance windows"
        empty={{ title: "No maintenance windows", action: <Button onClick={() => navigate("ssm", "create-maintenance-window")}>Create maintenance window</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (w) => <Link href={href("ssm", "maintenance-windows", w.WindowId)} onFollow={follow}>{w.Name}</Link> },
          { id: "id", header: "Maintenance window ID", cell: (w) => w.WindowId },
          { id: "enabled", header: "Enabled", cell: (w) => <StatusIndicator type={w.Enabled ? "success" : "stopped"}>{w.Enabled ? "Enabled" : "Disabled"}</StatusIndicator> },
          { id: "dur", header: "Duration", cell: (w) => `${w.Duration}h` },
          { id: "next", header: "Next execution", cell: (w) => fmtDate(w.NextExecutionTime) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("ssm", "create-maintenance-window")}>Create maintenance window</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal
        visible={del}
        onDismiss={() => setDel(false)}
        resourceType="maintenance window"
        names={sel.map((w) => w.Name)}
        onConfirm={async () => {
          for (const w of sel) await api.deleteMaintenanceWindow(w.WindowId);
          notify.success(`Deleted ${sel.length} maintenance window(s).`);
          setSel([]); t.reload();
        }}
      />
    </>
  );
}
