/* Shared multi-select picker dialog (Create new user's "Add group"/"Add role",
 * New Group's "Owners"/"Members"). */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle } from "@fluentui/react-components";

export function PickerDialog({ open, onClose, title, options, onPick }) {
  const [sel, setSel] = useState(new Set());
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={title}>
        <DialogBody>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent>
            {options.length === 0 && <p>Nothing to select yet.</p>}
            {options.map((o) => (
              <div key={o.id}><Checkbox label={o.label} checked={sel.has(o.id)}
                onChange={(_, d) => setSel((s) => { const n = new Set(s); d.checked ? n.add(o.id) : n.delete(o.id); return n; })} /></div>
            ))}
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" onClick={() => { onPick(options.filter((o) => sel.has(o.id))); onClose(); }}>Add</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
