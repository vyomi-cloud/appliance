import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import * as api from "./api.js";

export default function SubnetGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeDBSubnetGroups());

  return (
    <>
      <ResourceTable
        resourceName="Subnet groups"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="DBSubnetGroupName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter by subnet groups"
        empty={{ title: "No db subnet groups", action: <Button href={href("rds", "create-db-subnet-group")} onFollow={follow}>Create DB subnet group</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.DBSubnetGroupName },
          { id: "desc", header: "Description", cell: (g) => g.DBSubnetGroupDescription },
          { id: "status", header: "Status", cell: (g) => g.SubnetGroupStatus },
          { id: "vpc", header: "VPC", cell: (g) => g.VpcId },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1}>Edit</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" href={href("rds", "create-db-subnet-group")} onFollow={follow}>Create DB subnet group</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="DB subnet group" names={sel.map((g) => g.DBSubnetGroupName)} onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const g of sel) await api.deleteDBSubnetGroup(g.DBSubnetGroupName);
          notify.success(`${sel.length} DB subnet group(s) deleted.`);
          setSel([]); t.reload();
        }} />
    </>
  );
}
