/* Packet mirroring — clones matching traffic on mirrored subnets/instances to a
 * collector. Vyomi enforces the config (mirrored resources, filter) for real; actual
 * packet duplication needs the offline netsim enforcer (real per-packet counters), see
 * core/gcp_compute_core.py:mirrored_packet_log_entries. */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function PacketMirroring() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", region: api.REGIONS[0], network: "", subnet: "", collector: "" });
  const { data: policies = [], loading, error, reload } = useAsync(api.listAllPacketMirrorings, []);
  const { data: networks = [] } = useAsync(api.listNetworks, []);
  const { data: subnets = [] } = useAsync(api.listAllSubnets, []);
  const { data: mirrored = [], loading: mirroredLoading } = useAsync(api.listMirroredPacketLogEntries, []);

  const create = async () => {
    const err = api.validName(draft.name, "Name") || (!draft.network && "Network is required.")
      || (!draft.subnet && "A mirrored subnetwork is required.") || (!draft.collector && "A collector forwarding rule name is required.");
    if (err) { notify.error({ message: err }); return; }
    try {
      await api.insertPacketMirroring(draft.region, {
        name: draft.name, network: { name: draft.network }, mirroredResources: { subnetworks: [{ name: draft.subnet }] },
        collectorIlb: { name: draft.collector },
      });
      notify.success(`Created packet mirroring policy "${draft.name}"`);
      setOpen(false);
      setDraft({ name: "", region: api.REGIONS[0], network: "", subnet: "", collector: "" });
      reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Packet mirroring" />
      <CapabilityContainer id="gcp.networking.packet-mirroring" title="Packet mirroring policies"
        description="Mirrors matching traffic on the selected subnetworks to a collector."
        actions={<>
          <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create policy</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </>}
      >
        <ResourceTable
          resourceName="packet mirroring policies"
          items={policies}
          rowKey={(p) => `${p._region}|${p.name}`}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", cell: (p) => p.name },
            { id: "region", header: "Region", cell: (p) => p._region },
            { id: "network", header: "Network", cell: (p) => api.nameOf(p.network?.url) },
            { id: "mirrored", header: "Mirrored resources", cell: (p) => (p.mirroredResources?.subnetworks || []).map((s) => api.nameOf(s.url || s.name)).join(", ") || "—" },
            { id: "collector", header: "Collector", cell: (p) => api.nameOf(p.collectorIlb?.url) },
            { id: "enable", header: "Enabled", cell: (p) => (p.enable === "TRUE" ? "On" : "Off") },
          ]}
        />
      </CapabilityContainer>

      <Box sx={{ mt: 2 }}>
        <Section title="Mirrored packet records" description="Real events from traffic that crossed the appliance's network enforcer and matched an enabled policy's filter.">
          <ResourceTable
            resourceName="mirrored records"
            items={mirrored}
            rowKey={(e) => e.insertId}
            loading={mirroredLoading}
            filterPlaceholder="Filter"
            empty={<Typography variant="body2" color="text.secondary">No mirrored packets yet — they appear once real traffic crosses the appliance's network enforcer.</Typography>}
            columns={[
              { id: "time", header: "Timestamp", cell: (e) => e.timestamp },
              { id: "policy", header: "Policy", cell: (e) => e.jsonPayload?.mirroringPolicy },
              { id: "src", header: "Source", cell: (e) => e.jsonPayload?.connection?.src_ip },
              { id: "dst", header: "Destination", cell: (e) => e.jsonPayload?.connection?.dest_ip },
            ]}
          />
        </Section>
      </Box>

      <DeleteDialog open={del} onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete packet mirroring policy?" : `Delete ${sel.length} policies?`}
        confirmText={sel.length === 1 ? sel[0].split("|")[1] : "DELETE"}
        onConfirm={async () => {
          for (const k of sel) { const [region, name] = k.split("|"); await api.deletePacketMirroring(region, name); }
          notify.success(`Deleted ${sel.length} policy(ies)`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.map((k) => k.split("|")[1]).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create packet mirroring policy</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <TextField label="Name" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value.trim() })} />
            <FormControl required>
              <InputLabel id="pm-region">Region</InputLabel>
              <Select labelId="pm-region" label="Region" value={draft.region} onChange={(e) => setDraft({ ...draft, region: e.target.value })}>
                {api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl required>
              <InputLabel id="pm-net">Network</InputLabel>
              <Select labelId="pm-net" label="Network" value={draft.network} onChange={(e) => setDraft({ ...draft, network: e.target.value })}>
                {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl required>
              <InputLabel id="pm-sub">Mirrored subnetwork</InputLabel>
              <Select labelId="pm-sub" label="Mirrored subnetwork" value={draft.subnet} onChange={(e) => setDraft({ ...draft, subnet: e.target.value })}>
                {api.subnetsOf(subnets, draft.network).map((s) => <MenuItem key={s.name} value={s.name}>{s.name}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField label="Collector forwarding rule name" required value={draft.collector} onChange={(e) => setDraft({ ...draft, collector: e.target.value.trim() })} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={create}>Create</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
