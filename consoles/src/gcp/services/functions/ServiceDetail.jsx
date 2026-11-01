/* Service details: summary strip + tabs (Observability, Revisions, Source, Networking,
 * Security, Triggers, YAML), all on the native Cloud Run Admin API v2. The real console's
 * /functions/add reaches this same page set via Cloud Run > Services (see gaps_note in
 * ui-spec/gcp/functions.json). */
import { useState } from "react";
import {
  Alert, Box, Breadcrumbs, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, Tab, Tabs, TextField, Tooltip, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import SyncIcon from "@mui/icons-material/esm/Sync.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtDate, NotSimulated, NotSimulatedContainer, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { getProject } from "../../project.js";
import * as api from "./api.js";

const TABS = [["observability", "Observability"], ["revisions", "Revisions"], ["source", "Source"],
  ["networking", "Networking"], ["security", "Security"], ["triggers", "Triggers"], ["yaml", "YAML"]];

export default function ServiceDetail({ params, query }) {
  const { region, name } = params;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "observability";
  const notify = useNotify();
  const svc = useAsync(() => api.getService(region, name), [region, name, tab]);
  const pol = useAsync(() => api.getIamPolicy(region, name).catch(() => null), [region, name, tab]);
  const [del, setDel] = useState(false);
  const [cd, setCd] = useState(false);
  const reloadAll = () => { svc.reload(); pol.reload(); };
  const tabHref = (t) => hashHref("functions", "detail", region, name) + (t === "observability" ? "" : `?tab=${t}`);

  return (
    <>
      <PageHeader title="Service details" back={<IconButton aria-label="Back to services" href="#/functions/services"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<SyncIcon />} onClick={() => setCd(true)}>Set up continuous deployment</Button>
          <Button startIcon={<RefreshIcon />} onClick={reloadAll}>Refresh</Button>
          <Button startIcon={<DeleteIcon />} color="error" onClick={() => setDel(true)}>Delete</Button>
        </>} />
      <Breadcrumbs sx={{ mb: 1 }} aria-label="Service path">
        <Typography variant="body2" color="text.secondary">Cloud Run</Typography>
        <Link href="#/functions/services">Services</Link>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{name}</Typography>
      </Breadcrumbs>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ fontSize: 22 }}>{name}</Typography>
        <Tooltip title="Copy service name"><IconButton size="small" aria-label="Copy service name" onClick={() => navigator.clipboard?.writeText(name).catch(() => {})}><ContentCopyIcon fontSize="inherit" /></IconButton></Tooltip>
      </Stack>
      {svc.error ? <ErrorAlert error={svc.error} title="Failed to load service" /> : svc.data && (
        <Stack direction="row" spacing={4} sx={{ mb: 1, flexWrap: "wrap", rowGap: 1 }} aria-label="Service summary">
          <Box><Typography variant="caption" color="text.secondary">URL</Typography><Typography variant="body2">{svc.data.uri}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Region</Typography><Typography variant="body2">{region}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Authentication</Typography><Typography variant="body2">{api.authLabel(pol.data)}</Typography></Box>
        </Stack>
      )}
      <Tabs value={tab} onChange={(_, t) => { location.hash = tabHref(t).slice(1); }}
        variant="scrollable" scrollButtons="auto" sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Service tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {!svc.data && !svc.error && <Box sx={{ textAlign: "center", py: 4 }}><CircularProgress size={24} /></Box>}
      {svc.data && tab === "observability" && <Observability name={name} />}
      {svc.data && tab === "revisions" && <Revisions region={region} name={name} service={svc.data} reload={svc.reload} />}
      {svc.data && tab === "source" && <Source region={region} name={name} service={svc.data} reload={svc.reload} notify={notify} />}
      {svc.data && tab === "networking" && <Networking region={region} name={name} service={svc.data} reload={svc.reload} notify={notify} />}
      {svc.data && tab === "security" && <Security region={region} name={name} policy={pol} reload={reloadAll} notify={notify} />}
      {svc.data && tab === "triggers" && <Triggers region={region} name={name} />}
      {svc.data && tab === "yaml" && <Yaml region={region} name={name} service={svc.data} />}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete service?" confirmText={name}
        warning="All revisions are deleted as well. This can't be undone."
        onConfirm={async () => { await api.deleteService(region, name); notify.success(`Deleted service "${name}"`); location.hash = "/functions/services"; }}>
        <Typography variant="body2">Service <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
      {cd && svc.data && <ContinuousDeploymentDialog region={region} name={name} service={svc.data} notify={notify}
        onClose={() => setCd(false)} reload={svc.reload} />}
    </>
  );
}

// ── Observability (real Cloud Monitoring + Cloud Logging reads, fed by actual invocations) ─
function Observability({ name }) {
  const metrics = useAsync(() => api.getObservabilityMetrics(name), [name]);
  const logs = useAsync(() => api.listServiceLogs(name), [name]);
  return (
    <Stack spacing={2}>
      <CapabilityContainer id="gcp.functions.services.observability" title="Metrics">
        {metrics.error ? <ErrorAlert error={metrics.error} title="Failed to load metrics" /> : (
          <Stack direction="row" spacing={5} sx={{ flexWrap: "wrap", rowGap: 2 }}>
            <Metric label="Request count" value={metrics.data?.requestCount} />
            <Metric label="Request latencies" value={metrics.data?.latencyMs != null ? `${metrics.data.latencyMs.toFixed(1)} ms` : null} />
            <Metric label="Container instance count" value={metrics.data?.instances} />
          </Stack>
        )}
      </CapabilityContainer>
      <CapabilityContainer id="gcp.functions.services.observability" title="Logs"
        actions={<Button size="small" startIcon={<RefreshIcon />} onClick={logs.reload}>Refresh</Button>}>
        {logs.error ? <ErrorAlert error={logs.error} title="Failed to load logs" /> : (
          <ResourceTable resourceName="log entries" items={logs.data || []} rowKey={(l) => l.insertId} loading={logs.loading}
            error={logs.error} onRetry={logs.reload} filterPlaceholder="Filter log entries"
            columns={[
              { id: "time", header: "Time", sortField: "timestamp", cell: (l) => fmtDate(l.timestamp) },
              { id: "severity", header: "Severity", cell: (l) => l.severity },
              { id: "message", header: "Message", cell: (l) => l.textPayload },
            ]} />
        )}
      </CapabilityContainer>
    </Stack>
  );
}

function Metric({ label, value }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h4">{value == null ? "—" : value}</Typography>
    </Box>
  );
}

// ── Triggers (Eventarc, Pub/Sub-sourced — really deliver, see gcp_run_core.invoke_service) ─
function Triggers({ region, name }) {
  const notify = useNotify();
  const trigs = useAsync(() => api.listTriggers(region, name), [region, name]);
  const [open, setOpen] = useState(false);
  return (
    <CapabilityContainer id="gcp.functions.services.triggers" title="Triggers"
      actions={<Button size="small" startIcon={<AddIcon />} onClick={() => setOpen(true)}>Add trigger</Button>}>
      <ResourceTable resourceName="triggers" items={trigs.data || []} rowKey={(t) => t.name} loading={trigs.loading}
        error={trigs.error} onRetry={trigs.reload} filterPlaceholder="Filter triggers"
        columns={[
          { id: "name", header: "Name", cell: (t) => t.name.split("/").pop() },
          { id: "type", header: "Type", cell: () => "Cloud Pub/Sub" },
          { id: "event", header: "Event", cell: api.triggerEventLabel },
          { id: "destination", header: "Destination", cell: api.triggerDestination },
          { id: "actions", header: "Actions", cell: (t) => (
            <Button size="small" color="error" onClick={async () => {
              await api.deleteTrigger(region, name, t.name.split("/").pop()); notify.success("Trigger deleted"); trigs.reload();
            }}>Delete</Button>
          ) },
        ]}
      />
      {open && <AddTriggerDialog region={region} name={name} notify={notify}
        onClose={() => setOpen(false)} onCreated={() => { setOpen(false); trigs.reload(); }} />}
    </CapabilityContainer>
  );
}

function AddTriggerDialog({ region, name, notify, onClose, onCreated }) {
  const [triggerId, setTriggerId] = useState("");
  const [eventType, setEventType] = useState(api.TRIGGER_EVENT_TYPES[0][0]);
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.createTrigger(region, name, triggerId, eventType, `projects/${getProject()}/topics/${topic}`);
      notify.success(`Trigger "${triggerId}" created`);
      onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Add trigger">
      <DialogTitle>Add trigger</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Trigger name" required value={triggerId} onChange={(e) => setTriggerId(e.target.value.trim())} />
          <FormControl>
            <InputLabel id="evt-l">Event type</InputLabel>
            <Select labelId="evt-l" label="Event type" value={eventType} onChange={(e) => setEventType(e.target.value)}>
              {api.TRIGGER_EVENT_TYPES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Pub/Sub topic ID" required value={topic} onChange={(e) => setTopic(e.target.value.trim())}
            helperText="An existing topic in this project; publishing to it invokes this service." />
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !triggerId || !topic} onClick={save}>{busy ? "Adding…" : "Add trigger"}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ── Continuous deployment ("Set up continuous deployment" header action) ──────────────────
function ContinuousDeploymentDialog({ region, name, service, notify, onClose, reload }) {
  const conn = api.repoConnection(service);
  const [repository, setRepository] = useState(conn?.repository || "");
  const [branch, setBranch] = useState(conn?.branch || "main");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const builds = useAsync(() => (conn ? api.listBuilds(region, name) : Promise.resolve([])), [region, name, conn?.repository]);

  const connect = async () => {
    setBusy(true); setError(null);
    try { await api.connectRepo(region, name, repository, branch); notify.success(`Connected to "${repository}"`); reload(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  const disconnect = async () => {
    setBusy(true);
    try { await api.disconnectRepo(region, name); notify.success("Repository disconnected"); reload(); }
    finally { setBusy(false); }
  };
  const push = async () => {
    setBusy(true); setError(null);
    try {
      const b = await api.triggerBuild(region, name, {});
      notify[b.status === "SUCCESS" ? "success" : "error"](`Build ${b.id}: ${b.status}${b.revision ? ` → revision ${b.revision}` : ""}`);
      builds.reload(); reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Set up continuous deployment">
      <DialogTitle>Continuous deployment</DialogTitle>
      <DialogContent>
        <CapabilityContainer id="gcp.functions.services.continuous_deployment" title="Repository">
          <Stack spacing={2}>
            {!conn ? (
              <>
                <TextField label="Repository" placeholder="owner/repo" required value={repository}
                  onChange={(e) => setRepository(e.target.value)} />
                <TextField label="Branch" required value={branch} onChange={(e) => setBranch(e.target.value)} />
                <Box><Button variant="contained" disabled={busy || !repository.includes("/")} onClick={connect}>
                  {busy ? "Connecting…" : "Connect"}
                </Button></Box>
              </>
            ) : (
              <>
                <Typography variant="body2">Connected to <b>{conn.repository}</b> @ <b>{conn.branch}</b></Typography>
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" startIcon={<SyncIcon />} disabled={busy} onClick={push}>
                    {busy ? "Pushing…" : "Simulate push (trigger build)"}
                  </Button>
                  <Button color="error" disabled={busy} onClick={disconnect}>Disconnect</Button>
                </Stack>
                <Typography variant="subtitle2" sx={{ mt: 1 }}>Build history</Typography>
                {(builds.data || []).length === 0 && <Typography variant="body2" color="text.secondary">No builds yet.</Typography>}
                {(builds.data || []).map((b) => (
                  <Typography key={b.id} variant="body2">
                    {b.id} — {b.status}{b.revision ? ` → ${b.revision}` : ""}{b.logs ? ` (${b.logs})` : ""}
                  </Typography>
                ))}
              </>
            )}
            {error && <Alert severity="error">{error.message}</Alert>}
          </Stack>
        </CapabilityContainer>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={onClose} disabled={busy}>Close</Button></DialogActions>
    </Dialog>
  );
}

// ── Revisions ────────────────────────────────────────────────────────────────────────────
function Revisions({ region, name, service, reload }) {
  const notify = useNotify();
  const [traffic, setTraffic] = useState(false);
  const revs = useAsync(() => api.listRevisions(region, name), [region, name]);
  const latest = (service.latestReadyRevision || "").split("/").pop();
  const trafficFor = (rid) => (service.trafficStatuses || []).find((t) => t.revision === rid)?.percent ?? 0;
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2" sx={{ flex: 1 }}>Revisions</Typography>
        <Button onClick={() => setTraffic(true)}>Manage traffic</Button>
      </Stack>
      <ResourceTable
        resourceName="revisions"
        items={revs.data || []}
        rowKey={(r) => r.name}
        loading={revs.loading}
        error={revs.error}
        onRetry={revs.reload}
        filterPlaceholder="Filter revisions"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (r) => r.name.split("/").pop() },
          { id: "traffic", header: "Traffic", cell: (r) => `${trafficFor(r.name.split("/").pop())}%` },
          { id: "deployed", header: "Deployed", sortField: "createTime", cell: (r) => fmtDate(r.createTime) },
          { id: "tags", header: "Revision tags", cell: () => "—" },
          { id: "actions", header: "Actions", cell: (r) => (
            <Button size="small" color="error" disabled={r.name.split("/").pop() === latest}
              onClick={async () => { await api.deleteRevision(region, name, r.name.split("/").pop()); notify.success("Revision deleted"); revs.reload(); }}>
              Delete
            </Button>
          ) },
        ]}
      />
      <NotSimulated compact feature="Revision tags" note="Vyomi serves traffic by percentage split only; named revision tags aren't modelled." />
      {traffic && <TrafficDialog region={region} name={name} service={service} revisions={revs.data || []}
        onClose={() => setTraffic(false)} onSaved={() => { reload(); revs.reload(); }} />}
    </Stack>
  );
}

function TrafficDialog({ region, name, service, revisions, onClose, onSaved }) {
  const notify = useNotify();
  const latest = (service.latestReadyRevision || "").split("/").pop();
  const [mode, setMode] = useState(service.trafficStatuses?.some((t) => t.type !== "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST") ? "pinned" : "latest");
  const [pinned, setPinned] = useState(service.trafficStatuses?.find((t) => t.type !== "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST")?.revision || latest);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const traffic = mode === "latest"
        ? [{ type: "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", percent: 100 }]
        : [{ type: "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION", revision: pinned, percent: 100 }];
      await api.patchService(region, name, { traffic }, "traffic");
      notify.success("Traffic updated");
      onSaved(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Manage traffic">
      <DialogTitle>Manage traffic</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <RadioGroup value={mode} onChange={(e) => setMode(e.target.value)}>
            <FormControlLabel value="latest" control={<Radio size="small" />} label="Route 100% of traffic to the latest ready revision" />
            <FormControlLabel value="pinned" control={<Radio size="small" />} label="Pin 100% of traffic to a specific revision" />
          </RadioGroup>
          {mode === "pinned" && (
            <FormControl sx={{ maxWidth: 420 }}><InputLabel id="pin-l">Revision</InputLabel>
              <Select labelId="pin-l" label="Revision" value={pinned} onChange={(e) => setPinned(e.target.value)}>
                {revisions.map((r) => { const rid = r.name.split("/").pop(); return <MenuItem key={rid} value={rid}>{rid}</MenuItem>; })}
              </Select>
            </FormControl>
          )}
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={save}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

// ── Source ───────────────────────────────────────────────────────────────────────────────
function Source({ region, name, service, reload, notify }) {
  const isFn = api.isFunction(service);
  if (!isFn) {
    return <NotSimulatedContainer title="Source" feature="Function entry point, Runtime, Source files"
      note="This service was deployed from a container image, not an inline function source — there is no source to edit." />;
  }
  const [edit, setEdit] = useState(false);
  const [entry, setEntry] = useState(api.functionEntryPoint(service));
  const [runtime, setRuntime] = useState(api.functionRuntime(service));
  const [source, setSource] = useState(api.functionSource(service));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await api.redeploySource(region, name, service, runtime, entry, source);
      notify.success("Source saved and redeployed");
      setEdit(false); reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} justifyContent="flex-end">
        {!edit && <Button startIcon={<EditIcon />} onClick={() => setEdit(true)}>Edit source</Button>}
        {edit && <Button variant="contained" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save and redeploy"}</Button>}
      </Stack>
      {error && <Alert severity="error">{error.message}</Alert>}
      <TextField label="Function entry point" required value={entry} onChange={(e) => setEntry(e.target.value)} disabled={!edit} sx={{ maxWidth: 420 }} />
      <FormControl sx={{ maxWidth: 320 }} disabled={!edit}>
        <InputLabel id="src-rt-l">Runtime</InputLabel>
        <Select labelId="src-rt-l" label="Runtime" value={runtime} onChange={(e) => setRuntime(e.target.value)}>
          {api.RUNTIMES.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
        </Select>
      </FormControl>
      <TextField label="Source files" value={source} onChange={(e) => setSource(e.target.value)} disabled={!edit}
        multiline minRows={10} InputProps={{ sx: { fontFamily: "monospace", fontSize: 13 } }} />
    </Stack>
  );
}

// ── Networking ───────────────────────────────────────────────────────────────────────────
function Networking({ region, name, service, reload, notify }) {
  const [ingress, setIngress] = useState(service.ingress === "INGRESS_TRAFFIC_INTERNAL_ONLY" || service.ingress === "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" ? "internal" : "all");
  const [busy, setBusy] = useState(false);
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h3" component="h2" sx={{ mb: 1.5 }}>Ingress control</Typography>
        <RadioGroup value={ingress} onChange={(e) => setIngress(e.target.value)} aria-label="Ingress">
          <FormControlLabel value="internal" control={<Radio size="small" />} label="Internal" />
          <FormControlLabel value="all" control={<Radio size="small" />} label="All" />
        </RadioGroup>
        <Button variant="contained" sx={{ mt: 1 }} disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            await api.patchService(region, name, { ingress: ingress === "internal" ? "INGRESS_TRAFFIC_INTERNAL_ONLY" : "INGRESS_TRAFFIC_ALL" }, "ingress");
            notify.success("Ingress updated"); reload();
          } catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Save</Button>
      </Box>
    </Stack>
  );
}

// ── Security ─────────────────────────────────────────────────────────────────────────────
function Security({ region, name, policy, reload, notify }) {
  const [auth, setAuth] = useState(api.isPublic(policy.data) ? "public" : "auth");
  const [busy, setBusy] = useState(false);
  return (
    <Box>
      <Typography variant="h3" component="h2" sx={{ mb: 1.5 }}>Authentication</Typography>
      <RadioGroup value={auth} onChange={(e) => setAuth(e.target.value)} aria-label="Authentication">
        <FormControlLabel value="public" control={<Radio size="small" />} label="Allow public access" />
        <FormControlLabel value="auth" control={<Radio size="small" />} label="Require authentication" />
      </RadioGroup>
      <Button variant="contained" sx={{ mt: 1 }} disabled={busy} onClick={async () => {
        setBusy(true);
        try { await api.setPublic(region, name, auth === "public"); notify.success("Authentication updated"); reload(); }
        catch (e) { notify.error(e); } finally { setBusy(false); }
      }}>Save</Button>
    </Box>
  );
}

// ── YAML ─────────────────────────────────────────────────────────────────────────────────
function Yaml({ service }) {
  const yamlText = toYaml(service);
  return (
    <CapabilityContainer id="gcp.functions.services.yaml" title="YAML">
      <TextField label="Service YAML" value={yamlText} multiline minRows={14} fullWidth
        InputProps={{ readOnly: true, sx: { fontFamily: "monospace", fontSize: 12.5 } }} />
    </CapabilityContainer>
  );
}

function toYaml(o, indent = 0) {
  const pad = "  ".repeat(indent);
  if (Array.isArray(o)) return o.map((v) => `${pad}- ${typeof v === "object" && v ? "\n" + toYaml(v, indent + 1) : v}`).join("\n");
  if (o && typeof o === "object") {
    return Object.entries(o).filter(([k]) => !k.startsWith("_")).map(([k, v]) => {
      if (v && typeof v === "object") return `${pad}${k}:\n${toYaml(v, indent + 1)}`;
      return `${pad}${k}: ${v}`;
    }).join("\n");
  }
  return `${pad}${o}`;
}
