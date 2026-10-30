/* Overview dashboard — a real summary over the project's existing Cloud Run resources
 * (no separate backend call; it's the same lists the other pages use). */
import { Box, Paper, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { PageHeader } from "../../kit/common.jsx";
import { Link } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function Card({ label, value, href }) {
  const body = (
    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 2, minWidth: 180 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h2" component="div" sx={{ mt: 0.5 }}>{value}</Typography>
    </Paper>
  );
  return href ? <Link href={href} sx={{ textDecoration: "none" }}>{body}</Link> : body;
}

export default function Overview() {
  const project = useProject();
  const region = api.getRegion();
  const { data } = useAsync(async () => {
    const [services, jobs, workerPools, domains] = await Promise.all([
      api.listServices(region), api.listJobs(region), api.listWorkerPools(region), api.listDomainMappings(),
    ]);
    return { services, jobs, workerPools, domains };
  }, [project, region]);

  return (
    <Box>
      <PageHeader title="Overview" />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Project <b>{project}</b> · region <b>{api.regionLabel(region)}</b>
      </Typography>
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 2 }}>
        <Card label="Services" value={data?.services.length ?? "…"} href="#/functions/services" />
        <Card label="Jobs" value={data?.jobs.length ?? "…"} href="#/functions/jobs" />
        <Card label="Worker pools" value={data?.workerPools.length ?? "…"} href="#/functions/worker-pools" />
        <Card label="Domain mappings" value={data?.domains.length ?? "…"} href="#/functions/domain-mappings" />
      </Stack>
    </Box>
  );
}
