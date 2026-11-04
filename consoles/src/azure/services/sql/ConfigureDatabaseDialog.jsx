/* "Compute + storage" → "Configure database" modal, used from the create wizard (applies to
 * local wizard state only — the database doesn't exist yet). The standalone Compute + storage
 * settings panel (SqlDatabaseBlade.jsx) renders ComputeStorageFields directly instead, with a
 * real ARM PATCH behind Apply. */
import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle } from "@fluentui/react-components";
import ComputeStorageFields, { DEFAULT_COMPUTE_STORAGE } from "./ComputeStorageFields.jsx";

export { DEFAULT_COMPUTE_STORAGE };

export default function ConfigureDatabaseDialog({ open, initial, onClose, onApply }) {
  const [f, setF] = useState(initial);
  useEffect(() => { if (open) setF(initial); }, [open, initial]);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));

  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Configure" style={{ maxWidth: 640 }}>
        <DialogBody>
          <DialogTitle>Configure</DialogTitle>
          <DialogContent><ComputeStorageFields f={f} set={set} /></DialogContent>
          <DialogActions>
            <Button appearance="primary" onClick={() => { onApply(f); onClose(); }}>Apply</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
