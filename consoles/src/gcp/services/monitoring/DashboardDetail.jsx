/* A single dashboard — name, labels and raw layout, mirroring the console's dashboard page. */
import { useState } from "react";
import { Box, Button, IconButton } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function DashboardDetail({ params }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const { data: dash, loading, error } = useAsync(() => api.getDashboard(params.id), [params.id]);
  if (loading) return null;
  if (error || !dash) return <ErrorAlert error={error || { message: "Dashboard not found" }} title="Failed to load dashboard" />;
  const layoutKey = ["gridLayout", "mosaicLayout", "rowLayout", "columnLayout"].find((k) => dash[k]);
  return (
    <Box>
      <PageHeader title={dash.displayName} back={<IconButton aria-label="Back" href="#/monitoring/dashboards"><ArrowBackIcon /></IconButton>}
        actions={<Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>} />
      <Section title="Details">
        <KeyValue items={[
          ["Name", dash.name],
          ["Labels", Object.keys(dash.labels || {}).length ? Object.entries(dash.labels).map(([k, v]) => `${k}=${v}`).join(", ") : "—"],
          ["Layout", layoutKey ? `${layoutKey} (${(dash[layoutKey].tiles || []).length} tile(s))` : "—"],
          ["Etag", dash.etag],
        ]} />
      </Section>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete dashboard?" confirmText={dash.displayName}
        onConfirm={async () => { await api.deleteDashboard(params.id); notify.success(`Deleted dashboard "${dash.displayName}"`); location.hash = "/monitoring/dashboards"; }}>
        Dashboard <b>{dash.displayName}</b> will be permanently deleted.
      </DeleteDialog>
    </Box>
  );
}
