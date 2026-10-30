/* Service control policies (SCPs) — real create/list/delete over IAM's native wire
 * (Vyomi-only CreateOrgPolicy/ListOrgPolicies; see core/iam_core.py). The real console
 * only lets you VIEW this list here — creation happens in AWS Organizations — so there
 * is no "Create" action, matching the native console. */
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import * as api from "./api.js";

export default function ServiceControlPolicies() {
  const notify = useNotify();
  const p = useAsync(() => api.listOrgPolicies("SERVICE_CONTROL_POLICY"), []);

  return (
    <ResourceTable
      resourceName="Service control policies (SCPs)"
      items={p.data || []}
      loading={p.loading}
      error={p.error}
      onRefresh={p.reload}
      trackBy="Id"
      selectionType="single"
      empty={{ title: "No resources to display" }}
      actions={<Button onClick={() => notify.success("Service control policies are managed in AWS Organizations; Vyomi mirrors them here read-only.")}>Edit in AWS Organizations</Button>}
      columns={[
        { id: "name", header: "Policy name", isRowHeader: true, cell: (x) => <Link href={`#/iam/service-control-policies/${encodeURIComponent(x.Name)}`} onFollow={follow}>{x.Name}</Link> },
        { id: "attached", header: "Attached to entities", cell: () => "0" },
      ]}
    />
  );
}
