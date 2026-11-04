import { useState } from "react";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { href, follow } from "../../../common/router.js";
import ExportsInAmazonS3 from "./ExportsInAmazonS3.jsx";
import * as api from "./api.js";

const SNAPSHOT_COLUMNS = () => [
  { id: "name", header: "Snapshot name", isRowHeader: true, cell: (s) => s.DBSnapshotIdentifier },
  { id: "ev", header: "Engine version", cell: (s) => s.EngineVersion },
  { id: "inst", header: "DB instance or cluster", cell: (s) => s.DBInstanceIdentifier },
  { id: "created", header: "Snapshot creation time", cell: (s) => fmtDate(s.SnapshotCreateTime) },
  { id: "instcreated", header: "DB Instance created time", cell: () => "-" },
  { id: "status", header: "Status", cell: (s) => <StatusIndicator type={s.Status === "available" ? "success" : "in-progress"}>{s.Status}</StatusIndicator> },
  { id: "progress", header: "Progress", cell: () => "100%" },
  { id: "vpc", header: "VPC", cell: () => "vpc-default" },
  { id: "type", header: "Snapshot type", cell: (s) => s.SnapshotType },
  { id: "storage", header: "Storage", cell: (s) => `${s.AllocatedStorage} GiB` },
  { id: "storagetype", header: "Storage Type", cell: () => "gp3" },
  { id: "zone", header: "Zone", cell: () => "us-east-1a" },
  { id: "owner", header: "Owner", cell: () => "123456789012" },
  { id: "port", header: "Port", cell: (s) => (s.Engine?.includes("mysql") || s.Engine === "mariadb" ? 3306 : 5432) },
  { id: "enc", header: "Encrypted", cell: () => "No" },
  { id: "tz", header: "Timezone", cell: () => "-" },
  { id: "engine", header: "Engine", cell: (s) => s.Engine },
  { id: "dbtime", header: "Snapshot database time", cell: (s) => fmtDate(s.SnapshotCreateTime) },
  { id: "size", header: "Full snapshot size", cell: (s) => `${s.AllocatedStorage} GiB` },
];

function ManualSnapshots() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeDBSnapshots());
  const manual = (t.data || []).filter((s) => s.SnapshotType === "manual");
  return (
    <>
      <ResourceTable
        resourceName="Manual snapshots"
        items={manual}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="DBSnapshotIdentifier"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter by manual snapshots"
        empty={{ title: "No Snapshots found, you can take a snapshot using Take Snapshot button" }}
        columns={SNAPSHOT_COLUMNS()}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={sel.length !== 1} items={[
              { id: "restore", text: "Restore snapshot" },
              { id: "delete", text: "Delete snapshot" },
            ]} onItemClick={async ({ detail }) => {
              const s = sel[0];
              try {
                if (detail.id === "restore") {
                  await api.restoreDBInstanceFromDBSnapshot(`${s.DBSnapshotIdentifier}-restore`, s.DBSnapshotIdentifier);
                  notify.success(`Restoring database from "${s.DBSnapshotIdentifier}".`);
                } else if (detail.id === "delete") setDel(true);
                if (detail.id !== "delete") t.reload();
              } catch (e) { notify.error(e); }
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("rds", "take-snapshot")} onFollow={follow}>Take snapshot</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="snapshot" names={sel.map((s) => s.DBSnapshotIdentifier)} onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const s of sel) await api.deleteDBSnapshot(s.DBSnapshotIdentifier);
          notify.success(`${sel.length} snapshot(s) deleted.`);
          setSel([]); t.reload();
        }} />
    </>
  );
}

function EmptySnapshotTab({ resourceName, filterPlaceholder }) {
  return (
    <ResourceTable resourceName={resourceName} items={[]} trackBy="DBSnapshotIdentifier"
      filterPlaceholder={filterPlaceholder} empty={{ title: `No ${resourceName.toLowerCase()}` }} columns={SNAPSHOT_COLUMNS()} />
  );
}

function SystemSnapshots() {
  const t = useAsync(() => api.describeDBSnapshots());
  const system = (t.data || []).filter((s) => s.SnapshotType !== "manual");
  return (
    <ResourceTable resourceName="System snapshots" items={system} loading={t.loading} onRefresh={t.reload} trackBy="DBSnapshotIdentifier"
      filterPlaceholder="Filter by system snapshots" empty={{ title: "No system snapshots" }} columns={SNAPSHOT_COLUMNS()} />
  );
}

export default function Snapshots() {
  const [tab, setTab] = useState("manual");
  return (
    <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
      { id: "manual", label: "Manual", content: <ManualSnapshots /> },
      { id: "system", label: "System", content: <SystemSnapshots /> },
      { id: "shared", label: "Shared with me", content: <EmptySnapshotTab resourceName="Shared snapshots" filterPlaceholder="Filter by shared snapshots" /> },
      { id: "public", label: "Public", content: <EmptySnapshotTab resourceName="Public snapshots" filterPlaceholder="Filter by public snapshots" /> },
      { id: "backup", label: "Backup service", content: <EmptySnapshotTab resourceName="Backup service snapshots" filterPlaceholder="Filter by backup service snapshots" /> },
      { id: "exports", label: "Exports in Amazon S3", content: <ExportsInAmazonS3 /> },
    ]} />
  );
}
