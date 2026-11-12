/* A small modal form: fields = [{key, label, type?, options?, helper?, multiline?, default?}]. onSubmit(values) may throw. */
import { useState } from "react";
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, TextField } from "@mui/material";

export default function FormDialog({ open, title, fields, submitLabel = "Create", onClose, onSubmit }) {
  const init = () => Object.fromEntries(fields.map((f) => [f.key, f.default ?? (f.type === "bool" ? false : "")]));
  const [v, setV] = useState(init);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k, x) => setV((s) => ({ ...s, [k]: x }));
  const go = async () => {
    setBusy(true); setErr(null);
    try { await onSubmit(v); setV(init()); onClose(true); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={() => onClose(false)} fullWidth maxWidth="sm" aria-label={title}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {err && <Alert severity="error">{err.message}</Alert>}
          {fields.map((f) => f.type === "bool"
            ? <FormControlLabel key={f.key} control={<Checkbox checked={!!v[f.key]} onChange={(e) => set(f.key, e.target.checked)} />} label={f.label} />
            : <TextField key={f.key} size="small" label={f.label} value={v[f.key]} select={!!f.options} multiline={!!f.multiline} minRows={f.multiline ? 4 : undefined}
                helperText={f.helper} onChange={(e) => set(f.key, e.target.value)} inputProps={{ "aria-label": f.label }}>
                {(f.options || []).map((o) => (typeof o === "string" ? <MenuItem key={o} value={o}>{o}</MenuItem> : <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>))}
              </TextField>)}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => onClose(false)}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={go}>{submitLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}
