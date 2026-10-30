/* Overview — a real dashboard over the project's clusters (no separate backend needed:
 * it's a summary of clusters.list, like the console's landing dashboard). */
import { Box, Button, Chip, Grid, Paper, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function Stat({ label, value }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, flex: 1 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h2" component="div">{value}</Typography>
    </Paper>
  );
}

export default function Overview() {
  const project = useProject();
  const { data = [], loading, error } = useAsync(() => api.listClusters(), [project]);
  const nodes = data.reduce((a, c) => a + (typeof c.nodes === "number" ? c.nodes : 0), 0);
  const running = data.filter((c) => c.status === "RUNNING").length;

  return (
    <>
      <PageHeader title="Overview" actions={<Button startIcon={<AddIcon />} href={hashHref("kubernetes", "clusters", "create")}>Create cluster</Button>} />
      <ErrorAlert error={error} title="Failed to load clusters" />
      <Stack direction="row" spacing={2} sx={{ mb: 3 }}>
        <Stat label="Clusters" value={loading ? "…" : data.length} />
        <Stat label="Running" value={loading ? "…" : running} />
        <Stat label="Total nodes" value={loading ? "…" : nodes} />
      </Stack>
      <Typography variant="h3" component="h2" sx={{ mb: 1.5 }}>Clusters</Typography>
      {!loading && !data.length && (
        <Stack spacing={1.5} alignItems="flex-start">
          <Typography variant="body2" color="text.secondary">You don't have any Kubernetes clusters in this project yet.</Typography>
          <Button variant="contained" startIcon={<AddIcon />} href={hashHref("kubernetes", "clusters", "create")}>Create cluster</Button>
        </Stack>
      )}
      <Grid container spacing={2}>
        {data.map((c) => (
          <Grid item xs={12} sm={6} md={4} key={`${c.location}/${c.name}`}>
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                <Link href={hashHref("kubernetes", "clusters", c.location, c.name)} sx={{ fontWeight: 500 }}>{c.name}</Link>
                <Chip size="small" label={api.statusLabel(c.status)} color={c.status === "RUNNING" ? "success" : c.status === "ERROR" ? "error" : "default"} />
              </Stack>
              <Typography variant="body2" color="text.secondary">{c.location} · {c.mode} · {c.mode === "Autopilot" ? "Autopilot-managed nodes" : `${c.nodes} node${c.nodes === 1 ? "" : "s"}`}</Typography>
            </Paper>
          </Grid>
        ))}
      </Grid>
      <Box sx={{ mt: 2 }}><Link href={hashHref("kubernetes", "clusters")}>View all clusters</Link></Box>
    </>
  );
}
