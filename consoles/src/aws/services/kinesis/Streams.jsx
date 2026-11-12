/* Data streams — the main Kinesis list: create, delete, enable/disable enhanced monitoring. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const statusType = (s) => (s === "ACTIVE" ? "success" : s === "DELETING" ? "error" : "in-progress");

export default function Streams() {
  const notify = useNotify();
  const t = useAsync(() => api.listStreams(), []);
  const [sel, setSel] = useState([]);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const toggleMonitoring = async (enable) => {
    try {
      for (const s of sel) await (enable ? api.enableMonitoring : api.disableMonitoring)(s.StreamName, api.ALL_METRICS);
      notify.success(`Enhanced (shard-level) metrics ${enable ? "enabled" : "disabled"}.`);
      setSel([]); t.reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <ResourceTable
        resourceName="Data streams"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="StreamName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find data streams"
        empty={{ title: "You don't have any data streams.", action: <Button onClick={() => navigate("kinesis", "streams", "create")}>Create data stream</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (s) => <Link href={href("kinesis", "streams", s.StreamName)} onFollow={follow}>{s.StreamName}</Link> },
          { id: "status", header: "Status", cell: (s) => <StatusIndicator type={statusType(s.StreamStatus)}>{s.StreamStatus}</StatusIndicator> },
          { id: "created", header: "Creation time", cell: (s) => fmtDate(s.StreamCreationTimestamp) },
          { id: "mode", header: "Capacity mode", cell: (s) => api.capacityLabel(s.StreamModeDetails) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown
              items={[
                { id: "enable", text: "Enable enhanced (shard-level) metrics", disabled: !sel.length },
                { id: "disable", text: "Disable enhanced (shard-level) metrics", disabled: !sel.length },
              ]}
              onItemClick={({ detail }) => toggleMonitoring(detail.id === "enable")}
            >Actions</ButtonDropdown>
            <Button disabled={!sel.length} onClick={() => setDeleteOpen(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("kinesis", "streams", "create")}>Create data stream</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal
        visible={deleteOpen}
        onDismiss={() => setDeleteOpen(false)}
        resourceType="data stream"
        names={sel.map((s) => s.StreamName)}
        onConfirm={async () => { await api.deleteStream(sel[0].StreamName, true); notify.success(`Deleting data stream "${sel[0].StreamName}".`); setSel([]); t.reload(); }}
      />
    </>
  );
}
