import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function StateMachines() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listStateMachines());

  return (
    <>
      <ResourceTable
        resourceName="State machines"
        items={data}
        trackBy="stateMachineArn"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search state machines"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (m) => <Link href={href("states", "state-machines", m.name)} onFollow={follow}>{m.name}</Link> },
          { id: "type", header: "Type", cell: (m) => (m.type === "EXPRESS" ? "Express" : "Standard") },
          { id: "status", header: "Status", cell: () => <StatusIndicator type="success">Active</StatusIndicator> },
          { id: "created", header: "Created", cell: (m) => fmtDate(m.creationDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" href={href("states", "create")} onFollow={follow}>Create state machine</Button>
          </SpaceBetween>
        }
        empty={{ title: "No state machines", subtitle: "Create a state machine to get started.", action: <Button variant="primary" href={href("states", "create")} onFollow={follow}>Create state machine</Button> }}
      />
      <DeleteModal
        visible={del}
        resourceType="state machine"
        names={sel.map((m) => m.name)}
        confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const m of sel) await api.deleteStateMachine(m.stateMachineArn);
          notify.success(`${sel.length} state machine${sel.length > 1 ? "s" : ""} deleted.`);
          setSel([]); reload();
        }}
      />
    </>
  );
}
