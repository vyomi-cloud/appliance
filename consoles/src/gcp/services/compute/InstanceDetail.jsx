/* Instance detail: Details tab (all spec sections) + a real Observability tab (recorded
 * lifecycle activity) + a real Serial port output tab (same activity, replayed as console
 * lines) + honest OS info/Screenshot tabs (no guest OS is modeled, so there's nothing to
 * report there). */
import { useState } from "react";
import {
  Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Stack, Tab, Tabs,
  TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, NotSimulated, PageHeader, Section, fmtDate, fmtDuration } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

const TABS = ["Details", "Observability", "Serial port output", "OS info", "Screenshot"];

/** Real recorded activity for this instance: status duration (from its own real lifecycle
 * timestamps) + the operations the core actually performed, oldest action last. No Cloud
 * Monitoring chart / Cloud Logging entry is plotted (nothing meters real resource use). */
function ObservabilityPanel({ zone, name, inst }) {
  const { data: ops = [], loading } = useAsync(() => api.listOperations(), [zone, name, inst.status]);
  const mine = ops
    .filter((o) => (o.targetLink || "").includes(`/zones/${zone}/instances/${name}`))
    .sort((a, b) => Number(b.id) - Number(a.id));
  const since = inst.status === "RUNNING" ? inst.lastStartTimestamp : inst.lastStopTimestamp;
  const durSecs = since ? Math.max(0, Math.round((Date.now() - new Date(since).getTime()) / 1000)) : null;
  return (
    <Stack spacing={2}>
      <KeyValue items={[
        ["Status", inst.status],
        ["Time in current status", durSecs != null ? fmtDuration(durSecs) : "—"],
        ["Lifecycle operations recorded", String(mine.length)],
      ]} />
      <Box>
        <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Recent activity</Typography>
        {loading ? <CircularProgress size={20} /> : (
          <Box sx={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 14, borderCollapse: "collapse" }}>
              <thead><tr>{["Operation", "Status", "Time"].map((h) => <th key={h} style={{ textAlign: "left", padding: 6, borderBottom: "1px solid #ddd" }}>{h}</th>)}</tr></thead>
              <tbody>
                {mine.slice(0, 10).map((o) => (
                  <tr key={o.name}><td style={{ padding: 6 }}>{o.operationType}</td><td style={{ padding: 6 }}>{o.status}</td><td style={{ padding: 6 }}>{fmtDate(o.endTime)}</td></tr>
                ))}
                {!mine.length && <tr><td colSpan={3} style={{ padding: 6, color: "#666" }}>No recorded operations yet.</td></tr>}
              </tbody>
            </table>
          </Box>
        )}
      </Box>
      <NotSimulated compact feature="Recommender & VM Manager"
        note="Recommender suggestions and VM Manager (Patch, OS policies, VM Extension Manager) aren't modeled in Vyomi." />
    </Stack>
  );
}

/** Real serial port output: the instance's own recorded lifecycle operations, replayed as
 * console lines at their real timestamps — not a fabricated guest kernel boot log. */
function SerialPortPanel({ zone, name }) {
  const { data, loading, error, reload } = useAsync(() => api.getSerialPortOutput(zone, name), [zone, name]);
  return (
    <Stack spacing={1.5}>
      <Box><Button size="small" startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button></Box>
      {error && <ErrorAlert error={error} title="Failed to load serial port output" />}
      {loading && !data ? <CircularProgress size={20} /> : (
        <Box component="pre" sx={{
          m: 0, p: 1.5, bgcolor: "grey.900", color: "grey.100", fontFamily: "monospace", fontSize: 13,
          borderRadius: 1, maxHeight: 360, overflow: "auto", whiteSpace: "pre-wrap",
        }}>
          {data?.contents || "(no output yet)"}
        </Box>
      )}
    </Stack>
  );
}

export default function InstanceDetail({ params }) {
  const { zone, name } = params;
  const notify = useNotify();
  const [tab, setTab] = useState("Details");
  const [del, setDel] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editLabels, setEditLabels] = useState("");
  const { data: inst, loading, error, reload } = useAsync(() => api.getInstance(zone, name), [zone, name]);

  const act = async (action) => {
    try { await api.instanceAction(zone, name, action); notify.success(`${action} requested for "${name}"`); reload(); }
    catch (e) { notify.error(e.message); }
  };

  if (loading && !inst) return <Box sx={{ p: 4, textAlign: "center" }}><CircularProgress size={28} /></Box>;
  if (error && !inst) return <Box sx={{ pt: 2 }}><ErrorAlert error={error} title="Failed to load instance" /></Box>;
  if (!inst) return null;

  const boot = inst.disks?.find((d) => d.boot);
  const ni = inst.networkInterfaces?.[0];

  return (
    <Box>
      <PageHeader
        title={name}
        back={<IconButton aria-label="Back" href="#/compute/instances"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button onClick={() => { setEditLabels(Object.entries(inst.labels || {}).map(([k, v]) => `${k}=${v}`).join(", ")); setEditOpen(true); }}>Edit</Button>
          <Button onClick={() => act("reset")} disabled={inst.status !== "RUNNING"}>Reset</Button>
          <Button onClick={async () => { const mi = `${name}-image-${Date.now() % 100000}`; try { await api.insertMachineImage({ name: mi, sourceInstance: name }); notify.success(`Created machine image "${mi}"`); } catch (e) { notify.error(e.message); } }}>Create machine image</Button>
          <Button href={`#/compute/instances/create?like=${encodeURIComponent(name)}`}>Create similar</Button>
          <Button onClick={() => act("stop")} disabled={inst.status !== "RUNNING"}>Stop</Button>
          <Button onClick={() => act("suspend")} disabled={inst.status !== "RUNNING"}>Suspend</Button>
          <Button color="error" onClick={() => setDel(true)}>Delete</Button>
        </>}
      >
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
          <Chip size="small" color={api.statusChipColor(inst.status)} label={inst.status} />
          {inst.deletionProtection && <Chip size="small" label="Deletion protection on" />}
        </Stack>
      </PageHeader>

      <Box sx={{ mb: 2 }}>
        <CapabilityContainer id="gcp.compute.instances.data_plane" title="SSH" />
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {TABS.map((t) => <Tab key={t} label={t} value={t} />)}
      </Tabs>

      {tab === "Details" && (
        <Stack spacing={2}>
          <Section title="Basic information">
            <KeyValue items={[
              ["Name", inst.name], ["Instance ID", inst.id], ["Description", inst.description || "—"],
              ["Type", "Standard"], ["Status", inst.status], ["Creation time", fmtDate(inst.creationTimestamp)],
              ["Zone", zone], ["Instance template", "—"], ["In use by", "—"],
              ["Labels", Object.entries(inst.labels || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"],
              ["Tags", (inst.tags?.items || []).join(", ") || "—"],
              ["Deletion protection", inst.deletionProtection ? "On" : "Off"],
            ]} />
          </Section>
          <Section title="Machine configuration">
            <KeyValue items={[
              ["Machine type", api.machineTypeNameOf(inst)], ["CPU platform", inst.cpuPlatform],
              ["Architecture", "x86/64"], ["vCPUs to core ratio", "1 vCPU / core"],
              ["Display device", "Disabled"], ["GPUs", "None"],
            ]} />
          </Section>
          <Section title="Networking">
            <KeyValue items={[["Network tags", (inst.tags?.items || []).join(", ") || "—"]]} />
            <Typography variant="body2" sx={{ fontWeight: 500, mt: 1.5, mb: 0.5 }}>Network interfaces</Typography>
            <Box sx={{ overflowX: "auto" }}>
              <table style={{ width: "100%", fontSize: 14, borderCollapse: "collapse" }}>
                <thead><tr>{["Name", "Network", "Subnetwork", "Primary internal IP address", "Alias IP ranges", "External IP address", "Network Tier", "IP forwarding"].map((h) => <th key={h} style={{ textAlign: "left", padding: 6, borderBottom: "1px solid #ddd" }}>{h}</th>)}</tr></thead>
                <tbody><tr>
                  <td style={{ padding: 6 }}>{ni?.name}</td><td style={{ padding: 6 }}>default</td><td style={{ padding: 6 }}>default</td>
                  <td style={{ padding: 6 }}>{ni?.networkIP}</td><td style={{ padding: 6 }}>—</td>
                  <td style={{ padding: 6 }}>{api.externalIpOf(inst)}</td><td style={{ padding: 6 }}>{ni?.accessConfigs?.[0]?.networkTier || "—"}</td>
                  <td style={{ padding: 6 }}>{inst.canIpForward ? "On" : "Off"}</td>
                </tr></tbody>
              </table>
            </Box>
          </Section>
          <Section title="Storage">
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Boot disk</Typography>
            <Box sx={{ overflowX: "auto" }}>
              <table style={{ width: "100%", fontSize: 14, borderCollapse: "collapse" }}>
                <thead><tr>{["Name", "Image", "Interface type", "Size (GB)", "Device name", "Type", "Encryption", "Mode", "When deleting instance"].map((h) => <th key={h} style={{ textAlign: "left", padding: 6, borderBottom: "1px solid #ddd" }}>{h}</th>)}</tr></thead>
                <tbody><tr>
                  <td style={{ padding: 6 }}>{api.last(boot?.source)}</td><td style={{ padding: 6 }}>Debian</td><td style={{ padding: 6 }}>{boot?.interface}</td>
                  <td style={{ padding: 6 }}>{boot?.diskSizeGb}</td><td style={{ padding: 6 }}>{boot?.deviceName}</td><td style={{ padding: 6 }}>Persistent disk</td>
                  <td style={{ padding: 6 }}>Google-managed</td><td style={{ padding: 6 }}>{boot?.mode}</td>
                  <td style={{ padding: 6 }}>{boot?.autoDelete ? "Delete disk" : "Keep disk"}</td>
                </tr></tbody>
              </table>
            </Box>
          </Section>
          <Section title="Security and access">
            <KeyValue items={[
              ["Shielded VM", `Secure boot ${inst.shieldedInstanceConfig?.enableSecureBoot ? "on" : "off"}, vTPM ${inst.shieldedInstanceConfig?.enableVtpm ? "on" : "off"}, Integrity monitoring ${inst.shieldedInstanceConfig?.enableIntegrityMonitoring ? "on" : "off"}`],
              ["SSH Keys", "Project-wide keys"], ["Service account", inst.serviceAccounts?.[0]?.email || "—"],
              ["Cloud API access scopes", (inst.serviceAccounts?.[0]?.scopes || []).length > 1 ? "Allow full access to all Cloud APIs" : "Allow default access"],
            ]} />
          </Section>
          <Section title="Management">
            <KeyValue items={[
              ["Metadata", (inst.metadata?.items || []).map((m) => `${m.key}=${m.value}`).join(", ") || "None"],
              ["VM provisioning model", inst.scheduling?.provisioningModel], ["On host maintenance", inst.scheduling?.onHostMaintenance],
              ["Automatic restart", inst.scheduling?.automaticRestart ? "On" : "Off"],
            ]} />
          </Section>
        </Stack>
      )}
      {tab === "Observability" && (
        <CapabilityContainer id="gcp.compute.observability" title="Observability">
          <ObservabilityPanel zone={zone} name={name} inst={inst} />
        </CapabilityContainer>
      )}
      {tab === "Serial port output" && (
        <CapabilityContainer id="gcp.compute.instances.serial_console" title="Serial port output">
          <SerialPortPanel zone={zone} name={name} />
        </CapabilityContainer>
      )}
      {tab === "OS info" && <CapabilityContainer id="gcp.compute.instances.data_plane" title="OS info" />}
      {tab === "Screenshot" && <CapabilityContainer id="gcp.compute.instances.data_plane" title="Screenshot" />}

      <DeleteDialog
        open={del} onClose={() => setDel(false)} title="Delete instance?" confirmText={name}
        warning="Attached disks set to auto-delete are removed as well. This can't be undone."
        onConfirm={async () => { await api.deleteInstance(zone, name); notify.success(`Deleted instance "${name}"`); window.location.hash = hashHref("compute", "instances").slice(1); }}
      >
        <Typography variant="body2">Instance <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit instance</DialogTitle>
        <DialogContent>
          <TextField fullWidth label="Labels (key=value, comma-separated)" value={editLabels} onChange={(e) => setEditLabels(e.target.value)} sx={{ mt: 1 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={async () => {
            const labels = Object.fromEntries(editLabels.split(",").map((s) => s.trim()).filter(Boolean).map((s) => s.split("=").map((x) => x.trim())).filter((p) => p[0]));
            try { await api.setInstanceLabels(zone, name, labels); notify.success("Instance updated"); setEditOpen(false); reload(); }
            catch (e) { notify.error(e.message); }
          }}>Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
