/* Firewall policies — VPC nav "Firewall" opens Network Security > Cloud NGFW >
 * Firewall policies, its own side nav page in the real console. */
import { useState } from "react";
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel, InputLabel,
  MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
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
  const [polOpen, setPolOpen] = useState(false);
  const [polSel, setPolSel] = useState([]);
  const [polDraft, setPolDraft] = useState({ name: "", region: api.REGIONS[0], network: "" });
  const { data = [], loading, error, reload } = useAsync(api.listFirewalls, [project]);
  const { data: policies = [], loading: polLoading, reload: polReload } = useAsync(api.listAllFirewallPolicies, [project]);
  const { data: networks = [] } = useAsync(api.listNetworks, [project]);

  const createPolicy = async () => {
    const err = api.validName(polDraft.name, "Name") || (!polDraft.network && "A network to associate is required.");
    if (err) { notify.error({ message: err }); return; }
    try {
      await api.insertFirewallPolicy(polDraft.region, { name: polDraft.name });
      await api.addPolicyAssociation(polDraft.region, polDraft.name, polDraft.network);
      notify.success(`Created firewall policy "${polDraft.name}"`);
      setPolOpen(false);
      setPolDraft({ name: "", region: api.REGIONS[0], network: "" });
      polReload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Firewall policies" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setPolOpen(true)}>Create firewall policy</Button>
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
        <CapabilityContainer id="gcp.networking.network-firewall-policies" title="Network firewall policies"
          description="Regional policies whose rules are evaluated before this network's VPC firewall rules."
          actions={<Button startIcon={<DeleteIcon />} disabled={!polSel.length} onClick={async () => {
            for (const k of polSel) { const [region, name] = k.split("|"); await api.deleteFirewallPolicy(region, name); }
            notify.success(`Deleted ${polSel.length} policy(ies)`); setPolSel([]); polReload();
          }}>Delete</Button>}
        >
          <ResourceTable
            resourceName="network firewall policies"
            items={policies}
            rowKey={(p) => `${p._region}|${p.name}`}
            loading={polLoading}
            selectable
            selected={polSel}
            onSelectedChange={setPolSel}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Policy name", cell: (p) => p.name },
              { id: "type", header: "Policy type", cell: (p) => `Regional (${p._region})` },
              { id: "rules", header: "Firewall rules", cell: (p) => p.ruleTupleCount },
              { id: "mirroring", header: "Mirroring rules", cell: () => 0 },
              { id: "description", header: "Description", cell: (p) => p.description || "—" },
              { id: "scope", header: "Deployment scope", cell: () => "Regional network" },
              { id: "associated", header: "Associated with", cell: (p) => (p.associations || []).map((a) => a.attachmentTarget).join(", ") || "—" },
            ]}
          />
        </CapabilityContainer>
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

      <Dialog open={polOpen} onClose={() => setPolOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create firewall policy</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <TextField label="Name" required value={polDraft.name} onChange={(e) => setPolDraft({ ...polDraft, name: e.target.value.trim() })} />
            <FormControl required>
              <InputLabel id="fp-region">Region</InputLabel>
              <Select labelId="fp-region" label="Region" value={polDraft.region} onChange={(e) => setPolDraft({ ...polDraft, region: e.target.value })}>
                {api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl required>
              <InputLabel id="fp-net">Associate with network</InputLabel>
              <Select labelId="fp-net" label="Associate with network" value={polDraft.network} onChange={(e) => setPolDraft({ ...polDraft, network: e.target.value })}>
                {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPolOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={createPolicy}>Create</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
