/* Pick-one dialogs used by row actions (deploy a model to an endpoint, deploy an index, query neighbours...). */
import { useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import * as api from "./api.js";

const opt = (x) => ({ value: x.name, label: `${x.displayName || api.shortId(x.name)} (${api.pname(x.name).location})` });

export function DeployModelDialog({ endpoint, model, onClose }) {
  const notify = useNotify();
  const models = useAsync(() => (model ? Promise.resolve([model]) : api.list("models")), []);
  const eps = useAsync(() => (endpoint ? Promise.resolve([endpoint]) : api.list("endpoints")), []);
  const loc = api.pname((endpoint || model).name).location;
  return (
    <FormDialog open title="Deploy model to endpoint" submitLabel="Deploy" onClose={onClose}
      fields={[
        { key: "model", label: "Model", options: (models.data || []).filter((m) => api.pname(m.name).location === loc).map(opt), default: model?.name },
        { key: "endpoint", label: "Endpoint", options: (eps.data || []).filter((m) => api.pname(m.name).location === loc).map(opt), default: endpoint?.name },
        { key: "machine", label: "Machine type", options: ["n1-standard-2", "n1-standard-4", "n1-standard-8", "g2-standard-4"], default: "n1-standard-4" },
        { key: "min", label: "Minimum replica count", default: "1" },
        { key: "max", label: "Maximum replica count", default: "1" },
      ]}
      onSubmit={async (v) => {
        if (!v.model || !v.endpoint) throw new Error("Choose a model and an endpoint in the same region.");
        await api.verb(v.endpoint, "deployModel", { deployedModel: { model: v.model, dedicatedResources: { machineSpec: { machineType: v.machine }, minReplicaCount: +v.min || 1, maxReplicaCount: +v.max || 1 } } });
        notify.success("Model deployed");
      }} />
  );
}

export function DeployIndexDialog({ endpoint, onClose }) {
  const notify = useNotify();
  const idx = useAsync(() => api.list("indexes"), []);
  const loc = api.pname(endpoint.name).location;
  return (
    <FormDialog open title="Deploy index" submitLabel="Deploy" onClose={onClose}
      fields={[
        { key: "id", label: "Deployed index ID", helper: "Letters, numbers and underscores" },
        { key: "index", label: "Index", options: (idx.data || []).filter((m) => api.pname(m.name).location === loc).map(opt) },
      ]}
      onSubmit={async (v) => {
        await api.verb(endpoint.name, "deployIndex", { deployedIndex: { id: v.id, displayName: v.id, index: v.index } });
        notify.success(`Deployed index "${v.id}"`);
      }} />
  );
}

export function UpsertDialog({ index, onClose }) {
  const notify = useNotify();
  return (
    <FormDialog open title="Upsert datapoints" submitLabel="Upsert" onClose={onClose}
      fields={[{ key: "json", label: "Datapoints (JSON)", multiline: true, default: '[{"datapointId": "a", "featureVector": [0.1, 0.2]}]', helper: "A JSON array of {datapointId, featureVector}" }]}
      onSubmit={async (v) => {
        let dps; try { dps = JSON.parse(v.json); } catch { throw new Error("Datapoints must be valid JSON."); }
        await api.verb(index.name, "upsertDatapoints", { datapoints: dps });
        notify.success(`Upserted ${dps.length} datapoint(s)`);
      }} />
  );
}

export function QueryDialog({ endpoint, onClose }) {
  const [dep, setDep] = useState(endpoint.deployedIndexes?.[0]?.id || "");
  const [vec, setVec] = useState("[0.1, 0.2]");
  const [k, setK] = useState("5");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const run = async () => {
    setErr(null); setRes(null);
    try {
      const r = await api.verb(endpoint.name, "findNeighbors", { deployedIndexId: dep, queries: [{ datapoint: { featureVector: JSON.parse(vec) }, neighborCount: +k || 5 }] });
      setRes(r.nearestNeighbors?.[0]?.neighbors || []);
    } catch (e) { setErr(e); }
  };
  return (
    <Dialog open onClose={() => onClose(false)} fullWidth maxWidth="sm" aria-label="Query index">
      <DialogTitle>Query index</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        {!endpoint.deployedIndexes?.length && <Alert severity="info">Deploy an index to this endpoint first.</Alert>}
        <TextField select size="small" label="Deployed index" value={dep} onChange={(e) => setDep(e.target.value)}>{(endpoint.deployedIndexes || []).map((d) => <MenuItem key={d.id} value={d.id}>{d.id}</MenuItem>)}</TextField>
        <TextField size="small" label="Query vector (JSON)" value={vec} onChange={(e) => setVec(e.target.value)} />
        <TextField size="small" label="Neighbor count" value={k} onChange={(e) => setK(e.target.value)} />
        {err && <Alert severity="error">{err.message}</Alert>}
        {res && <Alert severity="success" icon={false} data-testid="neighbors">{res.length ? res.map((n) => <div key={n.datapoint.datapointId}>{n.datapoint.datapointId}: {Number(n.distance).toFixed(4)}</div>) : <Typography variant="body2">No neighbors.</Typography>}</Alert>}
      </Stack></DialogContent>
      <DialogActions><Button onClick={() => onClose(false)}>Close</Button><Button variant="contained" disabled={!dep} onClick={run}>Find neighbors</Button></DialogActions>
    </Dialog>
  );
}
