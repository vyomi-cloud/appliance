/* Patch Manager — patch baselines. Real CreatePatchBaseline/DescribePatchBaselines/Delete. */
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

export default function PatchBaselines() {
  const notify = useNotify();
  const t = useAsync(() => api.listPatchBaselines(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Patch baselines"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="BaselineId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search patch baselines"
        empty={{ title: "No patch baselines", action: <Button onClick={() => navigate("ssm", "create-patch-baseline")}>Create patch baseline</Button> }}
        columns={[
          { id: "name", header: "Baseline name", isRowHeader: true, cell: (b) => <Link href={href("ssm", "patch-baselines", b.BaselineId)} onFollow={follow}>{b.BaselineName}</Link> },
          { id: "id", header: "Baseline ID", cell: (b) => b.BaselineId },
          { id: "os", header: "Operating system", cell: (b) => b.OperatingSystem },
          { id: "default", header: "Default baseline", cell: (b) => (b.DefaultBaseline ? "Yes" : "No") },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => navigate("ssm", "create-patch-baseline")}>Create patch baseline</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal
        visible={del}
        onDismiss={() => setDel(false)}
        resourceType="patch baseline"
        names={sel.map((b) => b.BaselineName)}
        onConfirm={async () => {
          for (const b of sel) await api.deletePatchBaseline(b.BaselineId);
          notify.success(`Deleted ${sel.length} patch baseline(s).`);
          setSel([]); t.reload();
        }}
      />
    </>
  );
}
