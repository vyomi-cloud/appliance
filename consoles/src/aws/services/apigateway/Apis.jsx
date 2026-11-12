/* APIs — the combined list of REST (v1) and HTTP/WebSocket (v2) APIs, exactly like the
 * real console's unified APIs page. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow, navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Apis() {
  const notify = useNotify();
  const t = useAsync(() => api.listAllApis(), []);
  const [sel, setSel] = useState([]);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const doDelete = async () => {
    for (const a of sel) {
      if (a.kind === "rest") await api.deleteRestApi(a.id);
      else await api.deleteApiV2(a.id);
    }
    notify.success(`${sel.length} API${sel.length === 1 ? "" : "s"} deleted.`);
    setSel([]); setConfirmDelete(false); t.reload();
  };

  return (
    <>
      <ResourceTable
        resourceName="APIs"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="id"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find APIs"
        empty={{ title: "No API", subtitle: "You don't have any APIs.", action: <Button onClick={() => navigate("apigateway", "create")}>Create API</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (a) => (
            <Link href={href("apigateway", a.kind === "rest" ? "apis" : "api", a.id)} onFollow={follow}>{a.name}</Link>
          ) },
          { id: "description", header: "Description", cell: (a) => a.description || "-" },
          { id: "id", header: "ID", cell: (a) => a.id },
          { id: "protocol", header: "Protocol", cell: (a) => a.protocol },
          { id: "endpointType", header: "Endpoint type", cell: (a) => a.endpointType },
          { id: "created", header: "Created", cell: (a) => fmtDate(a.created) },
          { id: "securityPolicy", header: "Security policy", cell: (a) => a.securityPolicy },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setConfirmDelete(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("apigateway", "create")}>Create API</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal
        visible={confirmDelete}
        onDismiss={() => setConfirmDelete(false)}
        onConfirm={doDelete}
        resourceType="API"
        names={sel.map((a) => a.name)}
      />
    </>
  );
}
