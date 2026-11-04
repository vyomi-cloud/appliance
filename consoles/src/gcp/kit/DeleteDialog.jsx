/* Delete confirmation with the console's type-to-confirm pattern. The action runs for
 * real; a backend error is shown in the dialog, never swallowed. */
import { useEffect, useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";

export default function DeleteDialog({ open, onClose, onConfirm, title, confirmText, children, warning, actionLabel = "Delete" }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { if (open) { setTyped(""); setError(null); } }, [open]);
  const go = async () => {
    setBusy(true); setError(null);
    try { await onConfirm(); onClose(); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="vyomi-delete-title">
      <DialogTitle id="vyomi-delete-title">{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          {children}
          {warning && <Alert severity="warning">{warning}</Alert>}
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
          {confirmText && (
            <>
              <Typography variant="body2">To confirm, type <b>{confirmText}</b></Typography>
              <TextField autoFocus fullWidth value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={confirmText}
                inputProps={{ "aria-label": "Confirm deletion" }} onKeyDown={(e) => { if (e.key === "Enter" && typed === confirmText) go(); }} />
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" color="error" disabled={busy || (confirmText && typed !== confirmText)} onClick={go}>{busy ? "Deleting…" : actionLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}
