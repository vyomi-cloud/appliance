/* Replicas — Lambda@Edge copies of a function. A replica record is derived directly
 * from the function it replicates (same Description/Runtime/LastModified); Vyomi has
 * no CloudFront distribution to deploy a replica to, so this list is real but always
 * reflects only functions a caller has explicitly marked replicated. See
 * core/capabilities/aws/lambda.json (lambda.replicas). */
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

export default function Replicas() {
  const t = useAsync(() => api.listReplicas(), []);
  return (
    <ResourceTable
      resourceName="Replicas"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy={(r) => `${r.FunctionName}:${r.Region}`}
      selectionType={undefined}
      filterPlaceholder="Search by attributes or search by keyword"
      empty={{ title: "There is no data to display." }}
      columns={[
        { id: "name", header: "Function name", isRowHeader: true, cell: (r) => r.FunctionName },
        { id: "desc", header: "Description", cell: (r) => r.Description || "-" },
        { id: "runtime", header: "Runtime", cell: (r) => r.Runtime },
        { id: "modified", header: "Last modified", cell: (r) => fmtDate(r.LastModified) },
      ]}
    />
  );
}
