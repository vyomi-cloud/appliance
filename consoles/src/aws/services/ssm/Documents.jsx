/* Documents — owned-by-me + Amazon-owned, real CreateDocument/ListDocuments/DeleteDocument. */
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

export default function Documents() {
  const notify = useNotify();
  const t = useAsync(() => api.listDocuments(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Documents"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="Name"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search documents by name"
        empty={{ title: "No documents", action: <Button onClick={() => navigate("ssm", "create-document")}>Create document</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (doc) => <Link href={`${href("ssm", "documents", "view")}?name=${encodeURIComponent(doc.Name)}`} onFollow={follow}>{doc.Name}</Link> },
          { id: "owner", header: "Owner", cell: (doc) => doc.Owner },
          { id: "type", header: "Document type", cell: (doc) => doc.DocumentType },
          { id: "fmt", header: "Document format", cell: (doc) => doc.DocumentFormat },
          { id: "ver", header: "Default version", cell: (doc) => doc.DocumentVersion },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length || sel.some((d) => d.Owner === "Amazon")} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("ssm", "create-document")}>Create document</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal
        visible={del}
        onDismiss={() => setDel(false)}
        resourceType="document"
        names={sel.map((d) => d.Name)}
        onConfirm={async () => {
          for (const d of sel) await api.deleteDocument(d.Name);
          notify.success(`Deleted ${sel.length} document(s).`);
          setSel([]); t.reload();
        }}
      />
    </>
  );
}
