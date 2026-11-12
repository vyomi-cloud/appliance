/* Package/image details: the "Digests" table (versions), tags, delete — all native
 * packages.get / versions.list / versions.batchDelete / tags calls. */
import { useState } from "react";
import { Breadcrumbs, Button, CircularProgress, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function PackageDetail({ params }) {
  const { location, name, pkg } = params;
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const p = useAsync(() => api.getPackage(location, name, pkg), [project, location, name, pkg]);
  const versions = useAsync(async () => {
    if (!p.data) return [];
    const [vs, tags] = await Promise.all([api.listVersions(location, name, pkg), api.listTags(location, name, pkg)]);
    return vs.map((v) => ({ ...v, _tags: tags.filter((t) => t.version === v.name).map(api.tagIdOf) }));
  }, [project, location, name, pkg, p.data]);
  const repoHref = hashHref("artifacts", "repo", location, name);

  return (
    <>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ minHeight: 56, mb: 1 }}>
        <IconButton aria-label="Back to repository" href={repoHref}><ArrowBackIcon /></IconButton>
        <Typography variant="h1" component="h1" sx={{ flex: 1 }}>{p.data?.displayName || pkg}</Typography>
        <Button startIcon={<RefreshIcon />} onClick={() => { p.reload(); versions.reload(); }}>Refresh</Button>
      </Stack>
      <Breadcrumbs sx={{ mb: 2 }} aria-label="Package path">
        <Link href="#/artifacts">Repositories</Link>
        <Link href={repoHref}>{name}</Link>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{p.data?.displayName || pkg}</Typography>
      </Breadcrumbs>
      <ErrorAlert error={p.error} title="Failed to load package" />
      {!p.data && !p.error && <CircularProgress size={24} />}
      {p.data && (
        <>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
            <Typography variant="h3" component="h2" sx={{ flex: 1 }}>Digests</Typography>
            <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          </Stack>
          <ResourceTable
            resourceName="digests"
            items={versions.data || []}
            rowKey={api.versionIdOf}
            loading={versions.loading}
            error={versions.error}
            onRetry={versions.reload}
            selectable
            selected={sel}
            onSelectedChange={setSel}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", cell: (v) => api.versionIdOf(v) },
              { id: "tags", header: "Tags", cell: (v) => v._tags.join(", ") || "—" },
              { id: "created", header: "Created", sortField: "createTime", cell: (v) => fmtDate(v.createTime) },
              { id: "uploaded", header: "Uploaded", sortField: "createTime", cell: (v) => fmtDate(v.createTime) },
              { id: "updated", header: "Updated", sortField: "updateTime", cell: (v) => fmtDate(v.updateTime) },
              { id: "size", header: "Virtual size", sortValue: (v) => Number(v.sizeBytes || 0), cell: (v) => api.sizeHuman(v.sizeBytes) },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No digests for this package.</Typography>}
          />
        </>
      )}
      <DeleteDialog open={del} onClose={() => setDel(false)} title={`Delete ${sel.length} digest${sel.length === 1 ? "" : "s"}?`} confirmText="DELETE"
        onConfirm={async () => {
          await api.batchDeleteVersions(location, name, pkg, sel.map((v) => `${p.data.name}/versions/${v}`));
          notify.success(`Deleted ${sel.length} digest${sel.length === 1 ? "" : "s"}`); setSel([]); versions.reload();
        }}>
        <Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
