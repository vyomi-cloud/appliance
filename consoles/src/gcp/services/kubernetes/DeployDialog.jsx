/* The console's "Deploy" action: deploys a real Deployment/StatefulSet/Job (with its Pods)
 * to a cluster over the Kubernetes data plane (core/gcp_gke_dataplane_core.py), optionally
 * exposing it with a Service — the same two-resource flow the real console's Deploy wizard
 * offers ("Expose as a new service"). */
import { useState } from "react";
import {
  Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControl,
  FormControlLabel, IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const KINDS = [["Deployment", "Deployment"], ["StatefulSet", "StatefulSet"], ["Job", "Job"]];

export default function DeployDialog({ open, onClose, cluster, location, onDeployed }) {
  const project = useProject();
  const clusters = useAsync(() => (cluster ? Promise.resolve(null) : api.listClusters()), [project, open]);
  const [selCluster, setSelCluster] = useState(cluster || "");
  const [selLocation, setSelLocation] = useState(location || "");
  const [kind, setKind] = useState("Deployment");
  const [name, setName] = useState("");
  const [ns, setNs] = useState("default");
  const [image, setImage] = useState("nginx:latest");
  const [port, setPort] = useState("80");
  const [replicas, setReplicas] = useState("1");
  const [expose, setExpose] = useState(false);
  const [svcType, setSvcType] = useState("ClusterIP");
  const [labels, setLabels] = useState([{ key: "app", value: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;
  const effCluster = cluster || selCluster;
  const effLocation = location || (clusters.data || []).find((c) => c.name === selCluster)?.location;
  const ok = api.validNsName(ns) === null && /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/.test(name) && image.trim() && effCluster && effLocation;

  const close = () => { onClose(); setName(""); setExpose(false); setError(null); };
  const deploy = async () => {
    setBusy(true); setError(null);
    try {
      const appLabel = name;
      const lbls = { app: appLabel, ...Object.fromEntries(labels.filter((l) => l.key && l.key !== "app").map((l) => [l.key, l.value])) };
      const containers = [{ name: name, image: image.trim(), ports: port ? [{ containerPort: Number(port) }] : [] }];
      const template = { metadata: { labels: lbls }, spec: { containers } };
      const body = kind === "Job"
        ? { metadata: { name, labels: lbls }, spec: { template } }
        : { metadata: { name, labels: lbls }, spec: { replicas: Number(replicas) || 1, template } };
      if (kind === "Deployment") await api.createDeployment(effLocation, effCluster, ns, body);
      else if (kind === "StatefulSet") await api.createStatefulSet(effLocation, effCluster, ns, body);
      else await api.createJob(effLocation, effCluster, ns, body);
      if (expose && port) {
        await api.createService(effLocation, effCluster, ns, {
          metadata: { name: `${name}-svc` },
          spec: { selector: { app: appLabel }, ports: [{ port: Number(port), targetPort: Number(port) }], type: svcType },
        });
      }
      onDeployed?.();
      close();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : close} maxWidth="sm" fullWidth aria-labelledby="deploy-title">
      <DialogTitle id="deploy-title">Deploy to Kubernetes clusters</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {!cluster && (
            <FormControl disabled={!(clusters.data || []).length}>
              <InputLabel id="deploy-cluster-l">Cluster</InputLabel>
              <Select labelId="deploy-cluster-l" label="Cluster" value={selCluster} onChange={(e) => setSelCluster(e.target.value)} inputProps={{ "aria-label": "Cluster" }}>
                {(clusters.data || []).map((c) => <MenuItem key={`${c.location}/${c.name}`} value={c.name}>{c.name} ({c.location})</MenuItem>)}
              </Select>
            </FormControl>
          )}
          {!clusters.loading && !cluster && !(clusters.data || []).length && <Typography variant="body2" color="text.secondary">Create a cluster first — a workload needs one to run on.</Typography>}
          <FormControl>
            <InputLabel id="deploy-kind-l">Workload type</InputLabel>
            <Select labelId="deploy-kind-l" label="Workload type" value={kind} onChange={(e) => setKind(e.target.value)} inputProps={{ "aria-label": "Workload type" }}>
              {KINDS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value.trim())} inputProps={{ "aria-label": "Name" }} helperText="Lowercase letters, numbers and hyphens." />
          <TextField label="Namespace" value={ns} onChange={(e) => setNs(e.target.value.trim())} inputProps={{ "aria-label": "Namespace" }} />
          <TextField label="Container image" value={image} onChange={(e) => setImage(e.target.value)} inputProps={{ "aria-label": "Container image" }} />
          <TextField label="Container port" type="number" value={port} onChange={(e) => setPort(e.target.value)} inputProps={{ "aria-label": "Container port" }} />
          {kind !== "Job" && <TextField label="Replicas" type="number" value={replicas} onChange={(e) => setReplicas(e.target.value)} inputProps={{ "aria-label": "Replicas" }} />}
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Labels</Typography>
          {labels.map((l, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField label={`Key ${i + 1}`} value={l.key} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} disabled={i === 0} />
              <TextField label={`Value ${i + 1}`} value={i === 0 ? name : l.value} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} disabled={i === 0} />
              {i > 0 && <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>}
            </Stack>
          ))}
          <Button size="small" startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])} sx={{ alignSelf: "flex-start" }}>Add label</Button>
          <FormControlLabel control={<Checkbox checked={expose} onChange={(e) => setExpose(e.target.checked)} />} label="Expose as a new service" />
          {expose && (
            <FormControl>
              <InputLabel id="deploy-svctype-l">Service type</InputLabel>
              <Select labelId="deploy-svctype-l" label="Service type" value={svcType} onChange={(e) => setSvcType(e.target.value)} inputProps={{ "aria-label": "Service type" }}>
                <MenuItem value="ClusterIP">Cluster IP</MenuItem>
                <MenuItem value="NodePort">Node port</MenuItem>
                <MenuItem value="LoadBalancer">Load balancer</MenuItem>
              </Select>
            </FormControl>
          )}
          {error && <Alert severity="error"><b>{error.code || "Error"}</b>: {error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={close} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !ok} onClick={deploy}>{busy ? "Deploying…" : "Deploy"}</Button>
      </DialogActions>
    </Dialog>
  );
}
