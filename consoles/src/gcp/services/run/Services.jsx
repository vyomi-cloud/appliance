/* Services list — native Cloud Run Admin API v2, region-scoped like the real console's
 * region selector. */
import { useState } from "react";
import { Box, Button, FormControl, MenuItem, Select, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { NotSimulated, fmtDate, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Services() {
  const notify = useNotify();
  const project = useProject();
  const [region, setRegionState] = useState(api.getRegion());
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const setRegion = (r) => { api.setRegion(r); setRegionState(r); };
  const { data: rows = [], loading, error, reload } = useAsync(async () => {
    const svcs = await api.listServices(region);
    const policies = await Promise.all(svcs.map((s) => api.getIamPolicy(region, api.idOf(s.name)).catch(() => null)));
    return svcs.map((s, i) => ({ ...s, _id: api.idOf(s.name), _region: api.regionOf(s.name), _policy: policies[i] }));
  }, [project, region]);

  return (
    <>
      <PageHeader title="Services" actions={<>
        <FormControl size="small" sx={{ minWidth: 200, mr: 1 }}>
          <Select value={region} onChange={(e) => setRegion(e.target.value)} inputProps={{ "aria-label": "Region" }}>
            {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <Button startIcon={<CloudUploadIcon />} href="#/run/create?source=container">Deploy container</Button>
        <Button href="#/run/create?source=repo">Connect repo</Button>
        <Button startIcon={<AddIcon />} variant="contained" href="#/run/create?source=function">Write a function</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <Box sx={{ mb: 1.5 }}>
        <NotSimulated compact feature="Connect repo" note="Vyomi has no Cloud Build or source-repository integration — continuous deployment from a repository isn't backed by a Vyomi backend yet." />
      </Box>
      <ResourceTable
        resourceName="services"
        items={rows}
        rowKey={(s) => s._id}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter services"
        columns={[
          { id: "name", header: "Name", sortField: "_id", cell: (s) => <Link href={hashHref("run", "detail", s._region, s._id)}>{s._id}</Link> },
          { id: "type", header: "Deployment type", sortValue: api.deploymentType, cell: api.deploymentType },
          { id: "rps", header: "Req/sec", cell: () => "—" },
          { id: "region", header: "Region", sortField: "_region", cell: (s) => s._region },
          { id: "cost", header: "Cost", cell: () => "—" },
          { id: "auth", header: "Authentication", cell: (s) => api.authLabel(s._policy) },
          { id: "ingress", header: "Ingress", sortValue: api.ingressLabel, cell: api.ingressLabel },
          { id: "deployed", header: "Last deployed", sortField: "updateTime", cell: (s) => fmtDate(s.updateTime) },
          { id: "by", header: "Deployed by", sortField: "lastModifier", cell: (s) => s.lastModifier },
          { id: "recommendation", header: "Recommendation", cell: () => "—" },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center" sx={{ py: 2 }}>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>Run your app on a fully managed platform</Typography>
            <Typography variant="body2" color="text.secondary">Deploy container images or write a function and Vyomi runs it as a Cloud Run service.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/run/create">Create service</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete service?" : `Delete ${sel.length} services?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="All revisions are deleted as well. This can't be undone."
        onConfirm={async () => {
          for (const id of sel) {
            const s = rows.find((x) => x._id === id);
            await api.deleteService(s._region, s._id);
          }
          notify.success(sel.length === 1 ? "Deleted service" : `Deleted ${sel.length} services`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
