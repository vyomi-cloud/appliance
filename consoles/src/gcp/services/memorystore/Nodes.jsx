/* Nodes — the instance's node list (native NodeInfo: id + zone); the primary/replica role
 * is inferred client-side from position, since the native API has no role field. */
import { Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Nodes({ params }) {
  const { location: loc, id } = params;
  const inst = useAsync(() => api.getInstance(loc, id), [loc, id]);
  const nodes = (inst.data?.nodes || []).map((n, idx) => ({ ...n, role: idx === 0 ? "Primary" : "Replica" }));

  return (
    <>
      <InstanceNav location={loc} id={id} active="nodes" />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>Nodes</Typography>
      <CapabilityContainer id="gcp.memorystore.nodes" title="Nodes">
        <ResourceTable
          resourceName="nodes"
          items={nodes}
          rowKey={(n) => n.id}
          loading={inst.loading}
          error={inst.error}
          onRetry={inst.reload}
          filterPlaceholder="Filter nodes"
          columns={[
            { id: "id", header: "Node ID", cell: (n) => n.id },
            { id: "zone", header: "Zone", cell: (n) => n.zone },
            { id: "role", header: "Role", cell: (n) => n.role },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No nodes to display.</Typography>}
        />
      </CapabilityContainer>
    </>
  );
}
