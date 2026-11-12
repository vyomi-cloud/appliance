/* API Gateway > Gateways: every gateway of the project across regions. */
import { useState } from "react";
import { Button, Chip, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Gateways() {
  const project = useProject();
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listGateways(), [project]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const chosen = () => data.filter((g) => sel.includes(g.name));

  return (
    <>
      <PageHeader title="API Gateway" actions={<>
        <Button startIcon={<AddIcon />} href="#/apigateway/gateways/new">Create gateway</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable resourceName="gateways" items={data} rowKey={(g) => g.name} loading={loading} error={error} onRetry={reload}
        selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter gateways"
        columns={[
          { id: "name", header: "Gateway ID", sortValue: (g) => api.last(g.name), cell: (g) => <Link href={hashHref("apigateway", "gateways", api.regionOf(g.name), api.last(g.name))}>{api.last(g.name)}</Link> },
          { id: "state", header: "State", cell: (g) => <Chip size="small" color={g.state === "ACTIVE" ? "success" : "default"} label={g.state === "ACTIVE" ? "Active" : g.state} /> },
          { id: "region", header: "Location", sortValue: (g) => api.regionOf(g.name), cell: (g) => api.regionOf(g.name) },
          { id: "api", header: "API", cell: (g) => api.apiOfConfig(g.apiConfig) },
          { id: "config", header: "API config", cell: (g) => api.last(g.apiConfig) },
          { id: "host", header: "Default hostname", cell: (g) => g.defaultHostname },
        ]}
        empty={<Stack spacing={1.5} alignItems="center"><Typography variant="body2" color="text.secondary">There are no gateways in this project.</Typography>
          <Button variant="contained" startIcon={<AddIcon />} href="#/apigateway/gateways/new">Create gateway</Button></Stack>} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title={sel.length === 1 ? "Delete gateway?" : `Delete ${sel.length} gateways?`}
        confirmText={sel.length === 1 ? api.last((chosen()[0] || { name: "" }).name) : "DELETE"} warning="This can't be undone."
        onConfirm={async () => { for (const g of chosen()) await api.deleteGateway(api.regionOf(g.name), api.last(g.name)); notify.success(`Deleted ${sel.length} gateway${sel.length === 1 ? "" : "s"}`); setSel([]); reload(); }}>
        <Typography variant="body2">{chosen().map((g) => api.last(g.name)).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
