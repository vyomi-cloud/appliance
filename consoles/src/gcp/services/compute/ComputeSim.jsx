/* Rollouts + Preview features (core/gcp_computesim_core).
 * Rollouts are REAL: a rollout rolls an instance template over the project's managed instance groups wave by wave
 * (rolling replace through the MIG engine, per-wave health check, rollback). Preview features are config records only. */
import { useState } from "react";
import { Alert, Box, Button, Chip, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import { FormDialog } from "./Ext.jsx";

const COLOR = { RUNNING: "info", PAUSED: "warning", SUCCEEDED: "success", CANCELLED: "default", ROLLED_BACK: "warning" };
const lc = (s) => String(s).toLowerCase().replace("_", " ");

export function Rollouts() {
  const project = useProject();
  const notify = useNotify();
  const [plan, setPlan] = useState(false);
  const [start, setStart] = useState(false);
  const { data, error, reload } = useAsync(async () => {
    const [plans, rollouts, migs, templates] = await Promise.all([api.listRolloutPlans(), api.listRollouts(), api.listInstanceGroupManagersAllZones(), api.listInstanceTemplates()]);
    return { plans, rollouts, migs, templates };
  }, [project]);
  const d = data || { plans: [], rollouts: [], migs: [], templates: [] };
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); reload(); } catch (e) { notify.error(e); } };
  const migOpts = d.migs.map((g) => [`${g._zoneScope}/${g.name}`, `${g.name} (${g._zoneScope})`]);
  return (
    <Box sx={{ pt: 2 }}>
      <PageHeader title="Rollouts" actions={<>
        <Button size="small" startIcon={<AddIcon />} disabled={!migOpts.length} onClick={() => setPlan(true)}>Create rollout plan</Button>
        <Button size="small" startIcon={<AddIcon />} disabled={!d.plans.length || !d.templates.length} onClick={() => setStart(true)}>Start rollout</Button>
        <Button size="small" startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Stack spacing={2}>
        <Alert severity="info" icon={false} sx={{ py: 0.5 }}>
          A rollout rolls an instance template over this project's managed instance groups, one wave at a time: each wave replaces the
          group's instances (new instances are created, old ones deleted), checks every new instance is RUNNING, and rolls back to the previous
          template if a wave fails. It does not roll out Google-managed product updates.
        </Alert>
        <ErrorAlert error={error} title="Could not load rollouts" />
        <Section title="Rollouts" actions={<CapabilityBadge id="gcp.compute.rollouts" />}>
          {d.rollouts.length === 0 ? <Typography variant="body2" color="text.secondary">No rollouts. Create a rollout plan, then start a rollout.</Typography> : (
            <Table size="small"><TableHead><TableRow><TableCell>Rollout</TableCell><TableCell>Plan</TableCell><TableCell>Template</TableCell><TableCell>State</TableCell><TableCell>Waves</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
              <TableBody>{d.rollouts.map((r) => (
                <TableRow key={r.name}>
                  <TableCell>{r.name}{r.error && <Typography variant="caption" color="error" display="block">{r.error.message}</Typography>}</TableCell>
                  <TableCell>{r.rolloutPlan.split("/").pop()}</TableCell>
                  <TableCell>{r.instanceTemplate}</TableCell>
                  <TableCell><Chip size="small" color={COLOR[r.state] || "default"} label={lc(r.state)} /></TableCell>
                  <TableCell>{r.waveDetails.map((w) => `${w.waveNumber}: ${lc(w.status)} (${w.managedInstanceGroups.map((g) => g.name).join(", ")})`).join("; ")}</TableCell>
                  <TableCell align="right">
                    {r.state === "RUNNING" && <Button size="small" onClick={() => act(() => api.rolloutVerb(r.name, "advance"), "Wave applied")}>Advance wave {r.currentWaveNumber}</Button>}
                    {r.state === "PAUSED" && <Button size="small" onClick={() => act(() => api.rolloutVerb(r.name, "resume"), "Wave retried")}>Resume</Button>}
                    {!["CANCELLED", "ROLLED_BACK"].includes(r.state) && <Button size="small" onClick={() => act(() => api.rolloutVerb(r.name, "rollback"), "Rolled back")}>Roll back</Button>}
                    {["RUNNING", "PAUSED"].includes(r.state) && <Button size="small" onClick={() => act(() => api.rolloutVerb(r.name, "cancel"), "Rollout cancelled")}>Cancel</Button>}
                    {!["RUNNING", "PAUSED"].includes(r.state) && <Button size="small" color="error" onClick={() => act(() => api.deleteRollout(r.name), "Rollout deleted")}>Delete</Button>}
                  </TableCell>
                </TableRow>))}</TableBody></Table>)}
        </Section>
        <Section title="Rollout plans">
          {d.plans.length === 0 ? <Typography variant="body2" color="text.secondary">No rollout plans.</Typography> : (
            <Table size="small"><TableHead><TableRow><TableCell>Plan</TableCell><TableCell>Scope</TableCell><TableCell>Waves</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
              <TableBody>{d.plans.map((p) => (
                <TableRow key={p.name}><TableCell>{p.name}</TableCell><TableCell>{p.locationScope}</TableCell>
                  <TableCell>{p.waves.map((w) => `${w.number}. ${w.displayName} [${(w.selectors || []).flatMap((s) => s.locationSelector?.includedLocations || []).join(", ")}${w.vyomiManagedInstanceGroups ? ` / ${w.vyomiManagedInstanceGroups.join(", ")}` : ""}]`).join("  ")}</TableCell>
                  <TableCell align="right"><Button size="small" color="error" onClick={() => act(() => api.deleteRolloutPlan(p.name), "Plan deleted")}>Delete</Button></TableCell></TableRow>))}</TableBody></Table>)}
        </Section>
      </Stack>
      <FormDialog open={plan} title="Create rollout plan" onClose={() => setPlan(false)} fields={[
        { key: "name", label: "Name", default: "plan-1", required: true },
        { key: "wave1", label: "Wave 1: managed instance group", options: migOpts },
        { key: "wave2", label: "Wave 2 (optional): managed instance group", options: [["", "None"], ...migOpts], default: "" },
      ]} onSubmit={async (v) => {
        const wave = (n, ref) => { const [zone, mig] = ref.split("/"); return { number: n, displayName: `Wave ${n}`, selectors: [{ locationSelector: { includedLocations: [zone] } }], vyomiManagedInstanceGroups: [mig] }; };
        await api.insertRolloutPlan({ name: v.name, locationScope: "ZONE", waves: [wave(1, v.wave1), ...(v.wave2 ? [wave(2, v.wave2)] : [])] });
        notify.success("Rollout plan created"); reload();
      }} />
      <FormDialog open={start} title="Start rollout" submitLabel="Start" onClose={() => setStart(false)} fields={[
        { key: "name", label: "Rollout name", default: "rollout-1", required: true },
        { key: "plan", label: "Rollout plan", options: d.plans.map((p) => [p.name, p.name]) },
        { key: "tpl", label: "Instance template to roll out", options: d.templates.map((t) => [t.name, t.name]) },
      ]} onSubmit={async (v) => { await api.insertRollout({ name: v.name, rolloutPlan: v.plan, instanceTemplate: v.tpl }); notify.success("Rollout started: advance each wave to apply it"); reload(); }} />
    </Box>
  );
}

export function PreviewFeatures() {
  const project = useProject();
  const notify = useNotify();
  const { data, error, reload } = useAsync(() => api.listPreviewFeatures(), [project]);
  const toggle = async (f) => {
    try { await api.setPreviewFeature(f.name, f.activationStatus === "ACTIVATED" ? "DISABLED" : "ACTIVATED"); reload(); } catch (e) { notify.error(e); }
  };
  return (
    <Box sx={{ pt: 2 }}>
      <PageHeader title="Preview Features" actions={<Button size="small" startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>} />
      <Stack spacing={2}>
        <Alert severity="info" icon={false} sx={{ py: 0.5 }}>
          Config only: this is a Vyomi-held catalogue. Enrolling records your choice for this project and gates no Compute behaviour.
        </Alert>
        <ErrorAlert error={error} title="Could not load preview features" />
        <Section title="Features" actions={<CapabilityBadge id="gcp.compute.preview-features" />}>
          <Table size="small"><TableHead><TableRow><TableCell>Feature</TableCell><TableCell>Stage</TableCell><TableCell>Enrolled</TableCell></TableRow></TableHead>
            <TableBody>{(data || []).map((f) => (
              <TableRow key={f.name}>
                <TableCell><Typography variant="body2" fontWeight={600}>{f.name}</Typography><Typography variant="caption" color="text.secondary">{f.status?.description}</Typography></TableCell>
                <TableCell>{f.status?.releaseStatus?.stage}</TableCell>
                <TableCell><Switch size="small" checked={f.activationStatus === "ACTIVATED"} onChange={() => toggle(f)} inputProps={{ "aria-label": `Enroll in ${f.name}` }} /></TableCell>
              </TableRow>))}</TableBody></Table>
        </Section>
      </Stack>
    </Box>
  );
}
