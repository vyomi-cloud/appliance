/* Applications — a tracked deployment record (name/description/status), not a real
 * CloudFormation/SAM stack: Vyomi has no CloudFormation core to provision one. See
 * core/capabilities/aws/lambda.json (lambda.applications). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function Applications() {
  const notify = useNotify();
  const t = useAsync(() => api.listApplications(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Applications"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="Name"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by attributes or search by keyword"
        empty={{ title: "You don't have any serverless applications yet.", action: <Button variant="primary" href={href("lambda", "create", "application")} onFollow={follow}>Create application</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (a) => <Link href={href("lambda", "applications")} onFollow={follow}>{a.Name}</Link> },
          { id: "desc", header: "Description", cell: (a) => a.Description || "-" },
          { id: "status", header: "Status", cell: (a) => <StatusIndicator type={a.Status === "CREATE_COMPLETE" ? "success" : "info"}>{a.Status}</StatusIndicator> },
          { id: "modified", header: "Last modified", cell: (a) => fmtDate(a.LastModified) },
        ]}
        actions={
          <>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            {" "}
            <Button variant="primary" href={href("lambda", "create", "application")} onFollow={follow}>Create application</Button>
          </>
        }
      />
      <DeleteModal visible={del} resourceType="application" names={sel.map((a) => a.Name)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const a of sel) await api.deleteApplication(a.Name); notify.success(`${sel.length} application(s) deleted.`); setSel([]); t.reload(); }} />
    </>
  );
}
