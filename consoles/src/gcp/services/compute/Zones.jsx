/* Zones — the Compute Engine catalog (real wire call), plus which of your instances sit in
 * each zone (real backend state, not static data). */
import { Box, Chip, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Zones() {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(async () => {
    const [zones, instances] = await Promise.all([api.listZones(), api.listInstancesAllZones()]);
    return zones.map((z) => ({ ...z, _instances: instances.filter((i) => i._zoneScope === z.name).map((i) => i.name) }));
  }, [project]);

  return (
    <Box>
      <PageHeader title="Zones" />
      <ResourceTable
        resourceName="zones"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter zones"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (z) => z.name },
          { id: "region", header: "Region", sortField: "region_name", cell: (z) => z.region_name },
          { id: "status", header: "Status", sortField: "status", cell: (z) => <Chip size="small" color="success" label={z.status} /> },
          { id: "cpu", header: "Available CPU platforms", cell: (z) => z.availableCpuPlatforms.join(", ") },
          {
            id: "instances", header: "Instances in use",
            cell: (z) => z._instances.length
              ? <Stack direction="row" spacing={0.5} flexWrap="wrap">{z._instances.map((n) => <Chip key={n} size="small" label={n} />)}</Stack>
              : <Typography variant="body2" color="text.secondary">None</Typography>,
          },
        ]}
      />
    </Box>
  );
}
