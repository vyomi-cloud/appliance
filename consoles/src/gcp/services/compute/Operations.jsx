/* Operations — every zonal + global mutation logged by the core, same as the real
 * console's combined Operations page (operations.aggregatedList under the hood). */
import { Box } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader, fmtDate } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Operations() {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(() => api.listOperations(), [project]);

  return (
    <Box>
      <PageHeader title="Operations" />
      <ResourceTable
        resourceName="operations"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter operations"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (o) => o.name },
          { id: "target", header: "Target", cell: (o) => api.last(o.targetLink) },
          { id: "status", header: "Status", sortField: "status", cell: (o) => o.status },
          { id: "start", header: "Start time", sortField: "startTime", cell: (o) => fmtDate(o.startTime) },
          { id: "end", header: "End time", sortField: "endTime", cell: (o) => fmtDate(o.endTime) },
          { id: "user", header: "User", cell: (o) => o.user },
        ]}
      />
    </Box>
  );
}
