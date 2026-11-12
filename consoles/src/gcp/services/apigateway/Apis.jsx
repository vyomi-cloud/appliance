/* API Gateway > APIs. */
import { useState } from "react";
import { Button, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, fmtDate } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Apis() {
  const project = useProject();
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listApis(), [project]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const chosen = () => data.filter((a) => sel.includes(a.name));
  return (
    <>
      <PageHeader title="APIs" actions={<>
        <Button startIcon={<AddIcon />} href="#/apigateway/apis/new">Create API</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable resourceName="APIs" items={data} rowKey={(a) => a.name} loading={loading} error={error} onRetry={reload}
        selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter APIs"
        columns={[
          { id: "name", header: "API ID", sortValue: (a) => api.last(a.name), cell: (a) => <Link href={hashHref("apigateway", "apis", api.last(a.name))}>{api.last(a.name)}</Link> },
          { id: "display", header: "Display name", cell: (a) => a.displayName },
          { id: "svc", header: "Managed service", cell: (a) => a.managedService },
          { id: "created", header: "Created", sortValue: (a) => a.createTime, cell: (a) => fmtDate(a.createTime) },
        ]}
        empty={<Stack spacing={1.5} alignItems="center"><Typography variant="body2" color="text.secondary">There are no APIs in this project.</Typography>
          <Button variant="contained" startIcon={<AddIcon />} href="#/apigateway/apis/new">Create API</Button></Stack>} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title={sel.length === 1 ? "Delete API?" : `Delete ${sel.length} APIs?`}
        confirmText={sel.length === 1 ? api.last((chosen()[0] || { name: "" }).name) : "DELETE"} warning="An API with API configs can't be deleted until its configs are."
        onConfirm={async () => { for (const a of chosen()) await api.deleteApi(api.last(a.name)); notify.success(`Deleted ${sel.length} API${sel.length === 1 ? "" : "s"}`); setSel([]); reload(); }}>
        <Typography variant="body2">{chosen().map((a) => api.last(a.name)).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
