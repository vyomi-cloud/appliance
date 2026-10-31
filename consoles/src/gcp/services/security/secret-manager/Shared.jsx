/* Pieces shared between the Secrets list, Create secret and Secret details pages:
 * the key/value row editor (labels, annotations, version aliases) and the Edit secret
 * dialog (labels / annotations / rotation / expiration — everything secrets.patch covers). */
import { useState } from "react";
import {
  Alert, Box, Button, Checkbox, FormControlLabel, IconButton, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { Dialog, DialogActions, DialogContent, DialogTitle } from "@mui/material";
import * as api from "./api.js";

/** Editable key/value pairs — labels, annotations, version aliases all use this shape. */
export function KeyValueRows({ rows, setRows, addText, keyLabel = "Key", valueLabel = "Value", keyError }) {
  return (
    <Stack spacing={1}>
      {rows.map((r, i) => (
        <Stack key={i} direction="row" spacing={1} alignItems="center">
          <TextField size="small" label={`${keyLabel} ${i + 1}`} value={r.key}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
          <TextField size="small" label={`${valueLabel} ${i + 1}`} value={r.value}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
          <IconButton size="small" aria-label={`Delete ${keyLabel.toLowerCase()} ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Stack>
      ))}
      {keyError && <Typography variant="caption" color="error">{keyError}</Typography>}
      <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setRows([...rows, { key: "", value: "" }])}>{addText}</Button></Box>
    </Stack>
  );
}

export const toMap = (rows) => Object.fromEntries(rows.filter((r) => r.key).map((r) => [r.key, r.value]));
export const fromMap = (m) => Object.entries(m || {}).map(([key, value]) => ({ key, value: String(value) }));

/** "Edit secret": every secrets.patch-able field in one dialog, the native way the console
 * updates a secret after creation (labels, annotations, rotation, expiration). */
export function EditSecretDialog({ secret, onClose, onSaved, notify }) {
  const [labels, setLabels] = useState(fromMap(secret.labels));
  const [annotations, setAnnotations] = useState(fromMap(secret.annotations));
  const [rotation, setRotation] = useState(!!secret.rotation?.rotationPeriod);
  const [rotationDays, setRotationDays] = useState(String(Number(secret.rotation?.rotationPeriod?.replace("s", "") || 2592000) / 86400));
  const [expiration, setExpiration] = useState(!!secret.expireTime);
  const [expireAt, setExpireAt] = useState(secret.expireTime ? secret.expireTime.slice(0, 10) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const labelErr = labels.some((r) => r.key && !api.validLabelKey(r.key)) ? "Label keys must start with a lowercase letter and contain only lowercase letters, numbers, underscores and dashes." : null;

  const save = async () => {
    if (labelErr) return;
    setBusy(true); setError(null);
    try {
      const name = api.shortName(secret.name);
      const body = {
        labels: toMap(labels),
        annotations: toMap(annotations),
        rotation: rotation ? { rotationPeriod: `${Math.round(Number(rotationDays) * 86400)}s` } : {},
        expireTime: expiration && expireAt ? `${expireAt}T00:00:00.000000Z` : null,
      };
      await api.patchSecret(name, body, "labels,annotations,rotation,expireTime");
      notify.success(`Updated secret "${name}"`);
      onSaved?.();
      onClose();
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="edit-secret-title">
      <DialogTitle id="edit-secret-title">Edit secret</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ pt: 1 }}>
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Labels</Typography>
            <KeyValueRows rows={labels} setRows={setLabels} addText="Add label" keyError={labelErr} />
          </Box>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Annotations</Typography>
            <KeyValueRows rows={annotations} setRows={setAnnotations} addText="Add annotation" />
          </Box>
          <Box>
            <FormControlLabel control={<Checkbox size="small" checked={rotation} onChange={(e) => setRotation(e.target.checked)} />} label="Set rotation period" />
            {rotation && <Stack sx={{ ml: 4 }} spacing={0.5}>
              <TextField size="small" type="number" label="Rotation period (days)" value={rotationDays} onChange={(e) => setRotationDays(e.target.value)} sx={{ width: 220 }} />
              <Typography variant="caption" color="text.secondary">Requires at least one notification topic already configured on this secret.</Typography>
            </Stack>}
          </Box>
          <Box>
            <FormControlLabel control={<Checkbox size="small" checked={expiration} onChange={(e) => setExpiration(e.target.checked)} />} label="Set expiration date" />
            {expiration && <TextField size="small" type="date" label="Expiration date" value={expireAt} onChange={(e) => setExpireAt(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ ml: 4, width: 220 }} />}
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !!labelErr} onClick={save}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}

export const VERSION_STATE_LABEL = { ENABLED: "Enabled", DISABLED: "Disabled", DESTROYED: "Destroyed" };
