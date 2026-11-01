/* Applications — groups real Workloads by their app label, across every cluster, over the
 * data plane bridge's /applications aggregate (core/gcp_gke_dataplane_core.py:list_applications). */
import { Button, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Applications() {
  const list = useAsync(() => api.overAllClusters(api.listApplications), []);
  const data = list.data || [];

  return (
    <>
      <PageHeader title="Applications" actions={<Button startIcon={<RefreshIcon />} onClick={list.reload}>Refresh</Button>} />
      <ErrorAlert error={list.error} title="Failed to load applications" />
      <ResourceTable
        resourceName="applications"
        items={data}
        rowKey={(a) => `${a._location}/${a._cluster}/${a.namespace}/${a.name}`}
        loading={list.loading}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (a) => a.name },
          { id: "ns", header: "Namespace", cell: (a) => a.namespace },
          { id: "workloads", header: "Workloads", sortValue: (a) => a.workloads, cell: (a) => a.workloads },
          { id: "pods", header: "Pods", sortValue: (a) => a.pods, cell: (a) => a.pods },
          { id: "cluster", header: "Cluster", cell: (a) => a._cluster },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No applications yet — deploy a workload with an "app" label.</Typography>}
      />
    </>
  );
}
