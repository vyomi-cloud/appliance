/* VPC networks — "Networks in current project" / "Subnets in current project" tabs,
 * as in the console's VPC networks page. */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MenuBookIcon from "@mui/icons-material/esm/MenuBookOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { NotSimulated, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function VpcNetworks() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("networks");
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [flowLogsOpen, setFlowLogsOpen] = useState(false);
  const { data, loading, error, reload } = useAsync(async () => {
    const [networks, subnets, firewalls] = await Promise.all([api.listNetworks(), api.listAllSubnets(), api.listFirewalls()]);
    return { networks, subnets, firewalls };
  }, [project]);
  const networks = data?.networks || [];
  const subnets = data?.subnets || [];
  const firewalls = data?.firewalls || [];

  return (
    <>
      <PageHeader title="VPC networks" actions={<>
        <Button startIcon={<AddIcon />} href="#/networking/networks/add">Create VPC network</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<MenuBookIcon />} href="https://cloud.google.com/vpc/docs" target="_blank" rel="noreferrer">Learn</Button>
      </>} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="networks" label="Networks in current project" />
        <Tab value="subnets" label="Subnets in current project" />
      </Tabs>

      {tab === "networks" && (
        <>
          <ResourceTable
            resourceName="VPC networks"
            items={networks}
            loading={loading}
            error={error}
            onRetry={reload}
            selectable
            selected={sel}
            onSelectedChange={setSel}
            filterPlaceholder="Filter"
            toolbar={<Button size="small" onClick={() => setFlowLogsOpen(true)}>Manage flow logs</Button>}
            columns={[
              { id: "name", header: "Name", sortField: "name", cell: (n) => <Link href={hashHref("networking", "networks", "details", n.name)}>{n.name}</Link> },
              { id: "subnets", header: "Subnets", cell: (n) => api.subnetsOf(subnets, n.name).length },
              { id: "mtu", header: "MTU", sortField: "mtu", cell: (n) => n.mtu },
              { id: "mode", header: "Mode", cell: (n) => (n.autoCreateSubnetworks ? "Auto" : "Custom") },
              { id: "ula", header: "IPv6 ULA range", cell: (n) => n.internalIpv6Range || "—" },
              { id: "gateways", header: "Gateways", cell: () => "—" },
              { id: "flowlogs", header: "Flow log configs", cell: (n) => { const c = api.subnetsOf(subnets, n.name).filter((s) => s.logConfig?.enable).length; return c || "—"; } },
              { id: "fwrules", header: "Firewall rules", cell: (n) => firewalls.filter((f) => f.network.endsWith(`/networks/${n.name}`)).length },
              { id: "dynrouting", header: "Global dynamic routing", cell: (n) => (n.routingConfig?.routingMode === "GLOBAL" ? "On" : "Off") },
              { id: "profile", header: "Network profile", cell: () => "Default" },
            ]}
            empty={
              <Box sx={{ textAlign: "center" }}>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>No rows to display</Typography>
                <Button variant="contained" startIcon={<AddIcon />} href="#/networking/networks/add">Create VPC network</Button>
              </Box>
            }
          />
          <Box sx={{ mt: 1 }}>
            <Button color="error" startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete VPC network</Button>
          </Box>
        </>
      )}

      {tab === "subnets" && (
        <ResourceTable
          resourceName="subnets"
          items={subnets}
          loading={loading}
          error={error}
          onRetry={reload}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", sortField: "name", cell: (s) => s.name },
            { id: "network", header: "Network", cell: (s) => api.nameOf(s.network) },
            { id: "region", header: "Region", cell: (s) => api.nameOf(s.region) },
            { id: "stack", header: "Stack type", cell: (s) => s.stackType },
            { id: "range", header: "Primary IPv4 range", cell: (s) => s.ipCidrRange },
            { id: "gateway", header: "Gateway", cell: (s) => s.gatewayAddress },
            { id: "pga", header: "Private Google Access", cell: (s) => (s.privateIpGoogleAccess ? "On" : "Off") },
            { id: "flowlogs", header: "Flow logs", cell: (s) => (s.logConfig?.enable ? "On" : "Off") },
          ]}
        />
      )}

      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete VPC network?" : `Delete ${sel.length} VPC networks?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="Deleting a network fails while it still has subnets, firewall rules or routes attached — remove those first."
        onConfirm={async () => {
          for (const n of sel) await api.deleteNetwork(n);
          notify.success(sel.length === 1 ? `Deleted network "${sel[0]}"` : `Deleted ${sel.length} networks`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Network <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.join(", ")} will be permanently deleted.</>}</Typography>
      </DeleteDialog>

      <Dialog open={flowLogsOpen} onClose={() => setFlowLogsOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Manage flow logs</DialogTitle>
        <DialogContent>
          <NotSimulated feature="Project-wide flow log management" note="Flow logs are configured per subnet (Create subnet / subnet details). A centralized log-router view across all subnets isn't modeled." />
        </DialogContent>
        <DialogActions><Button onClick={() => setFlowLogsOpen(false)}>Close</Button></DialogActions>
      </Dialog>
    </>
  );
}
