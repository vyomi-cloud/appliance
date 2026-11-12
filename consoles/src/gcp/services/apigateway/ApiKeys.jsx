/* API Gateway > API keys: the project's API keys over the API Keys v2 API (what an apiKey security definition is checked against). */
import { useState } from "react";
import { Button, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import VisibilityIcon from "@mui/icons-material/esm/Visibility.js";
import VisibilityOffIcon from "@mui/icons-material/esm/VisibilityOff.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import { PageHeader, fmtDate } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function KeyValueCell({ id }) {
  const [val, setVal] = useState(null);
  const [err, setErr] = useState(null);
  const reveal = async () => { try { setVal(await api.getKeyString(id)); } catch (e) { setErr(e.message); } };
  if (err) return <Typography variant="caption" color="error">{err}</Typography>;
  if (val === null) return <Button size="small" startIcon={<VisibilityIcon />} aria-label={`Show key string of ${id}`} onClick={reveal}>Show key</Button>;
  return <Stack direction="row" alignItems="center" spacing={0.5}>
    <code data-testid={`keystring-${id}`}>{val}</code>
    <Tooltip title="Copy key string"><IconButton size="small" aria-label={`Copy key string of ${id}`} onClick={() => navigator.clipboard?.writeText(val).catch(() => {})}><ContentCopyIcon fontSize="small" /></IconButton></Tooltip>
    <Tooltip title="Hide"><IconButton size="small" aria-label={`Hide key string of ${id}`} onClick={() => setVal(null)}><VisibilityOffIcon fontSize="small" /></IconButton></Tooltip>
  </Stack>;
}

export default function ApiKeys() {
  const project = useProject();
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listKeys(), [project]);
  const [adding, setAdding] = useState(false);
  const [del, setDel] = useState(null);
  return (
    <>
      <PageHeader title="API keys" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setAdding(true)}>Create API key</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <ResourceTable resourceName="API keys" items={data} rowKey={(k) => k.name} loading={loading} error={error} onRetry={reload} filterPlaceholder="Filter API keys"
        columns={[
          { id: "id", header: "Key ID", sortValue: (k) => api.last(k.name), cell: (k) => api.last(k.name) },
          { id: "dn", header: "Name", cell: (k) => k.displayName },
          { id: "created", header: "Created", cell: (k) => fmtDate(k.createTime) },
          { id: "ks", header: "Key string", cell: (k) => <KeyValueCell id={api.last(k.name)} /> },
          { id: "act", header: "Actions", cell: (k) => <Button size="small" color="error" startIcon={<DeleteIcon />} aria-label={`Delete key ${api.last(k.name)}`} onClick={() => setDel(k)}>Delete</Button> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">There are no API keys in this project. Create one to call a gateway whose config requires an API key.</Typography>} />
      {adding && <FormDialog open title="Create API key" submitLabel="Create" onClose={(ok) => { setAdding(false); if (ok) reload(); }}
        fields={[{ key: "id", label: "Key ID (optional)", default: "", helper: "Lowercase letters, numbers and hyphens; generated when empty" },
          { key: "name", label: "Display name (optional)", default: "" }]}
        onSubmit={async (v) => {
          const id = v.id.trim();
          if (id && !api.KEY_ID.test(id)) throw new Error("Key ID must be 1-63 characters: lowercase letters, numbers and hyphens, starting with a letter.");
          await api.createKey(id, v.name.trim() ? { displayName: v.name.trim() } : {});
          notify.success(`Created API key${id ? ` "${id}"` : ""}`);
        }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete API key?" confirmText={del ? api.last(del.name) : ""} warning="Clients using this key are refused immediately."
        onConfirm={async () => { await api.deleteKey(api.last(del.name)); notify.success(`Deleted API key "${api.last(del.name)}"`); reload(); }}>
        <Typography variant="body2">Key <b>{del ? api.last(del.name) : ""}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
