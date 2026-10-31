/* Overview, Monitoring, Settings, Advisor, Storage Intelligence configuration and
 * Object enrichments — the nav pages around Buckets. None are honest_page: the console's
 * title and tabs render for real; individual sections that need telemetry, a separate
 * identity/billing concept or a separate product stay honest via CapabilityContainer. */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
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
export function Monitoring() {
  const [tab, setTab] = useState("overview");
  return (
    <Box sx={{ pt: 1 }}>
      <PageHeader title="Monitoring" />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Monitoring tabs">
        <Tab value="overview" label="Overview" />
        <Tab value="rapid-cache" label="Rapid Cache" />
      </Tabs>
      <CapabilityContainer id="gcp.storage.observability" title="Charts" />
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
      {tab === "soft-delete" && <CapabilityContainer id="gcp.storage.soft-delete" title="Soft delete" />}
    </Box>
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
