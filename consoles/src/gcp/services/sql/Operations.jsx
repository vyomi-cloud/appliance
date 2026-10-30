/* Operations — the instance's control-plane operation log. */
import { Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Operations({ params }) {
  const name = params.name;
  const { data = [], loading, error, reload } = useAsync(() => api.listOperations(name), [name]);

  return (
    <>
      <InstanceNav name={name} active="operations" />
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ flex: 1, fontSize: 20 }}>Operations</Typography>
      </Stack>
      <CapabilityContainer id="gcp.sql.operations" title="Operation log">
        <ResourceTable
          resourceName="operations"
          items={data}
          rowKey={(o) => o.name}
          loading={loading}
          error={error}
          onRetry={reload}
          filterPlaceholder="Filter operations"
          columns={[
            { id: "created", header: "Creation time", cell: () => "Just now" },
            { id: "completed", header: "Completion time", cell: () => "Just now" },
            { id: "type", header: "Type", cell: (o) => o.operationType },
            { id: "status", header: "Status", cell: (o) => o.status },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No operations recorded for this instance yet.</Typography>}
        />
      </CapabilityContainer>
    </>
  );
}
