/* State Manager — associations. Real CreateAssociation/ListAssociations/DeleteAssociation. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

export default function Associations() {
  const notify = useNotify();
  const t = useAsync(() => api.listAssociations(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Associations"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="AssociationId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search associations"
        empty={{ title: "No associations", action: <Button onClick={() => navigate("ssm", "create-association")}>Create association</Button> }}
        columns={[
          { id: "id", header: "Association ID", isRowHeader: true, cell: (a) => <Link href={href("ssm", "associations", a.AssociationId)} onFollow={follow}>{a.AssociationId}</Link> },
          { id: "name", header: "Name", cell: (a) => a.Name },
          { id: "aname", header: "Association name", cell: (a) => a.AssociationName || "-" },
          { id: "sched", header: "Schedule", cell: (a) => a.ScheduleExpression || "-" },
          { id: "status", header: "Status", cell: (a) => a.Overview?.Status || "-" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("ssm", "create-association")}>Create association</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal
        visible={del}
        onDismiss={() => setDel(false)}
        resourceType="association"
        names={sel.map((a) => a.AssociationId)}
        onConfirm={async () => {
          for (const a of sel) await api.deleteAssociation(a.AssociationId);
          notify.success(`Deleted ${sel.length} association(s).`);
          setSel([]); t.reload();
        }}
      />
    </>
  );
}
