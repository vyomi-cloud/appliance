/* Cloud Build: build history, build detail (steps + logs + pushed images), triggers (create/run/enable/delete) and a push-to-repo helper. */
import { useState } from "react";
import { Alert, Box, Button, Chip, Stack, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import { PageHeader, KeyValue, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const COLOR = { SUCCESS: "success", FAILURE: "error", WORKING: "info", QUEUED: "default", CANCELLED: "default", TIMEOUT: "error", INTERNAL_ERROR: "error" };

export default function Builds({ query }) {
  const tab = ["triggers"].includes(query.tab) ? query.tab : "history";
  const project = useProject();
  const notify = useNotify();
  const builds = useAsync(api.listBuilds, [project]);
  const triggers = useAsync(api.listTriggers, [project]);
  const [open, setOpen] = useState(null);     // build
  const [dlg, setDlg] = useState(null);
  const reload = () => { builds.reload(); triggers.reload(); };
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); } catch (e) { notify.error(e.message); } reload(); };
  const trName = (id) => triggers.data?.find((t) => t.id === id)?.name || id;

  return (
    <>
      <PageHeader title="Cloud Build" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setDlg("trigger")}>Create trigger</Button>
        <Button onClick={() => setDlg("push")}>Push files to repo</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = "#/cloudbuild" + (t === "triggers" ? "?tab=triggers" : ""); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }}>
        <Tab value="history" label="History" />
        <Tab value="triggers" label="Triggers" />
      </Tabs>
      {tab === "history" ? (
        <Stack spacing={2.5}>
          <CapabilityContainer id="gcp.cloudbuild.builds" title="Build history">
            <ResourceTable resourceName="builds" items={builds.data || []} loading={builds.loading} error={builds.error} onRetry={builds.reload} rowKey={(b) => b.id}
              filterPlaceholder="Filter builds"
              columns={[
                { id: "id", header: "Build", sortValue: (b) => b.createTime, cell: (b) => <Button size="small" onClick={() => setOpen(b)}>{b.id.slice(0, 8)}</Button> },
                { id: "status", header: "Status", cell: (b) => <Chip size="small" color={COLOR[b.status] || "default"} label={b.status} /> },
                { id: "trig", header: "Trigger", cell: (b) => (b.buildTriggerId ? trName(b.buildTriggerId) : "Manual") },
                { id: "src", header: "Source", cell: (b) => { const r = b.sourceProvenance?.resolvedRepoSource; return r ? `${r.repoName}@${(r.commitSha || "").slice(0, 7)}` : "—"; } },
                { id: "imgs", header: "Images", cell: (b) => (b.results?.images || []).map((i) => i.name).join(", ") },
                { id: "dur", header: "Duration", cell: api.duration },
                { id: "created", header: "Started", cell: (b) => fmtDate(b.createTime) },
              ]}
              empty={<Typography variant="body2" color="text.secondary">No builds yet. Push to a repository with a trigger, or run a trigger.</Typography>} />
          </CapabilityContainer>
          {open && <BuildDetail build={open} act={act} onClose={() => setOpen(null)} />}
        </Stack>
      ) : (
        <CapabilityContainer id="gcp.cloudbuild.triggers" title="Triggers">
          <ResourceTable resourceName="triggers" items={triggers.data || []} loading={triggers.loading} error={triggers.error} onRetry={triggers.reload} rowKey={(t) => t.id}
            filterPlaceholder="Filter triggers"
            columns={[
              { id: "name", header: "Name", sortValue: (t) => t.name, cell: (t) => t.name },
              { id: "repo", header: "Repository", cell: (t) => t.triggerTemplate?.repoName || (t.github && `${t.github.owner}/${t.github.name}`) || "—" },
              { id: "event", header: "Event", cell: (t) => { const rx = t.triggerTemplate?.branchName || t.github?.push?.branch; return rx ? `Push to branch ${rx}` : "Manual"; } },
              { id: "cfg", header: "Configuration", cell: (t) => t.filename || "Inline" },
              { id: "st", header: "Status", cell: (t) => <Chip size="small" color={t.disabled ? "default" : "success"} label={t.disabled ? "Disabled" : "Enabled"} /> },
              { id: "act", header: "Actions", cell: (t) => <Stack direction="row" spacing={0.5}>
                <Button size="small" onClick={() => act(() => api.runTrigger(t.id, "main"), "Trigger run started")}>Run</Button>
                <Button size="small" onClick={() => act(() => api.patchTrigger(t.id, { disabled: !t.disabled }), t.disabled ? "Enabled" : "Disabled")}>{t.disabled ? "Enable" : "Disable"}</Button>
                <Button size="small" color="error" onClick={() => act(() => api.deleteTrigger(t.id), "Deleted")}>Delete</Button></Stack> },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No triggers. Create one to build on every push.</Typography>} />
        </CapabilityContainer>
      )}
      <FormDialog open={dlg === "trigger"} title="Create trigger" onClose={(ok) => { setDlg(null); if (ok) reload(); }}
        onSubmit={async (v) => { await api.createTrigger({ name: v.name, triggerTemplate: { repoName: v.repo, branchName: v.branch }, filename: v.filename }); notify.success("Trigger created"); }}
        fields={[{ key: "name", label: "Name" }, { key: "repo", label: "Repository (Vyomi source repo)", default: "shop" }, { key: "branch", label: "Branch (regex)", default: "^main$" }, { key: "filename", label: "Build configuration file", default: "cloudbuild.yaml" }]} />
      <FormDialog open={dlg === "push"} title="Push a file to a source repo" submitLabel="Push" onClose={(ok) => { setDlg(null); if (ok) reload(); }}
        onSubmit={async (v) => { const r = await api.pushToRepo({ repoName: v.repo, branch: v.branch, files: { [v.path]: v.content }, message: v.message }); notify.success(`Pushed ${r.commitSha.slice(0, 7)}; ${r.builds.length} build(s) triggered`); }}
        fields={[{ key: "repo", label: "Repository", default: "shop" }, { key: "branch", label: "Branch", default: "main" }, { key: "path", label: "File path", default: "cloudbuild.yaml" },
          { key: "content", label: "Content", multiline: true }, { key: "message", label: "Commit message", default: "Update" }]} />
    </>
  );
}

function BuildDetail({ build, act, onClose }) {
  return (
    <CapabilityContainer id="gcp.cloudbuild.builds" title={`Build ${build.id.slice(0, 8)}`}
      actions={<><Button size="small" onClick={() => act(() => api.retryBuild(build.id), "Retried")}>Retry</Button><Button size="small" onClick={onClose}>Close</Button></>}>
      <Box sx={{ px: 2.5, pb: 2 }}>
        {build.failureInfo && <Alert severity="error" sx={{ mb: 2 }}>{build.failureInfo.detail}</Alert>}
        <KeyValue items={[["Status", build.status], ["Build ID", build.id], ["Duration", api.duration(build)], ["Substitutions", JSON.stringify(build.substitutions || {})]]} />
        <Typography variant="h3" sx={{ mt: 2, mb: 1 }}>Steps</Typography>
        <ResourceTable resourceName="steps" items={build.steps || []} rowKey={(s) => `${s.name}-${(s.args || []).join(" ")}`}
          columns={[{ id: "st", header: "Status", cell: (s) => <Chip size="small" color={COLOR[s.status] || "default"} label={s.status || "—"} /> }, { id: "n", header: "Builder", cell: (s) => s.name }, { id: "a", header: "Args", cell: (s) => (s.args || []).join(" ") }]} />
        <Typography variant="h3" sx={{ mt: 2, mb: 1 }}>Logs</Typography>
        <Box component="pre" data-testid="build-logs" sx={{ m: 0, p: 1.5, bgcolor: "action.hover", borderRadius: 1, fontSize: 12, overflow: "auto", maxHeight: 280 }}>{(build.vyomiLogs || []).join("\n")}</Box>
        {(build.results?.images || []).length > 0 && <>
          <Typography variant="h3" sx={{ mt: 2, mb: 1 }}>Artifacts pushed to Artifact Registry</Typography>
          <ResourceTable resourceName="images" items={build.results.images} rowKey={(i) => i.name} columns={[{ id: "n", header: "Image", cell: (i) => i.name }, { id: "d", header: "Digest", cell: (i) => i.digest }]} /></>}
      </Box>
    </CapabilityContainer>
  );
}
