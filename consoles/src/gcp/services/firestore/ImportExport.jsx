/* Import/Export — exportDocuments / importDocuments recorded as completed operations, as
 * the real console's Import/Export page lists them. Export really writes a Cloud Storage
 * object (via Vyomi's own GCS simulator) and import really reads it back (see the
 * capability badge for the file-format caveat). */
import { useState } from "react";
import { Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function ImportExport({ params }) {
  const db = params.name;
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listOperations(db), [db]);
  const [dialog, setDialog] = useState(null); // "import" | "export" | null

  return (
    <>
      <PageHeader title="Import/Export" actions={<>
        <Button onClick={() => setDialog("import")}>Import</Button>
        <Button onClick={() => setDialog("export")}>Export</Button>
      </>} />
      <CapabilityContainer id="gcp.firestore.import-export" title="Operations">
        <ResourceTable
          resourceName="operations"
          items={data}
          rowKey={(o) => o.name}
          loading={loading}
          error={error}
          onRetry={reload}
          columns={[
            { id: "operation", header: "Operation", cell: (o) => o.metadata["@type"].includes("Export") ? "Export" : "Import" },
            { id: "status", header: "Status", cell: (o) => <Chip size="small" color="success" label={o.done ? "Completed" : "Running"} /> },
            { id: "start", header: "Start time", sortField: "metadata.startTime", cell: (o) => fmtDate(o.metadata.startTime) },
            { id: "collections", header: "Collection IDs", cell: (o) => (o.metadata.collectionIds || []).join(", ") || "All collections" },
            { id: "location", header: "Location", cell: (o) => o.metadata.outputUriPrefix || o.metadata.inputUriPrefix || "—" },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No import or export operations yet.</Typography>}
        />
      </CapabilityContainer>
      <TransferDialog open={!!dialog} kind={dialog} onClose={() => setDialog(null)} onRun={async (collectionIds, uri) => {
        if (dialog === "export") await api.exportDocuments(db, { collectionIds, outputUriPrefix: uri });
        else await api.importDocuments(db, { collectionIds, inputUriPrefix: uri });
        notify.success(`${dialog === "export" ? "Export" : "Import"} started`);
        reload();
      }} />
    </>
  );
}

function TransferDialog({ open, kind, onClose, onRun }) {
  const [collections, setCollections] = useState("");
  const [uri, setUri] = useState("gs://uic-bucket/firestore-export");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onRun(collections.split(",").map((s) => s.trim()).filter(Boolean), uri); onClose(); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="xfer-title">
      <DialogTitle id="xfer-title">{kind === "export" ? "Export documents" : "Import documents"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Collection IDs (optional)" value={collections} onChange={(e) => setCollections(e.target.value)} helperText="Comma-separated. Leave blank for all collections." />
          <TextField label={kind === "export" ? "Output URI prefix" : "Input URI prefix"} value={uri} onChange={(e) => setUri(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={go}>{busy ? "Starting…" : kind === "export" ? "Export" : "Import"}</Button>
      </DialogActions>
    </Dialog>
  );
}
