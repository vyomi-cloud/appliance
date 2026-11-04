/* Parameter Store — list, delete. Every row is a real PutParameter/DescribeParameters round trip. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Parameters() {
  const notify = useNotify();
  const t = useAsync(() => api.listParameters(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Parameters"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="Name"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search parameters by name, description, or value"
        empty={{ title: "You don't have any parameters", action: <Button onClick={() => navigate("ssm", "create-parameter")}>Create parameter</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (p) => <Link href={`${href("ssm", "parameters", "view")}?name=${encodeURIComponent(p.Name)}`} onFollow={follow}>{p.Name}</Link> },
          { id: "desc", header: "Description", cell: (p) => p.Description || "-" },
          { id: "type", header: "Type", cell: (p) => <StatusIndicator type={p.Type === "SecureString" ? "info" : "success"}>{p.Type}</StatusIndicator> },
          { id: "tier", header: "Tier", cell: (p) => p.Tier },
          { id: "modified", header: "Last modified", cell: (p) => fmtDate(p.LastModifiedDate) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("ssm", "create-parameter")}>Create parameter</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal
        visible={del}
        onDismiss={() => setDel(false)}
        resourceType="parameter"
        names={sel.map((p) => p.Name)}
        onConfirm={async () => {
          for (const p of sel) await api.deleteParameter(p.Name);
          notify.success(`Deleted ${sel.length} parameter(s).`);
          setSel([]); t.reload();
        }}
      />
    </>
  );
}
