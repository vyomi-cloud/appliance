/* Network Intelligence Center > Connectivity Tests — list, as in the real console. Answered
 * by the native networkmanagement v1 API (core/gcp_compute_core.py's connectivityTests,
 * computed by the shared netsim evaluator — same engine firewall/route pages use). */
import { useState } from "react";
import { Box, Button, Chip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const resultChip = (t) => {
  const r = api.ctResult(t);
  if (!r) return "—";
  return <Chip size="small" color={r === "REACHABLE" ? "success" : "error"} label={r === "REACHABLE" ? "Reachable" : "Unreachable"} />;
};

export default function ConnectivityTests() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listConnectivityTests(), [project]);

  return (
    <>
      <PageHeader title="Connectivity Tests" actions={<>
        <Button startIcon={<AddIcon />} href="#/networking/connectivity-tests/add">Create Connectivity Test</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <ResourceTable
        resourceName="connectivity tests"
        items={data}
        rowKey={api.ctId}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (t) => <Link href={hashHref("networking", "connectivity-tests", "details", api.ctId(t))}>{api.ctId(t)}</Link> },
          { id: "protocol", header: "Protocol", cell: (t) => t.protocol },
          { id: "source", header: "Source", cell: (t) => api.endpointLabel(t.source) },
          { id: "destination", header: "Destination", cell: (t) => api.endpointLabel(t.destination) },
          { id: "result", header: "Result", cell: resultChip },
          { id: "lastrun", header: "Last run", cell: (t) => t.updateTime || "—" },
        ]}
        empty={
          <Box sx={{ textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>No rows to display</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/networking/connectivity-tests/add">Create Connectivity Test</Button>
          </Box>
        }
      />
      <Box sx={{ mt: 1 }}>
        <Button color="error" startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </Box>

      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete connectivity test?" : `Delete ${sel.length} connectivity tests?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        onConfirm={async () => {
          for (const n of sel) await api.deleteConnectivityTest(n);
          notify.success(sel.length === 1 ? `Deleted connectivity test "${sel[0]}"` : `Deleted ${sel.length} connectivity tests`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Connectivity test <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.join(", ")} will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
