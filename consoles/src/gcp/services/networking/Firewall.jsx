/* Firewall policies — VPC nav "Firewall" opens Network Security > Cloud NGFW >
 * Firewall policies, its own side nav page in the real console. */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Radio, RadioGroup, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import ArticleIcon from "@mui/icons-material/esm/ArticleOutlined.js";
import MenuBookIcon from "@mui/icons-material/esm/MenuBookOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Firewall() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [logsValue, setLogsValue] = useState("On");
  const { data = [], loading, error, reload } = useAsync(api.listFirewalls, [project]);

  return (
    <>
      <PageHeader title="Firewall policies" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => notify.info("Network firewall policies aren't modeled — see the Network firewall policies panel below.")}>Create firewall policy</Button>
        <Button startIcon={<AddIcon />} href="#/networking/firewall/add">Create firewall rule</Button>
        <Button startIcon={<MenuBookIcon />} href="https://cloud.google.com/firewall/docs" target="_blank" rel="noreferrer">Learn</Button>
      </>} />

      <CapabilityContainer id="gcp.networking.firewall.crud" title="VPC firewall rules"
        actions={<>
          <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
          <Button startIcon={<ArticleIcon />} disabled={!sel.length} onClick={() => setLogsOpen(true)}>Configure logs</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </>}
      >
        <ResourceTable
          resourceName="VPC firewall rules"
          items={data}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", sortField: "name", cell: (f) => f.name },
            { id: "type", header: "Type", cell: (f) => f.direction },
            { id: "targets", header: "Targets", cell: api.firewallTargets },
            { id: "filters", header: "Filters", cell: api.firewallFilters },
            { id: "ports", header: "Protocols / ports", cell: api.firewallProtoPorts },
            { id: "action", header: "Action", cell: api.firewallAction },
            { id: "priority", header: "Priority", cell: (f) => f.priority },
            { id: "network", header: "Network", cell: (f) => api.nameOf(f.network) },
            { id: "logs", header: "Logs", cell: (f) => (f.logConfig?.enable ? "On" : "Off") },
            { id: "hits", header: "Hit count", cell: () => "—" },
            { id: "lasthit", header: "Last hit", cell: () => "—" },
            { id: "insights", header: "Insights", cell: () => "—" },
          ]}
        />
      </CapabilityContainer>

      <Box sx={{ mt: 3 }}>
        <CapabilityContainer id="gcp.networking.network-firewall-policies" title="Network firewall policies" />
      </Box>

      <DeleteDialog open={del} onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete firewall rule?" : `Delete ${sel.length} firewall rules?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        onConfirm={async () => {
          for (const n of sel) await api.deleteFirewall(n);
          notify.success(sel.length === 1 ? `Deleted "${sel[0]}"` : `Deleted ${sel.length} firewall rules`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Firewall rule <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.join(", ")} will be permanently deleted.</>}</Typography>
      </DeleteDialog>

      <Dialog open={logsOpen} onClose={() => setLogsOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Configure logs</DialogTitle>
        <DialogContent>
          <RadioGroup value={logsValue} onChange={(e) => setLogsValue(e.target.value)} aria-label="Firewall rule logging">
            <FormControlLabel value="On" control={<Radio size="small" />} label="On" />
            <FormControlLabel value="Off" control={<Radio size="small" />} label="Off" />
          </RadioGroup>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLogsOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={async () => {
            for (const n of sel) await api.patchFirewall(n, { logConfig: { enable: logsValue === "On" } });
            notify.success(`Updated logging for ${sel.length} rule(s)`);
            setLogsOpen(false); setSel([]); reload();
          }}>Save</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
