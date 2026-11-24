/* Deployment details: Overview, Revisions (each with the resources it applied), and the Terraform configuration. Update / Preview / Delete on top. */
import { useState } from "react";
import { Alert, Box, Button, Chip, CircularProgress, IconButton, Stack, Tab, Tabs, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section, fmtDate } from "../../kit/common.jsx";
import { getProject } from "../../project.js";
import * as api from "./api.js";
import { PlanDialog } from "./PlanView.jsx";

const chip = (s) => <Chip size="small" label={s} color={api.STATE_COLOR[s] || "default"} variant={api.STATE_COLOR[s] ? "filled" : "outlined"} />;

export default function DeploymentDetail({ params, query }) {
  const { region, name } = params;
  const tab = ["revisions", "resources", "terraform"].includes(query.tab) ? query.tab : "overview";
  const notify = useNotify();
  const [del, setDel] = useState(false), [plan, setPlan] = useState(null), [busy, setBusy] = useState(false), [abandon, setAbandon] = useState(false);
  const d = useAsync(() => api.getDeployment(region, name), [region, name]);
  const revs = useAsync(() => api.listRevisions(region, name), [region, name, d.data?.latestRevision]);
  const tf = useAsync(() => (tab === "terraform" ? api.getFiles(region, name) : Promise.resolve({})), [region, name, tab, d.data?.latestRevision]);
  const res = useAsync(() => (d.data?.latestRevision ? api.listRevisionResources(d.data.latestRevision) : Promise.resolve([])), [d.data?.latestRevision]);

  const preview = async () => {
    setBusy(true);
    try {
      // a preview naming only the deployment re-reads the configuration it holds and plans it against the project as it is now
      setPlan(await api.createPreview(region, `pv-${name.slice(0, 20)}-${Date.now().toString(36)}`.replace(/[^a-z0-9-]/g, "-"), { deployment: d.data.name, serviceAccount: d.data.serviceAccount }));
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  if (d.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (d.error) return <ErrorAlert error={d.error} title="Failed to load deployment" />;
  const dep = d.data;
  const go = (t) => { location.hash = `#/infra-manager/deployments/${region}/${name}${t === "overview" ? "" : `?tab=${t}`}`; };

  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back to deployments" href="#/infra-manager"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<EditIcon />} href={`#/infra-manager/deployments/${region}/${name}/edit`}>Update</Button>
          <Button onClick={preview} disabled={busy} data-testid="dep-preview">Preview</Button>
          <Button startIcon={<RefreshIcon />} onClick={() => { d.reload(); revs.reload(); res.reload(); }}>Refresh</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>
        </>} />
      {dep.state === "FAILED" && <Alert severity="error" sx={{ mb: 2 }}>{dep.stateDetail || "The last revision failed."}</Alert>}
      <Tabs value={tab} onChange={(_, t) => go(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Deployment tabs">
        <Tab value="overview" label="Overview" /><Tab value="revisions" label="Revisions" /><Tab value="resources" label="Resources" /><Tab value="terraform" label="Terraform" />
      </Tabs>
      {tab === "overview" && (
        <Section title="Deployment details">
          <KeyValue items={[
            ["Name", name], ["Status", chip(dep.state)], ["Region", region], ["Project", getProject()], ["Service account", (dep.serviceAccount || "").split("/").pop()],
            ["Latest revision", api.idOf(dep.latestRevision) || "—"], ["Terraform version", dep.tfVersion], ["Created", fmtDate(dep.createTime)], ["Last modified", fmtDate(dep.updateTime)],
            ["Source", dep.terraformBlueprint?.gcsSource ? dep.terraformBlueprint.gcsSource.source : `Inline configuration (${(dep.terraformBlueprint?.vyomiFiles || []).join(", ") || "main.tf"})`],
            ["Labels", Object.entries(dep.labels || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "None"], ["Status detail", dep.stateDetail || "—"],
          ]} />
        </Section>
      )}
      {tab === "revisions" && (
        <ResourceTable resourceName="revisions" items={revs.data || []} rowKey={(r) => r.name} loading={revs.loading} error={revs.error} onRetry={revs.reload} filterPlaceholder="Filter revisions"
          columns={[
            { id: "name", header: "Revision", sortValue: (r) => r.name, cell: (r) => api.idOf(r.name) },
            { id: "action", header: "Action", cell: (r) => r.action }, { id: "state", header: "Status", cell: (r) => chip(r.state) },
            { id: "created", header: "Created", sortValue: (r) => r.createTime, cell: (r) => fmtDate(r.createTime) },
            { id: "applied", header: "Applied", cell: (r) => `${(r.applyResults?.vyomiResources || []).filter((x) => x.action === "created").length} created, ${(r.applyResults?.vyomiResources || []).filter((x) => x.action === "unchanged").length} unchanged` },
            { id: "detail", header: "Detail", cell: (r) => r.stateDetail || "—" },
          ]} />
      )}
      {tab === "resources" && (
        <ResourceTable resourceName="resources" items={res.data || []} rowKey={(r) => r.name} loading={res.loading} error={res.error} onRetry={res.reload} filterPlaceholder="Filter resources"
          columns={[
            { id: "addr", header: "Terraform address", sortValue: (r) => r.terraformInfo.address, cell: (r) => <code>{r.terraformInfo.address}</code> },
            { id: "type", header: "Type", cell: (r) => r.terraformInfo.type },
            { id: "id", header: "ID", cell: (r) => r.terraformInfo.id || "—" },
            { id: "state", header: "State", cell: (r) => (r.vyomiAction === "unsupported" ? <Chip size="small" color="warning" label="Not applied" title={r.vyomiNote} /> : chip(r.state === "RECONCILED" ? "APPLIED" : r.state)) },
            { id: "act", header: "Last action", cell: (r) => r.vyomiAction },
          ]} />
      )}
      {tab === "terraform" && (tf.loading ? <CircularProgress /> : tf.error ? <ErrorAlert error={tf.error} title="Failed to load configuration" /> : Object.keys(tf.data || {}).sort().map((f) => (
        <Section key={f} title={f}><Box component="pre" data-testid="dep-tf" sx={{ m: 0, p: 2, maxHeight: 420, overflow: "auto", fontSize: 12 }}>{tf.data[f]}</Box></Section>
      )))}
      <PlanDialog preview={plan} onClose={() => setPlan(null)} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title={`Delete deployment ${name}?`} confirmText={name}
        warning={abandon ? "Resources created by this deployment will be kept." : "Resources created by this deployment will be deleted from the project."}
        onConfirm={async () => { await api.deleteDeployment(region, name, abandon ? "ABANDON" : "DELETE"); notify.success(`Deployment ${name} deleted`); location.hash = "#/infra-manager"; }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <input type="checkbox" id="im-abandon" checked={abandon} onChange={(e) => setAbandon(e.target.checked)} />
          <label htmlFor="im-abandon">Abandon: keep the resources this deployment created</label>
        </Stack>
      </DeleteDialog>
    </>
  );
}
