/* Kubernetes clusters list — columns, tabs and actions as in the console's Clusters page.
 * Overview tab is the real cluster grid; Observability / Cost optimization need Cloud
 * Monitoring data this simulator doesn't generate for GKE, so they're honest gaps. */
import { useState } from "react";
import { Box, Button, Chip, Stack, Tab, Tabs, Tooltip, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import LinkIcon from "@mui/icons-material/esm/Link.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import DeployDialog from "./DeployDialog.jsx";
import ConnectDialog from "./ConnectDialog.jsx";

const TABS = [["overview", "Overview"], ["observability", "Observability"], ["cost-optimization", "Cost optimization"]];

export default function Clusters() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("overview");
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [deploy, setDeploy] = useState(false);
  const [connect, setConnect] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listClusters(), [project]);

  const byKey = (k) => data.find((c) => `${c.location}/${c.name}` === k);
  const one = sel.length === 1 ? byKey(sel[0]) : null;

  return (
    <>
      <PageHeader title="Kubernetes clusters" actions={<>
        <Button startIcon={<AddIcon />} href={hashHref("kubernetes", "clusters", "create")}>Create</Button>
        <Button startIcon={<CloudUploadIcon />} onClick={() => setDeploy(true)}>Deploy</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<EditIcon />} disabled={!one} href={one ? hashHref("kubernetes", "clusters", one.location, one.name) : undefined}>Edit</Button>
        <Button startIcon={<LinkIcon />} disabled={!one} onClick={() => setConnect(true)}>Connect</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Clusters tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "overview" && (
        <ResourceTable
          resourceName="clusters"
          items={data}
          rowKey={(c) => `${c.location}/${c.name}`}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Enter property name or value"
          columns={[
            { id: "status", header: "Status", sortField: "status", cell: (c) => <Chip size="small" label={api.statusLabel(c.status)} color={c.status === "RUNNING" ? "success" : c.status === "ERROR" ? "error" : "default"} /> },
            { id: "name", header: "Name", sortField: "name", cell: (c) => <Link href={hashHref("kubernetes", "clusters", c.location, c.name)}>{c.name}</Link> },
            { id: "location", header: "Location", sortField: "location", cell: (c) => c.location },
            { id: "mode", header: "Mode", sortField: "mode", cell: (c) => c.mode },
            { id: "nodes", header: "Number of nodes", sortValue: (c) => c.nodes, cell: (c) => c.nodes },
            { id: "vcpus", header: "Total vCPUs", cell: (c) => c.vcpus },
            { id: "memory", header: "Total memory", cell: (c) => c.memory },
            { id: "notifications", header: "Notifications", cell: (c) => c.notifications },
            { id: "labels", header: "Labels", cell: (c) => {
              const ls = Object.entries(c.resourceLabels || {});
              if (!ls.length) return "—";
              return <Stack direction="row" spacing={0.5}>{ls.slice(0, 2).map(([k, v]) => <Chip key={k} size="small" label={`${k}: ${v}`} />)}{ls.length > 2 && <Tooltip title={ls.slice(2).map(([k, v]) => `${k}: ${v}`).join(", ")}><Chip size="small" label={`+${ls.length - 2}`} /></Tooltip>}</Stack>;
            } },
          ]}
          empty={
            <Stack spacing={1.5} alignItems="center">
              <Typography variant="body2" color="text.secondary">There are no clusters in this project.</Typography>
              <Button variant="contained" startIcon={<AddIcon />} href={hashHref("kubernetes", "clusters", "create")}>Create cluster</Button>
            </Stack>
          }
        />
      )}
      {tab === "observability" && <Box sx={{ pt: 1 }}><CapabilityContainer id="gcp.kubernetes.observability" title="Observability" /></Box>}
      {tab === "cost-optimization" && <Box sx={{ pt: 1 }}><CapabilityContainer id="gcp.kubernetes.observability" title="Cost optimization" /></Box>}
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete cluster?" : `Delete ${sel.length} clusters?`}
        confirmText={sel.length === 1 ? one?.name : "DELETE"}
        warning="Deleting a cluster deletes all its node pools. This can't be undone."
        onConfirm={async () => {
          for (const k of sel) { const c = byKey(k); await api.deleteCluster(c.location, c.name); }
          notify.success(sel.length === 1 ? `Deleted cluster "${sel[0].split("/")[1]}"` : `Deleted ${sel.length} clusters`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.map((k) => k.split("/")[1]).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
      <DeployDialog open={deploy} onClose={() => setDeploy(false)} />
      <ConnectDialog open={connect} onClose={() => setConnect(false)} cluster={one} />
    </>
  );
}
