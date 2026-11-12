import { useState } from "react";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import * as api from "./api.js";

const DEFAULT_FAMILIES = [
  { DBParameterGroupName: "default.postgres16", DBParameterGroupFamily: "postgres16", Description: "Default parameter group for postgres16", Type: "DB Parameter Group" },
  { DBParameterGroupName: "default.mysql8.0", DBParameterGroupFamily: "mysql8.0", Description: "Default parameter group for mysql8.0", Type: "DB Parameter Group" },
];

function CustomParameterGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeDBParameterGroups());

  return (
    <>
      <ResourceTable
        resourceName="Custom parameter groups"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="DBParameterGroupName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter by parameter groups"
        empty={{ title: "No parameter group found", action: <Button href={href("rds", "create-parameter-group")} onFollow={follow}>Create parameter group</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => <Link href={href("rds", "parameter-groups", g.DBParameterGroupName)} onFollow={follow}>{g.DBParameterGroupName}</Link> },
          { id: "family", header: "Family", cell: (g) => g.DBParameterGroupFamily },
          { id: "type", header: "Type", cell: (g) => g.Type || "DB Parameter Group" },
          { id: "desc", header: "Description", cell: (g) => g.Description },
          { id: "arn", header: "ARN", cell: (g) => g.DBParameterGroupArn },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setDel(true)}>Actions</Button>
            <Button variant="primary" href={href("rds", "create-parameter-group")} onFollow={follow}>Create parameter group</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="parameter group" names={sel.map((g) => g.DBParameterGroupName)} onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const g of sel) await api.deleteDBParameterGroup(g.DBParameterGroupName);
          notify.success(`${sel.length} parameter group(s) deleted.`);
          setSel([]); t.reload();
        }} />
    </>
  );
}

function DefaultParameterGroups() {
  return (
    <Table variant="container" items={DEFAULT_FAMILIES} trackBy="DBParameterGroupName"
      header={`Default parameter groups (${DEFAULT_FAMILIES.length})`}
      columnDefinitions={[
        { id: "name", header: "Name", cell: (g) => g.DBParameterGroupName },
        { id: "family", header: "Family", cell: (g) => g.DBParameterGroupFamily },
        { id: "type", header: "Type", cell: (g) => g.Type },
        { id: "desc", header: "Description", cell: (g) => g.Description },
      ]} />
  );
}

export default function ParameterGroups() {
  const [tab, setTab] = useState("custom");
  return (
    <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
      { id: "custom", label: "Custom", content: <CustomParameterGroups /> },
      { id: "default", label: "Default", content: <DefaultParameterGroups /> },
    ]} />
  );
}
