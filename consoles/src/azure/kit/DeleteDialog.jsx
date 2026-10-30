/* Delete confirmation: the portal's type-to-confirm dialog (name for one resource,
 * "delete" for several). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, MessageBar, MessageBarBody } from "@fluentui/react-components";

export default function DeleteDialog({ open, onClose, onConfirm, resourceType, names = [], confirmText, warning, children }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const need = confirmText ?? (names.length === 1 ? names[0] : "delete");
  const close = () => { setTyped(""); setError(null); onClose(); };
  const go = async () => {
    setBusy(true); setError(null);
    try { await onConfirm(); setTyped(""); onClose(); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && close()}>
      <DialogSurface aria-label={`Delete ${resourceType}`}>
        <DialogBody>
          <DialogTitle>Delete {names.length > 1 ? `${names.length} ${resourceType}s` : resourceType}</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <MessageBar intent="warning"><MessageBarBody>
                {warning || <>Deleting {names.length === 1 ? <b>{names[0]}</b> : <b>{names.length} {resourceType}s</b>} permanently removes it and all of its data. This action can't be undone.</>}
              </MessageBarBody></MessageBar>
              {names.length > 1 && <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>{names.map((n) => <li key={n}>{n}</li>)}</ul>}
              {children}
              {error && <MessageBar intent="error"><MessageBarBody>{error.code ? `${error.code}: ` : ""}{error.message}</MessageBarBody></MessageBar>}
              <Field label={<span>Type <b>{need}</b> to confirm</span>} required>
                <Input value={typed} placeholder={need} onChange={(_, d) => setTyped(d.value)} aria-label="Confirm deletion" />
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" style={typed === need ? { background: "var(--colorPaletteRedBackground3)" } : undefined} disabled={typed !== need || busy} onClick={go}>
              {busy ? "Deleting..." : "Delete"}
            </Button>
            <Button onClick={close}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
