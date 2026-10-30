/* Overview dashboard — real resource counts from the native wire; the Google Cloud status
 * feed isn't modeled (Vyomi has no incidents of its own to report). */
import { Box, Button, Paper, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import ListIcon from "@mui/icons-material/esm/List.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { NotSimulatedContainer, PageHeader, Section } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const Stat = ({ label, value }) => (
  <Paper variant="outlined" sx={{ p: 2, textAlign: "center", borderRadius: 2 }}>
    <Typography variant="h3" component="div">{value ?? "—"}</Typography>
    <Typography variant="body2" color="text.secondary">{label}</Typography>
  </Paper>
);

export default function Overview() {
  const project = useProject();
  const { data, loading, error, reload } = useAsync(async () => {
    const [instances, groups, disks, snapshots, images] = await Promise.all([
      api.listInstancesAllZones(), api.listInstanceGroupsAllZones(), api.listDisksAllZones(), api.listSnapshots(), api.listImages(),
    ]);
    return { instances: instances.length, groups: groups.length, disks: disks.length, snapshots: snapshots.length, images: images.length };
  }, [project]);

  return (
    <Box>
      <PageHeader title="Overview" actions={<>
        <Button startIcon={<AddIcon />} href="#/compute/instances/create">Create instance</Button>
        <Button startIcon={<ListIcon />} href="#/compute/instances">View instances</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Stack spacing={2}>
        <NotSimulatedContainer title="Google Cloud incidents" feature="Google Cloud incidents" note="Vyomi is a simulator with no real Google Cloud status feed to report." />
        <Section title="Resource footprint">
          {error ? <Typography color="error" variant="body2">{error.message}</Typography> : (
            <Stack direction="row" spacing={2} flexWrap="wrap">
              <Box sx={{ minWidth: 140, flex: 1 }}><Stat label="Total VMs" value={loading ? undefined : data?.instances} /></Box>
              <Box sx={{ minWidth: 140, flex: 1 }}><Stat label="Instance Groups" value={loading ? undefined : data?.groups} /></Box>
              <Box sx={{ minWidth: 140, flex: 1 }}><Stat label="Disks" value={loading ? undefined : data?.disks} /></Box>
              <Box sx={{ minWidth: 140, flex: 1 }}><Stat label="Snapshots" value={loading ? undefined : data?.snapshots} /></Box>
              <Box sx={{ minWidth: 140, flex: 1 }}><Stat label="Images" value={loading ? undefined : data?.images} /></Box>
            </Stack>
          )}
        </Section>
      </Stack>
    </Box>
  );
}
