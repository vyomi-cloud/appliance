/* Repositories list — columns, actions and delete flow as in the console's Repositories page. */
import { useState } from "react";
import { Button, Chip, Stack, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Repositories() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listRepositories(), [project]);

  const labels = (r) => {
    const ls = Object.entries(r.labels || {});
    if (!ls.length) return "—";
    return <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}{ls.length > 2 && <Tooltip title={ls.slice(2).map(([k, v]) => `${k}: ${v}`).join(", ")}><Chip size="small" label={`+${ls.length - 2}`} /></Tooltip>}</Stack>;
  };

  return (
    <>
      <PageHeader title="Repositories" actions={<>
        <Button startIcon={<AddIcon />} href="#/artifacts/create-repo">Create repository</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="repositories"
        items={data}
        rowKey={(r) => r.id}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "id", cell: (r) => <Link href={hashHref("artifacts", "repo", r.location, r.id)}>{r.id}</Link> },
          { id: "format", header: "Format", sortValue: (r) => api.FORMAT_LABEL[r.format] || r.format, cell: (r) => api.FORMAT_LABEL[r.format] || r.format },
          { id: "mode", header: "Mode", sortValue: (r) => api.MODE_LABEL[r.mode] || r.mode, cell: (r) => api.MODE_LABEL[r.mode] || r.mode },
          { id: "type", header: "Type", sortValue: (r) => api.locationTypeLabel(r.location), cell: (r) => api.locationTypeLabel(r.location) },
          { id: "location", header: "Location", sortField: "location", cell: (r) => r.location },
          { id: "description", header: "Description", cell: (r) => r.description || "—" },
          { id: "labels", header: "Labels", cell: labels },
          { id: "encryption", header: "Encryption", sortValue: api.encryptionLabel, cell: api.encryptionLabel },
          { id: "created", header: "Created", sortField: "createTime", cell: (r) => fmtDate(r.createTime) },
          { id: "updated", header: "Updated", sortField: "updateTime", cell: (r) => fmtDate(r.updateTime) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no repositories in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/artifacts/create-repo">Create repository</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete repository?" : `Delete ${sel.length} repositories?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="All packages, versions and tags in the repository are deleted as well. This can't be undone."
        onConfirm={async () => {
          for (const id of sel) {
            const r = data.find((x) => x.id === id);
            if (r) await api.deleteRepository(r.location, r.id);
          }
          notify.success(sel.length === 1 ? "Deleted repository" : `Deleted ${sel.length} repositories`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
