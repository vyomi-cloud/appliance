/* Object details: metadata from objects.get, download via ?alt=media, delete, edit
 * metadata, and the real object holds / object retention from core/gcp_storage_core.py. */
import { useState } from "react";
import { Box, Breadcrumbs, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import DownloadIcon from "@mui/icons-material/esm/Download.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import * as api from "./api.js";

const TABS = [["live", "Live object"], ["versions", "Version history"]];

export default function ObjectDetail({ params, query }) {
  const notify = useNotify();
  const bucket = params.name;
  const name = query.name || "";
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "live";
  const [del, setDel] = useState(false);
  const [editMeta, setEditMeta] = useState(false);
  const { data: o, loading, error, reload } = useAsync(() => api.getObject(bucket, name), [bucket, name]);
  const bkt = useAsync(() => api.getBucket(bucket), [bucket]);
  const pol = useAsync(() => api.getIamPolicy(bucket).catch(() => null), [bucket]);
  const parts = name.split("/");
  const parent = parts.slice(0, -1).join("/");
  const back = hashHref("storage", "browser", bucket) + (parent ? `?prefix=${encodeURIComponent(parent + "/")}` : "");
  const objHref = (t) => { const qs = new URLSearchParams({ name, ...(t !== "live" ? { tab: t } : {}) }).toString(); return hashHref("storage", "browser", bucket, "object") + "?" + qs; };
  const patch = async (body, msg) => { try { await api.patchObject(bucket, name, body); notify.success(msg); reload(); } catch (e) { notify.error(e); } };
  return (
    <>
      <PageHeader title="Object details" back={<IconButton aria-label="Back" href={back}><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<DownloadIcon />} href={api.downloadUrl(bucket, name)} download={parts[parts.length - 1]} disabled={!o}>Download</Button>
          <Button startIcon={<EditIcon />} disabled={!o} onClick={() => setEditMeta(true)}>Edit metadata</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)} disabled={!o}>Delete</Button>
        </>} />
      <Breadcrumbs sx={{ mb: 2 }} aria-label="Object path">
        <Link href="#/storage/browser">Buckets</Link>
        <Link href={hashHref("storage", "browser", bucket)}>{bucket}</Link>
        {parts.slice(0, -1).map((p, i) => <Link key={i} href={hashHref("storage", "browser", bucket) + `?prefix=${encodeURIComponent(parts.slice(0, i + 1).join("/") + "/")}`}>{p}</Link>)}
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{parts[parts.length - 1]}</Typography>
      </Breadcrumbs>
      <ErrorAlert error={error} title="Failed to load object" />
      {loading && <CircularProgress size={24} />}
      <Tabs value={tab} onChange={(_, t) => { location.hash = objHref(t).slice(1); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Object tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "live" && o && (
        <LiveObject o={o} bucket={bucket} bucketMeta={bkt.data} policy={pol.data} onHoldChange={patch} />
      )}
      {tab === "versions" && <CapabilityContainer id="gcp.storage.versioning" title="Versions" />}
      {editMeta && o && <EditMetadataDialog o={o} onClose={() => setEditMeta(false)} onSave={(body) => patch(body, "Updated object metadata")} />}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete object?" confirmText="DELETE"
        onConfirm={async () => { await api.deleteObject(bucket, name); notify.success(`Deleted "${name}"`); location.hash = back.slice(1); }}>
        <Typography variant="body2"><b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function LiveObject({ o, bucket, bucketMeta, policy, onHoldChange }) {
  const ret = o.retention || {};
  const retentionEnabled = bucketMeta?.objectRetention?.mode === "Enabled";
  const custom = Object.entries(o.metadata || {});
  return (
    <Stack spacing={2}>
      <Section title="Overview">
        <KeyValue items={[
          ["Type", o.contentType], ["Size", fmtBytes(o.size)], ["Created", fmtDate(o.timeCreated)], ["Last modified", fmtDate(o.updated)],
          ["Storage class", api.classLabel(o.storageClass)], ["Custom time", o.customTime ? fmtDate(o.customTime) : "—"],
          ["Public URL", <Link key="u" href={api.downloadUrl(bucket, o.name)} target="_blank" rel="noreferrer">{api.downloadUrl(bucket, o.name)}</Link>],
          ["Authenticated URL", <Link key="a" href={api.downloadUrl(bucket, o.name)} target="_blank" rel="noreferrer">Download link (Vyomi wire)</Link>],
          ["gsutil URI", `gs://${bucket}/${o.name}`],
        ]} />
      </Section>
      <Section title="Permissions">
        <Typography variant="body2">Public access: {bucketMeta ? api.publicAccess(bucketMeta, policy) : "…"}</Typography>
      </Section>
      <CapabilityContainer id="gcp.storage.object-holds" title="Protection">
        <KeyValue items={[
          ["Hold status", [o.temporaryHold && "Temporary hold", o.eventBasedHold && "Event-based hold"].filter(Boolean).join(", ") || "None"],
          ["Version history", "Not enabled"],
          ["Retention expiration time", ret.retainUntilTime ? fmtDate(ret.retainUntilTime) : "None"],
          ["Encryption type", "Google-managed key"],
        ]} />
        <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: "wrap", rowGap: 1 }}>
          <Button size="small" variant="outlined" onClick={() => onHoldChange({ temporaryHold: !o.temporaryHold }, o.temporaryHold ? "Removed temporary hold" : "Added temporary hold")}>
            {o.temporaryHold ? "Remove temporary hold" : "Add temporary hold"}
          </Button>
          <Button size="small" variant="outlined" onClick={() => onHoldChange({ eventBasedHold: !o.eventBasedHold }, o.eventBasedHold ? "Removed event-based hold" : "Added event-based hold")}>
            {o.eventBasedHold ? "Remove event-based hold" : "Add event-based hold"}
          </Button>
          {retentionEnabled && !ret.retainUntilTime && (
            <Button size="small" variant="outlined" startIcon={<AddIcon />}
              onClick={() => onHoldChange({ retention: { mode: "Unlocked", retainUntilTime: new Date(Date.now() + 30 * 86400000).toISOString() } }, "Object retention set (30 days)")}>
              Set object retention (30 days)
            </Button>
          )}
        </Stack>
      </CapabilityContainer>
      <Section title="Metadata">
        <KeyValue items={[
          ["Content-Type", o.contentType || "—"], ["Cache-Control", o.cacheControl || "—"],
          ["Content-Encoding", o.contentEncoding || "—"], ["Content-Disposition", o.contentDisposition || "—"],
        ]} />
        <Box sx={{ mt: 1.5 }}>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Custom metadata</Typography>
          {custom.length ? <KeyValue items={custom} /> : <Typography variant="body2" color="text.secondary">No custom metadata.</Typography>}
        </Box>
      </Section>
    </Stack>
  );
}

function EditMetadataDialog({ o, onClose, onSave }) {
  const [rows, setRows] = useState(Object.entries(o.metadata || {}).map(([key, value]) => ({ key, value })));
  const [contentType, setContentType] = useState(o.contentType || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bad = rows.some((r) => !r.key);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const cur = Object.keys(o.metadata || {});
      const next = Object.fromEntries(rows.map((r) => [r.key, r.value]));
      const metadata = { ...Object.fromEntries(cur.filter((k) => !(k in next)).map((k) => [k, null])), ...next };
      await onSave({ contentType, metadata });
      onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Edit metadata">
      <DialogTitle>Edit metadata</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Content-Type" value={contentType} onChange={(e) => setContentType(e.target.value)} />
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Custom metadata</Typography>
          {rows.map((r, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField label={`Key ${i + 1}`} value={r.key} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
              <TextField label={`Value ${i + 1}`} value={r.value} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
              <IconButton aria-label={`Delete metadata ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
          <Box><Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { key: "", value: "" }])}>Add metadata</Button></Box>
          {error && <Typography color="error" variant="body2">{error.message}</Typography>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || bad} onClick={save}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
