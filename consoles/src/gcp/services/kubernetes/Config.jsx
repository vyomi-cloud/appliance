/* Config — Config Sync + Policy Controller (GKE Enterprise's ConfigManagement object), per
 * cluster, over the data plane bridge (core/gcp_gke_dataplane_core.py). Policy Controller
 * constraints are genuinely enforced on Workload admission; Config Sync's git half is
 * stored in the real shape but never fetched — see the capability badge for why. */
import { useState } from "react";
import {
  Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  FormControlLabel, IconButton, InputLabel, MenuItem, Select, Stack, Switch, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function Config() {
  const notify = useNotify();
  const clusters = useAsync(() => api.listClusters(), []);
  const [cluster, setCluster] = useState("");
  const [add, setAdd] = useState(false);
  const cl = (clusters.data || []).find((c) => c.name === cluster) || (clusters.data || [])[0];
  const cm = useAsync(() => (cl ? api.getConfigManagement(cl.location, cl.name) : Promise.resolve(null)), [cl?.name]);
  const constraints = useAsync(() => (cl ? api.listConstraints(cl.location, cl.name) : Promise.resolve([])), [cl?.name]);

  const togglePolicyController = async (enabled) => {
    try {
      await api.applyConfigManagement(cl.location, cl.name, { ...cm.data.spec, policyController: { enabled } });
      notify.success(enabled ? "Policy Controller enabled" : "Policy Controller disabled");
      cm.reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Config" />
      <FormControl sx={{ minWidth: 260, mb: 2.5 }} disabled={!(clusters.data || []).length}>
        <InputLabel id="cfg-cluster-l">Cluster</InputLabel>
        <Select labelId="cfg-cluster-l" label="Cluster" value={cl?.name || ""} onChange={(e) => setCluster(e.target.value)} inputProps={{ "aria-label": "Cluster" }}>
          {(clusters.data || []).map((c) => <MenuItem key={`${c.location}/${c.name}`} value={c.name}>{c.name} ({c.location})</MenuItem>)}
        </Select>
      </FormControl>
      {!(clusters.data || []).length && !clusters.loading ? (
        <Typography variant="body2" color="text.secondary">Create a cluster first — fleet configuration applies to a cluster.</Typography>
      ) : (
        <Stack spacing={2.5}>
          <ErrorAlert error={cm.error} title="Failed to load ConfigManagement" />
          <CapabilityContainer id="gcp.kubernetes.config" title="Config Sync" description="Syncs configuration from a git repository.">
            <ConfigSyncForm cluster={cl} cm={cm.data} onSaved={() => { notify.success("Config Sync settings saved"); cm.reload(); }} />
          </CapabilityContainer>
          {cm.data && (
            <Section title="Policy Controller" description="Enforces admission constraints on new Kubernetes objects."
              actions={<FormControlLabel control={<Switch checked={!!cm.data.spec.policyController.enabled} onChange={(e) => togglePolicyController(e.target.checked)} />} label="Enabled" />}>
              {cm.data.spec.policyController.enabled ? (
                <Stack spacing={1.5}>
                  <Button size="small" startIcon={<AddIcon />} onClick={() => setAdd(true)} sx={{ alignSelf: "flex-start" }}>Add constraint</Button>
                  <ResourceTable
                    resourceName="constraints"
                    items={constraints.data || []}
                    rowKey={(c) => c.metadata.name}
                    loading={constraints.loading}
                    dense
                    columns={[
                      { id: "name", header: "Name", cell: (c) => c.metadata.name },
                      { id: "kinds", header: "Kinds", cell: (c) => (c.spec.match.kinds || []).flatMap((k) => k.kinds || []).join(", ") || "All" },
                      { id: "labels", header: "Required labels", cell: (c) => c.spec.parameters.labels.join(", ") },
                      { id: "del", header: "", cell: (c) => (
                        <IconButton size="small" aria-label={`Delete constraint ${c.metadata.name}`}
                          onClick={async () => { try { await api.deleteConstraint(cl.location, cl.name, c.metadata.name); notify.success("Constraint deleted"); constraints.reload(); } catch (e) { notify.error(e); } }}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      ) },
                    ]}
                    empty={<Typography variant="body2" color="text.secondary">No constraints yet — Workloads admit freely.</Typography>}
                  />
                </Stack>
              ) : <Typography variant="body2" color="text.secondary">Enable Policy Controller to enforce admission constraints.</Typography>}
            </Section>
          )}
        </Stack>
      )}
      {add && cl && <AddConstraintDialog cluster={cl} onClose={() => setAdd(false)} onSaved={() => { notify.success("Constraint created"); constraints.reload(); setAdd(false); }} />}
    </>
  );
}

function ConfigSyncForm({ cluster, cm, onSaved }) {
  const [repo, setRepo] = useState(cm?.spec.git?.syncRepo || "");
  const [branch, setBranch] = useState(cm?.spec.git?.syncBranch || "main");
  const [dir, setDir] = useState(cm?.spec.git?.policyDir || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (!cm) return null;

  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.applyConfigManagement(cluster.location, cluster.name, {
        ...cm.spec, git: repo ? { syncRepo: repo, syncBranch: branch, policyDir: dir } : null,
      });
      onSaved();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Stack spacing={2} sx={{ maxWidth: 480 }}>
      <TextField label="Sync repo URL" value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="https://github.com/org/config-repo" />
      <TextField label="Branch" value={branch} onChange={(e) => setBranch(e.target.value)} />
      <TextField label="Policy directory" value={dir} onChange={(e) => setDir(e.target.value)} />
      {error && <Alert severity="error">{error.message}</Alert>}
      <Button variant="outlined" disabled={busy} onClick={save} sx={{ alignSelf: "flex-start" }}>{busy ? "Saving…" : "Save"}</Button>
      {cm.status.configSyncStatus === "SYNCED" && <Typography variant="caption" color="text.secondary">Stored: {cm.spec.git?.syncRepo} @ {cm.spec.git?.syncBranch}</Typography>}
    </Stack>
  );
}

const CANDIDATE_KINDS = ["Deployment", "StatefulSet", "Job"];

function AddConstraintDialog({ cluster, onClose, onSaved }) {
  const [name, setName] = useState("");
  const [kinds, setKinds] = useState(["Deployment"]);
  const [labelsCsv, setLabelsCsv] = useState("team");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const labels = labelsCsv.split(",").map((s) => s.trim()).filter(Boolean);
  const ok = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/.test(name) && labels.length;

  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.createConstraint(cluster.location, cluster.name, { metadata: { name }, spec: { match: { kinds: [{ kinds }] }, parameters: { labels } } });
      onSaved();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="constraint-title">
      <DialogTitle id="constraint-title">Add K8sRequiredLabels constraint</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Name" }} />
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Applies to</Typography>
          <Stack direction="row" spacing={1}>
            {CANDIDATE_KINDS.map((k) => (
              <FormControlLabel key={k} label={k} control={
                <Checkbox checked={kinds.includes(k)} onChange={(e) => setKinds(e.target.checked ? [...kinds, k] : kinds.filter((x) => x !== k))} />
              } />
            ))}
          </Stack>
          <TextField label="Required labels (comma-separated)" value={labelsCsv} onChange={(e) => setLabelsCsv(e.target.value)} helperText="e.g. team, cost-center" />
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !ok} onClick={save}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
