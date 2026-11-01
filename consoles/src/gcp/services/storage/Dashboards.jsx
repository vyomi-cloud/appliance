/* Overview, Monitoring, Settings, Advisor, Storage Intelligence configuration and
 * Object enrichments — the nav pages around Buckets. None are honest_page: the console's
 * title and tabs render for real; individual sections that need telemetry, a separate
 * identity/billing concept or a separate product stay honest via CapabilityContainer. */
import { useState } from "react";
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormControlLabel, InputLabel,
  MenuItem, Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const DEV_USER_EMAIL = "dev@example.com";

// ── Overview ────────────────────────────────────────────────────────────────────────────
async function projectGlance() {
  const buckets = await api.listBuckets();
  const perBucket = await Promise.all(buckets.map((b) => api.listAll(b.name).catch(() => [])));
  const objects = perBucket.flat();
  const totalSize = objects.reduce((n, o) => n + Number(o.size || 0), 0);
  const withObjects = perBucket.filter((os) => os.length).length;
  return { totalSize, withObjects, totalObjects: objects.length, avgSize: objects.length ? totalSize / objects.length : 0 };
}

export function Overview() {
  const project = useProject();
  const [tab, setTab] = useState("overview");
  const g = useAsync(projectGlance, [project]);
  return (
    <Box sx={{ pt: 1 }}>
      <PageHeader title="Overview" actions={<Link href="#/storage/create-bucket">Create bucket</Link>} />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Overview tabs">
        <Tab value="overview" label="Overview" />
        <Tab value="guides" label="Guides" />
      </Tabs>
      {tab === "overview" && (
        <Box sx={{ display: "grid", gap: 2, maxWidth: 820 }}>
          <Section title="Project at a glance">
            {g.data ? <KeyValue items={[
              ["Total storage size", fmtBytes(g.data.totalSize)],
              ["Total buckets with objects", g.data.withObjects],
              ["Total objects", g.data.totalObjects],
              ["Average object size", fmtBytes(Math.round(g.data.avgSize))],
            ]} /> : <Typography variant="body2" color="text.secondary">Loading…</Typography>}
          </Section>
          <Section title="Jump back in">
            <Typography variant="body2" color="text.secondary">No pinned or recently visited buckets yet.</Typography>
          </Section>
          <Section title="Recent transfer activity">
            <Typography variant="body2" color="text.secondary">No transfer jobs yet.</Typography>
          </Section>
          <Section title="Features you may like">
            <Typography variant="body2" color="text.secondary"><Link href="#/storage/batch-operations">Batch Operations</Link> and <Link href="#/storage/insights-datasets">Insights datasets</Link> are available for this project.</Typography>
          </Section>
        </Box>
      )}
      {tab === "guides" && <Typography variant="body2" color="text.secondary">See the Buckets page to get started with Cloud Storage.</Typography>}
    </Box>
  );
}

// ── Monitoring ──────────────────────────────────────────────────────────────────────────
function Sparkline({ points }) {
  const vals = points.map((p) => p.v);
  if (!vals.length) return <Typography variant="body2" color="text.secondary">No requests recorded yet for this bucket in the selected range.</Typography>;
  const max = Math.max(...vals, 1);
  const d = vals.map((v, i) => `${i === 0 ? "M" : "L"} ${(i / Math.max(vals.length - 1, 1)) * 320} ${40 - (v / max) * 36}`).join(" ");
  return <svg width={320} height={44} role="img" aria-label="Request count over time"><path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} /></svg>;
}

const RANGES = [["1", "Last hour"], ["6", "Last 6 hours"], ["24", "Last 24 hours"]];

export function Monitoring() {
  const [tab, setTab] = useState("overview");
  const [bucket, setBucket] = useState("");
  const [hours, setHours] = useState("1");
  const [location, setLocation] = useState("all");
  const buckets = useAsync(() => api.listBuckets(), []);
  const allBuckets = buckets.data || [];
  const locations = [...new Set(allBuckets.map((b) => b.location))];
  const bucketNames = location === "all" ? allBuckets : allBuckets.filter((b) => b.location === location);
  const effectiveBucket = bucketNames.some((b) => b.name === bucket) ? bucket : (bucketNames[0]?.name || "");
  const series = useAsync(() => effectiveBucket ? api.getRequestCountSeries(effectiveBucket, Number(hours)) : Promise.resolve([]), [effectiveBucket, hours]);
  const total = (series.data || []).reduce((n, p) => n + p.v, 0);
  return (
    <Box sx={{ pt: 1 }}>
      <PageHeader title="Monitoring" />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Monitoring tabs">
        <Tab value="overview" label="Overview" />
        <Tab value="rapid-cache" label="Rapid Cache" />
      </Tabs>
      {tab === "overview" && (
        <CapabilityContainer id="gcp.storage.observability" title="Charts"
          description="Real request-count metering, fed by actual API activity against the selected bucket — metered live, not synthetic data.">
          <Stack direction="row" spacing={2} sx={{ mb: 2 }} alignItems="center">
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Typography variant="body2">Filter by:</Typography>
              <Select size="small" value={location} onChange={(e) => { setLocation(e.target.value); setBucket(""); }}
                displayEmpty renderValue={(v) => v === "all" ? "All locations" : v} inputProps={{ "aria-label": "Filter by location" }}>
                <MenuItem value="all">All locations</MenuItem>
                {locations.map((l) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
              </Select>
            </Stack>
            <FormControl sx={{ minWidth: 220 }} size="small">
              <InputLabel id="mon-bucket">Bucket</InputLabel>
              <Select labelId="mon-bucket" label="Bucket" value={effectiveBucket} onChange={(e) => setBucket(e.target.value)}>
                {bucketNames.map((b) => <MenuItem key={b.name} value={b.name}>{b.name}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl sx={{ minWidth: 160 }} size="small">
              <InputLabel id="mon-range">Time range</InputLabel>
              <Select labelId="mon-range" label="Time range" value={hours} onChange={(e) => setHours(e.target.value)}>
                {RANGES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
          {!bucketNames.length ? <Typography variant="body2" color="text.secondary">Create a bucket to see its request metrics.</Typography> : (
            <>
              <Typography variant="body2" sx={{ mb: 1 }}><b>{total}</b> API requests in the selected range</Typography>
              <Sparkline points={series.data || []} />
            </>
          )}
        </CapabilityContainer>
      )}
      {tab === "rapid-cache" && <CapabilityContainer id="gcp.storage.rapid-cache" title="Rapid Cache" />}
    </Box>
  );
}

// ── Settings ────────────────────────────────────────────────────────────────────────────
export function Settings() {
  const project = useProject();
  const [tab, setTab] = useState("project-access");
  return (
    <Box sx={{ pt: 1 }}>
      <PageHeader title="Settings" />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Settings tabs">
        <Tab value="project-access" label="Project access" />
        <Tab value="interoperability" label="Interoperability" />
        <Tab value="soft-delete" label="Soft delete" />
      </Tabs>
      {tab === "project-access" && (
        <Box sx={{ display: "grid", gap: 2, maxWidth: 820 }}>
          <Section title="Public access prevention for the project">
            <KeyValue items={[["Public access prevention policy", "Inherited — unset at the project level"]]} />
          </Section>
          <Section title="Identifying your project">
            <KeyValue items={[["x-goog-project-id", project]]} />
          </Section>
          <Section title="Cloud Storage Service Account">
            <KeyValue items={[["Service account", `service-000000000000@gs-project-accounts.iam.gserviceaccount.com`]]} />
          </Section>
          <Section title="Cloud Storage IDs">
            <KeyValue items={[
              ["You", `user:dev@example.com`], ["Owners", `projectOwner:${project}`],
              ["Editor", `projectEditor:${project}`], ["Team", `projectViewer:${project}`],
            ]} />
          </Section>
        </Box>
      )}
      {tab === "interoperability" && (
        <Box sx={{ display: "grid", gap: 2, maxWidth: 820 }}>
          <Section title="Request endpoint">
            <KeyValue items={[["Storage URI", "storage.vyomi.cloud"]]} />
          </Section>
          <ServiceAccountHmac project={project} />
          <UserAccountHmac project={project} />
        </Box>
      )}
      {tab === "soft-delete" && <SoftDeleteSettings project={project} />}
    </Box>
  );
}

// ── Soft delete project default (applied to buckets created from now on; a bucket's own
// Protection tab always overrides this when the user picks something different there) ──
function SoftDeleteSettings({ project }) {
  const notify = useNotify();
  const current = api.getDefaultSoftDeleteDays(project);
  const [enabled, setEnabled] = useState(current !== null);
  const [days, setDays] = useState(String(current || 7));
  const ok = !enabled || (Number(days) > 0 && Number.isInteger(Number(days)));
  return (
    <CapabilityContainer id="gcp.storage.soft-delete" title="Soft delete"
      description="The default retention duration applied to buckets you create in this project from now on. Vyomi stores this in the browser, same as the real console's project preference, and CreateBucket reads it for real."
      actions={<Button variant="contained" disabled={!ok} onClick={() => {
        api.setDefaultSoftDeleteDays(project, enabled ? Number(days) : null);
        notify.success("Default soft delete retention saved");
      }}>Save</Button>}>
      <FormControlLabel control={<Checkbox size="small" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />} label="Enable soft delete by default for new buckets" />
      {enabled && <TextField label="Retention duration (days)" type="number" size="small" sx={{ ml: 4, mt: 1, width: 220 }}
        value={days} onChange={(e) => setDays(e.target.value)} error={!ok} helperText={ok ? " " : "Enter a whole number greater than 0."} />}
    </CapabilityContainer>
  );
}

// ── Interoperability: HMAC keys (projects/{p}/hmacKeys) ────────────────────────────────
function HmacSecretDialog({ secret, onClose }) {
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-label="HMAC key created">
      <DialogTitle>HMAC key created</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 1.5 }}>Copy this secret now — Vyomi only shows it once, same as the real API.</Typography>
        <TextField fullWidth label="Secret" value={secret} InputProps={{ readOnly: true }} inputProps={{ "aria-label": "Secret" }} />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button variant="contained" onClick={onClose}>Done</Button></DialogActions>
    </Dialog>
  );
}

function ServiceAccountHmac({ project }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listHmacKeys(project), [project]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [sa, setSa] = useState("");
  const [secret, setSecret] = useState(null);
  const keys = (data || []).filter((k) => k.serviceAccountEmail !== DEV_USER_EMAIL);
  return (
    <>
      <Section title={<Stack component="span" direction="row" spacing={1} alignItems="center"><span>Service account HMAC</span><CapabilityBadge id="gcp.storage.interoperability" /></Stack>}
        description="Access keys for service accounts"
        actions={<Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create a key for a service account</Button>}>
        {error && <ErrorAlert error={error} />}
        <ResourceTable resourceName="access keys" items={keys} rowKey={(k) => k.accessId} loading={loading} selectable selected={sel} onSelectedChange={setSel} dense
          filterPlaceholder="Filter access keys"
          columns={[
            { id: "accessId", header: "Access key", cell: (k) => k.accessId },
            { id: "secret", header: "Secret", cell: () => "•••••••••• (shown once, at creation)" },
            { id: "sa", header: "Service account", cell: (k) => k.serviceAccountEmail },
            { id: "state", header: "State", cell: (k) => k.state },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No access keys for service accounts.</Typography>} />
        {!!sel.length && <Button startIcon={<DeleteIcon />} sx={{ mt: 1 }} onClick={async () => {
          try {
            for (const id of sel) { await api.setHmacKeyState(project, id, "INACTIVE"); await api.deleteHmacKey(project, id); }
            notify.success(`Deleted ${sel.length} access key${sel.length === 1 ? "" : "s"}`); setSel([]); reload();
          } catch (e) { notify.error(e); }
        }}>Remove access</Button>}
      </Section>
      {create && (
        <Dialog open onClose={() => setCreate(false)} maxWidth="sm" fullWidth aria-label="Create a key for a service account">
          <DialogTitle>Create a key for a service account</DialogTitle>
          <DialogContent>
            <TextField fullWidth autoFocus label="Service account" value={sa} onChange={(e) => setSa(e.target.value)}
              helperText="e.g. app@vyomi-project.iam.gserviceaccount.com" sx={{ mt: 1 }} />
          </DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button onClick={() => setCreate(false)}>Cancel</Button>
            <Button variant="contained" disabled={!sa.includes("@")} onClick={async () => {
              try { const r = await api.createHmacKey(project, sa); setCreate(false); setSa(""); setSecret(r.secret); reload(); }
              catch (e) { notify.error(e); }
            }}>Create</Button>
          </DialogActions>
        </Dialog>
      )}
      {secret && <HmacSecretDialog secret={secret} onClose={() => setSecret(null)} />}
    </>
  );
}

function UserAccountHmac({ project }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listHmacKeys(project), [project]);
  const [del, setDel] = useState(null);
  const [secret, setSecret] = useState(null);
  const keys = (data || []).filter((k) => k.serviceAccountEmail === DEV_USER_EMAIL);
  return (
    <>
      <Section title={<Stack component="span" direction="row" spacing={1} alignItems="center"><span>User account HMAC</span><CapabilityBadge id="gcp.storage.interoperability" /></Stack>}
        actions={<Button startIcon={<AddIcon />} onClick={async () => {
          try { const r = await api.createHmacKey(project, DEV_USER_EMAIL); setSecret(r.secret); reload(); }
          catch (e) { notify.error(e); }
        }}>Create a key</Button>}>
        <KeyValue items={[["Default project for interoperable access", project]]} />
        <ResourceTable resourceName="access keys" items={keys} rowKey={(k) => k.accessId} loading={loading} dense
          columns={[
            { id: "accessId", header: "Access key", cell: (k) => k.accessId },
            { id: "secret", header: "Secret", cell: () => "•••••••••• (shown once, at creation)" },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No rows to display.</Typography>} />
        {error && <ErrorAlert error={error} />}
        {keys.map((k) => (
          <Button key={k.accessId} size="small" color="error" sx={{ mt: 1 }} onClick={() => setDel(k)}>Remove {k.accessId}</Button>
        ))}
      </Section>
      {del && <DeleteDialog open onClose={() => setDel(null)} title={`Remove access key ${del.accessId}?`} actionLabel="Remove"
        onConfirm={async () => { await api.setHmacKeyState(project, del.accessId, "INACTIVE"); await api.deleteHmacKey(project, del.accessId); notify.success("Access key removed"); reload(); }}>
        <Typography variant="body2">This key will stop working immediately.</Typography>
      </DeleteDialog>}
      {secret && <HmacSecretDialog secret={secret} onClose={() => setSecret(null)} />}
    </>
  );
}

// ── Advisor ─────────────────────────────────────────────────────────────────────────────
export function Advisor() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>Advisor</Typography>
      <CapabilityContainer id="gcp.storage.security-insights" title="Recommendations" />
    </Box>
  );
}

// ── Storage Intelligence configuration ─────────────────────────────────────────────────
export function StorageIntelligenceConfiguration() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>Configuration</Typography>
      <Section title="Storage Intelligence">
        <Typography variant="body2" color="text.secondary">
          Project-wide Storage Intelligence filters and inventory settings. Vyomi's equivalents —{" "}
          <Link href="#/storage/batch-operations">Batch Operations</Link> and <Link href="#/storage/insights-datasets">Insights datasets</Link> — are configured per job/dataset on their own pages.
        </Typography>
      </Section>
    </Box>
  );
}

// ── Object enrichments (Smart Storage) ─────────────────────────────────────────────────
export function ObjectEnrichments() {
  return (
    <Box sx={{ pt: 2 }}>
      <Typography variant="h1" component="h1" sx={{ mb: 2 }}>Object enrichments</Typography>
      <CapabilityContainer id="gcp.storage.object-enrichments" title="Object enrichments" />
    </Box>
  );
}
