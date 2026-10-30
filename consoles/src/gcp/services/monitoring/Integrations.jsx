/* Integrations — the Google-curated catalog of pre-built dashboards/alerts for common
 * platforms. This is reference catalog data (the same on every project), not a simulated
 * resource; installing one is out of scope (see gcp.monitoring.integrations). */
import { useState } from "react";
import { Checkbox, FormControlLabel, Grid, Paper, Stack, Typography } from "@mui/material";
import { PageHeader, Section } from "../../kit/common.jsx";

const CATALOG = [
  { name: "MongoDB Atlas", platform: "Any platform", status: "Available", type: "Third-party" },
  { name: "Istio", platform: "Kubernetes", status: "Available", type: "Open source" },
  { name: "NGINX", platform: "Any platform", status: "Available", type: "Open source" },
  { name: "Cloud SQL for MySQL", platform: "Google Cloud", status: "Available", type: "Google Cloud" },
  { name: "Memorystore for Redis", platform: "Google Cloud", status: "Available", type: "Google Cloud" },
  { name: "Elasticsearch", platform: "Any platform", status: "Available", type: "Third-party" },
];

export default function Integrations() {
  const [platform, setPlatform] = useState([]);
  const [status, setStatus] = useState([]);
  const [type, setType] = useState([]);
  const toggle = (list, setList, v) => setList(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const shown = CATALOG.filter((c) => (!platform.length || platform.includes(c.platform)) && (!status.length || status.includes(c.status)) && (!type.length || type.includes(c.type)));

  return (
    <>
      <PageHeader title="Integrations" />
      <Stack spacing={2.5}>
        <Section title="Get started with Integrations">
          <Typography variant="body2" color="text.secondary">
            Integrations install Google-curated dashboards and alerting policies tuned for a specific platform or
            open-source package. Browse the catalog below; installing an integration isn't simulated in Vyomi.
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
              {[...new Set(CATALOG.map((c) => c.status))].map((s) => (
                <FormControlLabel key={s} control={<Checkbox size="small" checked={status.includes(s)} onChange={() => toggle(status, setStatus, s)} />} label={s} />
              ))}
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
                <Typography variant="body2" color="text.secondary">{c.platform} · {c.type}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      </Stack>
    </>
  );
}
