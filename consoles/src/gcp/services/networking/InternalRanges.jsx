/* Internal ranges — the Internal Range Allocator (networkconnectivity.googleapis.com),
 * plans/reserves CIDR blocks on a VPC network before subnets claim them. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel, InputLabel,
  MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function InternalRanges() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("auto");
  const [draft, setDraft] = useState({ name: "", network: "", prefixLength: "20", targetCidrRange: "10.0.0.0/8", ipCidrRange: "" });
  const { data: ranges = [], loading, error, reload } = useAsync(api.listInternalRanges, []);
  const { data: networks = [] } = useAsync(api.listNetworks, []);

  const create = async () => {
    const err = api.validName(draft.name, "Name") || (!draft.network && "Network is required.");
    if (err) { notify.error({ message: err }); return; }
    try {
      const body = { name: draft.name, network: draft.network };
      if (mode === "auto") { body.prefixLength = Number(draft.prefixLength); body.targetCidrRange = [draft.targetCidrRange]; }
      else body.ipCidrRange = draft.ipCidrRange;
      await api.insertInternalRange(body);
      notify.success(`Reserved internal range "${draft.name}"`);
      setOpen(false);
      setDraft({ name: "", network: "", prefixLength: "20", targetCidrRange: "10.0.0.0/8", ipCidrRange: "" });
      reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Internal ranges" />
      <CapabilityContainer id="gcp.networking.internal-ranges" title="Internal ranges"
        description="Reserve CIDR blocks on a VPC network ahead of time so subnets and other allocations never collide with them."
        actions={<>
          <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create internal range</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        </>}
      >
        <ResourceTable
          resourceName="internal ranges"
          items={ranges}
          rowKey={(r) => api.nameOf(r.name)}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", cell: (r) => api.nameOf(r.name) },
            { id: "range", header: "IP range", cell: (r) => r.ipCidrRange },
            { id: "network", header: "Network", cell: (r) => api.nameOf(r.network) },
            { id: "usage", header: "Usage", cell: (r) => r.usage },
            { id: "peering", header: "Peering type", cell: (r) => r.peering },
          ]}
        />
      </CapabilityContainer>

      <DeleteDialog open={del} onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete internal range?" : `Delete ${sel.length} internal ranges?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        onConfirm={async () => {
          for (const n of sel) await api.deleteInternalRange(n);
          notify.success(`Deleted ${sel.length} internal range(s)`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create internal range</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 1 }}>
            <TextField label="Name" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value.trim() })} />
            <FormControl required>
              <InputLabel id="ir-net">Network</InputLabel>
              <Select labelId="ir-net" label="Network" value={draft.network} onChange={(e) => setDraft({ ...draft, network: e.target.value })}>
                {networks.map((n) => <MenuItem key={n.name} value={n.name}>{n.name}</MenuItem>)}
              </Select>
            </FormControl>
            <RadioGroup row value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Allocation mode">
              <FormControlLabel value="auto" control={<Radio size="small" />} label="Allocate automatically" />
              <FormControlLabel value="custom" control={<Radio size="small" />} label="Custom range" />
            </RadioGroup>
            {mode === "auto" ? (
              <>
                <TextField label="Target range" value={draft.targetCidrRange} onChange={(e) => setDraft({ ...draft, targetCidrRange: e.target.value })} />
                <FormControl>
                  <InputLabel id="ir-prefix">Prefix length</InputLabel>
                  <Select labelId="ir-prefix" label="Prefix length" value={draft.prefixLength} onChange={(e) => setDraft({ ...draft, prefixLength: e.target.value })}>
                    {["16", "20", "24", "28"].map((p) => <MenuItem key={p} value={p}>/{p}</MenuItem>)}
                  </Select>
                </FormControl>
              </>
            ) : (
              <TextField label="IP range" required placeholder="10.10.0.0/20" value={draft.ipCidrRange} onChange={(e) => setDraft({ ...draft, ipCidrRange: e.target.value })} />
            )}
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
