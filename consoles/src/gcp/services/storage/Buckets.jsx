/* Buckets list — columns, actions and delete flow as in the console's Buckets page. */
import { useState } from "react";
import { Box, Button, Chip, Stack, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, fmtDuration, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Buckets() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(async () => {
    const bs = await api.listBuckets();
    const pols = await Promise.all(bs.map((b) => api.getIamPolicy(b.name).catch(() => null)));
    return bs.map((b, i) => ({ ...b, _policy: pols[i] }));
  }, [project]);

  const labels = (b) => {
    const ls = Object.entries(b.labels || {});
    if (!ls.length) return "—";
    return <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}{ls.length > 2 && <Tooltip title={ls.slice(2).map(([k, v]) => `${k}: ${v}`).join(", ")}><Chip size="small" label={`+${ls.length - 2}`} /></Tooltip>}</Stack>;
  };

  return (
    <>
      <PageHeader title="Buckets" actions={<>
        <Button startIcon={<AddIcon />} href="#/storage/create-bucket">Create</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="buckets"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter buckets"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (b) => <Link href={hashHref("storage", "browser", b.name)}>{b.name}</Link> },
          { id: "created", header: "Created", sortField: "timeCreated", cell: (b) => fmtDate(b.timeCreated) },
          { id: "locationType", header: "Location type", sortField: "locationType", cell: (b) => api.LOCATION_TYPE_LABEL[b.locationType] || b.locationType },
          { id: "location", header: "Location", sortField: "location", cell: (b) => b.location.toLowerCase() },
          { id: "storageClass", header: "Default storage class", sortField: "storageClass", cell: (b) => api.classLabel(b.storageClass) },
          { id: "updated", header: "Last modified", sortField: "updated", cell: (b) => fmtDate(b.updated) },
          { id: "public", header: "Public access", cell: (b) => api.publicAccess(b, b._policy) },
          { id: "access", header: "Access control", sortValue: (b) => api.accessControl(b), cell: (b) => api.accessControl(b) },
          { id: "protection", header: "Protection", cell: (b) => api.protection(b) },
          { id: "hns", header: "Hierarchical namespace", cell: () => "Disabled" },
          { id: "bucketRetention", header: "Bucket retention", sortValue: (b) => Number(b.retentionPolicy?.retentionPeriod || 0), cell: (b) => b.retentionPolicy ? fmtDuration(b.retentionPolicy.retentionPeriod) : "Not set" },
          { id: "lifecycle", header: "Lifecycle rules", cell: (b) => api.lifecycleSummary(b) },
          { id: "tags", header: "Tags", cell: () => "—" },
          { id: "encryption", header: "Encryption", cell: () => "Google-managed key" },
          { id: "security", header: "Security insights", cell: () => "—" },
          { id: "labels", header: "Labels", cell: labels },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no buckets in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/storage/create-bucket">Create bucket</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? `Delete bucket?` : `Delete ${sel.length} buckets?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="All objects in the bucket are deleted as well. This can't be undone."
        onConfirm={async () => {
          for (const b of sel) {
            await api.deletePrefix(b, "");
            await api.deleteBucket(b);
          }
          notify.success(sel.length === 1 ? `Deleted bucket "${sel[0]}"` : `Deleted ${sel.length} buckets`);
          setSel([]);
          reload();
        }}
      >
        <Box><Typography variant="body2">{sel.length === 1 ? <>Bucket <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.join(", ")} will be permanently deleted.</>}</Typography></Box>
      </DeleteDialog>
    </>
  );
}
