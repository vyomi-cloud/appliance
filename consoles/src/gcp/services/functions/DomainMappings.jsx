/* Domain mappings — map a custom domain to a Cloud Run service, native v1 Knative-style
 * facade (`apis/domains.cloudrun.com/v1/...`; the Admin API v2 has no equivalent resource). */
import { useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem,
  Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function DomainMappings() {
  const notify = useNotify();
  const project = useProject();
  const region = api.getRegion();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const { data: rows = [], loading, error, reload } = useAsync(async () => {
    const dms = await api.listDomainMappings();
    return dms.map((d) => ({ ...d, _domain: api.dmDomain(d) }));
  }, [project]);
  const services = useAsync(async () => {
    const svcs = await api.listServices(region);
    return svcs.map((s) => ({ ...s, _id: api.idOf(s.name) }));
  }, [project, region]);

  return (
    <>
      <PageHeader title="Domain mappings" actions={<>
        <Button startIcon={<AddIcon />} variant="contained" onClick={() => setCreate(true)}>Add mapping</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="domain mappings"
        items={rows}
        rowKey={(d) => d._domain}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter domain mappings"
        columns={[
          { id: "domain", header: "Domain", sortField: "_domain", cell: (d) => d._domain },
          { id: "service", header: "Service", sortValue: api.dmRoute, cell: api.dmRoute },
          { id: "status", header: "Status", sortValue: api.dmStatus, cell: api.dmStatus },
          { id: "certificate", header: "Certificate", cell: api.dmCertificate },
          { id: "records", header: "DNS records", wrap: true, cell: api.dmRecordsText },
          { id: "created", header: "Created", cell: (d) => fmtDate(api.dmCreated(d)) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center" sx={{ py: 2 }}>
            <Typography variant="body2" color="text.secondary">Map a custom domain to one of your services.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Add mapping</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete domain mapping?" : `Delete ${sel.length} domain mappings?`}
        confirmText="DELETE"
        onConfirm={async () => {
          for (const d of sel) await api.deleteDomainMapping(d);
          notify.success(sel.length === 1 ? "Deleted domain mapping" : `Deleted ${sel.length} domain mappings`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
      {create && <CreateDialog services={services.data || []} onClose={() => setCreate(false)} onCreated={() => { notify.success("Domain mapping added"); reload(); }} />}
    </>
  );
}

function CreateDialog({ services, onClose, onCreated }) {
  const [domain, setDomain] = useState("");
  const [route, setRoute] = useState(services[0]?._id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createDomainMapping(domain, route, "AUTOMATIC"); onCreated(); onClose(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Add domain mapping">
      <DialogTitle>Add domain mapping</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Domain" required value={domain} onChange={(e) => setDomain(e.target.value.trim())} helperText="e.g. www.example.com" />
          <FormControl required><InputLabel id="rt-l">Service</InputLabel>
            <Select labelId="rt-l" label="Service" value={route} onChange={(e) => setRoute(e.target.value)}>
              {services.map((s) => <MenuItem key={s._id} value={s._id}>{s._id}</MenuItem>)}
            </Select>
          </FormControl>
          {!services.length && <Typography variant="body2" color="text.secondary">Create a service first, then map a domain to it.</Typography>}
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !domain || !route} onClick={submit}>{busy ? "Adding…" : "Add"}</Button>
      </DialogActions>
    </Dialog>
  );
}
