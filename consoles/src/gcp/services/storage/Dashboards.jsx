/* Overview, Monitoring, Settings, Advisor, Storage Intelligence configuration and
 * Object enrichments — the nav pages around Buckets. None are honest_page: the console's
 * title and tabs render for real; individual sections that need telemetry, a separate
 * identity/billing concept or a separate product stay honest via CapabilityContainer. */
import { useState } from "react";
import { Box, Tab, Tabs, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { fmtBytes, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

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
          <CapabilityContainer id="gcp.storage.interoperability" title="Service account HMAC" />
          <CapabilityContainer id="gcp.storage.interoperability" title="User account HMAC" />
        </Box>
      )}
      {tab === "soft-delete" && <CapabilityContainer id="gcp.storage.soft-delete" title="Soft delete" />}
    </Box>
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
