/* Project metadata — custom key/value metadata + the ssh-keys item split into its own tab,
 * exactly like the real console (both are the same commonInstanceMetadata resource). */
import { useState } from "react";
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Paper, Stack, Tab, Table, TableBody,
  TableCell, TableHead, TableRow, Tabs, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Metadata() {
  const project = useProject();
  const notify = useNotify();
  const [tab, setTab] = useState("metadata");
  const [editOpen, setEditOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [sshRows, setSshRows] = useState([]);
  const [error, setError] = useState(null);
  const { data, loading, reload } = useAsync(() => api.getProjectResource(), [project]);
  const items = data?.commonInstanceMetadata?.items || [];
  const metaItems = items.filter((i) => i.key !== "ssh-keys");
  const sshKeyItem = items.find((i) => i.key === "ssh-keys");
  const sshLines = (sshKeyItem?.value || "").split("\n").filter(Boolean).map((l) => { const [user, ...rest] = l.split(":"); return { user, key: rest.join(":") }; });

  const openEdit = () => {
    setRows(metaItems.map((i) => ({ key: i.key, value: i.value })));
    setSshRows(sshLines);
    setError(null);
    setEditOpen(true);
  };
  const save = async () => {
    const items2 = [
      ...rows.filter((r) => r.key).map((r) => ({ key: r.key, value: r.value })),
      ...(sshRows.filter((r) => r.user && r.key).length ? [{ key: "ssh-keys", value: sshRows.filter((r) => r.user && r.key).map((r) => `${r.user}:${r.key}`).join("\n") }] : []),
    ];
    try { await api.setCommonInstanceMetadata(items2); notify.success("Metadata saved"); setEditOpen(false); reload(); }
    catch (e) { setError(e); }
  };

  return (
    <Box>
      <PageHeader title="Metadata" actions={<>
        <Button startIcon={<EditIcon />} onClick={openEdit}>Edit</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Metadata" value="metadata" />
        <Tab label="SSH keys" value="ssh" />
      </Tabs>
      {tab === "metadata" && (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead><TableRow><TableCell>Key</TableCell><TableCell>Value</TableCell></TableRow></TableHead>
            <TableBody>
              {metaItems.map((i) => <TableRow key={i.key}><TableCell>{i.key}</TableCell><TableCell sx={{ wordBreak: "break-word" }}>{i.value}</TableCell></TableRow>)}
              {!loading && !metaItems.length && <TableRow><TableCell colSpan={2}><Typography variant="body2" color="text.secondary">No custom metadata.</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Paper>
      )}
      {tab === "ssh" && (
        <Paper variant="outlined">
          <Table size="small">
            <TableHead><TableRow><TableCell>Key</TableCell><TableCell>Value</TableCell></TableRow></TableHead>
            <TableBody>
              {sshLines.map((r, i) => <TableRow key={i}><TableCell>{r.user}</TableCell><TableCell sx={{ wordBreak: "break-word" }}>{r.key}</TableCell></TableRow>)}
              {!loading && !sshLines.length && <TableRow><TableCell colSpan={2}><Typography variant="body2" color="text.secondary">No project-wide SSH keys.</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit metadata</DialogTitle>
        <DialogContent>
          <ErrorAlert error={error} title="Failed to save metadata" />
          <Typography variant="subtitle2" sx={{ mt: 1, mb: 1 }}>Custom metadata</Typography>
          <Stack spacing={1}>
            {rows.map((r, i) => (
              <Stack key={i} direction="row" spacing={1}>
                <TextField label="Key" value={r.key} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                <TextField label="Value" value={r.value} fullWidth onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                <IconButton aria-label={`Delete item ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            <Box><Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { key: "", value: "" }])}>Add item</Button></Box>
          </Stack>
          <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>SSH keys</Typography>
          <Stack spacing={1}>
            {sshRows.map((r, i) => (
              <Stack key={i} direction="row" spacing={1}>
                <TextField label="User" value={r.user} onChange={(e) => setSshRows(sshRows.map((x, j) => j === i ? { ...x, user: e.target.value } : x))} />
                <TextField label="Public key" value={r.key} fullWidth onChange={(e) => setSshRows(sshRows.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                <IconButton aria-label={`Delete SSH key ${i + 1}`} onClick={() => setSshRows(sshRows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
            <Box><Button startIcon={<AddIcon />} onClick={() => setSshRows([...sshRows, { user: "", key: "" }])}>Add SSH key</Button></Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={save}>Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
