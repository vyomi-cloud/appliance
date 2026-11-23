/* Infrastructure Manager > Deployments / Previews, the way Google's console lays it out. Vyomi's "Export project as Terraform" sits on top as an extra. */
import { useState } from "react";
import { Button, Chip, Tab, Tabs } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DownloadIcon from "@mui/icons-material/esm/FileDownloadOutlined.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, fmtDate } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import { PlanDialog } from "./PlanView.jsx";

export default function Deployments({ query }) {
  const tab = query.tab === "previews" ? "previews" : "deployments";
  const project = useProject();
  return (
    <>
      <PageHeader title="Infrastructure Manager" actions={<>
        <Button startIcon={<AddIcon />} href="#/infra-manager/deployments/new">Create deployment</Button>
        <Button startIcon={<DownloadIcon />} href="#/infra-manager/export" data-testid="export-project">Export project as Terraform</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = hashHref("infra-manager") + (t === "previews" ? "?tab=previews" : ""); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Infrastructure Manager tabs">
        <Tab value="deployments" label="Deployments" />
        <Tab value="previews" label="Previews" />
      </Tabs>
      {tab === "deployments" ? <DeploymentsTable key={project} /> : <PreviewsTable key={project} />}
    </>
  );
}

const statusChip = (s) => <Chip size="small" label={s} color={api.STATE_COLOR[s] || "default"} variant={api.STATE_COLOR[s] ? "filled" : "outlined"} />;

function DeploymentsTable() {
  const { data = [], loading, error, reload } = useAsync(() => api.listDeployments(), []);
  return (
    <ResourceTable
      resourceName="deployments"
      items={data}
      rowKey={(d) => d.name}
      loading={loading}
      error={error}
      onRetry={reload}
      filterPlaceholder="Filter deployments"
      empty={<>No deployments yet. <Link to="#/infra-manager/deployments/new">Create a deployment</Link> from a Terraform configuration, or <Link to="#/infra-manager/export">export this project as Terraform</Link> first.</>}
      toolbar={<Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>}
      columns={[
        { id: "name", header: "Name", sortValue: (d) => api.idOf(d.name), cell: (d) => <Link to={`#/infra-manager/deployments/${api.regionOf(d.name)}/${api.idOf(d.name)}`}>{api.idOf(d.name)}</Link> },
        { id: "state", header: "Status", sortValue: (d) => d.state, cell: (d) => statusChip(d.state) },
        { id: "region", header: "Region", sortValue: (d) => api.regionOf(d.name), cell: (d) => api.regionOf(d.name) },
        { id: "revision", header: "Latest revision", cell: (d) => api.idOf(d.latestRevision) || "—" },
        { id: "sa", header: "Service account", cell: (d) => (d.serviceAccount || "").split("/").pop() },
        { id: "created", header: "Created", sortValue: (d) => d.createTime, cell: (d) => fmtDate(d.createTime) },
        { id: "updated", header: "Last modified", sortValue: (d) => d.updateTime, cell: (d) => fmtDate(d.updateTime) },
      ]}
    />
  );
}

function PreviewsTable() {
  const { data = [], loading, error, reload } = useAsync(() => api.listPreviews(), []);
  const notify = useNotify();
  const [open, setOpen] = useState(null), [del, setDel] = useState(null);
  return (
    <>
      <ResourceTable
        resourceName="previews"
        items={data}
        rowKey={(p) => p.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter previews"
        empty="No previews. Open a deployment and choose Preview, or create one from the deployment's Update page."
        toolbar={<Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>}
        columns={[
          { id: "name", header: "Name", sortValue: (p) => api.idOf(p.name), cell: (p) => <Link to="#" onClick={(e) => { e.preventDefault(); setOpen(p); }}>{api.idOf(p.name)}</Link> },
          { id: "state", header: "Status", cell: (p) => statusChip(p.state) },
          { id: "region", header: "Region", cell: (p) => api.regionOf(p.name) },
          { id: "dep", header: "Deployment", cell: (p) => (p.deployment ? api.idOf(p.deployment) : "—") },
          { id: "plan", header: "Plan", cell: (p) => (p.vyomiPlan ? `${p.vyomiPlan.summary.create} to create, ${p.vyomiPlan.summary.unchanged} unchanged${p.vyomiPlan.summary.unsupported ? `, ${p.vyomiPlan.summary.unsupported} unsupported` : ""}` : p.errorStatus?.message || "—") },
          { id: "created", header: "Created", sortValue: (p) => p.createTime, cell: (p) => fmtDate(p.createTime) },
          { id: "act", header: "", cell: (p) => <Button size="small" startIcon={<DeleteIcon />} onClick={() => setDel(p)}>Delete</Button> },
        ]}
      />
      <PlanDialog preview={open} onClose={() => setOpen(null)} />
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title={`Delete preview ${api.idOf(del?.name)}?`}
        onConfirm={async () => { await api.deletePreview(api.regionOf(del.name), api.idOf(del.name)); notify.success("Preview deleted"); reload(); }} />
    </>
  );
}
