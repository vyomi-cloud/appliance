/* Resource control policies (RCPs) — same real list as SCPs, filtered by type. */
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import * as api from "./api.js";

export default function ResourceControlPolicies() {
  const notify = useNotify();
  const p = useAsync(() => api.listOrgPolicies("RESOURCE_CONTROL_POLICY"), []);

  return (
    <ResourceTable
      resourceName="Resource control policies (RCPs)"
      items={p.data || []}
      loading={p.loading}
      error={p.error}
      onRefresh={p.reload}
      trackBy="Id"
      selectionType="single"
      empty={{ title: "No resources to display." }}
      actions={<Button onClick={() => notify.success("Resource control policies are managed in AWS Organizations; Vyomi mirrors them here read-only.")}>Edit in AWS Organizations</Button>}
      columns={[
        { id: "name", header: "Policy name", isRowHeader: true, cell: (x) => x.Name },
        { id: "attached", header: "Attached to entities", cell: () => "0" },
      ]}
    />
  );
}
