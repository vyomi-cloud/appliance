/* Capacity providers — the resource (name/architectures/max vCPU/scaling mode/VPC) is
 * real, stored state; Vyomi's Lambda core only has one runtime (the sandboxed serverless
 * one), so attaching a capacity provider never changes where Invoke runs. See
 * core/capabilities/aws/lambda.json (lambda.capacity-providers). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function CapacityProviders() {
  const notify = useNotify();
  const t = useAsync(() => api.listCapacityProviders(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);

  return (
    <>
      <ResourceTable
        resourceName="Capacity providers"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="Name"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search by attributes or search by keyword"
        empty={{ title: "No capacity providers.", action: <Button variant="primary" href={href("lambda", "create", "capacity-provider")} onFollow={follow}>Create capacity provider</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "Name", cell: (c) => c.Name },
          { id: "state", header: "State", cell: (c) => <StatusIndicator type={c.State === "ACTIVE" ? "success" : "info"}>{c.State}</StatusIndicator> },
          { id: "arch", header: "Architectures", cell: (c) => (c.Architectures || []).join(", ") },
          { id: "vcpu", header: "Maximum vCPU", cell: (c) => c.MaximumVcpu },
          { id: "scaling", header: "Scaling mode", cell: (c) => c.ScalingMode },
          { id: "modified", header: "Last modified", cell: (c) => fmtDate(c.LastModified) },
        ]}
        actions={
          <>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            {" "}
            <Button variant="primary" href={href("lambda", "create", "capacity-provider")} onFollow={follow}>Create capacity provider</Button>
          </>
        }
      />
      <DeleteModal visible={del} resourceType="capacity provider" names={sel.map((c) => c.Name)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const c of sel) await api.deleteCapacityProvider(c.Name); notify.success(`${sel.length} capacity provider(s) deleted.`); setSel([]); t.reload(); }} />
    </>
  );
}
