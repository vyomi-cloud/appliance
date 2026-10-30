/* IP addresses — All / Internal / External tabs, as in the console's IP addresses page. */
import { useState } from "react";
import { Alert, Box, Button, IconButton, ListItemIcon, ListItemText, Menu, MenuItem, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import MenuBookIcon from "@mui/icons-material/esm/MenuBookOutlined.js";
import VisibilityOffIcon from "@mui/icons-material/esm/VisibilityOffOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const scopePath = (a) => (a._scope === "global" ? "global" : a._scope);

function RowMenu({ onRelease }) {
  const [anchor, setAnchor] = useState(null);
  return (
    <>
      <IconButton size="small" aria-label="Actions" onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => { setAnchor(null); onRelease(); }}>
          <ListItemIcon><DeleteIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Release static address</ListItemText>
        </MenuItem>
      </Menu>
    </>
  );
}

export default function IpAddresses() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("all");
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [infoHidden, setInfoHidden] = useState(false);
  const { data = [], loading, error, reload } = useAsync(api.listAllAddresses, [project]);

  const rows = data.filter((a) => tab === "all" || (tab === "internal" ? a.addressType === "INTERNAL" : a.addressType === "EXTERNAL"));

  const release = async (names) => {
    for (const n of names) { const a = data.find((x) => x.name === n); if (a) await api.deleteAddress(scopePath(a), n); }
    notify.success(names.length === 1 ? `Released "${names[0]}"` : `Released ${names.length} addresses`);
    setSel([]); reload();
  };

  return (
    <>
      <PageHeader title="IP addresses" actions={<>
        <Button startIcon={<AddIcon />} href="#/networking/addresses/add">Reserve external</Button>
        <Button startIcon={<AddIcon />} href="#/networking/addresses/add?type=internal">Reserve internal</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Release static address</Button>
        <Button startIcon={<VisibilityOffIcon />} onClick={() => setInfoHidden((v) => !v)}>Hide info panel</Button>
        <Button startIcon={<MenuBookIcon />} href="https://cloud.google.com/vpc/docs/ip-addresses" target="_blank" rel="noreferrer">Learn</Button>
      </>} />
      {!infoHidden && <Alert severity="info" sx={{ mb: 2 }}>Reserved static addresses keep their IP even when nothing is using them.</Alert>}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="all" label="All" />
        <Tab value="internal" label="Internal IP addresses" />
        <Tab value="external" label="External IP addresses" />
      </Tabs>
      <ResourceTable
        resourceName="IP addresses"
        items={rows}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (a) => a.name },
          { id: "address", header: "IP address", cell: (a) => a.address },
          { id: "access", header: "Access type", cell: (a) => (a.addressType === "INTERNAL" ? "Internal" : "External") },
          { id: "region", header: "Region", cell: (a) => (a._scope === "global" ? "—" : a._scope.replace("regions/", "")) },
          { id: "type", header: "Type", cell: () => "Static" },
          { id: "version", header: "Version", cell: (a) => (a.ipVersion === "IPV6" ? "IPv6" : "IPv4") },
          { id: "inuse", header: "In use by", cell: (a) => (a.users?.length ? a.users.join(", ") : "—") },
          { id: "source", header: "Source", cell: () => "Manual" },
          { id: "tier", header: "Network Tier", cell: (a) => (a.networkTier === "STANDARD" ? "Standard" : "Premium") },
          { id: "labels", header: "Labels", cell: () => "—" },
          { id: "actions", header: "Actions", cell: (a) => <RowMenu onRelease={() => release([a.name])} /> },
        ]}
        empty={
          <Box sx={{ textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>No rows to display</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/networking/addresses/add">Reserve a static address</Button>
          </Box>
        }
      />
      <DeleteDialog open={del} onClose={() => setDel(false)}
        title={sel.length === 1 ? "Release static address?" : `Release ${sel.length} static addresses?`}
        actionLabel="Release"
        confirmText={sel.length === 1 ? sel[0] : "RELEASE"}
        onConfirm={() => release(sel)}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Address <b>{sel[0]}</b> will be released.</> : <>{sel.join(", ")} will be released.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
