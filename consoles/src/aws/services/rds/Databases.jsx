import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Toggle from "@cloudscape-design/components/toggle";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { DeleteDatabaseModal, ModifyModal, SnapshotModal } from "./DatabaseActions.jsx";
import * as api from "./api.js";

export const statusOf = (s) => (
  <StatusIndicator type={s === "available" ? "success" : s === "stopped" ? "stopped" : s === "deleting" ? "loading" : "in-progress"}>
    {s || "unknown"}
  </StatusIndicator>
);

export default function Databases() {
  const notify = useNotify();
  const [group, setGroup] = useState(true);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [modify, setModify] = useState(false);
  const [snapModal, setSnapModal] = useState(false);
  const t = useAsync(() => api.describeDBInstances());

  return (
    <>
      <ResourceTable
        resourceName="Databases"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="DBInstanceIdentifier"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter by databases"
        description={<Toggle checked={group} onChange={({ detail }) => setGroup(detail.checked)}>Group resources</Toggle>}
        empty={{ title: "No resources", action: <Button variant="primary" href={href("rds", "create-database")} onFollow={follow}>Create database</Button> }}
        columns={[
          { id: "id", header: "DB identifier", isRowHeader: true, cell: (d) => <Link href={href("rds", "databases", d.DBInstanceIdentifier)} onFollow={follow}>{d.DBInstanceIdentifier}</Link> },
          { id: "status", header: "Status", cell: (d) => statusOf(d.DBInstanceStatus) },
          { id: "role", header: "Role", cell: () => "Instance" },
          { id: "engine", header: "Engine", cell: (d) => `${d.Engine} ${d.EngineVersion}` },
          { id: "rollout", header: "Upgrade rollout order", cell: () => "-" },
          { id: "az", header: "Region & AZ", cell: (d) => d.AvailabilityZone },
          { id: "size", header: "Size", cell: (d) => d.DBInstanceClass },
          { id: "reco", header: "Recommendations", cell: () => "-" },
          { id: "cpu", header: "CPU", cell: () => "-" },
          { id: "activity", header: "Current activity", cell: () => "-" },
          { id: "maint", header: "Maintenance", cell: () => "-" },
          { id: "vpc", header: "VPC", cell: (d) => d.DBSubnetGroup?.VpcId || "vpc-default" },
          { id: "multiaz", header: "Multi-AZ", cell: (d) => (d.MultiAZ === "true" ? "Yes" : "No") },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setModify(true)}>Modify</Button>
            <ButtonDropdown
              disabled={sel.length !== 1}
              items={[
                { id: "reboot", text: "Reboot" },
                { id: "snapshot", text: "Take snapshot" },
                { id: "stop", text: "Stop temporarily", disabled: sel[0]?.DBInstanceStatus !== "available" },
                { id: "start", text: "Start", disabled: sel[0]?.DBInstanceStatus !== "stopped" },
                { id: "delete", text: "Delete" },
              ]}
              onItemClick={async ({ detail }) => {
                const id = sel[0].DBInstanceIdentifier;
                try {
                  if (detail.id === "reboot") { await api.rebootDBInstance(id); notify.success(`Rebooting "${id}".`); t.reload(); }
                  else if (detail.id === "stop") { await api.stopDBInstance(id); notify.success(`Stopping "${id}".`); t.reload(); }
                  else if (detail.id === "start") { await api.startDBInstance(id); notify.success(`Starting "${id}".`); t.reload(); }
                  else if (detail.id === "snapshot") { setSnapModal(true); }
                  else if (detail.id === "delete") { setDel(true); }
                } catch (e) { notify.error(e); }
              }}
            >Actions</ButtonDropdown>
            <Button variant="primary" href={href("rds", "create-database")} onFollow={follow}>Create database</Button>
          </SpaceBetween>
        }
      />
      <ModifyModal db={sel[0]} visible={modify} onDismiss={() => setModify(false)} onDone={t.reload} notify={notify} />
      <SnapshotModal dbId={sel[0]?.DBInstanceIdentifier} visible={snapModal} onDismiss={() => setSnapModal(false)} notify={notify} />
      <DeleteDatabaseModal
        dbIds={sel.map((d) => d.DBInstanceIdentifier)}
        visible={del}
        onDismiss={() => setDel(false)}
        onDone={() => { setDel(false); setSel([]); t.reload(); }}
        notify={notify}
      />
    </>
  );
}
