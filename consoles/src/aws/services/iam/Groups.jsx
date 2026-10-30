/* IAM user groups list — real ListGroups/DeleteGroup. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate, follow } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Groups() {
  const notify = useNotify();
  const g = useAsync(() => api.listGroups(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="IAM user groups"
        items={g.data || []}
        loading={g.loading}
        error={g.error}
        onRefresh={g.reload}
        trackBy="GroupName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={{ title: "No resources to display" }}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("iam", "create-user-group")}>Create group</Button>
          </SpaceBetween>
        }
        columns={[
          { id: "name", header: "Group name", isRowHeader: true, cell: (x) => <Link href={`#/iam/groups/${x.GroupName}`} onFollow={follow}>{x.GroupName}</Link> },
          { id: "users", header: "Users", cell: () => "-" },
          { id: "perm", header: "Permissions", cell: () => "-" },
          { id: "created", header: "Creation time", cell: (x) => fmtDate(x.CreateDate) },
        ]}
      />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="group"
        names={sel.map((x) => x.GroupName)}
        onConfirm={async () => { for (const x of sel) await api.deleteGroup(x.GroupName); notify.success("Group(s) deleted."); setSel([]); g.reload(); }} />
    </>
  );
}
