/* Health checks — global resource, list + a Create dialog (no dedicated create page in
 * the spec). Only global health checks are modeled by the backend. */
import { useEffect, useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import OpenInNewIcon from "@mui/icons-material/esm/OpenInNew.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const DEFAULT_PORT = { TCP: 80, HTTP: 80, HTTPS: 443, SSL: 443, HTTP2: 80, GRPC: 80 };
const HAS_PATH = (p) => p === "HTTP" || p === "HTTPS" || p === "HTTP2";

function CreateDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [protocol, setProtocol] = useState("TCP");
  const [port, setPort] = useState(DEFAULT_PORT.TCP);
  const [path, setPath] = useState("/");
  const [host, setHost] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setName(""); setTouched(false); setError(null); setProtocol("TCP"); setPort(DEFAULT_PORT.TCP); setPath("/"); setHost("");
  }, [open]);

  const nameErr = touched ? api.validResourceName(name) : null;

  const changeProtocol = (p) => { setProtocol(p); setPort(DEFAULT_PORT[p]); };

  const submit = async () => {
    setTouched(true);
    if (api.validResourceName(name)) return;
    setBusy(true); setError(null);
    const detail = { port: Number(port), host: host || undefined, ...(HAS_PATH(protocol) ? { requestPath: path || undefined } : {}) };
    try {
      await api.insertHealthCheck({ name, type: protocol, [`${protocol.toLowerCase()}HealthCheck`]: detail });
      notify.success(`Created health check "${name}"`);
      onCreated();
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create health check</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <TextField label="Name" required autoFocus value={name} onChange={(e) => setName(e.target.value.trim())}
            onBlur={() => setTouched(true)} error={!!nameErr} helperText={nameErr || " "} inputProps={{ "aria-label": "Name" }} />
          <FormControl fullWidth>
            <InputLabel id="hc-proto-l">Protocol</InputLabel>
            <Select labelId="hc-proto-l" label="Protocol" value={protocol} onChange={(e) => changeProtocol(e.target.value)}>
              {api.HEALTH_CHECK_TYPES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Port" type="number" value={port} onChange={(e) => setPort(e.target.value)} sx={{ maxWidth: 160 }} />
          {HAS_PATH(protocol) && <TextField label="Path" value={path} onChange={(e) => setPath(e.target.value)} />}
          <TextField label="Host (optional)" value={host} onChange={(e) => setHost(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function HealthChecks() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listHealthChecks(), [project]);

  const byKey = (k) => data.find((h) => h.name === k);

  return (
    <>
      <PageHeader title="Health checks" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create health check</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<OpenInNewIcon />} href="https://cloud.google.com/load-balancing/docs/health-check-concepts" target="_blank" rel="noopener">Learn</Button>
      </>} />
      <ResourceTable
        resourceName="health checks"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        rowKey={(h) => h.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (h) => h.name },
          { id: "scope", header: "Scope", cell: (h) => h._display?.scope || "Global" },
          { id: "region", header: "Region", cell: () => "—" },
          { id: "host", header: "Host", cell: (h) => h._display?.host || "—" },
          { id: "path", header: "Path", cell: (h) => h._display?.path || "—" },
          { id: "protocol", header: "Protocol", sortField: "type", cell: (h) => h.type },
          { id: "port", header: "Port", cell: (h) => h._display?.port ?? "—" },
          { id: "inuse", header: "In use by", cell: () => "—" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No rows to display</Typography>}
      />
      <CreateDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete health check?" : `Delete ${sel.length} health checks?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.name : "DELETE"}
        warning="This can't be undone."
        onConfirm={async () => {
          for (const k of sel) {
            const h = byKey(k);
            if (h) await api.deleteHealthCheck(h.name);
          }
          notify.success(sel.length === 1 ? `Deleted health check "${byKey(sel[0])?.name}"` : `Deleted ${sel.length} health checks`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Health check <b>{byKey(sel[0])?.name}</b> will be permanently deleted.</> : <>{sel.length} health checks will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
