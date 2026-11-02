/* Manage traffic: percentage split across revisions + named revision tags (each tag gets its
 * own https://TAG---service URL that really routes to that revision). Shared by Cloud Run and
 * Functions service details; `patch(body, mask)` is the lens's native services.patch call. */
import { useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import AddIcon from "@mui/icons-material/esm/Add.js";

const LATEST = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST";
const REVISION = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION";
const TAG_RE = /^[a-z]([a-z0-9-]{0,45}[a-z0-9])?$/;

export const tagsFor = (service, rid) =>
  (service.trafficStatuses || []).filter((t) => t.tag && t.revision === rid).map((t) => t.tag);

export function TrafficDialog({ service, revisions, patch, onClose, onSaved }) {
  const latest = (service.latestReadyRevision || "").split("/").pop();
  const [rows, setRows] = useState(() => {
    const r = (service.traffic || service.trafficStatuses || []).map((t) => ({
      rev: t.type === LATEST ? "LATEST" : t.revision, percent: t.percent ?? 0, tag: t.tag || "",
    }));
    return r.length ? r : [{ rev: "LATEST", percent: 100, tag: "" }];
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const total = rows.reduce((a, r) => a + (Number(r.percent) || 0), 0);
  const tagErr = (r, i) => (r.tag && !TAG_RE.test(r.tag) ? "Lowercase letters, digits, hyphens" :
    r.tag && rows.findIndex((x) => x.tag === r.tag) !== i ? "Tag already used" : "");
  const used = new Set(rows.map((r) => r.rev));
  const choices = ["LATEST", ...revisions.map((r) => r.name.split("/").pop())];
  const upd = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const bad = total !== 100 || rows.some(tagErr);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const traffic = rows.map((r) => ({
        ...(r.rev === "LATEST" ? { type: LATEST } : { type: REVISION, revision: r.rev }),
        percent: Number(r.percent) || 0, ...(r.tag ? { tag: r.tag } : {}),
      }));
      await patch({ traffic }, "traffic");
      onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="md" fullWidth aria-label="Manage traffic">
      <DialogTitle>Manage traffic</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Split traffic across revisions. A revision tag gives a revision its own URL (TAG---service) that always serves that revision, even at 0%.
          </Typography>
          {rows.map((r, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="flex-start">
              <Select size="small" sx={{ minWidth: 260 }} value={r.rev} onChange={(e) => upd(i, "rev", e.target.value)} inputProps={{ "aria-label": `Revision ${i + 1}` }}>
                {choices.map((c) => <MenuItem key={c} value={c} disabled={c !== r.rev && used.has(c)}>{c === "LATEST" ? `Serve the latest revision (${latest})` : c}</MenuItem>)}
              </Select>
              <TextField size="small" type="number" label="Traffic %" sx={{ width: 110 }} value={r.percent}
                onChange={(e) => upd(i, "percent", e.target.value)} inputProps={{ min: 0, max: 100 }} />
              <TextField size="small" label="Tag" sx={{ width: 180 }} value={r.tag} onChange={(e) => upd(i, "tag", e.target.value.trim())}
                error={!!tagErr(r, i)} helperText={tagErr(r, i) || " "} />
              <IconButton aria-label={`Remove revision ${i + 1}`} disabled={rows.length === 1} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
          <div>
            <Button startIcon={<AddIcon />} size="small" disabled={used.size >= choices.length}
              onClick={() => setRows([...rows, { rev: choices.find((c) => !used.has(c)), percent: 0, tag: "" }])}>Add revision</Button>
          </div>
          <Typography variant="body2" color={total === 100 ? "text.secondary" : "error"}>Total: {total}% (must be 100%)</Typography>
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || bad} onClick={save}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
