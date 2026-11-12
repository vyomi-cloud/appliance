/* Cloud Deploy: delivery pipelines + targets lists, with create dialogs. */
import { useState } from "react";
import { Button, Chip, Stack, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Pipelines({ query }) {
  const tab = query.tab === "targets" ? "targets" : "pipelines";
  const project = useProject();
  const pl = useAsync(api.listPipelines, [project]);
  const tg = useAsync(api.listTargets, [project]);
  const notify = useNotify();
  const [dlg, setDlg] = useState(null);
  const reload = () => { pl.reload(); tg.reload(); };

  const createTarget = async (v) => {
    const body = { requireApproval: v.requireApproval, description: v.description };
    if (v.type === "Cloud Run") body.run = { location: `projects/${project}/locations/${v.location}` };
    else body.gke = { cluster: v.cluster };
    await api.createTarget(api.DEFAULT_REGION, v.id, body);
    notify.success(`Created target ${v.id}`);
  };
  const createPipeline = async (v) => {
    const ids = v.stages.split(",").map((s) => s.trim()).filter(Boolean);
    const strategy = v.strategy === "Canary" ? { canary: { canaryDeployment: { percentages: v.percentages.split(",").map((x) => parseInt(x, 10)).filter((x) => !isNaN(x)), verify: v.verify } } } : { standard: { verify: v.verify } };
    await api.createPipeline(api.DEFAULT_REGION, v.id, { description: v.description, serialPipeline: { stages: ids.map((targetId) => ({ targetId, strategy })) },
      deployParameters: Object.fromEntries([["service", v.service], ["deployment", v.deployment], ["namespace", v.namespace]].filter(([, x]) => x)) });
    notify.success(`Created delivery pipeline ${v.id}`);
  };

  return (
    <>
      <PageHeader title="Delivery pipelines" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setDlg("pipeline")}>Create pipeline</Button>
        <Button startIcon={<AddIcon />} onClick={() => setDlg("target")}>Create target</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = hashHref("clouddeploy") + (t === "targets" ? "?tab=targets" : ""); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }}>
        <Tab value="pipelines" label="Delivery pipelines" />
        <Tab value="targets" label="Targets" />
      </Tabs>
      {tab === "pipelines" ? (
        <CapabilityContainer id="gcp.clouddeploy.pipelines_targets" title="Delivery pipelines">
          <ResourceTable resourceName="delivery pipelines" items={pl.data || []} loading={pl.loading} error={pl.error} onRetry={pl.reload} rowKey={(p) => p.name}
            filterPlaceholder="Filter pipelines"
            columns={[
              { id: "name", header: "Name", sortValue: (p) => api.tail(p.name), cell: (p) => <Link href={hashHref("clouddeploy", "pipelines", api.regionOf(p.name), api.tail(p.name))}>{api.tail(p.name)}</Link> },
              { id: "region", header: "Region", cell: (p) => api.regionOf(p.name) },
              { id: "stages", header: "Targets (stages)", cell: (p) => (p.serialPipeline?.stages || []).map((s) => s.targetId).join(" → ") },
              { id: "ready", header: "Status", cell: (p) => p.condition?.pipelineReadyCondition?.status ? <Chip size="small" color="success" label="Ready" /> : <Chip size="small" color="warning" label="Missing targets" /> },
              { id: "created", header: "Created", cell: (p) => p.createTime },
            ]}
            empty={<Typography variant="body2" color="text.secondary">There are no delivery pipelines in this project.</Typography>} />
        </CapabilityContainer>
      ) : (
        <CapabilityContainer id="gcp.clouddeploy.pipelines_targets" title="Targets">
          <ResourceTable resourceName="targets" items={tg.data || []} loading={tg.loading} error={tg.error} onRetry={tg.reload} rowKey={(t) => t.name}
            filterPlaceholder="Filter targets"
            columns={[
              { id: "name", header: "Name", sortValue: (t) => api.tail(t.name), cell: (t) => api.tail(t.name) },
              { id: "type", header: "Runtime", cell: (t) => (t.run ? "Cloud Run" : "GKE") },
              { id: "where", header: "Location / cluster", cell: (t) => t.run?.location || t.gke?.cluster },
              { id: "approval", header: "Requires approval", cell: (t) => (t.requireApproval ? "Yes" : "No") },
            ]}
            empty={<Typography variant="body2" color="text.secondary">There are no targets in this project.</Typography>} />
        </CapabilityContainer>
      )}
      <FormDialog open={dlg === "target"} title="Create target" onClose={(ok) => { setDlg(null); if (ok) reload(); }} onSubmit={createTarget}
        fields={[{ key: "id", label: "Target name" }, { key: "description", label: "Description" },
          { key: "type", label: "Runtime", options: ["Cloud Run", "GKE"], default: "Cloud Run" },
          { key: "location", label: "Cloud Run region", default: "us-central1" },
          { key: "cluster", label: "GKE cluster (projects/P/locations/L/clusters/C)", helper: "Used when the runtime is GKE" },
          { key: "requireApproval", label: "Require approval for rollouts", type: "bool" }]} />
      <FormDialog open={dlg === "pipeline"} title="Create delivery pipeline" onClose={(ok) => { setDlg(null); if (ok) reload(); }} onSubmit={createPipeline}
        fields={[{ key: "id", label: "Pipeline name" }, { key: "description", label: "Description" },
          { key: "stages", label: "Target IDs in order (comma separated)", helper: "e.g. dev,prod" },
          { key: "strategy", label: "Strategy", options: ["Standard", "Canary"], default: "Standard" },
          { key: "percentages", label: "Canary percentages", default: "25,50" },
          { key: "verify", label: "Verify after deploy", type: "bool" },
          { key: "service", label: "Cloud Run service name (deploy parameter)", helper: "Defaults to the pipeline name" },
          { key: "deployment", label: "GKE Deployment name (deploy parameter)" },
          { key: "namespace", label: "GKE namespace (deploy parameter)", default: "default" }]} />
    </>
  );
}
