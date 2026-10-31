/* Services & SLOs — real Service Monitoring API (v3) resources. A request-based SLO's
 * error budget is computed for real from the good/total time series its filters match (see
 * api.sloBudgetFraction / select_slo_budget_fraction in the core); other SLI types and
 * "SLOs with firing alert" stay an honest gap — see gcp.monitoring.slos in the registry. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function DefineServiceDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Define service</DialogTitle>
      <DialogContent><TextField autoFocus fullWidth label="Service name" value={name} onChange={(e) => setName(e.target.value)} sx={{ mt: 1 }} /></DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || busy} onClick={async () => {
          setBusy(true);
          await api.createService({ displayName: name });
          notify.success(`Defined service "${name}"`);
          setBusy(false); onCreated();
        }}>Define</Button>
      </DialogActions>
    </Dialog>
  );
}

function CreateSloDialog({ svc, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("99");
  const [days, setDays] = useState("28");
  const [goodFilter, setGoodFilter] = useState('metric.type = "custom.googleapis.com/requests/good"');
  const [totalFilter, setTotalFilter] = useState('metric.type = "custom.googleapis.com/requests/total"');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const id = svc.name.split("/").pop();
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createSlo(id, {
        displayName: name, goal: Number(goal) / 100, rollingPeriod: `${Math.round(Number(days) * 86400)}s`,
        serviceLevelIndicator: { requestBased: { goodTotalRatio: { goodServiceFilter: goodFilter, totalServiceFilter: totalFilter } } },
      });
      notify.success(`Created SLO "${name}" on ${svc.displayName}`);
      onCreated();
    } catch (e) { setError(e); setBusy(false); }
  };
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create SLO for {svc.displayName}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Typography variant="body2" color="error">{error.message}</Typography>}
          <TextField autoFocus fullWidth label="SLO name" value={name} onChange={(e) => setName(e.target.value)} />
          <Stack direction="row" spacing={2}>
            <TextField fullWidth label="Goal (%)" type="number" value={goal} onChange={(e) => setGoal(e.target.value)} />
            <TextField fullWidth label="Rolling period (days)" type="number" value={days} onChange={(e) => setDays(e.target.value)} />
          </Stack>
          <TextField fullWidth label="Good events filter" value={goodFilter} onChange={(e) => setGoodFilter(e.target.value)}
            helperText="A time series filter — e.g. successful requests you've written via writeTimeSeries." />
          <TextField fullWidth label="Total events filter" value={totalFilter} onChange={(e) => setTotalFilter(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || !goodFilter.trim() || !totalFilter.trim() || busy} onClick={submit}>
          {busy ? "Creating…" : "Create"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RowMenu({ svc, onDeleted, onCreateSlo }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  const [del, setDel] = useState(false);
  const id = svc.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label={`Actions for ${svc.displayName}`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => { setAnchor(null); onCreateSlo(svc); }}>Create SLO</MenuItem>
        <MenuItem onClick={() => { setAnchor(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete service?" confirmText={svc.displayName}
        onConfirm={async () => { await api.deleteService(id); notify.success(`Deleted service "${svc.displayName}"`); onDeleted(); }}>
        <Typography variant="body2">Service <b>{svc.displayName}</b> and its SLOs will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

/** Real error-budget status for one service: counts SLOs whose request-based good/total-ratio
 *  indicator has data and has burned through its budget — see api.sloBudgetFraction. */
async function sloStats(sid) {
  const slos = await api.listSlos(sid);
  let computed = 0, outOfBudget = 0;
  for (const slo of slos) {
    if (!slo.serviceLevelIndicator?.requestBased?.goodTotalRatio) continue;
    const days = slo.rollingPeriod ? Number(slo.rollingPeriod.replace(/s$/, "")) / 86400 : 28;
    const frac = await api.sloBudgetFraction(slo.name, days);
    if (frac != null) { computed += 1; if (frac < 0) outOfBudget += 1; }
  }
  return { total: slos.length, computed, outOfBudget };
}

export default function Slos() {
  const project = useProject();
  const [defineOpen, setDefineOpen] = useState(false);
  const [sloSvc, setSloSvc] = useState(null);
  const { data = [], loading, error, reload } = useAsync(async () => {
    const services = await api.listServices();
    const stats = {};
    for (const s of services) stats[s.name] = await sloStats(s.name.split("/").pop());
    return { services, stats };
  }, [project]);

  return (
    <>
      <PageHeader title="SLOs Overview" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setDefineOpen(true)}>Define service</Button>
        <Button disabled>Send feedback</Button>
        <Button disabled>Auto refresh</Button>
      </>} />
      <ResourceTable
        resourceName="services"
        items={data.services || []}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(s) => s.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "displayName", cell: (s) => s.displayName },
          { id: "type", header: "Type", cell: () => "Custom service" },
          { id: "budget", header: <>SLOs out of error budget<CapabilityBadge id="gcp.monitoring.slos" /></>, cell: (s) => {
            const st = data.stats?.[s.name];
            if (!st || st.total === 0) return "0";
            return st.computed > 0 ? String(st.outOfBudget) : "—";
          } },
          { id: "firing", header: "SLOs with firing alert", cell: () => "0" },
          { id: "labels", header: "Labels", cell: (s) => Object.keys(s.userLabels || {}).length ? Object.entries(s.userLabels).map(([k, v]) => `${k}=${v}`).join(", ") : "—" },
          { id: "actions", header: "", cell: (s) => <RowMenu svc={s} onDeleted={reload} onCreateSlo={setSloSvc} /> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No services</Typography>}
      />
      <DefineServiceDialog open={defineOpen} onClose={() => setDefineOpen(false)} onCreated={() => { setDefineOpen(false); reload(); }} />
      {sloSvc && <CreateSloDialog svc={sloSvc} onClose={() => setSloSvc(null)} onCreated={() => { setSloSvc(null); reload(); }} />}
    </>
  );
}
