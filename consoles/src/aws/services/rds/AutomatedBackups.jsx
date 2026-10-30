import { useState } from "react";
import Tabs from "@cloudscape-design/components/tabs";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const COLUMNS = [
  { id: "inst", header: "DB instance or cluster", isRowHeader: true, cell: (b) => b.DBInstanceIdentifier },
  { id: "earliest", header: "Earliest restorable time", cell: (b) => b.EarliestRestorableTime || "-" },
  { id: "latest", header: "Latest restorable time", cell: (b) => b.LatestRestorableTime || "-" },
  { id: "engine", header: "Engine", cell: (b) => b.Engine || "-" },
  { id: "zone", header: "Zone", cell: () => "us-east-1a" },
  { id: "replicated", header: "Replicated to", cell: () => "-" },
  { id: "source", header: "Source Region", cell: () => "us-east-1" },
  { id: "encrypted", header: "Encrypted", cell: (b) => (b.Encrypted === "true" ? "Yes" : "No") },
];

function CurrentRegion() {
  const [sel, setSel] = useState([]);
  const t = useAsync(() => api.describeDBInstanceAutomatedBackups());
  return (
    <ResourceTable resourceName="Current Region backups" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
      trackBy="DBInstanceIdentifier" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
      empty={{ title: "No current region backups found" }} columns={COLUMNS}
      actions={<ButtonDropdown disabled={sel.length !== 1} items={[{ id: "delete", text: "Delete" }]}>Actions</ButtonDropdown>} />
  );
}

export default function AutomatedBackups() {
  const [tab, setTab] = useState("current");
  return (
    <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
      { id: "current", label: "Current Region", content: <CurrentRegion /> },
      { id: "replicated", label: "Replicated", content: <ResourceTable resourceName="Replicated backups" items={[]} trackBy="DBInstanceIdentifier" empty={{ title: "No replicated backups found" }} columns={COLUMNS} /> },
      { id: "retained", label: "Retained", content: <ResourceTable resourceName="Retained backups" items={[]} trackBy="DBInstanceIdentifier" empty={{ title: "No retained backups found" }} columns={COLUMNS} /> },
    ]} />
  );
}
