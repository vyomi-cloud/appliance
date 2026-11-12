/* Monitoring > Rapid Cache — Anywhere Cache instances across buckets (storage/v1 anywhereCaches). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function RapidCache() {
  const notify = useNotify();
  const [create, setCreate] = useState(false);
  const { data, loading, error, reload } = useAsync(async () => {
    const buckets = await api.listBuckets();
    return (await Promise.all(buckets.map((b) => api.listAnywhereCaches(b.name)))).flat();
  }, []);
  const act = async (c, action) => { try { await api.anywhereCacheAction(c.bucket, c.zone, action); notify.success(`${action} ${c.zone}`); reload(); } catch (e) { notify.error(e); } };
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2">Anywhere Cache</Typography>
        <CapabilityBadge id="gcp.storage.rapid-cache" />
        <span style={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create cache</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <ErrorAlert error={error} title="Failed to list caches" />
      <ResourceTable resourceName="caches" items={data || []} rowKey={(c) => c.id} loading={loading} dense filterPlaceholder="Filter caches"
        columns={[
          { id: "bucket", header: "Bucket", cell: (c) => c.bucket },
          { id: "zone", header: "Zone", cell: (c) => c.zone },
          { id: "state", header: "State", cell: (c) => c.state },
          { id: "ttl", header: "TTL", cell: (c) => c.ttl },
          { id: "policy", header: "Admission policy", cell: (c) => c.admissionPolicy },
          { id: "created", header: "Created", sortValue: (c) => c.createTime, cell: (c) => fmtDate(c.createTime) },
          { id: "actions", header: "Actions", cell: (c) => (
            <Stack direction="row" spacing={0.5}>
              {c.state === "running" && <Button size="small" onClick={() => act(c, "pause")}>Pause</Button>}
              {c.state === "paused" && <Button size="small" onClick={() => act(c, "resume")}>Resume</Button>}
              {c.state !== "disabled" && <Button size="small" color="error" onClick={() => act(c, "disable")}>Disable</Button>}
            </Stack>) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No Anywhere Caches. Create one to cache a bucket's hot objects close to compute.</Typography>} />
      {create && <CreateCache onClose={() => setCreate(false)} onDone={() => { setCreate(false); notify.success("Cache created"); reload(); }} />}
    </Stack>
  );
}

function CreateCache({ onClose, onDone }) {
  const buckets = useAsync(() => api.listBuckets(), []);
  const [bucket, setBucket] = useState("");
  const [zone, setZone] = useState("us-central1-a");
  const [ttl, setTtl] = useState("86400s");
  const [policy, setPolicy] = useState("admit-on-first-miss");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const save = async () => { setBusy(true); setErr(null); try { await api.createAnywhereCache(bucket, { zone, ttl, admissionPolicy: policy }); onDone(); } catch (e) { setErr(e); } finally { setBusy(false); } };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="ac-title">
      <DialogTitle id="ac-title">Create Anywhere Cache</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Select size="small" displayEmpty value={bucket} onChange={(e) => setBucket(e.target.value)} inputProps={{ "aria-label": "Bucket" }} renderValue={(v) => v || "Select bucket"}>
            {(buckets.data || []).map((b) => <MenuItem key={b.name} value={b.name}>{b.name}</MenuItem>)}
          </Select>
          <TextField label="Zone" value={zone} onChange={(e) => setZone(e.target.value)} inputProps={{ "aria-label": "Zone" }} />
          <TextField label="TTL" value={ttl} onChange={(e) => setTtl(e.target.value)} helperText="1 hour to 7 days, e.g. 86400s" inputProps={{ "aria-label": "TTL" }} />
          <Select size="small" value={policy} onChange={(e) => setPolicy(e.target.value)} inputProps={{ "aria-label": "Admission policy" }}>
            <MenuItem value="admit-on-first-miss">admit-on-first-miss</MenuItem>
            <MenuItem value="admit-on-second-miss">admit-on-second-miss</MenuItem>
          </Select>
          <ErrorAlert error={err} title="Failed to create cache" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !bucket} onClick={save}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
