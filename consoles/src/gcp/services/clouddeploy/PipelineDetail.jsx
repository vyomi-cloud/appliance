/* Cloud Deploy pipeline detail: the stage visualisation, releases, and each release's rollouts with the state-machine actions. */
import { useState } from "react";
import { Alert, Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader, KeyValue, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const COLOR = { SUCCEEDED: "success", FAILED: "error", IN_PROGRESS: "info", PENDING_APPROVAL: "warning", APPROVAL_REJECTED: "error", CANCELLED: "default", PENDING: "default" };

export default function PipelineDetail({ params }) {
  const { region, name } = params;
  const notify = useNotify();
  const pl = useAsync(() => api.getPipeline(region, name), [region, name]);
  const rel = useAsync(() => api.listReleases(region, name), [region, name]);
  const [sel, setSel] = useState(null);       // release object
  const [dlg, setDlg] = useState(null);
  const [del, setDel] = useState(false);
  const ro = useAsync(() => (sel ? api.listRollouts(sel.name) : Promise.resolve([])), [sel?.name, rel.data]);
  const stages = pl.data?.serialPipeline?.stages || [];
  const reloadAll = () => { pl.reload(); rel.reload(); ro.reload(); };
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); } catch (e) { notify.error(e.message); } reloadAll(); };

  const createRelease = async (v) => {
    await api.createRelease(region, name, v.id, { description: v.description, buildArtifacts: [{ image: v.image, tag: v.tag }] });
    notify.success(`Created release ${v.id}`);
  };
  const nextTarget = (r) => {
    const last = [...(ro.data || [])].reverse().find((x) => x.state === "SUCCEEDED");
    const i = stages.findIndex((s) => s.targetId === last?.targetId);
    return i >= 0 && i + 1 < stages.length ? stages[i + 1].targetId : null;
  };

  return (
    <>
      <PageHeader title={name} back={<Button href="#/clouddeploy">‹ Pipelines</Button>} actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setDlg("release")}>Create release</Button>
        <Button onClick={() => setDlg("rollback")}>Roll back target</Button>
        <Button color="error" onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reloadAll}>Refresh</Button>
      </>} />
      {pl.error && <Alert severity="error">{pl.error.message}</Alert>}
      <Stack spacing={2.5}>
        <CapabilityContainer id="gcp.clouddeploy.pipelines_targets" title="Pipeline">
          <Box sx={{ px: 2.5, pb: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2, flexWrap: "wrap" }} data-testid="stage-flow">
              {stages.map((s, i) => <Stack key={s.targetId} direction="row" spacing={1} alignItems="center">
                <Chip label={s.targetId} variant="outlined" />{s.strategy?.canary && <Chip size="small" label="canary" />}{i + 1 < stages.length && <span>→</span>}
              </Stack>)}
            </Stack>
            <KeyValue items={[["Name", pl.data && api.tail(pl.data.name)], ["Region", region], ["Description", pl.data?.description],
              ["Deploy parameters", JSON.stringify(pl.data?.deployParameters || {})], ["Created", pl.data?.createTime]]} />
          </Box>
        </CapabilityContainer>
        <CapabilityContainer id="gcp.clouddeploy.releases_rollouts" title="Releases">
          <ResourceTable resourceName="releases" items={rel.data || []} loading={rel.loading} error={rel.error} onRetry={rel.reload} rowKey={(r) => r.name}
            filterPlaceholder="Filter releases"
            columns={[
              { id: "name", header: "Release", sortValue: (r) => r.createTime, cell: (r) => <Button size="small" onClick={() => setSel(r)}>{api.tail(r.name)}</Button> },
              { id: "render", header: "Render", cell: (r) => <Chip size="small" color={r.renderState === "SUCCEEDED" ? "success" : "error"} label={r.renderState} /> },
              { id: "img", header: "Artifacts", cell: (r) => (r.buildArtifacts || []).map((a) => a.tag).join(", ") },
              { id: "ab", header: "Abandoned", cell: (r) => (r.abandoned ? "Yes" : "No") },
              { id: "created", header: "Created", cell: (r) => r.createTime },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No releases yet. Create one to start rolling out.</Typography>} />
        </CapabilityContainer>
        {sel && (
          <CapabilityContainer id="gcp.clouddeploy.releases_rollouts" title={`Rollouts of ${api.tail(sel.name)}`}
            actions={<>{nextTarget(sel) && <Button size="small" variant="contained" onClick={() => act(() => api.createRollout(sel.name, `${api.tail(sel.name)}-to-${nextTarget(sel)}-p${Date.now() % 100000}`, nextTarget(sel)), `Promoting to ${nextTarget(sel)}`)}>Promote to {nextTarget(sel)}</Button>}
              {!sel.abandoned && <Button size="small" onClick={() => act(() => api.abandonRelease(sel.name), "Release abandoned")}>Abandon release</Button>}</>}>
            <ResourceTable resourceName="rollouts" items={ro.data || []} loading={ro.loading} error={ro.error} onRetry={ro.reload} rowKey={(r) => r.name}
              columns={[
                { id: "name", header: "Rollout", cell: (r) => api.tail(r.name) },
                { id: "target", header: "Target", cell: (r) => r.targetId },
                { id: "state", header: "State", cell: (r) => <Chip size="small" color={COLOR[r.state] || "default"} label={r.state} /> },
                { id: "phases", header: "Phases", cell: (r) => (r.phases || []).map((p) => `${p.id}:${p.state}`).join("  ") },
                { id: "why", header: "Failure", cell: (r) => r.failureReason },
                { id: "act", header: "Actions", cell: (r) => <RolloutActions r={r} act={act} /> },
              ]}
              empty={<Typography variant="body2" color="text.secondary">No rollouts.</Typography>} />
          </CapabilityContainer>
        )}
      </Stack>
      <FormDialog open={dlg === "release"} title="Create release" onClose={(ok) => { setDlg(null); if (ok) reloadAll(); }} onSubmit={createRelease}
        fields={[{ key: "id", label: "Release name" }, { key: "description", label: "Description" }, { key: "image", label: "Image name", default: "app" },
          { key: "tag", label: "Image to deploy (full reference)", helper: "e.g. us-central1-docker.pkg.dev/PROJECT/REPO/web:v1" }]} />
      <FormDialog open={dlg === "rollback"} title="Roll back target" submitLabel="Roll back" onClose={(ok) => { setDlg(null); if (ok) reloadAll(); }}
        onSubmit={async (v) => { await api.rollback(region, name, v.target, v.id); notify.success("Rollback rollout created"); }}
        fields={[{ key: "target", label: "Target", options: stages.map((s) => s.targetId), default: stages[0]?.targetId || "" }, { key: "id", label: "Rollback rollout ID", default: `rollback-${Date.now() % 100000}` }]} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete delivery pipeline?" confirmText={name} warning="Its releases and rollouts are deleted too."
        onConfirm={async () => { await api.deletePipeline(region, name); location.hash = "#/clouddeploy"; }}><Typography variant="body2">{name}</Typography></DeleteDialog>
    </>
  );
}

function RolloutActions({ r, act }) {
  const phasePending = (r.phases || []).find((p) => p.state === "PENDING");
  const failed = (r.phases || []).flatMap((p) => Object.values(p.deploymentJobs || {}).map((j) => ({ p, j }))).find((x) => x.j.state === "FAILED");
  return (
    <Stack direction="row" spacing={0.5}>
      {r.state === "PENDING_APPROVAL" && <>
        <Button size="small" onClick={() => act(() => api.rolloutAction(r.name, "approve", { approved: true }), "Approved")}>Approve</Button>
        <Button size="small" onClick={() => act(() => api.rolloutAction(r.name, "approve", { approved: false }), "Rejected")}>Reject</Button></>}
      {r.state === "IN_PROGRESS" && phasePending && <Button size="small" onClick={() => act(() => api.rolloutAction(r.name, "advance", { phaseId: phasePending.id }), `Advanced to ${phasePending.id}`)}>Advance to {phasePending.id}</Button>}
      {r.state === "FAILED" && failed && <>
        <Button size="small" onClick={() => act(() => api.rolloutAction(r.name, "retryJob", { phaseId: failed.p.id, jobId: failed.j.id }), "Retried")}>Retry job</Button>
        <Button size="small" onClick={() => act(() => api.rolloutAction(r.name, "ignoreJob", { phaseId: failed.p.id, jobId: failed.j.id }), "Ignored")}>Ignore job</Button></>}
      {["IN_PROGRESS", "PENDING_APPROVAL"].includes(r.state) && <Button size="small" color="error" onClick={() => act(() => api.rolloutAction(r.name, "cancel"), "Cancelled")}>Cancel</Button>}
    </Stack>
  );
}
