/* Backups — project-wide view, aggregated client-side the way the native console does
 * (the Admin API has no project-wide backups.list; each instance's backupRuns are listed
 * and merged). */
import { Button, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link } from "../../link.jsx";
import { instanceHref } from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Backups() {
  const { data = [], loading, error, reload } = useAsync(async () => {
    const instances = await api.listInstances();
    const lists = await Promise.all(instances.map((i) => api.listBackups(i.name).catch(() => [])));
    return lists.flat();
  }, []);

  return (
    <>
      <PageHeader title="Backups" actions={<Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>} />
      <CapabilityContainer id="gcp.sql.backups" title="Backup runs">
        <ResourceTable
          resourceName="backups"
          items={data}
          rowKey={(b) => `${b.instance}/${b.id}`}
          loading={loading}
          error={error}
          onRetry={reload}
          filterPlaceholder="Filter backups"
          columns={[
            { id: "instance", header: "Instance", sortField: "instance", cell: (b) => <Link href={instanceHref(b.instance, "backups")}>{b.instance}</Link> },
            { id: "created", header: "Created", cell: (b) => b.enqueuedTime ? fmtDate(b.enqueuedTime) : "Just now" },
            { id: "type", header: "Type", cell: (b) => b.type === "ON_DEMAND" ? "On-demand" : "Automated" },
            { id: "description", header: "Description", cell: (b) => b.description || "—" },
            { id: "location", header: "Location", cell: (b) => b.location },
            { id: "status", header: "Status", cell: (b) => b.status },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No backups across any Cloud SQL instance in this project.</Typography>}
        />
      </CapabilityContainer>
    </>
  );
}
