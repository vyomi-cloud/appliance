/* Integrations — the Google-curated catalog of pre-built dashboards/alerts for common
 * platforms (reference catalog data, the same on every project — see
 * gcp.monitoring.integrations). "Install" is real: it creates a Dashboards-API (v1)
 * dashboard in this project, pre-wired to a real metric filter for the platform, the same
 * way the real integration's installer would seed a starter dashboard. Vyomi doesn't model
 * the curated alerting policies an install also normally adds. */
import { useState } from "react";
import { Button, Checkbox, Chip, FormControlLabel, Grid, Paper, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const CATALOG = [
  { name: "MongoDB Atlas", platform: "Any platform", type: "Third-party", metric: "compute.googleapis.com/instance/cpu/utilization", resourceType: "gce_instance" },
  { name: "Istio", platform: "Kubernetes", type: "Open source", metric: "kubernetes.io/container/cpu/core_usage_time", resourceType: "k8s_container" },
  { name: "NGINX", platform: "Any platform", type: "Open source", metric: "compute.googleapis.com/instance/cpu/utilization", resourceType: "gce_instance" },
  { name: "Cloud SQL for MySQL", platform: "Google Cloud", type: "Google Cloud", metric: "cloudsql.googleapis.com/database/cpu/utilization", resourceType: "cloudsql_database" },
  { name: "Memorystore for Redis", platform: "Google Cloud", type: "Google Cloud", metric: "compute.googleapis.com/instance/cpu/utilization", resourceType: "gce_instance" },
  { name: "Elasticsearch", platform: "Any platform", type: "Third-party", metric: "compute.googleapis.com/instance/network/received_bytes_count", resourceType: "gce_instance" },
];

const dashboardName = (c) => `${c.name} Overview`;

export default function Integrations() {
  const project = useProject();
  const notify = useNotify();
  const [platform, setPlatform] = useState([]);
  const [type, setType] = useState([]);
  const [installing, setInstalling] = useState(null);
  const toggle = (list, setList, v) => setList(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const shown = CATALOG.filter((c) => (!platform.length || platform.includes(c.platform)) && (!type.length || type.includes(c.type)));
  const { data: dashboards = [], reload } = useAsync(() => api.listDashboards(), [project]);
  const installed = (c) => dashboards.some((d) => d.displayName === dashboardName(c));

  const install = async (c) => {
    setInstalling(c.name);
    try {
      await api.createDashboard({
        displayName: dashboardName(c),
        mosaicLayout: { columns: 12, tiles: [{
          xPos: 0, yPos: 0, width: 6, height: 4,
          widget: { title: `${c.name} — CPU`, xyChart: { dataSets: [{
            plotType: "LINE",
            timeSeriesQuery: { timeSeriesFilter: {
              filter: `metric.type = "${c.metric}" AND resource.type = "${c.resourceType}"`,
              aggregation: { perSeriesAligner: "ALIGN_MEAN", alignmentPeriod: "60s" },
            } },
          }] } },
        }] },
      });
      notify.success(`Installed "${c.name}" — added a starter dashboard`);
      reload();
    } finally { setInstalling(null); }
  };

  return (
    <>
      <PageHeader title={<>Integrations <CapabilityBadge id="gcp.monitoring.integrations" /></>} />
      <Stack spacing={2.5}>
        <Section title="Get started with Integrations">
          <Typography variant="body2" color="text.secondary">
            Integrations install Google-curated dashboards and alerting policies tuned for a specific platform or
            open-source package. Installing one in Vyomi adds a real starter dashboard wired to a matching metric;
            the curated alerting policies a real install also adds aren't modeled.
          </Typography>
        </Section>
        <Section title="Quick filters">
          <Stack direction="row" spacing={4}>
            <Stack>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>Deployment Platform</Typography>
              {[...new Set(CATALOG.map((c) => c.platform))].map((p) => (
                <FormControlLabel key={p} control={<Checkbox size="small" checked={platform.includes(p)} onChange={() => toggle(platform, setPlatform, p)} />} label={p} />
              ))}
            </Stack>
            <Stack>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>Status</Typography>
              {["Installed", "Not installed"].map((s) => <FormControlLabel key={s} disabled control={<Checkbox size="small" />} label={s} />)}
            </Stack>
            <Stack>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>Type</Typography>
              {[...new Set(CATALOG.map((c) => c.type))].map((t) => (
                <FormControlLabel key={t} control={<Checkbox size="small" checked={type.includes(t)} onChange={() => toggle(type, setType, t)} />} label={t} />
              ))}
            </Stack>
          </Stack>
        </Section>
        <Grid container spacing={2}>
          {shown.map((c) => (
            <Grid item xs={12} sm={6} md={4} key={c.name}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2">{c.name}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{c.platform} · {c.type}</Typography>
                {installed(c)
                  ? <Chip size="small" color="success" label="Installed" />
                  : <Button size="small" variant="outlined" disabled={installing === c.name} onClick={() => install(c)}>
                      {installing === c.name ? "Installing…" : "Install"}
                    </Button>}
              </Paper>
            </Grid>
          ))}
        </Grid>
        <Section title="Dashboards in this project">
          {dashboards.length ? (
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
              {dashboards.map((d) => (
                <Chip key={d.name} component={Link} clickable href={hashHref("monitoring", "dashboards", d.name.split("/").pop())} label={d.displayName} />
              ))}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">An installed integration adds dashboards here — this project has none yet.</Typography>
          )}
        </Section>
      </Stack>
    </>
  );
}
