/* Serverless VPC Access connectors (vpcaccess.googleapis.com) — bridges serverless
 * products into a VPC network over a dedicated /28 range. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function ServerlessVpcAccess() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", region: api.REGIONS[0], network: "", ipCidrRange: "" });
  const { data: connectors = [], loading, error, reload } = useAsync(api.listAllConnectors, []);
  const { data: networks = [] } = useAsync(api.listNetworks, []);

  const create = async () => {
    const err = api.validName(draft.name, "Name") || (!draft.network && "Network is required.") || (!draft.ipCidrRange && "IP range is required.");
    if (err) { notify.error({ message: err }); return; }
    try {
      await api.insertConnector(draft.region, { name: draft.name, network: draft.network, ipCidrRange: draft.ipCidrRange });
      notify.success(`Created connector "${draft.name}"`);
      setOpen(false);
      setDraft({ name: "", region: api.REGIONS[0], network: "", ipCidrRange: "" });
      reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Serverless VPC access" />
      <CapabilityContainer id="gcp.networking.serverless-vpc-access" title="VPC connectors"
        description="A dedicated /28 range that bridges Vyomi's serverless-style products into this VPC network."
        actions={<>
          <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create connector</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </>}
      >
        <ResourceTable
          resourceName="connectors"
          items={connectors}
          rowKey={(c) => `${c._region}|${api.nameOf(c.name)}`}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", cell: (c) => api.nameOf(c.name) },
            { id: "region", header: "Region", cell: (c) => c._region },
            { id: "network", header: "Network", cell: (c) => api.nameOf(c.network) },
            { id: "range", header: "IP range", cell: (c) => c.ipCidrRange || "—" },
            { id: "throughput", header: "Throughput (Mbps)", cell: (c) => `${c.minThroughput}–${c.maxThroughput}` },
            { id: "state", header: "State", cell: (c) => c.state },
          ]}
        />
      </CapabilityContainer>

      <DeleteDialog open={del} onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete connector?" : `Delete ${sel.length} connectors?`}
        confirmText={sel.length === 1 ? sel[0].split("|")[1] : "DELETE"}
        onConfirm={async () => {
          for (const k of sel) { const [region, name] = k.split("|"); await api.deleteConnector(region, name); }
          notify.success(`Deleted ${sel.length} connector(s)`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.map((k) => k.split("|")[1]).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create connector</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <TextField label="Name" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value.trim() })} />
            <FormControl required>
              <InputLabel id="c-region">Region</InputLabel>
              <Select labelId="c-region" label="Region" value={draft.region} onChange={(e) => setDraft({ ...draft, region: e.target.value })}>
                {api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl required>
              <InputLabel id="c-net">Network</InputLabel>
              <Select labelId="c-net" label="Network" value={draft.network} onChange={(e) => setDraft({ ...draft, network: e.target.value })}>
                {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
              </Select>
            </FormControl>
            <TextField label="IP range" required placeholder="10.8.0.0/28 (must be a /28)" value={draft.ipCidrRange}
              onChange={(e) => setDraft({ ...draft, ipCidrRange: e.target.value })} />
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
